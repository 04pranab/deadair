"""Enemy AI. Independent of rendering; updated on the fixed step."""
import math

import pygame

from src.config import BAL
from src.systems import combat, nav
from src.settings import TILE

V = pygame.Vector2
C = BAL.enemy_common


def pick_target(sim, e):
    from src.systems import host
    m = host.marked_target(sim, e)
    if m is not None:
        e.alert_t = max(e.alert_t, 6.0)            # the Host's command: this zombie hunts the marked crew member
        e.has_los = True
        return m
    best, bd = None, 1e9
    for p in sim.players:
        if not p.alive:
            continue
        d = e.pos.distance_to(p.pos)
        if e.kind == "warden" and p.carry is not None:
            d *= 0.4   # the Warden goes for Echo carriers
        if d < bd:
            best, bd = p, d
    return best


def update_enemies(sim, dt):
    speed_mult = sim.enemy_speed_mult
    from src.systems import machines as _mach
    for e in sim.enemies:
        if e.dead:
            continue
        e.flash = max(0.0, e.flash - dt)
        e.cd = max(0.0, e.cd - dt)
        e.hazard_cd = max(0.0, e.hazard_cd - dt)
        # knockback decays
        if e.knock.length_squared() > 1:
            kn, _, _, _ = sim.solids.move(e.pos, e.knock * dt, e.radius)
            e.pos = kn
            e.knock *= max(0.0, 1 - 8 * dt)
        if e.state == "stagger":
            e.stagger_t -= dt
            if e.stagger_t <= 0:
                e.state = "chase" if e.alert_t > 0 else "idle"
            continue
        if sim.machines:
            bm = _mach.beacon_target(sim, e)
            if bm is not None:                       # the Beacon's lure overrides hunting
                dv = bm.pos - e.pos
                if dv.length_squared() > 1:
                    _move(sim, e, dv.normalize() * e.spec.speed * speed_mult * dt)
                continue
        target = pick_target(sim, e)
        e.target = target
        if target is None:
            continue
        to = target.pos - e.pos
        dist = to.length()
        # perception
        e.los_t -= dt
        if e.los_t <= 0:
            e.los_t = 0.2
            e.has_los = dist < C.aggro_range * 1.2 and sim.solids.los(e.pos, target.pos)
        if getattr(e, "hunt", False) or (e.has_los and dist < C.aggro_range):
            e.alert_t = 6.0
        else:
            e.alert_t = max(0.0, e.alert_t - dt)
        if e.alert_t <= 0 and e.state in ("idle", "chase"):
            e.state = "idle"
            continue
        if e.state == "idle":
            e.state = "chase"
        beh = e.spec.behavior
        speed_mult = sim.enemy_speed_mult * (_mach.enemy_speed_factor(sim, e) if sim.machines else 1.0)
        if beh == "melee":
            _drifter(sim, e, target, to, dist, dt, speed_mult)
        elif beh == "ranged":
            _sentry(sim, e, target, to, dist, dt, speed_mult)
        else:
            _warden(sim, e, target, to, dist, dt, speed_mult)
    _separate(sim)


def _steer(sim, e, target, dist, speed, dt, direct_range=260):
    """Move toward the target using LOS shortcut or the nav gradient."""
    if e.has_los and dist < direct_range:
        d = target.pos - e.pos
    else:
        field = sim.nav_fields.get(target.idx)
        nxt = nav.next_step(field, e.pos) if field else None
        d = (V(nxt) - e.pos) if nxt else (target.pos - e.pos)
    if d.length_squared() == 0:
        return
    d = d.normalize()
    e.facing = V(d)
    _move(sim, e, d * speed * dt)


def _move(sim, e, delta):
    newpos, hx, hy, owner = sim.solids.move(e.pos, delta, e.radius)
    e.pos = newpos
    e.walk_phase += delta.length() * 0.06
    if (hx or hy) and owner is not None and hasattr(owner, "hp") and hasattr(owner, "life"):
        owner.hp -= 4 * (1 / 60)   # chewing on a barricade


