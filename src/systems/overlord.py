"""The finale: severing MERIDIAN's Core wakes its Avatar. The Avatar is shielded (it takes a sliver of damage) except in the
exposure windows the crew opens by overloading the three conduits around the Archive. While it lives it raises waves of
zombies, strikes the floor under the crew and folds a crew member away. Killing it is the only way to end the Director.
Everything is telegraphed; nothing here touches player health directly (slams and surges go through the combat module)."""
import math

import pygame

from src.config import BAL, load_json
from src.entities.models import Enemy, Telegraph
from src.settings import TILE
from src.systems import mission

V = pygame.Vector2
_CFG = None


def cfg():
    global _CFG
    if _CFG is None:
        _CFG = load_json("overlord.json")
    return _CFG


class Conduit:
    def __init__(self, cid, pos):
        self.id = cid
        self.pos = V(pos)
        self.progress = 0.0
        self.cool = 0.0              # >0: recharging after an overload
        self.flash = 0.0

    @property
    def ready(self):
        return self.cool <= 0


class OverlordState:
    def __init__(self):
        self.stage = 0               # 0 dormant, 2 avatar awake, 3 destroyed
        self.sever = 0.0
        self.avatar = None
        self.conduits = []
        self.exposed_t = 0.0
        self.wave_t = 0.0
        self.wave_n = 0
        self.arc_t = 0.0
        self.fold_t = 0.0
        self.fold = None             # (victim idx, fire time, telegraph)
        self.awake_t = 0.0
        self.phase = 1               # 1 Siege, 2 Foresight, 3 Lastlight (by Avatar health)
        self.guard_t = 0.0
        self.adapted = {}            # damage category -> adaptation level (MERIDIAN's doctrine)
        self.window = {}
        self.windows = 0
        self.seen = set()
        self.inherited = []
        self.dark_t = 0.0
        self.ghosts = 0


def crew(sim):
    return [p for p in sim.players if p.alive]


def damage_factor(sim, e, how="other"):
    ov = sim.overlord
    if ov is None or e is not ov.avatar:
        return 1.0
    base = 1.0 if ov.exposed_t > 0 else cfg()["avatar"]["shield_factor"]
    return base * learned_factor(ov, how)


# ------------------------------------------------------------------ doctrine: it learns how it is being hurt
def learned_factor(ov, how):
    """Each level of adaptation to a damage category cuts that category by `step`. It forgets a category the crew stops using."""
    return cfg()["doctrine"]["step"] ** ov.adapted.get(how, 0)


def note_damage(sim, e, amount, how):
    ov = sim.overlord
    if ov is None or e is not ov.avatar or ov.exposed_t <= 0:
        return
    if how not in ov.seen:
        # SURPRISED: something it has not seen this fight lengthens the window. It needs the unexpected, and it pays for it.
        ov.seen.add(how)
        if len(ov.seen) > 1:
            cap = cfg()["avatar"]["exposed_cap"]
            ov.exposed_t = min(cap, ov.exposed_t + cfg()["doctrine"]["novel_bonus"])
            sim.emit("surprised", pos=V(ov.avatar.pos), how=how)
    raw = amount / max(1e-6, learned_factor(ov, how))     # what the crew actually put out, before our resistance
    ov.window[how] = ov.window.get(how, 0.0) + raw


def _close_window(sim, ov):
    """Called when an exposure window ends: if one damage category did most of the work, MERIDIAN adapts to it; categories the
    crew did not lean on lose a level. A crew that mixes categories (shots, charges, blasts, surges) is never countered hard."""
    c = cfg()["doctrine"]
    tot = sum(ov.window.values())
    ov.windows += 1
    learned = None
    if tot >= c["min_total"]:
        top = max(ov.window, key=ov.window.get)
        if ov.window[top] / tot >= c["share"] and ov.adapted.get(top, 0) < c["max_level"]:
            ov.adapted[top] = ov.adapted.get(top, 0) + 1
            learned = top
    for k in list(ov.adapted):
        if k != learned and ov.window.get(k, 0.0) / max(1.0, tot) < c["share"] * 0.5 and ov.adapted[k] > 0:
            ov.adapted[k] -= 1
    ov.window = {}
    if learned:
        sim.emit("doctrine_learned", pos=V(ov.avatar.pos), how=learned, level=ov.adapted[learned])
        say(sim, "learned", learned)
        d = sim.director
        if d is not None and getattr(d, "memory", None) is not None:
            d.memory.record(d.exp_id, "doctrine", f"The Avatar learned to ignore {learned}.", 4, [f"doctrine:{learned}"],
                            t=sim.time, data={"how": learned})


