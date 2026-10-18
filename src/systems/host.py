"""The Host: a crew member the Director has rewritten. The Host is still a player (a person holds the controller), but now
plays against the crew with a zombie body and command over the horde.

 * state "host" is not "alive": every crew rule (targeting, hazards, extraction, relays, director observation) already
   ignores it, so the Host never leaks into crew logic.
 * claw / lunge / mark / summon / door-contest map onto the same InputFrame every other player uses.
 * the crew can shoot the Host; at zero health the person is cured and the horde it summoned dissolves.
 * crew can lock doors once the Director is exposed; only a Host can contest a locked door (a click contest). Zombies cannot.
Deterministic: no randomness here, apart from the optional AI brain which takes the sim's own rng."""
import math

import pygame

from src.config import load_json
from src.entities.models import Enemy, Telegraph
from src.settings import TILE
from src.systems import combat, nav

V = pygame.Vector2
_CFG = None


def cfg():
    global _CFG
    if _CFG is None:
        _CFG = load_json("host.json")
    return _CFG


class HostState:
    def __init__(self, crew):
        c = cfg()
        self.claw_cd = 0.0
        self.lunge_cd = 0.0
        self.lunge_t = 0.0
        self.lunge_dir = V(1, 0)
        self.lunge_hit = set()
        self.mark_cd = 0.0
        self.charge = 0.0                 # summon charge 0..1
        self.summon_cd = 0.0
        self.hold = 0.0                   # seconds the summon is being channelled
        self.swing = 0.0                  # visual: claw swing timer
        self.roar = 0.0
        self.crew_at_birth = crew
        self.born_t = 0.0
        self.veil_down_t = 0.0            # >0: the Veil is broken
        self.veil_win = 0.0               # raw damage taken in the recent burst window
        self.veil_win_t = 0.0


def crew_alive(sim):
    return [p for p in sim.players if p.alive]


def host_hp(crew_n):
    c = cfg()
    return c["hp_base"] + c["hp_per_crew"] * max(1, crew_n)


# ------------------------------------------------------------------ conversion / cure
def convert(sim, p, source="director"):
    """The person becomes the Host. Their carried Echo is dropped; nothing else of the crew is touched."""
    c = cfg()
    crew = len(crew_alive(sim)) - 1
    if p.carry is not None:
        p.carry.state = "dropped"
        p.carry.carrier = None
        p.carry.pos = V(p.pos)
        p.carry = None
    p.state = "host"
    p.max_hp = host_hp(crew)
    p.hp = float(p.max_hp)
    p.radius = c["radius"]
    p.host = HostState(crew)
    p.host.born_t = sim.time
    p.iframes = 0.0
    p.dodge_t = 0.0
    p.charge_t = 0.0
    p.interact_progress = 0.0
    p.channeling = False
    sim.host = p
    sim.hosts_made += 1
    sim.horde_idx, sim.horde_t = None, 0.0
    sim.emit("host_born", pos=V(p.pos), player=p.idx, source=source)


def cure(sim, p):
    """The Host is put down: the person is restored, the horde it raised dissolves."""
    c = cfg()
    p.state = "alive"
    p.host = None
    from src.config import BAL
    spec = BAL.roles[p.role]
    p.max_hp = spec.hp
    p.hp = p.max_hp * c["cure"]["hp_frac"]
    p.radius = BAL.player.radius
    p.weak_t = c["cure"]["weak"]
    p.iframes = 1.0
    sim.host = None
    sim.horde_idx, sim.horde_t = None, 0.0
    n = 0
    for e in sim.enemies:
        if getattr(e, "horde", False) and not e.dead:
            e.dead = True               # dissolved: no salvage, not a kill
            n += 1
    sim.summon_queue = []
    sim.emit("host_cured", pos=V(p.pos), player=p.idx, dissolved=n)


def veil_up(sim, p):
    """The Veil absorbs most damage. It is OFF while: it was just broken by a burst, a Ward/Emitter covers the Host, the Host is
    channelling a summon, or the Host has just lunged (its overextension windows). Otherwise it is on."""
    from src.systems import machines
    c = cfg()["veil"]
    h = p.host
    if h is None or h.veil_down_t > 0 or h.hold > 0:
        return False
    if h.lunge_cd >= cfg()["lunge"]["cooldown"] - c["lunge_window"]:
        return False
    if sim.machines and machines.veil_suppressed(sim, p.pos):
        return False
    return True


