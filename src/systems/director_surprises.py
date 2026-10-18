"""MERIDIAN surprises: events that change how the station *feels*, not just how many enemies are on the floor.

 isolate   the station folds one player into a distant, enemy-free room (telegraphed; the team can still reach them)
 blackout  the lights fail for a while; only a small radius around each player is visible (no spawns while it lasts)
 seal      a door is sealed for the rest of the expedition (only if every mandatory target stays reachable)
 hunter    one relentless heavy that tracks the crew across the whole station (telegraphed, one at a time)
 ambush    a false calm ends: groups arrive from several sides at once (every point telegraphed and far from the crew)

All of them obey the director invariants: revalidated at execution, never during a Rekindling or an active mandatory
interaction, never an unavoidable-damage placement, and none touches player health."""
import math

import pygame

from src.config import BAL
from src.entities.models import Telegraph
from src.settings import TILE
from src.systems import nav
from src.systems import director_events as ev
from src.systems.director_events import (ACTIVE, SCHEDULED, Event, RouteClosureEvent, _SpawnBase, alive_players,
                                         busy_zones, connectivity_ok, door_cells, pos_ok_for_threat, ritual_active)

V = pygame.Vector2


def _nearest_enemy_dist(sim, pos):
    return min((e.pos.distance_to(pos) for e in sim.enemies if not e.dead), default=1e9)


def _hazard_near(sim, pos, clear):
    for h in sim.floor_hazards:
        if V(h.rect.center).distance_to(pos) < clear + max(h.rect.w, h.rect.h) / 2:
            return True
    return False


