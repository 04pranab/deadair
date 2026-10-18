"""Machine glitches: seeded, announced, bounded, and more likely as the station fractures."""
import pytest

from tests.helpers import dsim
from src.systems import machines


def test_chance_rises_with_fracture_and_is_capped():
    s = dsim(5, ["mara", "dax"])
    s.fracture = 0
    lo = machines.glitch_chance(s)
    s.fracture = 6
    mid = machines.glitch_chance(s)
    s.fracture = 10
    hi = machines.glitch_chance(s)
    assert 0 < lo < mid <= hi <= 0.30


def _use_all(seed, fracture):
    s = dsim(seed, ["mara", "dax"])
    s.fracture = fracture
    s.team_salvage = 999
    out = []
    for m in s.machines:
        if m.kind == "incinerator":
            continue
        s.drain_events()
        s.players[0].pos = type(s.players[0].pos)(m.pos)
        for _ in range(12):
            m.cd = m.active_t = 0.0
            m.warn_t = 0.0
            if machines.use(s, m, s.players[0]):
                out.append(m.kind)
        out += [(e["kind"], e["how"]) for e in s.drain_events() if e["name"] == "machine_glitch"]
    return out


def test_glitches_are_deterministic_for_a_seed():
    assert _use_all(5, 8) == _use_all(5, 8)


def test_high_fracture_glitches_somewhere_and_each_glitch_is_announced():
    s = dsim(5, ["mara", "dax"])
    s.fracture = 10
    s.team_salvage = 999
    seen = 0
    for m in s.machines:
        if m.kind == "incinerator":
            continue
        s.players[0].pos = type(s.players[0].pos)(m.pos)
        for _ in range(40):
            m.cd = m.active_t = m.warn_t = 0.0
            s.drain_events()
            used = machines.use(s, m, s.players[0])
            names = [e["name"] for e in s.drain_events()]
            if "machine_glitch" in names:
                assert used and "machine_used" in names
                seen += 1
    assert seen > 0


@pytest.mark.parametrize("kind", ["ward", "emitter", "beacon"])
def test_a_glitch_never_zeroes_a_machine(kind):
    s = dsim(5, ["mara", "dax"])
    s.fracture = 10
    s.team_salvage = 9999
    ms = [m for m in s.machines if m.kind == kind]
    assert ms
    m = ms[0]
    s.players[0].pos = type(s.players[0].pos)(m.pos)
    for _ in range(60):
        m.cd = m.active_t = m.warn_t = 0.0
        if machines.use(s, m, s.players[0]):
            assert m.active_t > 0


# ------------------------------------------------------------------ MERIDIAN lies
def _false_tell(seed=5):
    from src.systems import director_events as ev
    s = dsim(seed, ["mara", "dax"])
    s.time = 300.0
    d = s.director
    e = ev.EVENT_CLASSES["false_tell"](1, d, {}, s.time, 0.0, "test", d.obs_id)
    ok, why = e.validate(s, "schedule")
    assert ok, why
    d.events.append(e)
    e.state = ev.SCHEDULED
    return s, d, e


def test_false_tell_looks_like_a_real_tell_and_then_nothing_happens():
    s, d, e = _false_tell()
    hp = [p.hp for p in s.players]
    names = []
    for _ in range(60 * 12):
        s.update(1 / 60, {})
        names += [x["name"] for x in s.drain_events()]
    assert names.count("rift_tell") == 1                 # the identical cue a real Rift gives
    assert names.count("rift_fizzle") == 1               # and then it admits nothing was there
    assert "rift_open" not in names and "rift_tear" not in names and not s.rift.papers
    assert [p.hp for p in s.players] == hp               # harmless by construction
    assert e.state == "resolved" and s.rift.tell_until == 0.0


def test_false_tell_is_refused_while_a_real_rift_is_open_or_during_the_ritual():
    from src.systems import director_events as ev
    s, d, e = _false_tell()
    s.rift.tell_until = s.time + 5
    assert e.validate(s, "schedule")[0] is False
    s.rift.tell_until = 0.0
    s.anchors[0].echo = object()
    assert e.validate(s, "schedule")[0] is False
