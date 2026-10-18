"""MERIDIAN executable events and the authored story-event engine.

Every event has an explicit lifecycle: scheduled -> active -> resolved | cancelled, with start/tick/resolve/cancel/cleanup.
Scheduling (the director's decision) is separate from execution: every event is revalidated against live game state the
moment it would take effect, and cancelled if an invariant would be broken. Events never touch player health; threats are
expressed only through existing game systems (telegraphed spawns, floor hazards, door locks)."""
import math

import pygame

from src.config import BAL, load_json
from src.entities.models import FloorHazard, Pickup, Telegraph, Fault
from src.settings import TILE
from src.systems import nav

V = pygame.Vector2

SCHEDULED, ACTIVE, RESOLVED, CANCELLED = "scheduled", "active", "resolved", "cancelled"


# ======================================================================== shared helpers
def alive_players(sim):
    return [p for p in sim.players if p.alive]


def ritual_active(sim):
    """True while an Echo is being carried, placed or channelled: the Rekindling must never be put under new pressure."""
    if any(a.echo is not None for a in sim.anchors):
        return True
    return any(e.state in ("carried", "placed", "ritual") for e in sim.echoes)


def busy_zones(sim, safety):
    """(position, radius, why) areas where new threats must not appear: active mandatory interactions."""
    z = []
    br, rr = safety["busy_radius"], safety["ritual_block_radius"]
    for r in sim.relays:
        if not r.online and (r.active or r.progress > 0):
            z.append((V(r.pos), br, "relay"))
    for a in sim.anchors:
        if a.echo is not None:
            z.append((V(a.pos), rr, "ritual"))
    for e in sim.echoes:
        if e.state in ("carried", "placed", "ritual"):
            z.append((V(e.pos), rr, "echo"))
        elif e.state == "dropped":
            z.append((V(e.pos), br, "echo_dropped"))
    for p in sim.players:
        if p.alive and (p.interact_progress > 0 or getattr(p, "channeling", False)):
            z.append((V(p.pos), br, "interact"))
    if sim.extract_progress > 0:
        z.append((V(sim.extract_pos), br, "extract"))
    return z


def pos_ok_for_threat(sim, pos, safety, clear=None, radius=20):
    """-> (ok, reason). A threat position must be open floor, far from every living player and outside busy zones."""
    pos = V(pos)
    if not sim.solids.free_at(pos, radius):
        return False, "blocked"
    c = clear if clear is not None else safety["spawn_clear"]
    for p in alive_players(sim):
        if p.pos.distance_to(pos) < c:
            return False, "too close to a player"
    for zp, zr, why in busy_zones(sim, safety):
        if zp.distance_to(pos) < zr:
            return False, f"inside busy zone ({why})"
    return True, ""


