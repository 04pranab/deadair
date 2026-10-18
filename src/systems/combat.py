"""Damage, bullets, player abilities."""
import math

import pygame

from src.config import BAL
from src.entities.models import Barricade, Bullet, Echo, Pickup

V = pygame.Vector2
P = BAL.player


def dax_guard(sim, p):
    """Dax's passive: allies channelling a Rekindling next to a living Dax take less damage."""
    if not getattr(p, "channeling", False):
        return 1.0
    for q in sim.players:
        if q is not p and q.alive and q.role == "dax" and q.pos.distance_to(p.pos) < 160:
            return 0.75
    return 1.0


def damage_player(sim, p, amount, grant_iframes=True, kind="hit", source=None):
    if not p.alive or amount <= 0:
        return 0.0
    if p.dodge_t > 0 or p.charge_t > 0:
        return 0.0
    if grant_iframes and p.iframes > 0:
        return 0.0
    if p.weakened:
        amount *= P.weakened_damage_mult
    amount *= dax_guard(sim, p)
    p.hp -= amount
    p.flash = 0.15
    if grant_iframes:
        p.iframes = P.iframes_after_hit
    sim.emit("player_hit", pos=V(p.pos), amount=amount, player=p.idx, kind=kind)
    if p.hp <= 0:
        defeat_player(sim, p)
    return amount


def defeat_player(sim, p):
    from src.systems import ritual
    p.hp = 0.0
    p.state = "down"
    p.down_t = 0.0
    p.defeats += 1
    sim.defeats += 1
    if p.carry is not None:
        p.carry.state = "dropped"
        p.carry.carrier = None
        p.carry.pos = V(p.pos)
        p.carry = None
    echo = Echo(p.idx, p.pos, ritual.echo_cost(sim))
    sim.echoes.append(echo)
    p.ghost_disrupt_cd = 2.0
    sim.emit("defeated", pos=V(p.pos), player=p.idx)


def damage_enemy(sim, e, amount, source=None, stagger=0.0, knock=None, how="other"):
    if e.dead:
        return
    if e.kind == "overlord":
        from src.systems import overlord
        amount *= overlord.damage_factor(sim, e, how)
        overlord.note_damage(sim, e, amount, how)
        stagger, knock = 0.0, None             # the Avatar cannot be stunned or pushed
    e.hp -= amount
    if e.kind == "overlord":
        from src.systems import overlord
        if overlord.cfg()["avatar"].get("invincible"):
            e.hp = max(e.hp, 1.0)               # MERIDIAN cannot be destroyed: damage still drives phases, doctrine and windows
    e.flash = BAL.enemy_common.hit_flash
    if stagger > 0:
        e.stagger_t = max(e.stagger_t, stagger)
        e.state = "stagger"
        e.timer = 0.0
    if knock is not None:
        e.knock += knock
    sim.emit("enemy_hit", pos=V(e.pos), kind=e.kind, amount=amount)
    if e.hp <= 0:
        e.dead = True
        if source is not None and hasattr(source, "kills"):
            source.kills += 1
        sim.kills += 1
        drop = e.spec.salvage_drop * (sim.director.drop_mult if sim.director is not None else 1.0)
        n = int(drop) + (1 if sim.rng.random() < drop - int(drop) else 0)
        for _ in range(n):
            off = V(sim.rng.uniform(-14, 14), sim.rng.uniform(-14, 14))
            sim.pickups.append(Pickup("salvage", e.pos + off, 1))
        sim.emit("enemy_died", pos=V(e.pos), kind=e.kind)


def damage_door(sim, door, amount):
    if door.kind != "barrier" or door.broken:
        return
    door.hp -= amount
    sim.emit("barrier_hit", pos=V(door.center))
    if door.hp <= 0:
        door.broken = True
        sim.emit("barrier_broken", pos=V(door.center))


def fire_player(sim, p):
    d = V(p.facing)
    if d.length_squared() == 0:
        d = V(1, 0)
    d = d.normalize()
    muzzle = p.pos + d * (p.radius + 8)
    p.fire_cd = P.fire_cooldown
    p.recoil = 0.08
    # no attacking through solid geometry: the muzzle must be reachable from the body
    if not sim.solids.los(p.pos, muzzle) or sim.solids.point_solid(muzzle.x, muzzle.y):
        sim.emit("bullet_wall", pos=V(muzzle))
        owner = sim.solids.rect_hits_dyn(pygame.Rect(int(muzzle.x) - 2, int(muzzle.y) - 2, 4, 4))
        if owner is not None and hasattr(owner, "kind") and owner.kind == "barrier":
            damage_door(sim, owner, P.bullet_damage)
        return
    b = Bullet(muzzle, d * P.bullet_speed, P.bullet_damage, True, p, life=P.bullet_range / P.bullet_speed)
    sim.bullets.append(b)
    sim.emit("shoot", pos=V(muzzle), dir=V(d), friendly=True)


def fire_enemy_bullet(sim, e, direction):
    d = V(direction).normalize()
    muzzle = e.pos + d * (e.radius + 6)
    if not sim.solids.los(e.pos, muzzle):
        return
    sim.bullets.append(Bullet(muzzle, d * e.spec.bullet_speed, e.spec.damage, False, e, life=2.4))
    sim.emit("shoot", pos=V(muzzle), dir=V(d), friendly=False)