def interact_targets(sim, p):
    """-> (label, progress, holder_key) for the sever Core or an overload conduit near this player, or None."""
    IR = BAL.player.interact_range
    ov = sim.overlord
    if ov is None:
        return None
    if ov.stage == 2:
        for c in ov.conduits:
            if p.pos.distance_to(c.pos) <= IR + 16:
                if c.ready:
                    return ("Hold INTERACT: overload conduit", c.progress, ("conduit", c.id))
                return ("Conduit recharging", 0.0, None)
    elif ov.stage == 0 and sim.exposed and sim.core_pos is not None and not sim.core_collected and p.pos.distance_to(sim.core_pos) <= IR + 10:
        return ("Hold INTERACT: sever MERIDIAN", ov.sever, ("sever", 0))
    return None


def update(sim, holders, dt):
    ov = sim.overlord
    if ov is None:
        return
    c = cfg()
    if ov.stage == 0:
        h = holders.get(("sever", 0), [])
        if h and sim.exposed:
            ov.sever = min(1.0, ov.sever + mission.hold_rate(sim, h) / c["sever_hold"] * dt)
            if ov.sever >= 1.0:
                _awaken(sim, ov)
        else:
            ov.sever = max(0.0, ov.sever - 0.3 * dt)
        return
    if ov.stage != 2:
        return
    ov.awake_t += dt
    was = ov.exposed_t
    ov.exposed_t = max(0.0, ov.exposed_t - dt)
    if was > 0 and ov.exposed_t <= 0 and ov.avatar is not None:
        _close_window(sim, ov)
    av = ov.avatar
    if av is None or av.dead:
        _destroyed(sim, ov)
        return
    for cd in ov.conduits:
        cd.flash = max(0.0, cd.flash - dt)
        if cd.cool > 0:
            cd.cool = max(0.0, cd.cool - dt)
            cd.progress = 0.0
            continue
        h = holders.get(("conduit", cd.id), [])
        if h:
            cd.progress = min(1.0, cd.progress + mission.hold_rate(sim, h) / c["conduits"]["hold"] * dt)
            if cd.progress >= 1.0:
                cd.progress, cd.cool, cd.flash = 0.0, c["conduits"]["recharge"], 0.6
                ov.exposed_t = min(c["avatar"]["exposed_cap"], ov.exposed_t + c["avatar"]["exposed_time"])
                sim.emit("conduit_overload", pos=V(cd.pos), exposed=ov.exposed_t)
                say(sim, "conduit")
        else:
            cd.progress = max(0.0, cd.progress - 0.5 * dt)
    _phase(sim, ov, dt)
    _waves(sim, ov, dt)
    _arcs(sim, ov, dt)
    _fold(sim, ov, dt)
    if ov.phase >= 2:
        _foresight(sim, ov, holders, dt)
    if ov.phase >= 3:
        _lastlight(sim, ov, dt)


PHASE_AT = {2: 0.66, 3: 0.33}
GHOST_NAMES = ["KESTREL", "ORIN", "VANTE", "LUMEN", "HALCYON", "SABLE", "TOLL", "WREN"]


def say(sim, key, sub=None, **fmt):
    """MERIDIAN speaks (a layered, personal voice; skippable text in the HUD, never blocks play)."""
    v = cfg()["voice"].get(key)
    if isinstance(v, dict):
        v = [v.get(sub, v.get("other", ""))]
    if not v:
        return
    line = v[sim.rng.randrange(len(v))].format(**fmt) if fmt else v[sim.rng.randrange(len(v))]
    sim.emit("director", who="MERIDIAN", text=line, ttl=7.0, source=f"avatar:{key}")


def generation(sim):
    d = sim.director
    mem = getattr(d, "memory", None) if d is not None else None
    return max(1, mem.expeditions) if mem is not None else 1