# ======================================================================== isolate
class IsolateEvent(Event):
    """Teleport one player to a far, quiet room. The destination is chosen so that the player is never dropped next to
    danger and always has a walkable route back to the team and to every mandatory target."""
    kind = "isolate"

    def _victim(self, sim):
        safety = self.d.cfg["safety"]
        zones = busy_zones(sim, safety)
        al = alive_players(sim)
        if len(al) < 2:
            return None
        pool = []
        for p in al:
            if p.hp < p.max_hp * self.d.cfg["isolate"]["min_hp_frac"]:
                continue
            if p.carry is not None or p.interact_progress > 0 or getattr(p, "channeling", False) or getattr(p, "resist_t", 0) > 0:
                continue
            if any(zp.distance_to(p.pos) < zr for zp, zr, _ in zones):
                continue
            if _nearest_enemy_dist(sim, p.pos) < 300:
                continue
            pool.append(p)
        return pool

    def _dest(self, sim, victim):
        cfg, safety = self.d.cfg["isolate"], self.d.cfg["safety"]
        others = [p for p in alive_players(sim) if p is not victim]
        dyn = nav.blocked_dynamic_tiles(sim)
        cands = []
        for r in sim.level.rooms:
            if r.id == sim.level.archive_room:
                continue
            cx, cy = r.center
            pos = V(cx * TILE + TILE / 2, cy * TILE + TILE / 2)
            for off in ((0, 0), (3, 0), (-3, 0), (0, 3), (0, -3)):
                q = pos + V(off[0], off[1]) * TILE
                if not sim.solids.free_at(q, 20):
                    continue
                dv = victim.pos.distance_to(q)
                do = min(p.pos.distance_to(q) for p in others)
                if dv < cfg["min_dist"] or do < cfg["min_dist"] * 0.8 or do > cfg["max_dist"]:
                    continue
                if _nearest_enemy_dist(sim, q) < cfg["enemy_clear"]:
                    continue
                if _hazard_near(sim, q, safety["hazard_clear"]):
                    continue
                if any(zp.distance_to(q) < zr for zp, zr, _ in busy_zones(sim, safety)):
                    continue
                if any(t.pos.distance_to(q) < 300 for t in sim.telegraphs):
                    continue
                st = (int(q.x // TILE), int(q.y // TILE))
                field = nav.build_field(sim, st, dyn)
                if st not in field:
                    continue
                ok = all(ev._reach(field, (int(p.pos.x // TILE), int(p.pos.y // TILE))) for p in others)
                ok = ok and all(ev._reach(field, t) for t in ev.mandatory_targets(sim))
                if not ok:
                    continue
                cands.append((do, q))
                break
        if not cands:
            return None
        cands.sort(key=lambda c: -c[0])
        top = cands[: max(1, min(3, len(cands)))]
        return V(top[self.d.rng.randrange(len(top))][1])

    def validate(self, sim, phase):
        if len(alive_players(sim)) < 2:
            return False, "needs two living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if getattr(sim, "host", None) is not None:
            return False, "a Host is already active"
        if any(isinstance(e, IsolateEvent) and e.state == ACTIVE for e in self.d.events):
            return False, "an isolation is already active"
        if phase == "schedule" and sim.time < self.d.cfg["isolate"]["after"]:
            return False, "too early"
        pool = self._victim(sim)
        if not pool:
            return False, "no player is in a safe state to be moved"
        if self.p.get("victim") is not None:
            pool = [p for p in pool if p.idx == self.p["victim"]]
        for v in pool:
            if self._dest(sim, v) is not None:
                return True, ""
        return False, "no safe destination with a route back"

    def on_start(self, sim):
        pool = self._victim(sim) or []
        if self.p.get("victim") is not None:
            pool = [p for p in pool if p.idx == self.p["victim"]]
        order = list(pool)
        self.d.rng.shuffle(order)
        self.victim, self.dest = None, None
        for v in order:
            dest = self._dest(sim, v)
            if dest is not None:
                self.victim, self.dest = v, dest
                break
        warn = max(self.p["warn"], self.d.cfg["safety"]["min_warn"])
        self.t_fire = sim.time + warn
        self.fired = False
        if self.victim is None:
            self.ends_at = sim.time
            return
        self.tele = Telegraph("isolate", self.victim.pos, warn, 70)
        sim.telegraphs.append(self.tele)
        sim.emit("isolate_warning", pos=V(self.victim.pos), player=self.victim.idx)
        self.duration = warn + self.d.cfg["isolate"]["duration"]
        self.ends_at = sim.time + self.duration

    def on_tick(self, sim, dt):
        v = self.victim
        if v is None:
            return
        if not self.fired:
            self.tele.pos = V(v.pos)
            if not v.alive or self.d.protect_now(sim) or v.interact_progress > 0 or getattr(v, "resist_t", 0) > 0:
                self.d.note(f"{self.label()} aborted: victim not safe to move")
                self.ends_at = sim.time
                return
            if sim.time >= self.t_fire:
                dest = self._dest(sim, v)                        # revalidated at the moment of execution
                if dest is None:
                    self.d.note(f"{self.label()} aborted: destination no longer safe")
                    self.ends_at = sim.time
                    return
                src = V(v.pos)
                v.pos = V(dest)
                v.dodge_t = 0.0
                self.fired = True
                self.tele.dead = True
                self.d.flags.add("isolated_once")
                sim.emit("teleport", pos=V(dest), src=src, player=v.idx)
                self.d.remember("isolate", f"{v.name} was folded away from the crew.", 3, [f"player:{v.idx}"])
        else:
            others = [p for p in alive_players(sim) if p is not v]
            if not v.alive or not others or min(p.pos.distance_to(v.pos) for p in others) < 380:
                self.ends_at = sim.time                          # reunited (or no longer relevant)

    def on_cleanup(self, sim):
        t = getattr(self, "tele", None)
        if t is not None:
            t.dead = True


# ======================================================================== blackout
class BlackoutEvent(Event):
    """Lights fail. Visibility shrinks to a small radius around each player. Nothing new spawns while it lasts, and it is
    only started when no awake enemy is close, so the fear is atmospheric and fair."""
    kind = "blackout"

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if self.d.blackout > 0:
            return False, "blackout already active"
        if sim.modifier == "blackout":
            return False, "station is already dark"
        if phase == "schedule" and sim.time < self.d.cfg["blackout"]["after"]:
            return False, "too early"
        near = self.d.cfg["blackout"]["enemy_clear"]
        if any(not e.dead and e.alert_t > 0 and any(p.pos.distance_to(e.pos) < near for p in alive_players(sim)) for e in sim.enemies):
            return False, "alerted enemies too close for a fair blackout"
        return True, ""

    def on_start(self, sim):
        self.d.blackout = self.d.cfg["blackout"]["fade"]
        self.d.blackout_total = self.duration
        sim.emit("blackout_start", dur=self.duration)

    def on_tick(self, sim, dt):
        pass

    def on_cleanup(self, sim):
        self.d.blackout = 0.0
        sim.emit("blackout_end")


# ======================================================================== seal
class SealEvent(RouteClosureEvent):
    """Permanently seal a normal door. The map gets smaller as the shift goes on; at least `min_open_frac` of the normal
    doors always remain and every mandatory target must stay reachable from every living player."""
    kind = "seal"

    def validate(self, sim, phase):
        normal = [d for d in sim.doors if d.kind == "normal"]
        sealed = sum(1 for d in normal if d.sealed)
        if (len(normal) - sealed - 1) < self.d.cfg["seal"]["min_open_frac"] * len(normal):
            return False, "enough of the station is already sealed"
        if phase == "schedule" and sim.time < self.d.cfg["seal"]["after"]:
            return False, "too early"
        if any(isinstance(e, SealEvent) and e is not self and e.state in (SCHEDULED, ACTIVE) for e in self.d.events):
            return False, "a seal is already pending"
        ok, why = super().validate(sim, phase)
        return ok, why

    def on_start(self, sim):
        super().on_start(sim)
        self.t_limit = sim.time + max(self.p["warn"], 2.5) + 10.0
        self.ends_at = self.t_limit
        self.sealed_now = False
        sim.emit("seal_warning", pos=V(sim.doors[self.door_i].center))

    def on_tick(self, sim, dt):
        dr = sim.doors[self.door_i]
        if not self.sealed_now and dr.lock_t > 0:
            if not connectivity_ok(sim, door_cells(dr)) and not connectivity_ok(sim):
                self.d.note(f"{self.label()} not sealed: route lost")
                dr.lock_t = 0.01
                self.ends_at = sim.time
                return
            dr.lock_t = 1e9
            dr.sealed = True
            self.sealed_now = True
            self.locked = True
            self.d.sealed_doors += 1
            self.d.remember("seal", "A path through the station was sealed.", 3, [f"door:{self.door_i}"])
            sim.emit("seal_done", pos=V(dr.center), door=self.door_i)
            self.ends_at = sim.time + 0.5
        elif not self.sealed_now and sim.time >= self.t_limit:
            self.ends_at = sim.time

    def on_cleanup(self, sim):
        di = getattr(self, "door_i", None)
        if di is not None and not self.sealed_now:
            dr = sim.doors[di]
            if dr.lock_t > 0.01 and not dr.sealed:
                dr.lock_t = 0.01
            if dr.warn_t > 0:
                dr.warn_t = 0.0


# ======================================================================== hunter
class HunterEvent(_SpawnBase):
    """One relentless brute. It knows where the crew is. Telegraphed, far away, one at a time, and killable."""
    kind = "hunter"

    def _score(self, sim, pt):
        c = self.d.obs_centroid(sim)
        return -abs(c.distance_to(pt) - 1100) if c is not None else 0.0

    def validate(self, sim, phase):
        if phase == "schedule" and sim.time < self.d.cfg["hunter"]["after"]:
            return False, "too early"
        if any(not e.dead and getattr(e, "hunt", False) for e in sim.enemies):
            return False, "a hunter is already alive"
        return super().validate(sim, phase)

    def _tag(self, e):
        e.hunt = True
        e.hp *= self.d.cfg["hunter"]["hp_mult"]
        e.max_hp = e.hp
        e.alert_t = 1e9


# ======================================================================== ambush
class AmbushEvent(Event):
    """The false calm ends: several groups arrive at once from different sides, each point telegraphed and far away."""
    kind = "ambush"

    def _points(self, sim):
        safety = self.d.cfg["safety"]
        c = self.d.obs_centroid(sim)
        if c is None:
            return []
        picks = []
        cands = []
        for pt in sim.level.patrol_spawns:
            pt = V(pt)
            ok, _ = pos_ok_for_threat(sim, pt, safety, clear=self.d.cfg["ambush"]["clear"])
            if not ok:
                continue
            d = c.distance_to(pt)
            if d > 1500:
                continue
            cands.append((abs(d - 800), pt))
        cands.sort(key=lambda x: x[0])
        for _, pt in cands:
            if all(pt.distance_to(q) > 520 for q in picks):
                picks.append(pt)
            if len(picks) >= self.p.get("sides", 3):
                break
        return picks if len(picks) >= 2 else []

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if phase == "schedule" and sim.time < self.d.cfg["ambush"]["after"]:
            return False, "too early"
        n = len(self.p["kinds"])
        if not self.d.room_for(sim, n):
            return False, "enemy cap"
        if not self._points(sim):
            return False, "fewer than two safe, separated spawn points"
        return True, ""

    def on_start(self, sim):
        pts = self._points(sim)
        warn = max(self.p["warn"], self.d.cfg["safety"]["min_warn"])
        kinds = list(self.p["kinds"])
        groups = [kinds[i::len(pts)] for i in range(len(pts))]
        self.teles = []
        for pt, g in zip(pts, groups):
            t = Telegraph("director", pt, warn, 40, payload=g)
            sim.telegraphs.append(t)
            self.teles.append((t, V(pt), g))
        self.t_spawn = sim.time + warn
        self.spawned = False
        sim.emit("spawn_warning", pos=V(pts[0]), kind="ambush")
        self.duration = warn + 0.6
        self.ends_at = sim.time + self.duration

    def on_tick(self, sim, dt):
        if self.spawned or sim.time < self.t_spawn:
            return
        from src.systems.fracture import spawn_group
        safety = self.d.cfg["safety"]
        al = alive_players(sim)
        for t, pos, g in self.teles:
            t.dead = True
            ok, why = pos_ok_for_threat(sim, pos, safety, clear=self.d.cfg["ambush"]["clear"])
            if not ok or self.d.protect_now(sim) or not self.d.room_for(sim, len(g)):
                self.d.note(f"{self.label()} group aborted at spawn: {why or 'protected/cap'}")
                continue
            self.d.spawn_log.append({"t": sim.time, "pos": V(pos), "ritual": ritual_active(sim), "warn": t.total,
                                     "min_player_dist": min((p.pos.distance_to(pos) for p in al), default=1e9),
                                     "dist": min((p.pos.distance_to(pos) for p in al), default=1e9),
                                     "alive_before": sum(1 for e in sim.enemies if not e.dead), "n": len(g)})
            before = {id(e) for e in sim.enemies}
            spawn_group(sim, pos, g)
            for e in sim.enemies:
                if id(e) not in before:
                    e.director = True
            sim.emit("enemies_arrive", pos=V(pos), count=len(g))
        self.spawned = True

    def finished(self, sim):
        return self.spawned and sim.time >= self.ends_at

    def on_cleanup(self, sim):
        for t, _, _ in getattr(self, "teles", []):
            t.dead = True


SURPRISE_CLASSES = {c.kind: c for c in (IsolateEvent, BlackoutEvent, SealEvent, HunterEvent, AmbushEvent)}


# ======================================================================== the Rift
class RiftEvent(Event):
    """An ordinary Rift: the station tears and scatters blank papers; burning them pays, ignoring them scars the station.

    Stage 2 of the three-stage design. It never picks a Host (`select = False`). Both kinds give the same tell and the
    same tear, so a Rift alone says nothing about whether somebody will be chosen. Everything is revalidated at execution
    from game state (never from the clock alone)."""
    kind = "rift"
    select = False

    def _conf(self):
        from src.systems import rift as R
        return R.cfg()

    def validate(self, sim, phase):
        from src.systems import rift as R
        c = self._conf()
        if R.active(sim):
            return False, "a Rift is already open"
        if any(e is not self and e.state in (SCHEDULED, ACTIVE) and e.kind in ("rift", "rift_select", "isolate", "blackout") for e in self.d.events):
            return False, "another surprise is active"
        if sim.extract_progress > 0:
            return False, "extraction in progress"
        if self.d.protect_now(sim) or ritual_active(sim):
            return False, "Rekindling is being protected"
        if any(not p.alive and p.state != "host" for p in sim.players):
            return False, "someone is down"
        if self.select:
            ok, why = R.select_ready(sim, sim.time)
        else:
            ok = sim.time - sim.rift.last_end >= c["rift"]["ordinary_cooldown"]
            why = "ordinary Rift cooldown"
            if ok and sim.host is not None:
                ok, why = False, "the Host is loose"
        if not ok:
            return False, why
        ok, why = R.can_open(sim, self.select)
        return ok, why

    def on_start(self, sim):
        lead = max(self.p.get("lead", 10.0), self.d.cfg["safety"]["min_warn"])
        self.t_open = sim.time + lead
        self.opened = False
        sim.rift.tell_until = self.t_open
        sim.emit("rift_tell", pos=V(sim.core_pos), t=lead)
        self.duration = lead + 200.0                    # a ceiling: the event ends when the Rift does
        self.ends_at = sim.time + self.duration

    def on_tick(self, sim, dt):
        from src.systems import rift as R
        if not self.opened:
            if sim.time >= self.t_open:
                ok, why = self.validate_open(sim)
                if not ok:
                    self.d.note(f"{self.label()} aborted at opening: {why}")
                    self.ends_at = sim.time
                    sim.rift.tell_until = 0.0
                    return
                R.open_rift(sim, self.select)
                self.opened = True
                self.d.note(f"{self.label()} opened ({'selection' if self.select else 'ordinary'})")
        elif not R.active(sim):
            self.ends_at = sim.time

    def validate_open(self, sim):
        from src.systems import rift as R
        if R.active(sim):
            return False, "a Rift is already open"
        if self.select:
            ok, why = R.select_ready(sim, sim.time)
            if not ok:
                return False, why
        return R.can_open(sim, self.select)

    def on_cleanup(self, sim):
        sim.rift.tell_until = 0.0


class RiftSelectEvent(RiftEvent):
    """Stage 2 of Host selection. Requested only when `rift.select_ready` holds: it is a function of evidence the crew
    produced (revivals, defeats, forced teleports, logs, the Gauge, relays) and never of the clock alone."""
    kind = "rift_select"
    select = True


SURPRISE_CLASSES["rift"] = RiftEvent
SURPRISE_CLASSES["rift_select"] = RiftSelectEvent


class FalseTellEvent(Event):
    """MERIDIAN lies. It plays the exact tell of a Rift (flicker, amber camera LEDs, the banner) and then nothing tears.
    Harmless by construction: it spawns nothing, locks nothing and touches no one. It exists so that a tell is evidence, not
    certainty, and so a crew that reads the Director too literally pays in nerves, never in health. It never runs while a real
    Rift is open or scheduled, and never during Rekindling."""
    kind = "false_tell"

    def validate(self, sim, phase):
        from src.systems import rift as R
        if not alive_players(sim):
            return False, "no living players"
        if R.active(sim) or sim.rift.tell_until > sim.time:
            return False, "a Rift or tell is already running"
        if any(e is not self and e.state in (SCHEDULED, ACTIVE) and e.kind in ("rift", "rift_select", "isolate", "blackout", "false_tell") for e in self.d.events):
            return False, "another surprise is active"
        if self.d.protect_now(sim) or ritual_active(sim):
            return False, "Rekindling is being protected"
        if phase == "schedule" and sim.time < self.d.cfg["false_tell"]["after"]:
            return False, "too early"
        return True, ""

    def on_start(self, sim):
        lead = self.d.cfg["false_tell"]["lead"]
        self.t_end = sim.time + lead
        sim.rift.tell_until = self.t_end
        sim.emit("rift_tell", pos=V(sim.core_pos), t=lead, fake=True)    # byte-for-byte the same cue as a real one
        self.duration = lead + 0.1
        self.ends_at = sim.time + self.duration

    def on_tick(self, sim, dt):
        pass

    def on_cleanup(self, sim):
        sim.rift.tell_until = 0.0
        sim.emit("rift_fizzle", pos=V(sim.core_pos))


SURPRISE_CLASSES["false_tell"] = FalseTellEvent
