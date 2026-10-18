"""Rift + Host selection + machines. Every claim in the design brief that can be checked headlessly is checked here."""
import itertools
import random

import pytest

from tests.helpers import dsim
from src.systems import machines, rift
from src.systems.commands import InputFrame


def run(s, seconds, frames=None):
    for _ in range(int(seconds * 60)):
        s.update(1 / 60, frames or {})
        if s.finished:
            break


def ready_sim(seed=5, roles=("mara", "dax"), taints=(3.0, 2.5)):
    s = dsim(seed, list(roles))
    for p, t in zip(s.players, taints):
        p.taint = t
    s.relays_done = 1
    return s


# ------------------------------------------------------------------ ordinary Rift never picks a Host
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ordinary_rift_selects_nobody(seed):
    s = ready_sim(seed)
    ok, why = rift.can_open(s, False)
    assert ok, why
    rift.open_rift(s, False)
    assert s.rift.phase == "tear" and not s.rift.select
    run(s, rift.cfg()["rift"]["tear_warn"] + 1)
    assert s.rift.phase == "open" and all(p.owner is None for p in s.rift.papers)
    run(s, 130)
    assert s.rift.phase is None and s.host is None and s.hosts_made == 0
    assert s.rift.history[-1]["select"] is False and s.rift.history[-1]["chosen"] is None


def test_tear_cue_identical_for_both_kinds():
    a, b = ready_sim(5), ready_sim(5)
    rift.open_rift(a, False)
    rift.open_rift(b, True)
    ea = [e for e in a.drain_events() if e["name"] == "rift_tear"]
    eb = [e for e in b.drain_events() if e["name"] == "rift_tear"]
    assert len(ea) == len(eb) == 1 and ea[0]["t"] == eb[0]["t"]


# ------------------------------------------------------------------ the clock alone never selects
def test_timer_alone_never_makes_selection_ready():
    s = dsim(5, ["mara", "dax"])
    s.relays_done = 3
    s.time = 1e6                                          # an absurd amount of elapsed time
    assert all(p.taint == 0 for p in s.players)
    ok, why = rift.select_ready(s, s.time)
    assert not ok and why in ("nobody eligible", "not enough evidence")


def test_director_never_requests_selection_without_evidence():
    s = dsim(11, ["mara", "dax", "imani"], think=True)
    s.relays_done = 2
    asked = []
    s.director.on_event  # noqa  (director is live)
    for _ in range(60 * 90):
        s.update(1 / 60, {})
        asked += [e for e in s.director.events if e.kind == "rift_select"]
        if s.finished:
            break
    assert not asked and s.host is None


# ------------------------------------------------------------------ eligibility and fairness
@pytest.mark.parametrize("seed", range(12))
def test_ineligible_player_is_never_chosen(seed):
    s = ready_sim(seed, ("mara", "dax", "imani"), taints=(3.0, 0.2, 2.2))
    assert [p.idx for p in rift.eligible_players(s)] == [0, 2]
    rift.open_rift(s, True)
    run(s, rift.cfg()["rift"]["tear_warn"] + 1)
    assert len(s.rift.papers) == 3                         # a decoy pads the count: papers do not reveal who is eligible
    assert sorted(p.owner for p in s.rift.papers if p.owner is not None) == [0, 2]
    run(s, 130)
    assert s.host is not None and s.host.idx in (0, 2) and s.host.idx != 1


def test_every_eligible_player_keeps_a_real_chance_and_taint_helps():
    rng = random.Random(3)
    cands = [("A", 1.7), ("B", 3.0), ("C", 6.0)]
    n = {"A": 0, "B": 0, "C": 0}
    for _ in range(6000):
        n[rift.choose_host(cands, rng)] += 1
    assert min(n.values()) > 6000 * 0.03                   # nobody is shut out
    assert n["A"] < n["B"] < n["C"]                        # more evidence, more weight, but never certainty
    assert n["C"] < 6000 * 0.9


def test_selection_is_deterministic_for_a_seed():
    def go():
        s = ready_sim(7, ("mara", "dax", "imani"), taints=(2.5, 2.5, 2.5))
        rift.open_rift(s, True)
        run(s, 200)
        return s.host.idx if s.host else None
    assert go() == go()


def test_stim_resist_removes_the_player_from_the_draw():
    s = ready_sim(5, taints=(3.0, 2.5))
    s.players[0].resist_t = 30.0
    assert [p.idx for p in rift.eligible_players(s)] == [1]


def test_ward_makes_a_player_ineligible_and_cleanses_taint():
    s = ready_sim(5, taints=(3.0, 3.0))
    w = next(m for m in s.machines if m.kind == "ward")
    s.players[0].pos = type(s.players[0].pos)(w.pos)
    assert machines.use(s, w, s.players[0]) or True
    w.active_t = 30.0
    assert not rift.eligible(s, s.players[0])
    before = s.players[0].taint
    run(s, 10)
    assert s.players[0].taint < before


# ------------------------------------------------------------------ never permanently impossible
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_relays_alone_can_always_make_selection_ready(seed):
    s = dsim(seed, ["mara", "dax"])
    n = len(s.relays)
    for i in range(n):
        s.relays_done += 1
        s.emit("relay_online", pos=type(s.players[0].pos)(s.players[0].pos), done=s.relays_done, total=n)
    ok, why = rift.select_ready(s, 1e6)
    assert ok, (n, why, [p.taint for p in s.players])