def _through_veil(sim, p, amount):
    c = cfg()["veil"]
    h = p.host
    now = sim.time
    if now - h.veil_win_t > c["window"]:
        h.veil_win = 0.0
    h.veil_win_t = now
    h.veil_win += amount
    if veil_up(sim, p):
        if h.veil_win >= c["burst"]:
            h.veil_down_t = c["down"]
            h.veil_win = 0.0
            sim.emit("host_veil_broken", pos=V(p.pos), player=p.idx)
            return amount
        return amount * c["factor"]
    return amount


def damage_host(sim, p, amount, source=None):
    if p.state != "host" or amount <= 0:
        return 0.0
    amount = _through_veil(sim, p, amount)
    p.hp -= amount
    p.flash = 0.12
    if source is not None and hasattr(source, "kills"):
        pass
    sim.emit("host_hit", pos=V(p.pos), amount=amount, player=p.idx)
    if p.hp <= 0:
        cure(sim, p)
    return amount


# ------------------------------------------------------------------ the Host's own update (called for state == "host")
def update_host(sim, p, f, dt):
    c = cfg()
    h = p.host
    h.claw_cd = max(0.0, h.claw_cd - dt)
    h.lunge_cd = max(0.0, h.lunge_cd - dt)
    h.mark_cd = max(0.0, h.mark_cd - dt)
    h.summon_cd = max(0.0, h.summon_cd - dt)
    h.swing = max(0.0, h.swing - dt)
    if h.veil_down_t > 0:
        h.veil_down_t = max(0.0, h.veil_down_t - dt)
    h.roar = max(0.0, h.roar - dt)
    p.flash = max(0.0, p.flash - dt)
    if h.summon_cd <= 0 and h.charge < 1.0:
        h.charge = min(1.0, h.charge + dt / c["summon"]["charge_time"])
    move = V(f.mx, f.my)
    if move.length_squared() > 1:
        move = move.normalize()
    aim = V(f.aim_x, f.aim_y)
    if aim.length_squared() > 0.09:
        p.facing = aim.normalize()
    elif move.length_squared() > 0.01:
        p.facing = move.normalize()
    p.moving = False
    if h.lunge_t > 0:
        h.lunge_t -= dt
        p.pos, _, _, _ = sim.solids.move(p.pos, h.lunge_dir * c["lunge"]["speed"] * dt, p.radius)
        p.moving = True
        for q in crew_alive(sim):
            if q.idx not in h.lunge_hit and q.pos.distance_to(p.pos) < q.radius + p.radius + 10:
                h.lunge_hit.add(q.idx)
                combat.damage_player(sim, q, c["lunge"]["damage"], kind="host")
                q.pos, _, _, _ = sim.solids.move(q.pos, h.lunge_dir * 60, q.radius)
    else:
        if f.dodge and h.lunge_cd <= 0:
            h.lunge_dir = move.normalize() if move.length_squared() > 0.01 else V(p.facing)
            h.lunge_t = c["lunge"]["time"]
            h.lunge_cd = c["lunge"]["cooldown"]
            h.lunge_hit = set()
            sim.emit("host_lunge", pos=V(p.pos), dir=V(h.lunge_dir), player=p.idx)
        elif move.length_squared() > 0.001:
            p.pos, _, _, _ = sim.solids.move(p.pos, move * c["speed"] * dt, p.radius)
            p.moving = True
            p.walk_phase += c["speed"] * dt * 0.05
        if f.fire and h.claw_cd <= 0:
            _claw(sim, p, h)
    if f.ability and h.mark_cd <= 0:
        _mark(sim, p, h)
    # summon: hold the interact button away from any door, once charged
    near_door = _door_in_reach(sim, p) is not None
    if f.interact_held and not near_door and h.charge >= 1.0 and h.summon_cd <= 0:
        h.hold += dt
        h.roar = 0.2
        if h.hold >= c["summon"]["hold"]:
            _summon(sim, p, h)
            h.hold = 0.0
    else:
        h.hold = max(0.0, h.hold - dt * 2)
    for q in sim.players:                  # a Host never overlaps a living crew member
        if q.alive:
            d = p.pos - q.pos
            L = d.length()
            if 0 < L < p.radius + q.radius:
                p.pos, _, _, _ = sim.solids.move(p.pos, d / L * (p.radius + q.radius - L) * 0.5, p.radius)