def _phase(sim, ov, dt):
    c = cfg()
    av = ov.avatar
    frac = av.hp / max(1.0, av.max_hp)
    nxt = ov.phase + 1
    if nxt in PHASE_AT and frac <= PHASE_AT[nxt]:
        ov.phase = nxt
        if ov.exposed_t > 0:
            ov.exposed_t = 0.0
            _close_window(sim, ov)
        ov.exposed_t = 0.0                       # the shield closes; every conduit has to be turned again
        for cd in ov.conduits:
            cd.cool, cd.progress, cd.flash = 0.0, 0.0, 0.8
        ov.wave_t = min(ov.wave_t, 4.0)
        sim.emit("overlord_phase", pos=V(av.pos), phase=nxt)
        say(sim, f"phase{nxt}")
        if nxt == 3:
            _summon_predecessors(sim, ov)


def _foresight(sim, ov, holders, dt):
    """Phase 2: MERIDIAN has read how the crew attacks it. A conduit being turned draws a telegraphed strike onto that
    spot every few seconds: step off the marked ring, or turn it in shifts."""
    c = cfg()["foresight"]
    ov.guard_t -= dt
    if ov.guard_t > 0:
        return
    for cd in ov.conduits:
        if cd.progress > 0.15 and holders.get(("conduit", cd.id)):
            ov.guard_t = c["interval"]
            sim.telegraphs.append(Telegraph("surge", V(cd.pos), c["warn"], c["radius"]))
            sim.emit("foresight", pos=V(cd.pos), conduit=cd.id)
            return


def _lastlight(sim, ov, dt):
    """Phase 3: the station goes dark in telegraphed pulses (the Director's own blackout rules apply: no spawns while it lasts)."""
    c = cfg()["lastlight"]
    ov.dark_t -= dt
    d = sim.director
    if ov.dark_t > 0 or d is None:
        return
    ov.dark_t = c["interval"]
    d.blackout = c["dark"]
    d.blackout_total = c["dark"]
    sim.emit("director", who="MERIDIAN", text="", ttl=0.1, source="lastlight")


