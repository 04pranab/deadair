"""Operable machines. Each has a clear loop: see what it offers, pay or risk something, get a consequence, and have a reason to
use it again in a different situation. They also combine (Ward + Emitter strip the Host's Veil together, the Beacon drags a
horde onto the Incinerator's corridor, the Switchboard's locks are exactly what a Host must win a click contest to break).

Per-machine state lives on the Machine object; all effects go through existing systems (door locks, enemy targeting, Rift)."""
import math

import pygame

from src.config import BAL, load_json
from src.systems import combat

V = pygame.Vector2
_CFG = None


def cfg():
    global _CFG
    if _CFG is None:
        _CFG = load_json("machines.json")
    return _CFG


class Machine:
    def __init__(self, mid, kind, pos, room):
        self.id = mid
        self.kind = kind
        self.pos = V(pos)
        self.room = room
        self.cd = 0.0
        self.active_t = 0.0
        self.progress = 0.0      # incinerator burn
        self.flash = 0.0
        self.warn_t = 0.0        # beacon: time to detonation
        self.reading = None      # gauge: what the last reading said
        self.users = 0

    @property
    def spec(self):
        return cfg()[self.kind]

    @property
    def ready(self):
        return self.cd <= 0 and self.active_t <= 0


def nearest(sim, pos, kind=None, rad=1e9):
    best, bd = None, rad
    for m in sim.machines:
        if kind is not None and m.kind != kind:
            continue
        d = m.pos.distance_to(pos)
        if d < bd:
            best, bd = m, d
    return best


def in_ward(sim, pos):
    return any(m.kind == "ward" and m.active_t > 0 and m.pos.distance_to(pos) <= m.spec["radius"] for m in sim.machines)


def emitter_hits(sim, pos):
    return any(m.kind == "emitter" and m.active_t > 0 and m.pos.distance_to(pos) <= m.spec["radius"] for m in sim.machines)


def veil_suppressed(sim, host_pos):
    return in_ward(sim, host_pos) or emitter_hits(sim, host_pos)


def enemy_speed_factor(sim, e):
    for m in sim.machines:
        if m.kind == "ward" and m.active_t > 0 and m.pos.distance_to(e.pos) <= m.spec["radius"]:
            return m.spec["slow"]
    return 1.0


# ------------------------------------------------------------------ interaction (tap-type)
def label(sim, m, p):
    s = m.spec
    if m.kind == "incinerator":
        return "Hold INTERACT: burn paper" if p.paper is not None else "Incinerator (needs a Rift paper)"
    if m.cd > 0 or m.active_t > 0:
        t = m.active_t if m.active_t > 0 else m.cd
        return f"{s['name']}: {'active' if m.active_t > 0 else 'recharging'} {t:0.0f}s"
    cost = f" ({s['cost']} salvage)" if s.get("cost") else ""
    return f"INTERACT: {s['name']}{cost}"


def use(sim, m, p):
    """Tap interaction. Returns True if something happened."""
    s = m.spec
    if m.kind == "incinerator" or m.cd > 0 or m.active_t > 0:
        return False
    cost = s.get("cost", 0)
    if sim.team_salvage < cost:
        sim.emit("machine_denied", pos=V(m.pos), machine=m.id, reason="salvage")
        return False
    fn = {"ward": _ward, "gauge": _gauge, "switchboard": _switch, "breaker": _breaker, "beacon": _beacon, "emitter": _emitter}[m.kind]
    if not fn(sim, m, p):
        sim.emit("machine_denied", pos=V(m.pos), machine=m.id, reason="no effect")
        return False
    sim.team_salvage -= cost
    m.users += 1
    m.flash = 0.5
    glitch = _maybe_glitch(sim, m)
    sim.emit("machine_used", pos=V(m.pos), machine=m.id, kind=m.kind, player=p.idx)
    return True


GLITCH_BASE, GLITCH_PER_FRACTURE = 0.08, 0.02