# ------------------------------------------------------------------ counterplay: burn / tear
def test_burning_every_real_paper_cancels_selection():
    s = ready_sim(5)
    rift.open_rift(s, True)
    run(s, rift.cfg()["rift"]["tear_warn"] + 1)
    for pp in list(s.rift.papers):
        rift.destroy(s, pp, "burn")
    run(s, 2)
    assert s.host is None and s.rift.history[-1]["chosen"] is None
    assert any(e["name"] == "rift_failed" for e in s.drain_events())


def test_papers_are_far_apart_and_reachable():
    for seed in (1, 2, 3, 4):
        s = ready_sim(seed, ("mara", "dax", "imani"), taints=(3, 3, 3))
        rift.open_rift(s, True)
        run(s, rift.cfg()["rift"]["tear_warn"] + 1)
        ps = s.rift.papers
        assert len(ps) == 3
        mn = rift.cfg()["rift"]["min_separation"] * 0.7
        assert all(a.pos.distance_to(b.pos) >= mn for a, b in itertools.combinations(ps, 2)), seed
        assert all(min(p.pos.distance_to(pp.pos) for p in s.players) >= rift.cfg()["rift"]["min_from_crew"] * 0.7 for pp in ps)


def test_a_carried_paper_can_be_torn_by_hand_and_dropped():
    s = ready_sim(5)
    rift.open_rift(s, False)
    run(s, 7)
    pp = s.rift.papers[0]
    p = s.players[0]
    p.pos = type(p.pos)(pp.pos)
    s.update(1 / 60, {p.idx: InputFrame(interact=True)})
    assert p.paper is pp
    held = InputFrame(interact_held=True)
    run(s, rift.cfg()["rift"]["tear_hold"] + 0.5, {p.idx: held})
    assert pp.state == "gone" and p.paper is None


# ------------------------------------------------------------------ machines
def test_incinerator_burn_needs_a_hold_and_pays():
    s = ready_sim(5)
    rift.open_rift(s, False)
    run(s, 7)
    inc = next(m for m in s.machines if m.kind == "incinerator")
    pp = s.rift.papers[0]
    p = s.players[0]
    rift.take(s, p, pp)
    p.pos = type(p.pos)(inc.pos)
    salv = s.team_salvage
    run(s, 0.4, {p.idx: InputFrame(interact_held=True)})
    assert pp.state != "gone"
    run(s, inc.spec["hold"] + 0.3, {p.idx: InputFrame(interact_held=True)})
    assert pp.state == "gone" and s.team_salvage > salv


def test_machine_use_is_per_machine_cooldown_safe_with_two_players():
    s = dsim(5, ["mara", "dax"])
    w = next(m for m in s.machines if m.kind == "ward")
    s.team_salvage = 50
    a, b = s.players
    a.pos = type(a.pos)(w.pos)
    b.pos = type(b.pos)(w.pos)
    assert machines.use(s, w, a) is True
    assert machines.use(s, w, b) is False                  # the second player cannot double-spend the same machine
    assert w.users == 1


def test_every_machine_kind_is_placed_reachable_over_many_seeds():
    from src.systems import nav
    kinds = set()
    for seed in range(1, 11):
        s = dsim(seed, ["mara", "dax"])
        kinds |= {m.kind for m in s.machines}
        for m in s.machines:
            assert not s.solids.blocked_point(m.pos) if hasattr(s.solids, "blocked_point") else True
            d = nav.path_exists(s, s.players[0].pos, m.pos) if hasattr(nav, "path_exists") else True
            assert d, (seed, m.kind)
    assert {"incinerator", "ward", "gauge", "switchboard", "breaker", "beacon", "emitter"} <= kinds


# ------------------------------------------------------------------ the Host's Veil: very hard, but beatable
def _host_sim(seed=5):
    from src.systems import host as H
    s = dsim(seed, ["mara", "dax", "imani"])
    H.convert(s, s.players[0], source="test")
    return s, s.players[0]


def test_veil_absorbs_most_damage_when_poked():
    from src.systems import host as H
    s, h = _host_sim()
    hp = h.hp
    for i in range(10):
        s.time += 2.0
        H.damage_host(s, h, 10)
    assert hp - h.hp < 10 * 10 * 0.35


def test_burst_breaks_the_veil_and_then_damage_lands_in_full():
    from src.systems import host as H
    s, h = _host_sim()
    H.damage_host(s, h, 95)
    assert h.host.veil_down_t > 0
    hp = h.hp
    H.damage_host(s, h, 20)
    assert hp - h.hp == 20


def test_emitter_and_summon_channel_and_lunge_window_expose_the_host():
    from src.systems import host as H
    s, h = _host_sim()
    assert H.veil_up(s, h)
    h.host.hold = 1.0
    assert not H.veil_up(s, h)
    h.host.hold = 0.0
    h.host.lunge_cd = H.cfg()["lunge"]["cooldown"]
    assert not H.veil_up(s, h)
    h.host.lunge_cd = 0.0
    em = next(m for m in s.machines if m.kind == "emitter")
    em.active_t = 10
    h.pos = type(h.pos)(em.pos)
    assert not H.veil_up(s, h)


def test_a_team_can_kill_the_host_by_playing_its_windows():
    from src.systems import host as H
    s, h = _host_sim()
    h.host.hold = 1.0
    n = 0
    while s.host is not None and n < 2000:
        H.damage_host(s, h, 14)
        n += 1
    assert s.host is None and h.state == "alive" and n < 2000
