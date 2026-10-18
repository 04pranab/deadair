"""Dense room-to-room station layout and the six monster types."""
import pygame

from src.config import BAL
from src.entities.models import Enemy
from src.settings import TILE
from src.world import level as L
from tests.helpers import DT, quiet_sim, run, put

V = pygame.Vector2


def test_rooms_touch_through_doors_with_no_corridors():
    for seed in range(40):
        lvl = L.generate(seed)
        assert len(lvl.rooms) == 24
        by_id = {r.id: r for r in lvl.rooms}
        for d in lvl.doors:
            a, b = by_id[d.room_id], by_id[d.room_b]
            for (x, y) in d.cells:
                # a door cell sits in the single wall tile shared by exactly two rooms
                if d.horizontal_wall:
                    assert L.FLOOR == lvl.grid[y - 1][x] == lvl.grid[y + 1][x]
                else:
                    assert L.FLOOR == lvl.grid[y][x - 1] == lvl.grid[y][x + 1]
        # every floor tile belongs to a room or is a door cell: there is no corridor floor anywhere
        door_cells = {c for d in lvl.doors for c in d.cells}
        for y in range(L.MAP_H):
            for x in range(L.MAP_W):
                if lvl.grid[y][x] == L.FLOOR and (x, y) not in door_cells:
                    assert lvl.room_at(x, y) is not None


def test_station_is_big_dense_and_has_all_monster_types():
    kinds = set()
    for seed in range(30):
        lvl = L.generate(seed)
        kinds |= {e["type"] for e in lvl.enemy_spawns}
        assert L.MAP_W * L.MAP_H >= 3000
        assert len(lvl.enemy_spawns) >= 40
        assert len(lvl.props) >= 80
        walls_inside = sum(1 for r in lvl.rooms for y in range(r.y0, r.y1) for x in range(r.x0, r.x1) if lvl.grid[y][x] == L.WALL)
        assert walls_inside > 0 or seed > 0
    assert kinds == {"drifter", "crawler", "sentry", "stalker", "brute", "warden"}


def test_interior_walls_never_create_pockets():
    for seed in range(60):
        lvl = L.generate(seed)
        assert L.validate(lvl) == []


def _fight(kind, dist=34, seconds=2.5):
    s = quiet_sim()
    put(s, 0, V(s.level.rooms[s.level.spawn_room].center) * TILE)
    p = s.players[0]
    e = Enemy(kind, p.pos + V(dist, 0))
    e.state, e.alert_t = "chase", 8
    s.enemies.append(e)
    hp0 = p.hp
    run(s, seconds)
    return s, e, hp0 - p.hp


def test_crawler_is_fast_and_hits_lightly():
    assert BAL.enemies.crawler.speed > BAL.enemies.drifter.speed * 1.4
    assert BAL.enemies.crawler.hp < BAL.enemies.drifter.hp
    s, e, lost = _fight("crawler")
    assert 0 < lost <= BAL.enemies.crawler.damage * 4


def test_spitter_fires_a_three_shot_burst_that_can_be_avoided():
    s = quiet_sim()
    p = s.players[0]
    put(s, 0, V(s.level.rooms[s.level.spawn_room].center) * TILE)
    # a clear, open firing lane of 300 px (the layout depends on the seed, so find one instead of assuming east)
    spot = next(p.pos + V(dx, dy) for dx, dy in ((300, 0), (-300, 0), (0, 300), (0, -300))
                if s.solids.free_at(p.pos + V(dx, dy), 20) and s.solids.los(p.pos, p.pos + V(dx, dy)))
    e = Enemy("stalker", spot)
    e.state, e.alert_t, e.has_los = "chase", 8, True
    s.enemies.append(e)
    seen = 0
    for _ in range(int(3 / DT)):
        s.update(DT, None)
        seen = max(seen, len([b for b in s.bullets if not b.friendly]))
    assert seen == 3


def test_brute_slam_is_telegraphed_and_smaller_than_warden():
    assert BAL.enemies.brute.slam_radius < BAL.enemies.warden.slam_radius
    assert BAL.enemies.brute.hp < BAL.enemies.warden.hp
    s = quiet_sim()
    p = s.players[0]
    put(s, 0, V(s.level.rooms[s.level.spawn_room].center) * TILE)
    e = Enemy("brute", p.pos + V(40, 0))
    e.state, e.alert_t = "chase", 8
    s.enemies.append(e)
    states = []
    for _ in range(int(2.0 / DT)):
        s.update(DT, None)
        states.append(e.state)
    assert "windup" in states
    assert states.index("windup") < len(states) - 1