def _summon_predecessors(sim, ov):
    """The crews MERIDIAN has already outlived come back as heavy hunters. One per previous generation (capped)."""
    c = cfg()["lastlight"]
    gen = generation(sim)
    n = int(min(c["ghost_cap"], c["ghost_base"] + (gen - 1) // c["ghost_per_gens"]))
    al = crew(sim)
    if not al:
        return
    ctr = sum((p.pos for p in al), V(0, 0)) / len(al)
    made = 0
    for i in range(n * 6):
        if made >= n:
            break
        ang = sim.rng.uniform(0, math.tau)
        pt = ctr + V(math.cos(ang), math.sin(ang)) * sim.rng.uniform(560, 820)
        if sim.solids.free_at(pt, 26) and all(p.pos.distance_to(pt) > 480 for p in al):
            sim.telegraphs.append(Telegraph("wave", pt, 3.0, 44, payload=["warden"]))
            made += 1
    ov.ghosts = made
    names = [GHOST_NAMES[(gen + i) % len(GHOST_NAMES)] for i in range(made)]
    sim.emit("predecessors", n=made, names=names)
    say(sim, "predecessors", names=", ".join(names[:3]))


def _awaken(sim, ov):
    c = cfg()
    ov.stage = 2
    sim.core_collected = True            # the Core is spent
    pos = V(sim.core_pos)
    av = Enemy("overlord", pos)
    av.hp = av.max_hp = av.spec.hp * c["avatar"]["hp_mult"] * min(1.6, 1.0 + 0.06 * (generation(sim) - 1))
    av.state = "chase"
    av.alert_t = 1e9
    sim.enemies.append(av)
    ov.avatar = av
    room = sim.level.rooms[sim.level.archive_room]
    cx, cy = room.center
    ctr = V(cx * TILE + TILE / 2, cy * TILE + TILE / 2)
    n = c["conduits"]["count"]
    ov.conduits = []
    for i in range(n):
        for r in (c["conduits"]["ring"][1], c["conduits"]["ring"][0], 220, 160):
            ang = i * math.tau / n + 0.5
            pt = V(pos) + V(math.cos(ang), math.sin(ang)) * r
            if sim.solids.free_at(pt, 20):
                ov.conduits.append(Conduit(i, pt))
                break
        else:
            ov.conduits.append(Conduit(i, V(ctr) + V(math.cos(i * 2.1), math.sin(i * 2.1)) * 120))
    ov.wave_t, ov.arc_t, ov.fold_t = c["waves"]["interval"] * 0.5, 3.0, c["fold"]["first"]
    _inherit(sim, ov)
    sim.emit("overlord_awake", pos=V(pos))
    say(sim, "awake")


def _inherit(sim, ov):
    """Across generations: MERIDIAN walks into this fight already resisting what hurt it the last time (level 1, and only the most
    recent lesson per category). The crew sees it in the opening line. Same tactic as last run: already half-answered."""
    d = sim.director
    mem = getattr(d, "memory", None) if d is not None else None
    if mem is None:
        return
    prior = [r for r in mem.query("doctrine") if r["exp"] != d.exp_id]
    last = {}
    for r in prior:
        k = r.get("data", {}).get("how")
        if k:
            last[k] = r["exp"]
    if not last:
        return
    newest = max(last.values())
    for k, e in last.items():
        if e >= newest - 1:
            ov.adapted[k] = 1
            ov.inherited.append(k)
    if ov.inherited:
        sim.emit("doctrine_inherited", how=list(ov.inherited))
        say(sim, "inherited", how=ov.inherited[0])


def _destroyed(sim, ov):
    ov.stage = 3
    say(sim, "destroyed")
    sim.emit("overlord_destroyed", pos=V(ov.avatar.pos) if ov.avatar else V(sim.core_pos))
    sim.finish("director_destroyed")


def _waves(sim, ov, dt):
    c = cfg()["waves"]
    ov.wave_t -= dt
    if ov.wave_t > 0:
        return
    ov.wave_t = c["interval"]
    ov.wave_n += 1
    al = crew(sim)
    if not al:
        return
    kinds = ["drifter"] * (c["normal"] * 6 // 10) + ["crawler"] * (c["normal"] - c["normal"] * 6 // 10)
    if ov.wave_n % c["giant_every"] == 0:
        kinds.append("giant")
    ctr = sum((p.pos for p in al), V(0, 0)) / len(al)
    for k in range(2):
        for _ in range(20):
            ang = sim.rng.uniform(0, math.tau)
            pt = ctr + V(math.cos(ang), math.sin(ang)) * sim.rng.uniform(520, 760)
            if sim.solids.free_at(pt, 20) and all(p.pos.distance_to(pt) > 440 for p in al):
                sim.telegraphs.append(Telegraph("wave", pt, c["warn"], 40, payload=kinds[k::2]))
                sim.emit("spawn_warning", pos=V(pt), kind="avatar")
                break


def _arcs(sim, ov, dt):
    c = cfg()["arc"]
    ov.arc_t -= dt
    if ov.arc_t > 0:
        return
    ov.arc_t = c["interval"]
    al = crew(sim)
    if al:
        t = al[sim.rng.randrange(len(al))]
        sim.telegraphs.append(Telegraph("surge", V(t.pos), c["warn"], c["radius"]))


def _fold(sim, ov, dt):
    c = cfg()["fold"]
    if ov.fold is not None:
        idx, t_fire, tele = ov.fold
        v = sim.players[idx]
        tele.pos = V(v.pos)
        if sim.time >= t_fire or not v.alive:
            tele.dead = True
            ov.fold = None
            d = sim.director
            if v.alive and d is not None:
                from src.systems.director_surprises import IsolateEvent
                probe = IsolateEvent(0, d, {"warn": 0.0}, sim.time, 0.0, "avatar", d.obs_id)
                dest = probe._dest(sim, v)
                if dest is not None:
                    src = V(v.pos)
                    v.pos = V(dest)
                    sim.emit("teleport", pos=V(dest), src=src, player=v.idx)
        return
    ov.fold_t -= dt
    if ov.fold_t > 0 or len([p for p in crew(sim)]) < 2:
        return
    ov.fold_t = c["interval"]
    al = [p for p in crew(sim) if p.interact_progress <= 0 and not getattr(p, "channeling", False) and p.carry is None]
    if not al:
        return
    v = al[sim.rng.randrange(len(al))]
    tele = Telegraph("isolate", V(v.pos), c["warn"], 70)
    sim.telegraphs.append(tele)
    ov.fold = (v.idx, sim.time + c["warn"], tele)
    sim.emit("isolate_warning", pos=V(v.pos), player=v.idx)
