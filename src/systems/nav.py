"""Breadth-first distance fields over the tile grid, rebuilt on a timer."""
from collections import deque

from src.settings import TILE
from src.world.level import MAP_H, MAP_W


def blocked_dynamic_tiles(sim):
    out = set()
    for d in sim.doors:
        if not d.broken and (d.kind == "barrier" or d.lock_t > 0):
            out.update(d.cells)
    for b in sim.barricades:
        r = b.rect
        for ty in range(r.top // TILE, (r.bottom - 1) // TILE + 1):
            for tx in range(r.left // TILE, (r.right - 1) // TILE + 1):
                out.add((tx, ty))
    return out


def build_field(sim, start, dyn_blocked):
    st = sim.solids.static
    dist = {start: 0}
    q = deque([start])
    while q:
        x, y = q.popleft()
        d = dist[(x, y)] + 1
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in dist or not (0 <= n[0] < MAP_W and 0 <= n[1] < MAP_H):
                continue
            if st[n[1]][n[0]] or n in dyn_blocked:
                continue
            dist[n] = d
            q.append(n)
    return dist


def update_fields(sim, dt):
    sim.nav_t -= dt
    if sim.nav_t > 0:
        return
    sim.nav_t = BAL_NAV()
    dyn = blocked_dynamic_tiles(sim)
    sim.nav_fields = {}
    for p in sim.players:
        if p.alive:
            sim.nav_fields[p.idx] = build_field(sim, (int(p.pos.x // TILE), int(p.pos.y // TILE)), dyn)


def BAL_NAV():
    from src.config import BAL
    return BAL.enemy_common.nav_interval


def next_step(field, pos):
    """Centre of the neighbouring tile with the lowest distance, or None when the tile is not in the field."""
    t = (int(pos.x // TILE), int(pos.y // TILE))
    d = field.get(t)
    if d is None:
        return None
    best, best_d = None, d
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (t[0] + dx, t[1] + dy)
        nd = field.get(n)
        if nd is not None and nd < best_d:
            best, best_d = n, nd
    if best is None:
        return None
    return (best[0] * TILE + TILE // 2, best[1] * TILE + TILE // 2)