def mandatory_targets(sim):
    """Tiles that must stay reachable: unfinished relays, anchors, the extraction point."""
    t = []
    for r in sim.relays:
        if not r.online:
            t.append((int(r.pos.x // TILE), int(r.pos.y // TILE)))
    for a in sim.anchors:
        t.append((int(a.pos.x // TILE), int(a.pos.y // TILE)))
    t.append((int(sim.extract_pos.x // TILE), int(sim.extract_pos.y // TILE)))
    return t


def _reach(field, tile):
    if tile in field:
        return True
    return any((tile[0] + dx, tile[1] + dy) in field for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def connectivity_ok(sim, extra_blocked=()):
    """Every living player can still reach every mandatory target with the given extra cells blocked (barrier doors,
    locked doors and barricades already count as blocked). Used for route closures and as a standing invariant."""
    dyn = set(nav.blocked_dynamic_tiles(sim)) | set(extra_blocked)
    targets = mandatory_targets(sim)
    for p in alive_players(sim):
        start = (int(p.pos.x // TILE), int(p.pos.y // TILE))
        field = nav.build_field(sim, start, dyn)
        if start not in field:
            return False
        for t in targets:
            if not _reach(field, t):
                return False
    return True


def door_cells(door):
    return list(door.cells)


# ======================================================================== event base
class Event:
    kind = ""

    def __init__(self, eid, director, params, start_at, ends_after, reason, obs_id):
        self.id = eid
        self.d = director
        self.p = params
        self.state = SCHEDULED
        self.scheduled_at = director.sim.time
        self.start_at = start_at
        self.duration = ends_after
        self.ends_at = None
        self.reason = reason
        self.obs_id = obs_id
        self.cancel_reason = ""
        self.tag = ""

    @property
    def category(self):
        return self.d.budget.category(self.kind)

    # --- lifecycle (override) ---
    def validate(self, sim, phase):
        """-> (ok, reason). Called when scheduling and again immediately before start."""
        return True, ""

    def on_start(self, sim):
        pass

    def on_tick(self, sim, dt):
        pass

    def finished(self, sim):
        return sim.time >= self.ends_at

    def on_cleanup(self, sim):
        pass

    # --- driven by the director ---
    def start(self, sim):
        self.state = ACTIVE
        self.ends_at = sim.time + self.duration
        self.on_start(sim)

    def resolve(self, sim):
        if self.state in (RESOLVED, CANCELLED):
            return
        self.on_cleanup(sim)
        self.state = RESOLVED

    def cancel(self, sim, why):
        if self.state in (RESOLVED, CANCELLED):
            return
        self.on_cleanup(sim)
        self.state = CANCELLED
        self.cancel_reason = why

    def label(self):
        return f"{self.kind}#{self.id}"


# ======================================================================== threats
def _spawn_candidates(sim, safety):
    return [V(p) for p in sim.level.patrol_spawns]


class _SpawnBase(Event):
    """Telegraphed spawn: a visible marker for `warn` seconds, then enemies arrive if the position is still valid."""

    def _choose(self, sim):
        safety = self.d.cfg["safety"]
        best = None
        for pt in _spawn_candidates(sim, safety):
            ok, _ = pos_ok_for_threat(sim, pt, safety)
            if not ok:
                continue
            s = self._score(sim, pt)
            if best is None or s > best[0]:
                best = (s, pt)
        return best[1] if best else None

    def _score(self, sim, pt):
        c = self.d.obs_centroid(sim)
        return -abs(c.distance_to(pt) - 700) if c is not None else 0.0

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        n = len(self.p["kinds"])
        if self.d.blackout > 0:
            return False, "blackout: nothing spawns in the dark"
        if not self.d.room_for(sim, n):
            return False, "enemy cap"
        if self._choose(sim) is None:
            return False, "no valid spawn point"
        return True, ""

    def on_start(self, sim):
        self.pos = self._choose(sim)
        warn = max(self.p["warn"], self.d.cfg["safety"]["min_warn"])
        self.t_spawn = sim.time + warn
        self.tele = Telegraph("director", self.pos, warn, 40, payload=self.p["kinds"])
        sim.telegraphs.append(self.tele)
        sim.emit("spawn_warning", pos=V(self.pos), kind="director")
        self.duration = warn + 0.5
        self.ends_at = sim.time + self.duration
        self.spawned = False

    def on_tick(self, sim, dt):
        if self.spawned or sim.time < self.t_spawn:
            return
        ok, why = pos_ok_for_threat(sim, self.pos, self.d.cfg["safety"])
        if not ok or self.d.protect_now(sim) or not self.d.room_for(sim, len(self.p["kinds"])):
            self.tele.dead = True
            self.spawned = True
            self.d.note(f"{self.label()} aborted at spawn: {why or 'protected/cap'}")
            self.aborted = True
            return
        from src.systems.fracture import spawn_group
        al = alive_players(sim)
        self.d.spawn_log.append({"t": sim.time, "pos": V(self.pos), "ritual": ritual_active(sim), "warn": self.tele.total,
                                 "min_player_dist": min((p.pos.distance_to(self.pos) for p in al), default=1e9),
                                 "dist": min((p.pos.distance_to(self.pos) for p in al), default=1e9),
                                 "alive_before": sum(1 for e in sim.enemies if not e.dead), "n": len(self.p["kinds"])})
        before = {id(e) for e in sim.enemies}
        spawn_group(sim, self.pos, list(self.p["kinds"]))
        for e in sim.enemies:
            if id(e) not in before:
                e.director = True
                self._tag(e)
        self.tele.dead = True
        self.spawned = True
        sim.emit("enemies_arrive", pos=V(self.pos), count=len(self.p["kinds"]))

    def _tag(self, e):
        """Hook for subclasses to mark the enemies this event created."""

    def finished(self, sim):
        return self.spawned and sim.time >= self.ends_at

    def on_cleanup(self, sim):
        t = getattr(self, "tele", None)
        if t is not None:
            t.dead = True

    aborted = False


class ReinforceEvent(_SpawnBase):
    kind = "reinforce"


class FlankEvent(_SpawnBase):
    kind = "flank"

    def _score(self, sim, pt):
        c = self.d.obs_centroid(sim)
        h = self.d.heading
        if c is None or h is None:
            return -abs(c.distance_to(pt) - 700) if c is not None else 0.0
        v = pt - c
        if v.length_squared() == 0:
            return -1e9
        behind = -V(v).normalize().dot(h)           # 1 = directly behind the crew's heading
        return behind * 1000 - abs(v.length() - 650)


class HazardEvent(Event):
    kind = "hazard"

    def _find(self, sim):
        safety = self.d.cfg["safety"]
        c = self.d.obs_centroid(sim)
        if c is None:
            return None
        lvl = sim.level
        cands = []
        for r in lvl.rooms:
            rc = V(r.center[0] * TILE + TILE / 2, r.center[1] * TILE + TILE / 2)
            if rc.distance_to(c) > 1100 or r.id == lvl.spawn_room:
                continue
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    tx, ty = r.center[0] + dx, r.center[1] + dy
                    cands.append((tx, ty))
        best = None
        for tx, ty in cands:
            cells = [(tx + i, ty + j) for i in range(2) for j in range(2)]
            if not all(0 <= x < len(lvl.grid[0]) and 0 <= y < len(lvl.grid) and lvl.grid[y][x] == 1 and not lvl.blocked[y][x] for x, y in cells):
                continue
            pos = V((tx + 1) * TILE, (ty + 1) * TILE)
            ok, _ = pos_ok_for_threat(sim, pos, safety, clear=safety["hazard_clear"], radius=10)
            if not ok:
                continue
            # keep door approaches, relays, anchors and the extraction point free
            if any(pos.distance_to(d.center) < TILE * 3 for d in sim.doors):
                continue
            if any(pos.distance_to(o) < TILE * 4 for o in [r.pos for r in sim.relays] + [a.pos for a in sim.anchors] + [sim.extract_pos]):
                continue
            if any((f.rect.collidepoint(pos.x, pos.y)) for f in sim.floor_hazards):
                continue
            s = -abs(pos.distance_to(c) - 420)
            if best is None or s > best[0]:
                best = (s, tx, ty)
        return best

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if sum(1 for f in sim.floor_hazards if getattr(f, "director", False)) >= 2:
            return False, "hazard limit"
        if self._find(sim) is None:
            return False, "no valid hazard site"
        return True, ""

    def on_start(self, sim):
        _, tx, ty = self._find(sim)
        cycle = BAL.hazards.floor_cycle
        # phase chosen so the first cycle begins in "idle": idle + warning (4 s) precede the first damage
        phase = (-sim.time) % cycle
        self.hz = FloorHazard({"tx": tx, "ty": ty, "w": 2, "h": 2, "phase": phase})
        self.hz.director = True
        sim.floor_hazards.append(self.hz)
        self.pos = V(self.hz.rect.center)
        sim.emit("director", who="STATION AI", text="Floor conduits are cycling in a nearby room. They are marked.", ttl=4.0, source=self.label())

    def on_tick(self, sim, dt):
        # revalidate every frame: a ritual or a busy zone near the hazard retires it early
        z = busy_zones(sim, self.d.cfg["safety"])
        for zp, zr, why in z:
            if zp.distance_to(self.pos) < 300:
                self.d.note(f"{self.label()} retired early: {why} nearby")
                self.ends_at = sim.time
                return

    def on_cleanup(self, sim):
        hz = getattr(self, "hz", None)
        if hz in sim.floor_hazards:
            sim.floor_hazards.remove(hz)


class RouteClosureEvent(Event):
    kind = "route_closure"
    with_fault = False

    def _door(self, sim):
        idx = self.p.get("door")
        cand = [idx] if idx is not None else self.d.door_candidates(sim)
        safety = self.d.cfg["safety"]
        for i in cand:
            if i is None or i >= len(sim.doors):
                continue
            dr = sim.doors[i]
            if dr.kind != "normal" or dr.broken or dr.warn_t > 0 or dr.lock_t > 0:
                continue
            if any(p.pos.distance_to(dr.center) < 150 for p in alive_players(sim)):
                continue
            if any(zp.distance_to(dr.center) < safety["door_busy_radius"] for zp, _, _ in busy_zones(sim, safety)):
                continue
            if any(e.pos.distance_to(dr.center) < 80 for e in sim.enemies if not e.dead):
                continue
            if not connectivity_ok(sim, door_cells(dr)):
                continue
            return i
        return None

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if any(isinstance(e, RouteClosureEvent) and e.state == ACTIVE for e in self.d.events):
            return False, "a closure is already active"
        if any(d.lock_t > 0 or d.warn_t > 0 for d in sim.doors):
            return False, "a door is already glitching or locked"
        if self._door(sim) is None:
            return False, "no door can close while leaving an alternative route"
        return True, ""

    def on_start(self, sim):
        self.door_i = self._door(sim)
        dr = sim.doors[self.door_i]
        warn = max(self.p["warn"], self.d.cfg["safety"]["min_warn"])
        dr.warn_t = warn                        # the fracture door state machine locks it after the warning
        self.locked = False
        self.t_limit = sim.time + warn + 12.0
        self.ends_at = None
        self.check_t = 0.0
        sim.emit("door_glitch", pos=V(dr.center))
        if self.with_fault:
            self._make_fault(sim, dr)
        self.duration = self.p["duration"]
        self.ends_at = sim.time + warn + 12.0 + self.duration

    def _make_fault(self, sim, dr):
        c = self.d.obs_centroid(sim)
        best = None
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                tx, ty = int(dr.center.x // TILE) + dx, int(dr.center.y // TILE) + dy
                if max(abs(dx), abs(dy)) < 3:
                    continue
                pos = V(tx * TILE + TILE / 2, ty * TILE + TILE / 2)
                if not sim.solids.free_at(pos, 16):
                    continue
                s = -pos.distance_to(c) if c is not None else 0
                if best is None or s > best[0]:
                    best = (s, pos)
        pos = best[1] if best else V(dr.center)
        self.fault = Fault(pos, self.door_i)
        sim.faults.append(self.fault)
        sim.emit("director", who="STATION AI", text="Door power fault. A fuse panel nearby can reroute it.", ttl=5.0, source=self.label())

    def on_tick(self, sim, dt):
        dr = sim.doors[self.door_i]
        if not self.locked and dr.lock_t > 0:
            self.locked = True
            dr.lock_t = self.p["duration"] if not self.with_fault else self.p["duration"]
            self.ends_at = sim.time + dr.lock_t
            if hasattr(self, "fault"):
                self.fault.active = True
        if self.locked:
            self.check_t -= dt
            if self.check_t <= 0:
                self.check_t = 1.0
                if not connectivity_ok(sim):
                    self.d.note(f"{self.label()} unlocked early: route lost")
                    self.ends_at = sim.time
            f = getattr(self, "fault", None)
            if f is not None and f.repaired:
                self.d.note(f"{self.label()} repaired by the crew")
                self.ends_at = sim.time
        elif sim.time >= self.t_limit:
            self.ends_at = sim.time           # the door never locked (kept occupied): give up quietly

    def finished(self, sim):
        return sim.time >= self.ends_at

    def on_cleanup(self, sim):
        di = getattr(self, "door_i", None)
        if di is not None:
            dr = sim.doors[di]
            if not self.locked:
                dr.warn_t = 0.0
            elif dr.lock_t > 0.01:
                dr.lock_t = 0.01              # unlock through the normal state machine
        f = getattr(self, "fault", None)
        if f is not None and f in sim.faults:
            sim.faults.remove(f)


class PowerFailureEvent(RouteClosureEvent):
    kind = "power_failure"
    with_fault = True


class OptionalEncounterEvent(Event):
    """An elite group guarding a salvage cache in a room that holds nothing mandatory. Unalerted and far away: avoidable."""
    kind = "optional_encounter"

    def _room(self, sim):
        safety = self.d.cfg["safety"]
        lvl = sim.level
        busy_rooms = set()
        for r in sim.relays:
            if not r.online:
                busy_rooms.add(lvl.room_at(int(r.pos.x // TILE), int(r.pos.y // TILE)).id)
        for a in sim.anchors:
            busy_rooms.add(lvl.room_at(int(a.pos.x // TILE), int(a.pos.y // TILE)).id)
        busy_rooms |= {lvl.spawn_room, lvl.archive_room, lvl.extraction_room}
        best = None
        for r in lvl.rooms:
            if r.id in busy_rooms:
                continue
            c = V(r.center[0] * TILE + TILE / 2, r.center[1] * TILE + TILE / 2)
            if not sim.solids.free_at(c, 20):
                continue
            if any(p.pos.distance_to(c) < safety["optional_min_dist"] for p in alive_players(sim)):
                continue
            ok, _ = pos_ok_for_threat(sim, c, safety, clear=safety["optional_min_dist"])
            if not ok:
                continue
            if any(e.pos.distance_to(c) < 250 for e in sim.enemies if not e.dead):
                continue
            s = -min(p.pos.distance_to(c) for p in alive_players(sim))
            if best is None or s > best[0]:
                best = (s, r, c)
        return best

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if not self.d.room_for(sim, 3):
            return False, "enemy cap"
        if self._room(sim) is None:
            return False, "no suitable optional room"
        return True, ""

    def on_start(self, sim):
        _, room, c = self._room(sim)
        from src.entities.models import Enemy
        kinds = ["brute", "stalker", "crawler"]
        for i, k in enumerate(kinds):
            off = V(math.cos(i * 2.1), math.sin(i * 2.1)) * 40
            pos = c + off if sim.solids.free_at(c + off, BAL.enemies[k].radius) else V(c)
            e = Enemy(k, pos)
            e.director = True               # idle and unalerted: players choose whether to engage
            sim.enemies.append(e)
        for i in range(4):
            off = V(math.cos(i * 1.6 + 0.5), math.sin(i * 1.6 + 0.5)) * 70
            pos = c + off
            if sim.solids.free_at(pos, 10):
                sim.pickups.append(Pickup("salvage", pos, 1))
        self.room_name = room.name
        self.duration = 5.0
        self.ends_at = sim.time + 5.0
        sim.emit("director", who="MERIDIAN", text=f"Signal spike in {room.name}. Something is guarding supplies there.", ttl=7.0, source=self.label())


class ModifierEvent(Event):
    kind = "modifier"

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self.d.protect_now(sim):
            return False, "Rekindling is being protected"
        if self.d.speed_mult != 1.0:
            return False, "modifier already active"
        return True, ""

    def on_start(self, sim):
        m = self.d.cfg["modifier"]
        self.d.speed_mult, self.d.drop_mult = m["speed_mult"], m["drop_mult"]
        sim._refresh_speed()
        sim.emit("director", who="MERIDIAN", text="Station feedback loop: hostiles are quicker but drop more salvage for a while.", ttl=6.0, source=self.label())

    def on_cleanup(self, sim):
        self.d.speed_mult, self.d.drop_mult = 1.0, 1.0
        sim._refresh_speed()


# ======================================================================== neutral / recovery
class CompositionEvent(Event):
    kind = "composition"

    def on_start(self, sim):
        self.d.comp_bias = self.p["bias"]

    def on_cleanup(self, sim):
        if self.d.comp_bias == self.p["bias"]:
            self.d.comp_bias = None


class ResourceEvent(Event):
    kind = "resource"

    def _site(self, sim):
        safety = self.d.cfg["safety"]
        ps = alive_players(sim)
        if not ps:
            return None
        anchor_pos = self.p.get("near")
        base = V(anchor_pos) if anchor_pos is not None else self.d.obs_centroid(sim)
        lo, hi = self.p.get("ring", (220, 420))
        best = None
        for i in range(24):
            ang = i * math.tau / 24 + (self.d.rng.random() * 0.3)
            for r in (lo, (lo + hi) / 2, hi):
                pos = base + V(math.cos(ang), math.sin(ang)) * r
                if not sim.solids.free_at(pos, 12):
                    continue
                if any(zp.distance_to(pos) < 120 and why == "ritual" for zp, _, why in busy_zones(sim, safety)):
                    continue
                if not sim.solids.los(base, pos):
                    continue
                if any(e.pos.distance_to(pos) < 160 for e in sim.enemies if not e.dead):
                    continue
                s = -abs(r - (lo + hi) / 2) + self.d.rng.random()
                if best is None or s > best[0]:
                    best = (s, pos)
        return best[1] if best else None

    def validate(self, sim, phase):
        if not alive_players(sim):
            return False, "no living players"
        if self._site(sim) is None:
            return False, "no reachable drop site"
        return True, ""

    def on_start(self, sim):
        site = self._site(sim)
        self.items = []
        n = self.p["n"]
        for i in range(n):
            pos = site + V(math.cos(i * 2.4), math.sin(i * 2.4)) * (14 if n > 1 else 0)
            if not sim.solids.free_at(pos, 8):
                pos = V(site)
            pk = Pickup(self.p["pickup"], pos, 1)
            self.items.append(pk)
            sim.pickups.append(pk)
        self.d.flags.add("director_supplied")
        if self.p.get("say"):
            sim.emit("director", who="STATION AI", text=self.p["say"], ttl=5.0, source=self.label())

    def on_cleanup(self, sim):
        for pk in getattr(self, "items", []):
            if pk in sim.pickups and not pk.dead:
                sim.pickups.remove(pk)


class QuietEvent(Event):
    kind = "quiet"

    def on_cleanup(self, sim):
        self.d.last_quiet_end = sim.time

    def on_start(self, sim):
        self.d.quiet_until = max(self.d.quiet_until, sim.time + self.duration)
        sim.t_patrol = max(sim.t_patrol, self.duration)
        sim.t_surge = max(sim.t_surge, min(self.duration, 12.0))
        sim.t_glitch = max(sim.t_glitch, self.duration)
        if self.p.get("say"):
            sim.emit("director", who="STATION AI", text=self.p["say"], ttl=5.0, source=self.label())


EVENT_CLASSES = {c.kind: c for c in (ReinforceEvent, FlankEvent, HazardEvent, RouteClosureEvent, PowerFailureEvent,
                                      OptionalEncounterEvent, ModifierEvent, CompositionEvent, ResourceEvent, QuietEvent)}


# ======================================================================== authored story events
class StoryEngine:
    """Authored story events from data/director_story.json: id, preconditions, flags, triggers, cooldowns, effects, asset
    paths, text, clue prerequisites, follow-ups and a resolution rule. Memory callbacks come only from recorded events."""

    def __init__(self, director, data=None):
        self.d = director
        data = data or load_json("director_story.json")
        self.defs = {e["id"]: e for e in data["events"]}
        self.callbacks = data.get("callbacks", [])
        self.fired = {}              # id -> time
        self.resolved = set()
        self.waiting = {}            # id -> (resolve_event, deadline)
        self.followups = []          # (due, id)
        self.cb_used = set()
        self.timers = []             # (due, id): resolve after a delay

    # --- definition checks (used by tests) ---
    def validate_defs(self, asset_root):
        problems = []
        for e in self.defs.values():
            icon = e.get("icon")
            if icon and not (asset_root / icon).exists():
                problems.append(f"{e['id']}: missing asset {icon}")
            for f in e.get("follow_ups", []):
                if f["id"] not in self.defs:
                    problems.append(f"{e['id']}: unknown follow-up {f['id']}")
            for k in ("id", "text", "preconditions", "triggers", "cooldown", "effects", "resolution"):
                if k not in e:
                    problems.append(f"{e.get('id')}: missing {k}")
        return problems

    # --- evaluation ---
    def _pre_ok(self, e, now):
        c = e["preconditions"]
        sim = self.d.sim
        if now < c.get("min_time", 0) or now > c.get("max_time", 1e9):
            return False
        if sim.fracture < c.get("min_fracture", 0) or sim.fracture > c.get("max_fracture", 99):
            return False
        flags = self.d.flags
        if not set(c.get("flags_all", [])) <= flags or (set(c.get("flags_none", [])) & flags):
            return False
        known = set(getattr(sim, "known_logs", ())) | set(sim.logs_read)
        if not set(c.get("clues_all", [])) <= known:
            return False
        if c.get("clues_any") and not (set(c["clues_any"]) & known):
            return False
        if c.get("patterns_any") and not any(self.d.patterns[p].active for p in c["patterns_any"] if p in self.d.patterns):
            return False
        mt = c.get("memory_type")
        if mt and not self.d.memory.query(rtype=mt):
            return False
        return True

    def trigger(self, name, ctx=None, now=None):
        now = self.d.sim.time if now is None else now
        for e in self.defs.values():
            if name not in e["triggers"] or e["id"] in self.waiting:
                continue
            last = self.fired.get(e["id"])
            if last is not None and now - last < e["cooldown"]:
                continue
            if e["id"] in self.fired and e["cooldown"] >= 9999:
                continue
            if not self._pre_ok(e, now):
                continue
            self._fire(e, ctx or {}, now)

    def tick(self, now):
        self.trigger("tick", {}, now)
        due = [f for f in self.followups if f[0] <= now]
        self.followups = [f for f in self.followups if f[0] > now]
        for _, sid in due:
            e = self.defs[sid]
            if self._pre_ok(e, now) and sid not in self.fired:
                self._fire(e, {}, now)
            else:
                self.d.note(f"story follow-up {sid} dropped: preconditions not met")
        for due, sid in [t for t in self.timers if t[0] <= now]:
            self.timers.remove((due, sid))
            self._resolve(self.defs[sid], now)
        for sid, (ev, deadline) in list(self.waiting.items()):
            if now >= deadline:
                del self.waiting[sid]
                self.d.note(f"story {sid} timed out unresolved")

    def on_game_event(self, ev):
        n = ev["name"]
        for sid, (rev, deadline) in list(self.waiting.items()):
            if rev == n:
                del self.waiting[sid]
                self._resolve(self.defs[sid], self.d.sim.time)
        ctx = {}
        if "player" in ev and 0 <= ev["player"] < len(self.d.sim.players):
            ctx["name"] = self.d.sim.players[ev["player"]].name.split()[0]
        self.trigger(n, ctx)

    def _fire(self, e, ctx, now):
        self.fired[e["id"]] = now
        for fx in e["effects"]:
            self._effect(fx, e, ctx, now)
        r = e["resolution"]
        if r["kind"] == "instant":
            self._resolve(e, now)
        elif r["kind"] == "on_event":
            self.waiting[e["id"]] = (r["event"], now + r.get("timeout", 120.0))
        elif r["kind"] == "timer":
            self.timers.append((now + r["after"], e["id"]))
        self.d.note(f"story {e['id']} fired")

    def _resolve(self, e, now):
        self.resolved.add(e["id"])
        for f in e.get("follow_ups", []):
            self.followups.append((now + f["delay"], f["id"]))

    def _effect(self, fx, e, ctx, now):
        d, sim = self.d, self.d.sim
        op = fx["op"]
        if op == "say":
            text = e["text"].format(name=ctx.get("name", "the crew"))
            sim.emit("director", who=e.get("who", "MERIDIAN"), text=text, ttl=fx.get("ttl", 7.0), source=e["id"], icon=e.get("icon"))
        elif op == "banner":
            sim.emit("director", who="MERIDIAN", text=e["text"], banner=True, ttl=3.0, source=e["id"], icon=e.get("icon"))
        elif op == "set_flag":
            d.flags.add(fx["flag"])
        elif op == "memory":
            d.remember(fx.get("type", "story"), e["text"].format(name=ctx.get("name", "the crew")), fx.get("importance", 2),
                       entities=[f"story:{e['id']}"])
        elif op == "quiet":
            d.quiet_until = max(d.quiet_until, now + fx.get("seconds", 20))

    # --- memory callbacks (only from recorded events) ---
    def maybe_callback(self, now):
        sim = self.d.sim
        if now < 25.0:
            return
        for tpl in self.callbacks:
            if tpl["id"] in self.cb_used:
                continue
            cb = self.d.memory.make_callback(tpl, self.d.exp_id)
            if cb:
                self.cb_used.add(tpl["id"])
                sim.emit("director", who="MERIDIAN", text=cb["text"], ttl=8.0, source=cb["callback_id"], memory_ids=cb["source_ids"])
                self.d.note(f"callback {cb['callback_id']} from {cb['source_ids']}")
                return