def glitch_chance(sim):
    """The station is not stable: the more Fracture, the likelier a machine misbehaves. Capped so machines stay worth using."""
    return min(0.30, GLITCH_BASE + GLITCH_PER_FRACTURE * getattr(sim, "fracture", 0))


def _maybe_glitch(sim, m):
    """A machine may misfire in a way that is always announced (banner + sparks) and always bounded. Seeded per machine and use,
    so the same seed and the same play give the same glitches, but nothing a crew did last run predicts the next one."""
    import random
    if m.kind == "incinerator":
        return None
    rng = random.Random(sim.seed * 7919 + m.id * 104729 + m.users * 1299709)
    if rng.random() >= glitch_chance(sim):
        return None
    how = {"ward": "flicker", "emitter": "sputter", "gauge": "lie", "switchboard": "crossed", "breaker": "overload", "beacon": "early"}[m.kind]
    if how in ("flicker", "sputter"):
        m.active_t *= 0.5
    elif how == "lie":
        if m.reading:
            m.reading = dict(m.reading, band=rng.choice(["LOW", "RISING", "CRITICAL"]),
                             forecast=[sim.director.plausible_wrong(k, rng) for k in m.reading["forecast"]] if sim.director else [], lied=True)
    elif how == "crossed":
        far = sorted([d for d in sim.doors if d.kind == "normal" and not d.broken and not d.sealed and d.center.distance_to(m.pos) < m.spec["reach"]],
                     key=lambda d: -d.center.distance_to(m.pos))[:1]
        for d in far:
            if not any(q.pos.distance_to(d.center) < 80 for q in sim.players) and d.lock_t <= 0 and d.warn_t <= 0:
                d.crew_lock, d.lock_t, d.contest = not d.crew_lock, m.spec["duration"] * 0.5, 0.0
    elif how == "overload":
        for e in sim.enemies:
            if not e.dead and e.kind != "overlord" and e.pos.distance_to(m.pos) < m.spec["alert_radius"] * 1.6:
                e.alert_t = max(e.alert_t, 5.0)
    elif how == "early":
        m.active_t = max(m.spec["warn"] + 0.5, m.active_t * 0.55)
    sim.emit("machine_glitch", pos=V(m.pos), machine=m.id, kind=m.kind, how=how)
    return how


def _ward(sim, m, p):
    m.active_t = m.spec["duration"]
    m.cd = m.spec["cooldown"]
    return True


def _emitter(sim, m, p):
    m.active_t = m.spec["duration"]
    m.cd = m.spec["cooldown"]
    return True


def _gauge(sim, m, p):
    """Incomplete information: a pressure band and the two likeliest next events, each reading right with probability
    `accuracy` (otherwise it names a plausible wrong one). Using it taints the user: the Gauge looks back."""
    from src.systems import rift
    s = m.spec
    d = sim.director
    pr = rift.pressure(sim, sim.time)
    band = "LOW" if pr < 0.34 else ("RISING" if pr < 0.8 else "CRITICAL")
    forecast = []
    if d is not None:
        kinds = d.forecast(3)
        for k in kinds[:2]:
            if sim.rng.random() > s["accuracy"]:
                k = d.plausible_wrong(k, sim.rng)
            forecast.append(k)
    m.reading = {"band": band, "forecast": forecast, "t": sim.time}
    m.active_t = s["duration"]
    m.cd = s["cooldown"]
    sim.emit("gauge_used", pos=V(m.pos), player=p.idx, band=band, forecast=list(forecast))
    return True


def _switch(sim, m, p):
    s = m.spec
    near = sorted([d for d in sim.doors if d.kind == "normal" and not d.broken and not d.sealed and d.center.distance_to(m.pos) < s["reach"]],
                  key=lambda d: d.center.distance_to(m.pos))[:2]
    if not near:
        return False
    locked = [d for d in near if d.crew_lock]
    if locked:
        for d in locked:
            d.crew_lock, d.lock_t, d.contest = False, 0.01, 0.0
    else:
        n = 0
        for d in near:
            if d.lock_t <= 0 and d.warn_t <= 0 and not any(abs(q.pos.x - d.center.x) < 40 and abs(q.pos.y - d.center.y) < 40 for q in sim.players):
                d.crew_lock, d.lock_t, d.contest = True, s["duration"], 0.0
                n += 1
        if n == 0:
            return False
    m.cd = s["cooldown"]
    return True