def _claw(sim, p, h):
    c = cfg()["claw"]
    h.claw_cd = c["cooldown"]
    h.swing = 0.25
    d = V(p.facing) if p.facing.length_squared() else V(1, 0)
    d = d.normalize()
    hit = 0
    for q in crew_alive(sim):
        to = q.pos - p.pos
        L = to.length()
        if L <= c["range"] + q.radius and L > 0 and abs(_angle(d, to.normalize())) <= c["arc"] / 2 and sim.solids.los(p.pos, q.pos):
            if combat.damage_player(sim, q, c["damage"], kind="host") > 0:
                hit += 1
                q.pos, _, _, _ = sim.solids.move(q.pos, to.normalize() * c["knock"], q.radius)
    for b in sim.barricades:
        if V(b.rect.center).distance_to(p.pos) < c["range"] + 24:
            b.hp -= c["damage"] * 2
            if b.hp <= 0:
                b.dead = True
    if hit:
        p.host.charge = min(1.0, p.host.charge + cfg()["summon"]["hit_charge"] * hit)
    sim.emit("host_claw", pos=V(p.pos), dir=V(d), hit=hit)


def _angle(a, b):
    return math.atan2(a.x * b.y - a.y * b.x, a.dot(b))


def _mark(sim, p, h):
    c = cfg()["mark"]
    d = V(p.facing) if p.facing.length_squared() else V(1, 0)
    best, bs = None, 1e9
    for q in crew_alive(sim):
        to = q.pos - p.pos
        L = to.length()
        if L > c["range"] or L == 0:
            continue
        score = L * (1.0 + 1.5 * (1 - max(0.0, d.dot(to.normalize()))))      # prefer the one the Host is looking at
        if score < bs:
            best, bs = q, score
    if best is None:
        return False
    h.mark_cd = c["cooldown"]
    sim.horde_idx, sim.horde_t = best.idx, c["duration"]
    h.roar = 0.8
    sim.emit("host_mark", pos=V(best.pos), player=best.idx, by=p.idx)
    return True