def _separate(sim):
    """Push overlapping enemies apart. Uses a spatial hash so hundreds of zombies stay cheap."""
    es = [e for e in sim.enemies if not e.dead]
    cell = 64
    grid = {}
    for e in es:
        grid.setdefault((int(e.pos.x // cell), int(e.pos.y // cell)), []).append(e)
    for e in es:
        cx, cy = int(e.pos.x // cell), int(e.pos.y // cell)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for b in grid.get((gx, gy), ()):
                    if b.id <= e.id:
                        continue
                    d = e.pos - b.pos
                    L = d.length()
                    m = e.radius + b.radius
                    if 0 < L < m:
                        push = d / L * (m - L) * 0.5
                        e.pos, _, _, _ = sim.solids.move(e.pos, push, e.radius)
                        b.pos, _, _, _ = sim.solids.move(b.pos, -push, b.radius)


def _drifter(sim, e, target, to, dist, dt, speed_mult):
    s = e.spec
    if e.state == "windup":
        e.timer -= dt
        e.pos, _, _, _ = sim.solids.move(e.pos, e.aim_dir * s.get("lunge", 55) * dt, e.radius)   # short lunge
        if e.timer <= 0:
            _melee_strike(sim, e)
            e.state = "recover"
            e.timer = 0.35
            e.cd = s.cooldown
        return
    if e.state == "recover":
        e.timer -= dt
        if e.timer <= 0:
            e.state = "chase"
        return
    if dist <= s.melee_range and e.cd <= 0 and e.has_los:
        e.state = "windup"
        e.timer = s.windup
        e.aim_dir = to.normalize()
        e.facing = V(e.aim_dir)
        sim.emit("telegraph_melee", pos=V(e.pos), dir=V(e.aim_dir), t=s.windup)
        return
    _steer(sim, e, target, dist, s.speed * speed_mult, dt)


def _melee_strike(sim, e):
    s = e.spec
    for p in sim.players:
        if not p.alive:
            continue
        v = p.pos - e.pos
        d = v.length()
        if d <= s.melee_range + 12 + p.radius and (d < 1 or v.normalize().dot(e.aim_dir) > 0.2) and sim.solids.los(e.pos, p.pos):
            combat.damage_player(sim, p, s.damage, kind="melee")
    for b in sim.barricades:
        if V(b.rect.center).distance_to(e.pos) < s.melee_range + 24:
            b.hp -= s.damage
            if b.hp <= 0:
                b.dead = True
    sim.emit("melee_strike", pos=e.pos + e.aim_dir * 24, dir=V(e.aim_dir))


def _sentry(sim, e, target, to, dist, dt, speed_mult):
    s = e.spec
    if e.state == "windup":
        e.timer -= dt
        if e.timer <= 0:
            n = s.get("burst", 1)
            for i in range(n):   # aim locked at wind-up start: dodgeable; bursts fan out
                off = (i - (n - 1) / 2) * s.get("spread", 0.0)
                combat.fire_enemy_bullet(sim, e, e.aim_dir.rotate_rad(off))
            e.state = "recover"
            e.timer = 0.4
            e.cd = s.cooldown
        return
    if e.state == "recover":
        e.timer -= dt
        if e.timer <= 0:
            e.state = "chase"
        return
    if e.has_los and dist <= s.prefer_max + 80 and e.cd <= 0:
        e.state = "windup"
        e.timer = s.windup
        e.aim_dir = to.normalize()
        e.facing = V(e.aim_dir)
        sim.emit("telegraph_aim", pos=V(e.pos), dir=V(e.aim_dir), t=s.windup)
        return
    sp = s.speed * speed_mult
    if e.has_los and dist < s.prefer_min:
        d = -to.normalize()
        e.facing = to.normalize()
        _move(sim, e, d * sp * dt)
    elif e.has_los and dist <= s.prefer_max:
        side = V(-to.y, to.x).normalize() * (1 if (e.id % 2) else -1)
        e.facing = to.normalize()
        _move(sim, e, side * sp * 0.5 * dt)
    else:
        _steer(sim, e, target, dist, sp, dt, direct_range=s.prefer_max)


def _warden(sim, e, target, to, dist, dt, speed_mult):
    s = e.spec
    if e.state == "windup":
        e.timer -= dt
        if e.timer <= 0:
            for p in sim.players:
                if p.alive and p.pos.distance_to(e.pos) <= s.slam_radius + p.radius and sim.solids.los(e.pos, p.pos):
                    combat.damage_player(sim, p, s.damage, kind="slam")
                    p.pos, _, _, _ = sim.solids.move(p.pos, (p.pos - e.pos).normalize() * 36, p.radius)
            for b in sim.barricades:
                if V(b.rect.center).distance_to(e.pos) < s.slam_radius + 20:
                    b.hp -= s.damage * 2
                    if b.hp <= 0:
                        b.dead = True
            sim.emit("slam", pos=V(e.pos), radius=s.slam_radius)
            e.state = "recover"
            e.timer = 0.6
            e.cd = s.cooldown
        return
    if e.state == "recover":
        e.timer -= dt
        if e.timer <= 0:
            e.state = "chase"
        return
    if dist <= s.slam_radius * 0.8 and e.cd <= 0 and e.has_los:
        e.state = "windup"
        e.timer = s.windup
        sim.emit("telegraph_slam", pos=V(e.pos), radius=s.slam_radius, t=s.windup)
        return
    _steer(sim, e, target, dist, s.speed * speed_mult, dt)