def _breaker(sim, m, p):
    s = m.spec
    d = sim.director
    had = d is not None and d.blackout > 0
    if d is not None and d.blackout > 0:
        d.blackout = 0.0
        sim.emit("blackout_end")
    n = 0
    for e in sim.enemies:
        if not e.dead and e.kind != "overlord" and e.pos.distance_to(m.pos) < s["alert_radius"]:
            e.alert_t = max(e.alert_t, 6.0)
            e.state = "chase" if e.state == "idle" else e.state
            n += 1
    m.cd = s["cooldown"]
    sim.emit("breaker_surge", pos=V(m.pos), woke=n, ended_blackout=had)
    return True


def _beacon(sim, m, p):
    m.active_t = m.spec["duration"]
    m.warn_t = m.spec["warn"]
    m.cd = m.spec["cooldown"] + m.spec["duration"]
    sim.emit("beacon_on", pos=V(m.pos))
    return True


def beacon_target(sim, e):
    """An active Beacon draws awake zombies (not bosses, not the Host's marked prey)."""
    if e.kind in ("warden", "overlord") or e.spec.behavior == "ranged":
        return None
    for m in sim.machines:
        if m.kind == "beacon" and m.active_t > m.spec["warn"] and m.pos.distance_to(e.pos) <= m.spec["pull_radius"]:
            return m
    return None


# ------------------------------------------------------------------ hold-type (incinerator) and per-frame update
def hold_target(sim, p):
    m = nearest(sim, p.pos, "incinerator", BAL.player.interact_range + 24)
    if m is None or p.paper is None:
        return None
    return (f"Hold INTERACT: burn paper", m.progress, m)


def update(sim, frames, dt):
    if not sim.machines:
        return
    from src.systems import rift
    for m in sim.machines:
        m.flash = max(0.0, m.flash - dt)
        if m.kind == "incinerator":
            holders = [p for p in sim.players if p.alive and p.paper is not None and (frames.get(p.idx) is not None and frames[p.idx].interact_held)
                       and m.pos.distance_to(p.pos) <= BAL.player.interact_range + 24]
            if holders:
                m.progress = min(1.0, m.progress + dt / m.spec["hold"])
                if m.progress >= 1.0:
                    m.progress = 0.0
                    rift.burn_paper(sim, holders[0])
                    m.flash = 0.6
            else:
                m.progress = max(0.0, m.progress - dt * 1.5)
            continue
        if m.active_t > 0:
            m.active_t = max(0.0, m.active_t - dt)
            if m.kind == "beacon":
                _beacon_tick(sim, m, dt)
        elif m.cd > 0:
            m.cd = max(0.0, m.cd - dt)
        if m.kind in ("ward", "gauge", "emitter") and m.active_t <= 0 and m.cd > 0:
            pass
    # the Emitter acts on the Host
    h = sim.host
    if h is not None and h.host is not None and emitter_hits(sim, h.pos):
        h.host.hold = 0.0                         # a summon being channelled is interrupted
        h.host.charge = max(0.0, h.host.charge - 0.02 * dt * 60 * dt)


def _beacon_tick(sim, m, dt):
    s = m.spec
    if m.active_t <= s["warn"] and m.warn_t > 0:
        m.warn_t = m.active_t
    if m.active_t <= 0:
        r = s["blast_radius"]
        for e in sim.enemies:
            if not e.dead and e.pos.distance_to(m.pos) <= r:
                combat.damage_enemy(sim, e, s["blast_damage"], how="blast")
        for p in sim.players:
            if p.alive and p.pos.distance_to(m.pos) <= r:
                combat.damage_player(sim, p, s["blast_damage"] * 0.4, kind="beacon")
        sim.emit("slam", pos=V(m.pos), radius=r)