def _summon(sim, p, h):
    c = cfg()["summon"]
    alive = sum(1 for e in sim.enemies if not e.dead)
    room = max(0, c["cap"] - alive)
    n_norm = min(c["normal"], max(0, room - c["giants"]))
    n_giant = min(c["giants"], room)
    kinds = (["drifter"] * (n_norm * 6 // 10) + ["crawler"] * (n_norm - n_norm * 6 // 10))
    # giants arrive first-ish, interleaved with the normal ones so the wave has a spine
    queue = []
    gi = 0
    step = max(1, len(kinds) // max(1, n_giant))
    for i, k in enumerate(kinds):
        if gi < n_giant and i % step == 0:
            queue.append("giant")
            gi += 1
        queue.append(k)
    queue += ["giant"] * (n_giant - gi)
    sim.summon_queue = queue
    sim.summon_t = 0.0
    sim.summon_origin = V(p.pos)
    h.charge, h.summon_cd = 0.0, c["cooldown"]
    h.roar = 2.0
    sim.emit("host_summon", pos=V(p.pos), normal=n_norm, giants=n_giant)


def _free_ring_pos(sim, origin, rng, r_lo, r_hi, radius, avoid, tries=14):
    for _ in range(tries):
        ang = rng.uniform(0, math.tau)
        pos = V(origin) + V(math.cos(ang), math.sin(ang)) * rng.uniform(r_lo, r_hi)
        if not sim.solids.free_at(pos, radius):
            continue
        if any(q.pos.distance_to(pos) < avoid for q in crew_alive(sim)):
            continue
        return pos
    return None


def update_summon(sim, dt):
    q = getattr(sim, "summon_queue", None)
    if not q:
        return
    c = cfg()["summon"]
    sim.summon_t -= dt
    if sim.summon_t > 0:
        return
    sim.summon_t = c["batch_gap"]
    org = sim.summon_origin
    for _ in range(min(c["batch"], len(q))):
        kind = q.pop(0)
        r = Enemy_radius(kind)
        pos = _free_ring_pos(sim, org, sim.rng, c["ring"][0], c["ring"][1], r, c["min_crew_dist"])
        if pos is None:
            continue
        e = Enemy(kind, pos)
        e.state = "chase"
        e.alert_t = 1e9
        e.horde = True
        sim.enemies.append(e)


def Enemy_radius(kind):
    from src.config import BAL
    return BAL.enemies[kind].radius


# ------------------------------------------------------------------ doors: crew lock + Host click contest
def _door_in_reach(sim, p):
    reach = cfg()["door"]["reach"]
    best, bd = None, 1e9
    for i, d in enumerate(sim.doors):
        if d.kind != "normal" or d.broken:
            continue
        dist = d.center.distance_to(p.pos)
        if dist < reach and dist < bd:
            best, bd = i, dist
    return best


def update_doors(sim, frames, dt):
    c = cfg()["door"]
    for p in sim.players:
        f = frames.get(p.idx)
        p.lock_cool = max(0.0, getattr(p, "lock_cool", 0.0) - dt)
        if f is None or not p.alive or not getattr(sim, "crew_lock_enabled", False):
            p.lock_hold = 0.0
            continue
        di = _door_in_reach(sim, p)
        lockable = di is not None and f.interact_held and p.interact_progress <= 0 and p.interact_target is None and p.lock_cool <= 0
        if not lockable:
            p.lock_hold = 0.0
            continue
        p.lock_hold = getattr(p, "lock_hold", 0.0) + dt
        if p.lock_hold < c["lock_time"]:
            continue
        p.lock_hold, p.lock_cool = 0.0, 1.5                  # one toggle per press
        d = sim.doors[di]
        if d.sealed:
            continue
        if d.crew_lock:
            d.crew_lock, d.lock_t, d.contest = False, 0.01, 0.0
            sim.emit("door_unlocked", pos=V(d.center))
        elif d.lock_t <= 0 and d.warn_t <= 0 and not any(abs(q.pos.x - d.center.x) < 40 and abs(q.pos.y - d.center.y) < 40 for q in sim.players):
            d.crew_lock, d.lock_t, d.contest = True, c["lock_duration"], 0.0
            sim.emit("door_crew_locked", pos=V(d.center), player=p.idx)
    for d in sim.doors:
        if not d.crew_lock:
            d.contest = 0.0
            continue
        if d.lock_t <= 0:
            d.crew_lock, d.contest = False, 0.0
            continue
        d.contest = max(0.0, d.contest - c["decay"] * dt)
        for p in sim.players:
            f = frames.get(p.idx)
            if f is None or not f.interact or p.pos.distance_to(d.center) > c["reach"]:
                continue
            if p.state == "host":
                d.contest = min(1.2, d.contest + c["host_tap"])
                sim.emit("door_contest", pos=V(d.center), value=d.contest, side="host")
            elif p.alive:
                d.contest = max(0.0, d.contest - c["crew_tap"])
                sim.emit("door_contest", pos=V(d.center), value=d.contest, side="crew")
        if d.contest >= c["threshold"]:
            d.crew_lock, d.lock_t, d.contest = False, 0.01, 0.0
            sim.emit("door_burst", pos=V(d.center))


# ------------------------------------------------------------------ the horde obeys the Host's mark
def update_horde(sim, dt):
    if sim.horde_t > 0:
        sim.horde_t -= dt
        t = sim.players[sim.horde_idx] if sim.horde_idx is not None else None
        if t is None or not t.alive or sim.horde_t <= 0:
            sim.horde_idx, sim.horde_t = None, 0.0


def marked_target(sim, e):
    """The crew member the Host has marked, if this zombie is within the pull range of them."""
    if sim.horde_idx is None or sim.host is None:
        return None
    if e.kind in ("warden", "overlord") or e.spec.behavior == "ranged":
        return None
    t = sim.players[sim.horde_idx]
    if t.alive and e.pos.distance_to(t.pos) <= cfg()["mark"]["pull_range"]:
        return t
    return None


# ------------------------------------------------------------------ AI brain (bots, tests, disconnected controllers)
def brain(sim, p, rng):
    from src.systems.commands import InputFrame
    c = cfg()
    h = p.host
    f = InputFrame()
    crew = crew_alive(sim)
    if not crew:
        return f
    t = min(crew, key=lambda q: q.pos.distance_to(p.pos))
    to = t.pos - p.pos
    dist = to.length()
    field = sim.nav_fields.get(t.idx)
    nxt = nav.next_step(field, p.pos) if field else None
    d = (V(nxt) - p.pos) if nxt else to
    if dist < 220 and sim.solids.los(p.pos, t.pos):
        d = to
    if d.length_squared():
        d = d.normalize()
    f.mx, f.my = d.x, d.y
    f.aim_x, f.aim_y = (to.normalize().x, to.normalize().y) if dist > 0 else (0, 0)
    f.fire = dist < c["claw"]["range"] + 14
    if 140 < dist < 330 and h.lunge_cd <= 0 and sim.solids.los(p.pos, t.pos):
        f.dodge = True
    if h.mark_cd <= 0 and dist < c["mark"]["range"]:
        f.ability = True
    if h.charge >= 1.0 and h.summon_cd <= 0 and dist > c["summon"]["min_crew_dist"] and _door_in_reach(sim, p) is None:
        f.interact_held = True
    # a crew-locked door in the way: tap it
    di = _door_in_reach(sim, p)
    if di is not None and sim.doors[di].crew_lock:
        f.mx = f.my = 0.0
        if int(sim.time * c["ai"]["tap_hz"] * 2) % 2 == 0 and int((sim.time - 1 / 60) * c["ai"]["tap_hz"] * 2) % 2 == 1:
            f.interact = True
    return f
