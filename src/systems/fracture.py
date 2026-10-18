"""Fracture complications, hazards, telegraphs and escalating pressure. Every effect is telegraphed."""
import math

import pygame

from src.config import BAL
from src.entities.models import Enemy, Telegraph
from src.settings import TILE

V = pygame.Vector2
F = BAL.fracture
H = BAL.hazards
M = BAL.mission
MAX_ENEMIES = BAL.enemy_common.max_alive


def far_from_players(sim, pos, dist=None):
    d = dist or BAL.enemy_common.spawn_safe_distance
    return all(p.pos.distance_to(pos) >= d for p in sim.players if p.alive)


def pick_spawn_point(sim):
    pts = [V(p) for p in sim.level.patrol_spawns if far_from_players(sim, V(p))]
    return sim.rng.choice(pts) if pts else None


def spawn_group(sim, center, kinds):
    n = len(kinds)
    for i, k in enumerate(kinds):
        ang = 2 * math.pi * i / max(1, n)
        pos = V(center) + V(math.cos(ang), math.sin(ang)) * (24 if n > 1 else 0)
        if not sim.solids.free_at(pos, BAL.enemies[k].radius):
            pos = V(center)
        e = Enemy(k, pos)
        e.state = "chase"
        e.alert_t = 8.0
        sim.enemies.append(e)


