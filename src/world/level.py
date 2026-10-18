"""Seeded station generation and solvability validation. Pure data, no pygame surfaces."""
import random
from collections import deque
from dataclasses import dataclass, field

from src.config import BAL
from src.settings import TILE

GRID_W, GRID_H = 6, 4        # 24 large open rooms, joined by wide doors in shared walls (no corridors)
MAP_W, MAP_H = 112, 61
COL_RANGE, ROW_RANGE = (14, 21), (12, 16)
DOOR_W = 4
FLOOR, WALL = 1, 0

ROOM_NAMES = ["Maintenance Deck", "Medbay", "Armory", "Control Hub", "Cargo Bay", "Research Lab", "Crew Quarters",
              "Server Vault", "Mess Hall", "Hydroponics", "Comms Array", "Engine Bay", "Brig", "Observation Deck",
              "Waste Processing", "Cold Storage", "Fabrication Shop", "Lounge", "Locker Room", "Pump Station"]


class _NoSpace(Exception):
    """Raised when a mandatory object cannot be placed; generate() retries with a new sub-seed."""


@dataclass
class Room:
    id: int
    cell: tuple
    x0: int
    y0: int
    x1: int  # exclusive
    y1: int
    kind: str = "generic"
    name: str = ""
    shape: str = "rect"

    @property
    def center(self):
        return ((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)

    def contains(self, tx, ty):
        return self.x0 <= tx < self.x1 and self.y0 <= ty < self.y1

    @property
    def area(self):
        return (self.x1 - self.x0) * (self.y1 - self.y0)


@dataclass
class DoorSpec:
    cells: list
    room_id: int
    link: tuple
    kind: str = "normal"      # normal | barrier (weak barrier guarding an optional room)
    horizontal_wall: bool = False  # True if the wall runs horizontally (passage is vertical)
    room_b: int = -1          # the room on the other side of the door


@dataclass
class Level:
    seed: int
    modifier: str
    grid: list = field(default_factory=list)       # grid[y][x] FLOOR/WALL
    blocked: list = field(default_factory=list)    # static solid props
    rooms: list = field(default_factory=list)
    links: list = field(default_factory=list)
    doors: list = field(default_factory=list)
    props: list = field(default_factory=list)      # dict(kind, tx, ty, tile, ...)
    relays: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    machines: list = field(default_factory=list)   # dict(id, kind, tx, ty, room)
    stabilizers: list = field(default_factory=list)
    anchors: list = field(default_factory=list)
    spawn_points: list = field(default_factory=list)
    enemy_spawns: list = field(default_factory=list)
    patrol_spawns: list = field(default_factory=list)
    floor_hazards: list = field(default_factory=list)
    extraction: tuple = (0, 0)
    core: tuple = (0, 0)
    spawn_room: int = 0
    archive_room: int = 0
    extraction_room: int = 0
    attempts: int = 1

    def room_at(self, tx, ty):
        for r in self.rooms:
            if r.contains(tx, ty):
                return r
        return None


def tile_center(tx, ty):
    return (tx * TILE + TILE // 2, ty * TILE + TILE // 2)


def passable_grid(level, closed_kinds=("barrier",)):
    """Boolean grid of walkable tiles for connectivity checks (doors count as passable unless barrier)."""
    ok = [[level.grid[y][x] == FLOOR and not level.blocked[y][x] for x in range(MAP_W)] for y in range(MAP_H)]
    for d in level.doors:
        if d.kind in closed_kinds:
            for (x, y) in d.cells:
                ok[y][x] = False
    return ok


def flood(ok, start):
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if 0 <= n[0] < MAP_W and 0 <= n[1] < MAP_H and ok[n[1]][n[0]] and n not in seen:
                seen.add(n)
                q.append(n)
    return seen


def adjacent_open(ok_set, tx, ty):
    return any((tx + dx, ty + dy) in ok_set for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def validate(level):
    """Return list of problems (empty if the level is solvable)."""
    problems = []
    ok = passable_grid(level)  # barriers closed: mandatory content must not depend on them
    sp = level.spawn_points[0]
    start = (int(sp[0] // TILE), int(sp[1] // TILE))
    reach = flood(ok, start)
    if start not in reach:
        problems.append("spawn blocked")
    for rl in level.relays:
        if not adjacent_open(reach, rl["tx"], rl["ty"]):
            problems.append(f"relay {rl['id']} unreachable")
    for a in level.anchors:
        if not adjacent_open(reach, a["tx"], a["ty"]) and (a["tx"], a["ty"]) not in reach:
            problems.append("anchor unreachable")
    ex = level.extraction
    if (ex[0], ex[1]) not in reach:
        problems.append("extraction unreachable")
    for sp in level.spawn_points:
        if (int(sp[0] // TILE), int(sp[1] // TILE)) not in reach:
            problems.append("spawn point unreachable")
    # the optional core must be reachable once barriers are broken
    okb = passable_grid(level, closed_kinds=())
    reach_b = flood(okb, start)
    if not adjacent_open(reach_b, level.core[0], level.core[1]):
        problems.append("core unreachable even with barrier broken")
    for lg in level.logs:
        if not adjacent_open(reach_b, lg["tx"], lg["ty"]):
            problems.append(f"log {lg['slot']} unreachable")
    for m in getattr(level, "machines", []):
        pos = (m["tx"], m["ty"])
        if not adjacent_open(reach_b, *pos):
            problems.append(f"machine {m['id']} ({m['kind']}) unreachable")
        elif m["kind"] == "incinerator" and not adjacent_open(reach, *pos):
            problems.append(f"incinerator {m['id']} only behind a barrier")
    return problems


# ----------------------------------------------------------------------------------------------
def _partition(rng, n, total, lo, hi):
    """n sizes in [lo, hi] summing to total (deterministic)."""
    while True:
        sizes = [rng.randint(lo, hi) for _ in range(n)]
        diff = total - sum(sizes)
        guard = 0
        while diff != 0 and guard < 400:
            i = rng.randrange(n)
            step = 1 if diff > 0 else -1
            if lo <= sizes[i] + step <= hi:
                sizes[i] += step
                diff -= step
            guard += 1
        if diff == 0:
            return sizes


def _carve_rect(grid, x0, y0, x1, y1):
    for y in range(y0, y1):
        for x in range(x0, x1):
            grid[y][x] = FLOOR


def generate(seed, modifier=None, modifiers=None):
    """Generate a solvable level for the seed. Deterministic. Retries with derived sub-seeds if validation fails."""
    mods = list(BAL.modifiers.keys())
    if modifier is None:
        modifier = random.Random(seed ^ 0x5EED).choice(mods)
    last = None
    for attempt in range(1, 40):
        rng = random.Random(seed * 1000 + attempt)
        try:
            lvl = _build(rng, seed, modifier)
        except _NoSpace:
            last = ["no space for a mandatory object"]
            continue
        lvl.attempts = attempt
        problems = validate(lvl)
        if not problems:
            return lvl
        last = problems
    raise RuntimeError(f"could not generate a solvable level for seed {seed}: {last}")


def _build(rng, seed, modifier):
    lvl = Level(seed=seed, modifier=modifier)
    grid = [[WALL] * MAP_W for _ in range(MAP_H)]
    widths = _partition(rng, GRID_W, MAP_W - (GRID_W + 1), *COL_RANGE)
    heights = _partition(rng, GRID_H, MAP_H - (GRID_H + 1), *ROW_RANGE)
    xs, x = [], 1
    for w in widths:
        xs.append(x)
        x += w + 1
    ys, y = [], 1
    for h in heights:
        ys.append(y)
        y += h + 1
    rooms = {}
    for cy in range(GRID_H):
        for cx in range(GRID_W):
            r = Room(len(rooms), (cx, cy), xs[cx], ys[cy], xs[cx] + widths[cx], ys[cy] + heights[cy])
            rooms[(cx, cy)] = r
            _carve_rect(grid, r.x0, r.y0, r.x1, r.y1)
    lvl.rooms = list(rooms.values())
    cells = list(rooms)

    # spanning tree (random DFS) + extra loops
    start = cells[rng.randrange(len(cells))]
    visited, stack, links = {start}, [start], []
    while stack:
        c = stack[-1]
        nbrs = [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if (c[0] + dx, c[1] + dy) in rooms and (c[0] + dx, c[1] + dy) not in visited]
        if not nbrs:
            stack.pop()
            continue
        n = rng.choice(nbrs)
        visited.add(n)
        links.append(tuple(sorted((c, n))))
        stack.append(n)
    for c in cells:
        for dx, dy in ((1, 0), (0, 1)):
            n = (c[0] + dx, c[1] + dy)
            if n in rooms and tuple(sorted((c, n))) not in links and rng.random() < 0.8:
                links.append(tuple(sorted((c, n))))
    lvl.links = links

    # one 2-wide door in the shared wall of every linked pair
    for (a, b) in links:
        A, B = rooms[a], rooms[b]
        if a[1] == b[1]:        # horizontal neighbours: wall column at A.x1
            y0 = rng.randint(A.y0 + 1, A.y1 - 1 - DOOR_W)
            cells2 = [(A.x1, y0 + k) for k in range(DOOR_W)]
            hw = False
        else:                   # vertical neighbours: wall row at A.y1
            x0 = rng.randint(A.x0 + 1, A.x1 - 1 - DOOR_W)
            cells2 = [(x0 + k, A.y1) for k in range(DOOR_W)]
            hw = True
        for (cx_, cy_) in cells2:
            grid[cy_][cx_] = FLOOR
        lvl.doors.append(DoorSpec(cells2, A.id, (a, b), horizontal_wall=hw, room_b=B.id))
    lvl.grid = grid
    lvl.blocked = [[False] * MAP_W for _ in range(MAP_H)]

    _assign_rooms(rng, lvl)
    _shape_rooms(rng, lvl)
    _add_interior_walls(rng, lvl)
    _place_content(rng, lvl)
    return lvl


SHAPES = ("ellipse", "octagon", "cross", "notch", "L")


def _shape_mask(shape, r, rng):
    """Cells (inside the room rectangle) that become wall for this shape. Every shape is symmetric or deliberately asymmetric but
    always leaves the centre cross open; door approaches are re-protected by the caller."""
    w, h = r.x1 - r.x0, r.y1 - r.y0
    cx, cy = (r.x0 + r.x1 - 1) / 2.0, (r.y0 + r.y1 - 1) / 2.0
    rx, ry = w / 2.0, h / 2.0
    out = set()
    for y in range(r.y0, r.y1):
        for x in range(r.x0, r.x1):
            dx, dy = (x - cx) / rx, (y - cy) / ry
            if shape == "ellipse":
                bad = dx * dx + dy * dy > 1.02
            elif shape == "octagon":
                bad = abs(dx) + abs(dy) > 1.42
            elif shape == "cross":
                bad = abs(dx) > 0.42 and abs(dy) > 0.42
            else:
                bad = False
            if bad:
                out.add((x, y))
    if shape == "L":
        qx, qy = rng.choice((-1, 1)), rng.choice((-1, 1))
        for y in range(r.y0, r.y1):
            for x in range(r.x0, r.x1):
                if (x - cx) * qx > w * 0.08 and (y - cy) * qy > h * 0.08:
                    out.add((x, y))
    elif shape == "notch":
        # asymmetric: two corners cut to different depths
        for k, (qx, qy) in enumerate(rng.sample([(-1, -1), (1, -1), (-1, 1), (1, 1)], 2)):
            fx, fy = (0.34, 0.30) if k == 0 else (0.2, 0.46)
            for y in range(r.y0, r.y1):
                for x in range(r.x0, r.x1):
                    if (x - cx) * qx > w * (0.5 - fx) and (y - cy) * qy > h * (0.5 - fy):
                        out.add((x, y))
    return out


def _shape_rooms(rng, lvl):
    """Replace most rooms' rectangles by distinct shapes. Reliability first: a door approach (4 tiles deep) and the centre cross
    are never walled, unreachable pockets are filled back in, and a room whose shape would disconnect a door is left rectangular."""
    door_by_room = {}
    for d in lvl.doors:
        for rid in (d.room_id, d.room_b):
            door_by_room.setdefault(rid, []).append(d)
    for r in lvl.rooms:
        if r.id in (lvl.spawn_room, lvl.archive_room) or rng.random() > 0.78:
            continue
        shape = rng.choice(SHAPES)
        mask = _shape_mask(shape, r, rng)
        protect = set()
        for d in door_by_room.get(r.id, []):
            for (x, y) in d.cells:
                for dx in range(-4, 5):
                    for dy in range(-4, 5):
                        protect.add((x + dx, y + dy))
        cx, cy = r.center
        for x in range(r.x0, r.x1):
            protect.add((x, cy))
        for y in range(r.y0, r.y1):
            protect.add((cx, y))
        mask = {c for c in mask if c not in protect}
        if len(mask) < 6:
            continue
        for (x, y) in mask:
            lvl.grid[y][x] = WALL
        # every floor cell of the room must still connect to the centre; fill pockets back in as wall
        seen = {(cx, cy)}
        q = deque([(cx, cy)])
        while q:
            x, y = q.popleft()
            for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + ddx, y + ddy)
                if r.contains(*n) and n not in seen and lvl.grid[n[1]][n[0]] == FLOOR:
                    seen.add(n)
                    q.append(n)
        for y in range(r.y0, r.y1):
            for x in range(r.x0, r.x1):
                if lvl.grid[y][x] == FLOOR and (x, y) not in seen:
                    lvl.grid[y][x] = WALL
        ok = all(any((x + ddx, y + ddy) in seen for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                 for d in door_by_room.get(r.id, []) for (x, y) in d.cells)
        if not ok:
            for y in range(r.y0, r.y1):
                for x in range(r.x0, r.x1):
                    lvl.grid[y][x] = FLOOR
            continue
        r.shape = shape


def _add_interior_walls(rng, lvl):
    """Partition walls / pillars inside rooms for density. Every block keeps a free ring around it, so no pockets or
    blocked passages can appear, and the centre of the room and the door approaches stay open."""
    door_cells = {c for d in lvl.doors for c in d.cells}
    for r in lvl.rooms:
        if r.id == lvl.spawn_room or r.id == lvl.archive_room:
            continue
        cx, cy = r.center
        for _ in range(rng.choice([0, 1, 1, 2])):
            w, h = rng.choice([(2, 2), (1, 4), (4, 1), (1, 3), (3, 1), (2, 1)])
            x = rng.randint(r.x0 + 2, r.x1 - w - 2)
            y = rng.randint(r.y0 + 2, r.y1 - h - 2)
            cells = [(x + i, y + j) for i in range(w) for j in range(h)]
            if any(abs(c[0] - cx) <= 2 and abs(c[1] - cy) <= 2 for c in cells):
                continue
            if any(abs(c[0] - dc[0]) <= 3 and abs(c[1] - dc[1]) <= 3 for c in cells for dc in door_cells):
                continue
            ring = [(x + i, y + j) for i in range(-1, w + 1) for j in range(-1, h + 1)]
            if not all(0 <= a < MAP_W and 0 <= b < MAP_H and lvl.grid[b][a] == FLOOR for a, b in ring):
                continue
            for a, b in cells:
                lvl.grid[b][a] = WALL


def _room_graph(lvl):
    adj = {r.id: set() for r in lvl.rooms}
    by_cell = {r.cell: r for r in lvl.rooms}
    for (a, b) in lvl.links:
        adj[by_cell[a].id].add(by_cell[b].id)
        adj[by_cell[b].id].add(by_cell[a].id)
    return adj


def _dist(adj, s, blocked=()):
    d = {s: 0}
    q = deque([s])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in d and v not in blocked:
                d[v] = d[u] + 1
                q.append(v)
    return d


def _assign_rooms(rng, lvl):
    adj = _room_graph(lvl)
    rooms = {r.id: r for r in lvl.rooms}
    # spawn = a small room, preferring few links
    spawn = min(lvl.rooms, key=lambda r: (len(adj[r.id]), r.area, rng.random()))
    d = _dist(adj, spawn.id)
    # archive = a far room whose removal keeps all other rooms connected
    cands = sorted((r for r in lvl.rooms if r.id != spawn.id), key=lambda r: -d[r.id])
    archive = None
    for r in cands:
        rest = _dist(adj, spawn.id, blocked={r.id})
        if len(rest) == len(lvl.rooms) - 1 and d[r.id] >= 2:
            archive = r
            break
    if archive is None:
        archive = cands[0]
    others = [r for r in lvl.rooms if r.id not in (spawn.id, archive.id)]
    extraction = max(others, key=lambda r: (d[r.id], r.area))
    reactor = max((r for r in others if r.id != extraction.id), key=lambda r: r.area)
    spawn.kind, archive.kind, extraction.kind, reactor.kind = "airlock", "archive", "dock", "reactor"
    names = ROOM_NAMES[:]
    rng.shuffle(names)
    spawn.name, archive.name, extraction.name, reactor.name = "Airlock C", "Archive Vault", "Escape Dock", "Reactor Annex"
    for r in lvl.rooms:
        if not r.name:
            r.name = names.pop() if names else f"Room {r.id}"
    lvl.spawn_room, lvl.archive_room, lvl.extraction_room = spawn.id, archive.id, extraction.id
    lvl.reactor_room = reactor.id


def _keep_clear(lvl):
    """Cells that must never hold props: near doors and on the straight lines between a room's doors."""
    clear = set()
    for d in lvl.doors:
        for (x, y) in d.cells:
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    clear.add((x + dx, y + dy))
    for r in lvl.rooms:
        cx, cy = r.center
        for x in range(r.x0, r.x1):
            clear.add((x, cy))
        for y in range(r.y0, r.y1):
            clear.add((cx, y))
        for x in range(cx - 2, cx + 3):
            for y in range(cy - 2, cy + 3):
                clear.add((x, y))
    return clear


def _place_content(rng, lvl):
    clear = _keep_clear(lvl)
    rooms = {r.id: r for r in lvl.rooms}
    used = set()
    mod = BAL.modifiers[lvl.modifier]

    def free_cells(r, margin=0, edge_only=False):
        out = []
        for y in range(r.y0 + margin, r.y1 - margin):
            for x in range(r.x0 + margin, r.x1 - margin):
                if (x, y) in clear or (x, y) in used or lvl.grid[y][x] != FLOOR:
                    continue
                if edge_only and not (x in (r.x0, r.x1 - 1) or y in (r.y0, r.y1 - 1)):
                    continue
                out.append((x, y))
        rng.shuffle(out)
        return out

    def take(r, required=False, **kw):
        c = free_cells(r, **kw) or free_cells(r)
        if not c:
            if required:
                raise _NoSpace()
            return None
        cell = c[0]
        used.add(cell)
        return cell

    spawn, archive = rooms[lvl.spawn_room], rooms[lvl.archive_room]
    ext = rooms[lvl.extraction_room]

    # spawn points
    cx, cy = spawn.center
    pts = [(cx - 1, cy), (cx + 1, cy), (cx - 1, cy + 1), (cx + 1, cy + 1), (cx, cy - 1), (cx, cy + 2)]
    lvl.spawn_points = [tile_center(x, y) for x, y in pts]
    for p in pts:
        used.add(p)

    # extraction hatch in dock
    ecx, ecy = ext.center
    lvl.extraction = (ecx, ecy)

    # relays: 3-5 in distinct non-spawn, non-archive rooms
    n_relays = rng.randint(3, 5)
    relay_rooms = [r for r in lvl.rooms if r.id not in (spawn.id, archive.id)]
    rng.shuffle(relay_rooms)
    reactor = rooms[lvl.reactor_room]
    relay_rooms = [reactor] + [r for r in relay_rooms if r.id != reactor.id]
    for i in range(min(n_relays, len(relay_rooms))):
        r = relay_rooms[i]
        x, y = take(r, required=True, edge_only=True)
        lvl.relays.append({"id": i, "tx": x, "ty": y, "room": r.id})
        lvl.blocked[y][x] = True

    # anchors: A near spawn (online), B in another room (comes online with first relay)
    nb = [r for r in lvl.rooms if r.id not in (spawn.id, archive.id)]
    adj = _room_graph(lvl)
    near = [r for r in nb if r.id in adj[spawn.id]] or nb
    ra = rng.choice(near)
    ax, ay = ra.center[0] + 2, ra.center[1] + 2
    used.add((ax, ay))
    lvl.anchors.append({"id": 0, "tx": ax, "ty": ay, "online": True, "room": ra.id})
    others = [r for r in nb if r.id != ra.id]
    rb = max(others, key=lambda r: (abs(r.center[0] - ra.center[0]) + abs(r.center[1] - ra.center[1]), rng.random()))
    bx, by = rb.center[0] - 2, rb.center[1] - 2
    used.add((bx, by))
    lvl.anchors.append({"id": 1, "tx": bx, "ty": by, "online": False, "room": rb.id})

    # core pedestal in archive
    ccx, ccy = archive.center
    lvl.core = (ccx, ccy)
    used.add((ccx, ccy))

    # barrier doors guarding the archive
    for d in lvl.doors:
        if archive.id in (d.room_id, d.room_b):
            d.kind = "barrier"

    # story logs (6) across rooms including the archive
    log_rooms = [archive] + rng.sample([r for r in lvl.rooms if r.id != archive.id], min(5, len(lvl.rooms) - 1))
    for i, r in enumerate(log_rooms):
        x, y = take(r, required=True, edge_only=True)
        lvl.logs.append({"slot": i, "tx": x, "ty": y, "room": r.id})
        lvl.blocked[y][x] = True

    # operable machines (see data/machines.json): spread over distinct rooms, edge tiles, never in the airlock
    from src.config import load_json
    mcfg = load_json("machines.json")
    pool = [r for r in lvl.rooms if r.id != spawn.id]
    rng.shuffle(pool)
    order = []
    for kind, spec in mcfg.items():
        order += [kind] * spec["count"]
    rng.shuffle(order)
    ri = 0
    for kind in order:
        for _ in range(len(pool)):
            r = pool[ri % len(pool)]
            ri += 1
            if r.id == archive.id and kind != "emitter":
                continue
            c = take(r, edge_only=True)
            if c:
                lvl.machines.append({"id": len(lvl.machines), "kind": kind, "tx": c[0], "ty": c[1], "room": r.id})
                lvl.blocked[c[1]][c[0]] = True
                break

    # stabilizer pickups (rare)
    for r in rng.sample([r for r in lvl.rooms if r.id not in (spawn.id,)], 2):
        c = take(r)
        if c:
            lvl.stabilizers.append({"tx": c[0], "ty": c[1]})

    # crates / cover / decor
    loot_mult = mod.get("loot_mult", 1.0)
    for r in lvl.rooms:
        n_loot = max(1, int(round((1 + r.area / 60) * loot_mult)))
        if r.id == spawn.id:
            n_loot = 1
        for _ in range(n_loot):
            c = take(r, edge_only=rng.random() < 0.7)
            if not c:
                continue
            x, y = c
            lvl.props.append({"kind": "crate", "tx": x, "ty": y, "tile": rng.choice([73, 85, 72, 84]), "salvage": rng.randint(1, 3)})
            lvl.blocked[y][x] = True
        for _ in range(max(4, r.area // 26 + rng.randint(0, 3))):
            c = take(r, margin=2)
            if not c:
                continue
            x, y = c
            lvl.props.append({"kind": "cover", "tx": x, "ty": y, "tile": rng.choice([97, 126, 74, 86])})
            lvl.blocked[y][x] = True

    # electrical floor hazards: two in the reactor, one guarding the dock, and one in roughly every third other room
    def hazard_ok(x, y):
        return all(0 <= x + dx < MAP_W and 0 <= y + dy < MAP_H and lvl.grid[y + dy][x + dx] == FLOOR and (x + dx, y + dy) not in used
                   for dx in range(2) for dy in range(2))

    spots = [(reactor.center[0] - 3, reactor.center[1] - 2), (reactor.center[0] + 2, reactor.center[1] + 1),
             (ext.center[0] - 4, ext.center[1] - 1)]
    for r in lvl.rooms:
        if r.id not in (spawn.id, archive.id, reactor.id, ext.id) and rng.random() < 0.34:
            spots.append((r.center[0] + rng.choice([-4, 3]), r.center[1] + rng.choice([-3, 2])))
    for i, (x, y) in enumerate(spots):
        if hazard_ok(x, y):
            lvl.floor_hazards.append({"tx": x, "ty": y, "w": 2, "h": 2, "phase": (i * 1.7) % 6.0})

    # enemies: every room but the airlock holds a mixed group; danger rises with distance from the airlock
    drifter_mult = mod.get("drifter_mult", 1.0)
    sentry_mult = mod.get("sentry_mult", 1.0)
    dist = _dist(_room_graph(lvl), spawn.id)
    for r in lvl.rooms:
        if r.id == spawn.id:
            continue
        d = dist[r.id]
        groups = [("drifter", int(round(rng.choice([1, 1, 2]) * drifter_mult)))]
        if rng.random() < 0.45:
            groups.append(("crawler", rng.randint(2, 3)))
        if rng.random() < 0.45 * sentry_mult:
            groups.append(("sentry", 1))
        if d >= 2 and rng.random() < 0.4:
            groups.append(("stalker", 1))
        if d >= 3 and rng.random() < 0.35:
            groups.append(("brute", 1))
        if r.id == archive.id:
            groups = [("drifter", 2), ("sentry", 1), ("stalker", 1), ("brute", 1)]
        for typ, cnt in groups:
            for _ in range(cnt):
                c = take(r, margin=1)
                if c:
                    lvl.enemy_spawns.append({"type": typ, "pos": tile_center(*c), "room": r.id})
    c = take(reactor, required=True, margin=2)
    lvl.enemy_spawns.append({"type": "warden", "pos": tile_center(*c), "room": reactor.id})

    # patrol entry points (used by Fracture patrols and pressure waves): centres of rooms far from spawn
    for r in lvl.rooms:
        if r.id not in (spawn.id,):
            lvl.patrol_spawns.append(tile_center(*r.center))
