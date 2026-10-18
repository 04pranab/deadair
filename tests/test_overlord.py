"""MERIDIAN's Avatar: shield, three phases, foresight, predecessors, beatability."""
from tests.helpers import dsim
from src.systems import overlord
from src.systems.commands import InputFrame
from src.systems.overlord import OverlordState


def awake(seed=5):
    s = dsim(seed, ["mara", "dax", "imani"])
    s.overlord = s.overlord or OverlordState()
    s.exposed = True
    overlord._awaken(s, s.overlord)
    return s, s.overlord


def run(s, sec, frames=None):
    for _ in range(int(sec * 60)):
        s.update(1 / 60, frames or {})
        if s.finished:
            break


def test_shield_blocks_almost_all_damage_until_a_conduit_opens_it():
    s, ov = awake()
    av = ov.avatar
    assert overlord.damage_factor(s, av) < 0.1
    ov.exposed_t = 10
    assert overlord.damage_factor(s, av) == 1.0


def test_phase_two_closes_the_shield_and_resets_every_conduit():
    s, ov = awake()
    ov.exposed_t = 20
    for c in ov.conduits:
        c.cool = 30
    ov.avatar.hp = ov.avatar.max_hp * 0.6
    run(s, 0.1)
    assert ov.phase == 2 and ov.exposed_t == 0 and all(c.cool == 0 for c in ov.conduits)


def test_phase_three_summons_predecessors_and_darkens_the_station():
    s, ov = awake()
    ov.avatar.hp = ov.avatar.max_hp * 0.3
    run(s, 0.1)
    assert ov.phase == 3 and ov.ghosts >= 1
    run(s, 1)
    assert s.director.blackout > 0 or ov.dark_t > 0


def test_foresight_strikes_the_conduit_being_turned():
    s, ov = awake()
    ov.avatar.hp = ov.avatar.max_hp * 0.5
    run(s, 0.1)
    assert ov.phase == 2
    cd = ov.conduits[0]
    p = s.players[0]
    p.pos = type(p.pos)(cd.pos)
    n0 = len(s.telegraphs)
    run(s, 2.5, {p.idx: InputFrame(interact_held=True)})
    assert any(e["name"] == "foresight" for e in s.drain_events())


def test_shipped_config_makes_meridian_invincible():
    """The shipped setting: nothing the crew does can destroy it. Damage still drives phases; the way out is extraction."""
    from src.systems import combat, overlord
    assert overlord.cfg()["avatar"]["invincible"] is True
    s, ov = awake()
    ov.exposed_t = 20
    combat.damage_enemy(s, ov.avatar, 1e9)
    run(s, 0.5)
    assert not s.finished and not ov.avatar.dead and ov.avatar.hp >= 1.0
    assert ov.phase == 3


def test_it_is_beatable_when_the_invincible_flag_is_off(monkeypatch):
    """With avatar.invincible=false every phase can be finished (a scripted best case, not a human)."""
    from src.systems import overlord
    monkeypatch.setitem(overlord.cfg()["avatar"], "invincible", False)
    s, ov = awake()
    av = ov.avatar
    for want in (2, 3):
        ov.exposed_t = 20
        av.hp = max(1.0, av.max_hp * (0.6 if want == 2 else 0.3))
        run(s, 0.1)
        assert ov.phase == want
    ov.exposed_t = 20
    from src.systems import combat
    combat.damage_enemy(s, av, 1e9)
    run(s, 0.1)
    assert s.finished and s.result["status"] == "director_destroyed"


def _window(s, ov, how, amount=200):
    from src.systems import combat
    ov.exposed_t = 5
    combat.damage_enemy(s, ov.avatar, amount, how=how)
    ov.exposed_t = 0.001
    run(s, 0.05)


def test_repeating_one_damage_type_gets_it_countered():
    s, ov = awake()
    _window(s, ov, "shot")
    assert ov.adapted.get("shot") == 1
    f1 = overlord.learned_factor(ov, "shot")
    _window(s, ov, "shot")
    assert ov.adapted["shot"] == 2 and overlord.learned_factor(ov, "shot") < f1
    assert overlord.learned_factor(ov, "charge") == 1.0       # other categories are untouched


def test_mixing_damage_types_is_never_countered_hard():
    s, ov = awake()
    from src.systems import combat
    for _ in range(4):
        ov.exposed_t = 5
        for how in ("shot", "charge", "blast"):
            combat.damage_enemy(s, ov.avatar, 80, how=how)
        ov.exposed_t = 0.001
        run(s, 0.05)
    assert all(v == 0 for v in ov.adapted.values())


def test_it_forgets_a_tactic_the_crew_stops_using():
    s, ov = awake()
    _window(s, ov, "shot")
    assert ov.adapted["shot"] == 1
    _window(s, ov, "charge")
    assert ov.adapted.get("shot", 0) == 0 and ov.adapted["charge"] == 1


def test_next_generation_starts_already_resisting_the_last_winning_tactic(tmp_path):
    from src.systems.director_memory import Memory
    mem = Memory(tmp_path / "director_memory.json")
    e = mem.begin_expedition()
    mem.record(e, "doctrine", "learned shot", 4, ["doctrine:shot"], data={"how": "shot"})
    mem.save()
    s = dsim(5, ["mara", "dax"], directory=tmp_path)
    s.overlord = s.overlord or OverlordState()
    s.exposed = True
    overlord._awaken(s, s.overlord)
    assert s.overlord.adapted.get("shot") == 1 and "shot" in s.overlord.inherited


def test_a_new_kind_of_attack_surprises_it_and_lengthens_the_window():
    from src.systems import combat
    s, ov = awake()
    ov.exposed_t = 5
    combat.damage_enemy(s, ov.avatar, 10, how="shot")
    t0 = ov.exposed_t
    combat.damage_enemy(s, ov.avatar, 10, how="charge")
    assert ov.exposed_t > t0
    combat.damage_enemy(s, ov.avatar, 10, how="charge")
    assert ov.exposed_t <= t0 + overlord.cfg()["doctrine"]["novel_bonus"]