def update(sim, dt):
    lvl = sim.fracture
    # --- electrical floor hazards: cycle idle -> warning -> active ---------------------------
    for h in sim.floor_hazards:
        t = (sim.time + h.phase) % H.floor_cycle
        act_start = H.floor_cycle - H.floor_active
        warn_start = act_start - H.floor_warning
        new = "active" if t >= act_start else ("warning" if t >= warn_start else "idle")
        if new != h.state:
            h.state = new
            if new == "warning":
                sim.emit("hazard_warning", pos=V(h.rect.center))
            elif new == "active":
                sim.emit("hazard_active", pos=V(h.rect.center))
        if h.state == "active":
            from src.systems import combat
            for p in sim.players:
                if p.alive and h.rect.collidepoint(p.pos.x, p.pos.y) and p.last_hazard_tick <= 0:
                    p.last_hazard_tick = H.floor_tick
                    combat.damage_player(sim, p, H.floor_damage, grant_iframes=False, kind="electric")
            for e in sim.enemies:
                if not e.dead and h.rect.collidepoint(e.pos.x, e.pos.y) and e.hazard_cd <= 0:
                    e.hazard_cd = H.floor_tick
                    combat.damage_enemy(sim, e, H.floor_damage, how="surge")

    # --- Fracture complications -----------------------------------------------------------------
    if lvl >= F.surge_from:
        sim.t_surge -= dt
        if sim.t_surge <= 0:
            sim.t_surge = max(6.0, F.surge_interval * (1 - 0.06 * lvl))
            _surge(sim)
    if lvl >= F.glitch_from:
        sim.t_glitch -= dt
        if sim.t_glitch <= 0:
            sim.t_glitch = F.glitch_interval
            _glitch_door(sim)
    if lvl >= F.patrol_from:
        sim.t_patrol -= dt
        if sim.t_patrol <= 0:
            sim.t_patrol = F.patrol_interval
            _queue_group(sim, "patrol", ["drifter", "crawler", "crawler"] + (["sentry"] if lvl >= 6 else []) + (["stalker"] if lvl >= 8 else []), F.patrol_warning)
    if lvl >= F.whisper_from:
        sim.t_whisper -= dt
        if sim.t_whisper <= 0:
            sim.t_whisper = F.whisper_interval
            _whisper(sim)

    if sim.pending_spawns:
        kind, kinds, warn = sim.pending_spawns[0]
        pt = pick_spawn_point(sim)
        if pt is not None:
            sim.pending_spawns.pop(0)
            sim.telegraphs.append(Telegraph(kind, pt, warn, 40, payload=kinds))
            sim.emit("spawn_warning", pos=V(pt), kind=kind)

    # --- time pressure waves ---------------------------------------------------------------------
    sim.t_wave -= dt
    if sim.t_wave <= 0:
        sim.t_wave = M.pressure_interval
        sim.wave_no += 1
        n = M.pressure_wave_size + sim.wave_no // 2
        kinds = (["drifter"] * max(1, n - sim.wave_no // 3) + ["crawler"] * min(4, 1 + sim.wave_no)
                 + ["sentry"] * (sim.wave_no // 3) + ["stalker"] * (sim.wave_no // 4) + ["brute"] * (sim.wave_no // 5))
        _queue_group(sim, "wave", kinds, M.pressure_warning)

    # --- telegraphs resolve ----------------------------------------------------------------------
    for t in sim.telegraphs:
        t.t -= dt
        if t.t <= 0 and not t.dead:
            t.dead = True
            if t.kind == "surge":
                from src.systems import combat
                for p in sim.players:
                    if p.alive and p.pos.distance_to(t.pos) <= t.radius + p.radius:
                        combat.damage_player(sim, p, F.surge_damage, kind="surge")
                for e in sim.enemies:
                    if not e.dead and e.pos.distance_to(t.pos) <= t.radius:
                        combat.damage_enemy(sim, e, F.surge_damage, how="surge")
                sim.emit("surge_hit", pos=V(t.pos), radius=t.radius)
            elif t.kind in ("patrol", "wave"):
                alive_n = sum(1 for e in sim.enemies if not e.dead)
                kinds = t.payload[: max(0, MAX_ENEMIES - alive_n)]
                if kinds:
                    spawn_group(sim, t.pos, kinds)
                    sim.emit("enemies_arrive", pos=V(t.pos), count=len(kinds))
    sim.telegraphs = [t for t in sim.telegraphs if not t.dead]

    # --- door glitch state machine -------------------------------------------------------------------
    for d in sim.doors:
        if d.warn_t > 0:
            d.warn_t -= dt
            if d.warn_t <= 0:
                if _occupied(sim, d):
                    d.warn_t = 0.5          # never lock a door with someone standing in it
                else:
                    d.lock_t = F.glitch_lock
                    sim.emit("door_locked", pos=V(d.center))
        elif d.lock_t > 0:
            d.lock_t -= dt
            if d.lock_t <= 0:
                sim.emit("door_unlocked", pos=V(d.center))


def _occupied(sim, d):
    r = d.rect.inflate(40, 40)
    for p in sim.players:
        if r.collidepoint(p.pos.x, p.pos.y):
            return True
    for e in sim.enemies:
        if not e.dead and r.collidepoint(e.pos.x, e.pos.y):
            return True
    return False


def _surge(sim):
    alive = [p for p in sim.players if p.alive]
    if not alive:
        return
    tgt = sim.rng.choice(alive)
    for _ in range(12):
        ang = sim.rng.uniform(0, math.tau)
        pos = tgt.pos + V(math.cos(ang), math.sin(ang)) * sim.rng.uniform(110, 280)
        if sim.solids.free_at(pos, 10):
            sim.telegraphs.append(Telegraph("surge", pos, F.surge_warning, F.surge_radius))
            sim.emit("surge_warning", pos=V(pos), radius=F.surge_radius)
            return


def _glitch_door(sim):
    cands = [d for d in sim.doors if d.kind == "normal" and d.warn_t <= 0 and d.lock_t <= 0]
    if not cands:
        return
    d = sim.rng.choice(cands)
    d.warn_t = F.glitch_warning
    sim.emit("door_glitch", pos=V(d.center))


def _queue_group(sim, kind, kinds, warn):
    pt = pick_spawn_point(sim)
    if pt is None:
        sim.pending_spawns.append((kind, kinds, warn))
        return
    sim.telegraphs.append(Telegraph(kind, pt, warn, 40, payload=kinds))
    sim.emit("spawn_warning", pos=V(pt), kind=kind)


def _whisper(sim):
    alive = [p for p in sim.players if p.alive]
    line = sim.rng.choice(sim.story.whispers)
    ally = sim.rng.choice(sim.players).name.split()[0] if sim.players else "Crew"
    sim.emit("whisper", text=line.replace("{ally}", ally))