def update_bullets(sim, dt):
    for b in sim.bullets:
        b.pos += b.vel * dt
        b.life -= dt
        if b.life <= 0:
            b.dead = True
            continue
        if sim.solids.tile_solid(int(b.pos.x // 48), int(b.pos.y // 48)):
            b.dead = True
            sim.emit("bullet_wall", pos=V(b.pos))
            continue
        owner = sim.solids.rect_hits_dyn(pygame.Rect(int(b.pos.x) - 2, int(b.pos.y) - 2, 4, 4))
        if owner is not None:
            b.dead = True
            sim.emit("bullet_wall", pos=V(b.pos))
            if hasattr(owner, "kind") and owner.kind == "barrier" and b.friendly:
                damage_door(sim, owner, b.damage)
            elif isinstance(owner, Barricade) and not b.friendly:
                owner.hp -= b.damage
                if owner.hp <= 0:
                    owner.dead = True
            continue
        if b.friendly:
            h = sim.host
            if h is not None and h.pos.distance_to(b.pos) < h.radius + b.radius:
                from src.systems import host as _host
                _host.damage_host(sim, h, b.damage, source=b.owner)
                b.dead = True
                continue
            for e in sim.enemies:
                if not e.dead and e.pos.distance_to(b.pos) < e.radius + b.radius:
                    damage_enemy(sim, e, b.damage, source=b.owner, knock=b.vel.normalize() * 40, how="shot")
                    b.dead = True
                    break
        else:
            for p in sim.players:
                if p.alive and p.pos.distance_to(b.pos) < p.radius + b.radius:
                    damage_player(sim, p, b.damage, kind="bullet")
                    b.dead = True
                    break


# ---- abilities -------------------------------------------------------------------------------
def use_ability(sim, p):
    spec = BAL.roles[p.role]
    ab = BAL.abilities[spec.ability]
    if p.ability_cd > 0 or p.charge_t > 0 or p.dodge_t > 0:
        return False
    d = V(p.facing) if p.facing.length_squared() else V(1, 0)
    d = d.normalize()
    if spec.ability == "barricade":
        pos = p.pos + d * (p.radius + ab.size / 2 + 6)
        bar = Barricade(pos, ab.size, ab.hp, ab.life)
        r = bar.rect
        blocked = sim.solids.rect_hits_tiles(r) or sim.solids.rect_hits_dyn(r) is not None
        if not blocked:
            for q in sim.players:
                if q.alive and r.inflate(q.radius * 2, q.radius * 2).collidepoint(q.pos.x, q.pos.y):
                    blocked = True
            for e in sim.enemies:
                if not e.dead and r.inflate(e.radius * 2, e.radius * 2).collidepoint(e.pos.x, e.pos.y):
                    blocked = True
        if blocked:
            sim.emit("ability_fail", pos=V(p.pos), player=p.idx, reason="no room")
            return False
        sim.barricades.append(bar)
        sim.emit("barricade", pos=V(pos))
    elif spec.ability == "charge":
        p.charge_t = ab.time
        p.charge_hit = set()
        p.dodge_dir = V(d)
        sim.emit("charge", pos=V(p.pos), player=p.idx)
    elif spec.ability == "stim":
        n = 0
        for q in sim.players:
            if q.alive and q.pos.distance_to(p.pos) <= ab.radius:
                q.hp = min(q.max_hp, q.hp + ab.heal)
                q.resist_t = 6.0              # a stim pulse also steadies the mind against a Host conversion
                if ab.cleanse:
                    q.weak_t = 0.0
                n += 1
        sim.emit("stim", pos=V(p.pos), radius=ab.radius, player=p.idx)
    p.ability_cd = spec.ability_cooldown
    return True


def update_charge(sim, p, dt):
    ab = BAL.abilities.charge
    step = p.dodge_dir * ab.speed * dt
    newpos, hx, hy, owner = sim.solids.move(p.pos, step, p.radius)
    p.pos = newpos
    h = sim.host
    if h is not None and -1 not in p.charge_hit and h.pos.distance_to(p.pos) < h.radius + p.radius + 6:
        from src.systems import host as _host
        p.charge_hit.add(-1)
        _host.damage_host(sim, h, ab.damage * 1.5, source=p)
    for e in sim.enemies:
        if e.dead or e.id in p.charge_hit:
            continue
        if e.pos.distance_to(p.pos) < e.radius + p.radius + 6:
            p.charge_hit.add(e.id)
            damage_enemy(sim, e, ab.damage, source=p, stagger=ab.stagger, knock=p.dodge_dir * ab.knockback, how="charge")
            e.state = "stagger"
    if owner is not None and getattr(owner, "kind", None) == "barrier":
        damage_door(sim, owner, 9999)
        p.charge_t = 0
    if hx or hy:
        p.charge_t = min(p.charge_t, 0.0)


def ghost_disrupt(sim, p):
    if p.ghost_disrupt_cd > 0:
        return False
    n = 0
    for e in sim.enemies:
        if not e.dead and e.pos.distance_to(p.pos) <= P.ghost_disrupt_radius:
            e.stagger_t = max(e.stagger_t, P.ghost_disrupt_stun)
            e.state = "stagger"
            e.timer = 0.0
            n += 1
    p.ghost_disrupt_cd = P.ghost_disrupt_cooldown
    sim.emit("ghost_disrupt", pos=V(p.pos), count=n)
    return True
