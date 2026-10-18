"""Room shapes must never cost reliability: every level solvable, every machine / relay / anchor reachable."""
from collections import Counter

import pytest

from src.world import level as L
from src.settings import TILE


SEEDS = list(range(1, 41))


def test_shapes_appear_and_are_varied():
    c = Counter()
    for s in SEEDS[:12]:
        c.update(r.shape for r in L.generate(s).rooms)
    assert c["rect"] > 0 and sum(v for k, v in c.items() if k != "rect") > 0.4 * sum(c.values())
    assert len([k for k in c if k != "rect"]) >= 4


@pytest.mark.parametrize("seed", SEEDS)
def test_level_valid_and_every_machine_reachable(seed):
    lvl = L.generate(seed)
    assert L.validate(lvl) == []
    ok = L.passable_grid(lvl)
    sp = lvl.spawn_points[0]
    reach = L.flood(ok, (int(sp[0] // TILE), int(sp[1] // TILE)))
    okb = L.passable_grid(lvl, closed_kinds=())
    reach_b = L.flood(okb, (int(sp[0] // TILE), int(sp[1] // TILE)))
    for m in lvl.machines:
        # optional rooms behind a barrier may hold machines (a reward); everything is reachable once the barrier is broken,
        # and the incinerator that Rift counterplay depends on is always reachable with barriers closed
        assert L.adjacent_open(reach_b, m["tx"], m["ty"]) or (m["tx"], m["ty"]) in reach_b, (seed, m["kind"])
        if m["kind"] == "incinerator":
            assert L.adjacent_open(reach, m["tx"], m["ty"]) or (m["tx"], m["ty"]) in reach, (seed, "incinerator behind a barrier")


@pytest.mark.parametrize("seed", SEEDS[:15])
def test_no_walled_in_pockets_and_rooms_keep_a_usable_floor(seed):
    lvl = L.generate(seed)
    ok = L.passable_grid(lvl, closed_kinds=())
    sp = lvl.spawn_points[0]
    reach = L.flood(ok, (int(sp[0] // TILE), int(sp[1] // TILE)))
    for r in lvl.rooms:
        cells = [(x, y) for y in range(r.y0, r.y1) for x in range(r.x0, r.x1) if ok[y][x]]
        assert cells and sum(c not in reach for c in cells) <= 3, (seed, r.name, r.shape)   # a lone tile boxed in by cover is harmless
        assert len(cells) >= 0.45 * r.area, (seed, r.shape)
