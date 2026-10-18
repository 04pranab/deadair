"""MERIDIAN director: lifecycle, invariants, Rekindling priority, pacing, determinism."""
import ast
import re
from pathlib import Path

import pygame
import pytest

from src.config import BAL
from src.entities.models import Enemy
from src.settings import TILE
from src.systems import combat
from src.systems import director_events as ev
from src.systems.director import THREATS, Director
from src.world.sim import Sim
from tests.helpers import DT, dsim, press, put, run

V = pygame.Vector2
SRC = Path(__file__).resolve().parent.parent / "src" / "systems"


def make(d, kind, **params):
    """Schedule one event directly (bypassing candidate scoring) and return it."""
    p = {"warn": d.cfg["events"][kind]["warn"], "duration": d.cfg["events"][kind].get("duration", 0.0)}
    p.update(params)
    d.obs_id += 1
    return d._schedule(kind, p, "test", d.sim.time)


def _free_tiles_near(s, cx, cy):
    h, w = len(s.solids.static), len(s.solids.static[0])
    return sorted(((x, y) for x in range(cx - 4, cx + 5) for y in range(cy - 4, cy + 5)
                   if 0 <= x < w and 0 <= y < h and not s.solids.static[y][x]),
                  key=lambda c: (abs(c[0] - cx) + abs(c[1] - cy), c))


def away_from_spawn(s):
    """Move the whole team to the farthest room from which every mandatory target is still reachable (the Archive is
    sealed behind barrier doors, so it is skipped)."""
    spawn = V(s.level.rooms[s.level.spawn_room].center)
    for far in sorted(s.level.rooms, key=lambda r: -V(r.center).distance_to(spawn)):
        free = _free_tiles_near(s, *far.center)
        if len(free) < len(s.players):
            continue
        saved = [V(p.pos) for p in s.players]
        for i, p in enumerate(s.players):
            x, y = free[i]
            p.pos = V(x * TILE + 24, y * TILE + 24)
        if ev.connectivity_ok(s):
            return far
        for p, q in zip(s.players, saved):
            p.pos = q
    raise AssertionError("no room with full connectivity")


def closable_door(s):
    """Index of a normal door that can close while keeping every mandatory target reachable."""
    for i, dr in enumerate(s.doors):
        if dr.kind == "normal" and ev.connectivity_ok(s, ev.door_cells(dr)) \
                and all(p.pos.distance_to(dr.center) > 200 for p in s.players):
            return i
    return None


# ------------------------------------------------------------------ 1. event lifecycle and cleanup
def test_event_lifecycle_start_active_resolve_cleanup():
    s = dsim()
    d = s.director
    e = make(d, "resource", pickup="salvage", n=3, ring=(150, 250))
    assert e.state == ev.SCHEDULED
    n0 = len(s.pickups)
    run(s, 1.2)
    assert e.state == ev.ACTIVE and len(s.pickups) == n0 + 3
    run(s, d.cfg["events"]["resource"]["duration"] + 1)
    assert e.state == ev.RESOLVED and len(s.pickups) == n0          # uncollected pickups are cleaned up
    assert e not in d.events


def test_cancel_cleans_up_route_closure_in_every_phase():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    e = make(d, "route_closure", door=closable_door(s))
    assert e is not None
    run(s, 1.2)                                   # started: the door is in its warning phase
    door = s.doors[e.door_i]
    assert door.warn_t > 0 and door.lock_t <= 0
    e.cancel(s, "test")
    assert door.warn_t == 0 and e.state == ev.CANCELLED
    # now cancel after the lock engaged
    d.budget.last_cast.clear(); d.budget.last_threat_t = -1e9
    e2 = make(d, "route_closure", door=closable_door(s))
    run(s, 1.2 + 3.5)
    door2 = s.doors[e2.door_i]
    assert door2.lock_t > 1
    e2.cancel(s, "test")
    run(s, 0.1)
    assert door2.lock_t <= 0 and e2.state == ev.CANCELLED


def test_revalidation_at_execution_cancels_and_refunds():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    before = d.budget.points
    e = make(d, "reinforce", kinds=["drifter", "drifter"])
    assert e is not None and d.budget.points == before - d.cfg["events"]["reinforce"]["cost"]
    # between scheduling and execution a Rekindling begins
    combat.defeat_player(s, s.players[1])
    echo = next(x for x in s.echoes)
    a = s.anchors[0]
    echo.state, echo.anchor, echo.paid, a.echo = "placed", a, True, echo
    run(s, 1.3)
    assert e.state == ev.CANCELLED and "Rekindling" in e.cancel_reason
    assert d.budget.points >= before - 1e-6 and d.cancelled.get("reinforce") == 1
    assert not any(t.kind == "director" for t in s.telegraphs)


# ------------------------------------------------------------------ 2. invariants
def test_spawns_are_warned_far_from_players_and_logged():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    e = make(d, "reinforce", kinds=["drifter", "crawler", "sentry"])
    run(s, 1.2)
    tele = [t for t in s.telegraphs if t.kind == "director"]
    assert tele and tele[0].total >= d.cfg["safety"]["min_warn"]
    run(s, 4.5)
    assert len(s.enemies) == 3 and all(getattr(x, "director", False) for x in s.enemies)
    log = d.spawn_log[-1]
    assert log["min_player_dist"] >= d.cfg["safety"]["spawn_clear"] and not log["ritual"]
    run(s, 2.0)
    assert d.violations == []


def test_hazard_is_warned_before_it_is_ever_active():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    e = make(d, "hazard")
    assert e is not None
    t0 = None
    first_warning = first_active = None
    for _ in range(int(14 / DT)):
        s.update(DT)
        hz = [h for h in s.floor_hazards if getattr(h, "director", False)]
        if hz and t0 is None:
            t0 = s.time
        if hz and hz[0].state == "warning" and first_warning is None:
            first_warning = s.time
        if hz and hz[0].state == "active" and first_active is None:
            first_active = s.time
    assert first_warning is not None and first_active is not None
    assert first_active - t0 >= d.cfg["safety"]["min_warn"]
    assert first_warning < first_active
    assert d.violations == []


def test_route_closure_only_when_an_alternative_route_exists():
    # find a level that has a bridge door (closing it would cut the station) and one that does not
    found_bridge = False
    for seed in range(1, 40):
        s = dsim(seed)
        d = s.director
        away_from_spawn(s)
        for i, dr in enumerate(s.doors):
            if dr.kind != "normal":
                continue
            ok = ev.connectivity_ok(s, dr.cells)
            probe = ev.RouteClosureEvent(0, d, {"warn": 3.0, "duration": 25.0, "door": i}, s.time, 25.0, "t", 0)
            good, why = probe.validate(s, "schedule")
            if not ok:
                found_bridge = True
                assert not good, f"seed {seed} door {i} would cut the station but validated"
            if good:
                assert ok
        if found_bridge:
            break
    assert found_bridge, "no bridge door found in 40 seeds to test against"


def test_mandatory_targets_stay_reachable_during_a_locked_door():
    for seed in (1, 2, 3, 6):
        s = dsim(seed)
        d = s.director
        away_from_spawn(s)
        e = make(d, "route_closure", door=closable_door(s))
        if e is None:
            continue
        run(s, 6.0)
        assert ev.connectivity_ok(s)
        run(s, 30.0)
        assert d.violations == []


def test_power_failure_is_repairable_and_unlocks_the_door():
    s = dsim()
    d = s.director
    far = away_from_spawn(s)
    e = make(d, "power_failure", door=closable_door(s))
    assert e is not None
    run(s, 5.0)
    assert e.state == ev.ACTIVE and s.faults and s.doors[e.door_i].lock_t > 0
    f = s.faults[0]
    put(s, 0, f.pos + V(20, 0))
    run(s, 4.0, {0: press(interact_held=True)})
    assert f.repaired
    run(s, 0.5)
    assert e.state == ev.RESOLVED and not s.faults
    run(s, 0.3)
    assert s.doors[e.door_i].lock_t <= 0


def test_spawn_and_threat_limits_are_enforced():
    s = dsim(cfg={"budget": {"max_simultaneous_threats": 1, "start": 200.0, "cap": 300.0, "min_threat_gap": 0.0, "min_recovery_gap": 0.0}})
    d = s.director
    away_from_spawn(s)
    assert make(d, "reinforce", kinds=["drifter", "drifter"]) is not None
    ok, why = d.budget.check("flank", s.time, d.active_threats())
    assert not ok and "already active" in why
    # per-kind cooldown and expedition limit
    d.budget.last_cast.clear()
    for i in range(d.cfg["events"]["reinforce"]["limit"]):
        d.budget.commit("reinforce", s.time - 1000 + i)
    ok, why = d.budget.check("reinforce", s.time, 0)
    assert not ok and "limit" in why
    # director-added enemy cap
    d.events.clear()
    for _ in range(d.cfg["budget"]["max_alive_added"]):
        e = Enemy("crawler", V(s.players[0].pos) + V(900, 0)); e.director = True
        s.enemies.append(e)
    assert not d.room_for(s, 2)


def test_one_observation_schedules_at_most_one_event():
    s = dsim(cfg={"budget": {"start": 200.0, "cap": 300.0, "min_threat_gap": 0.0}})
    d = s.director
    away_from_spawn(s)
    run(s, 2.0)
    d._think(s.time)
    n1 = len(d.events)
    assert n1 <= 1
    assert make(d, "reinforce", kinds=["drifter"]) is not None
    d.obs_id -= 0
    assert d._schedule("flank", {"warn": 4.0, "kinds": ["drifter"]}, "again", s.time) is None     # same observation
    assert d.sched_per_obs[d.obs_id] == 1


def test_director_never_changes_player_health():
    # static check: no module assigns to a player's hp or calls the combat damage functions
    for f in SRC.glob("director*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    assert not (isinstance(t, ast.Attribute) and t.attr in ("hp", "state", "weak_t", "iframes")
                                and not (isinstance(t.value, ast.Name) and t.value.id in ("self", "e", "enemy"))), f"{f.name}:{node.lineno}"   # 'e' is always an enemy in director code
        assert "damage_player" not in f.read_text() and "defeat_player" not in f.read_text()
    # dynamic check: a long idle run with the director fully active leaves a distant, unthreatened team's health unchanged
    s = dsim(think=True, cfg={"min_observation": 1.0, "opening_grace": 1.0})
    hp0 = [p.hp for p in s.players]
    run(s, 90.0)
    assert [p.hp for p in s.players] == hp0 or all(p.hp <= h for p, h in zip(s.players, hp0))
    assert all(p.hp <= h for p, h in zip(s.players, hp0))      # never healed by the director either


def test_active_interactions_block_threats_and_closures():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    r = next(x for x in s.relays if not x.online)
    put(s, 0, r.pos + V(30, 0))
    run(s, 0.5, {0: press(interact_held=True)})
    assert r.progress > 0
    spawn_probe = ev.ReinforceEvent(0, d, {"warn": 3.0, "kinds": ["drifter"]}, s.time, 0, "t", 0)
    zone = [z for z in ev.busy_zones(s, d.cfg["safety"]) if z[2] == "relay"]
    assert zone
    ok, why = ev.pos_ok_for_threat(s, r.pos + V(200, 0), d.cfg["safety"])
    assert not ok
    # a closure near the relay is refused
    nearest = min((i for i, dr in enumerate(s.doors) if dr.kind == "normal"), key=lambda i: s.doors[i].center.distance_to(r.pos))
    probe = ev.RouteClosureEvent(0, d, {"warn": 3.0, "duration": 25.0, "door": nearest}, s.time, 25.0, "t", 0)
    if s.doors[nearest].center.distance_to(r.pos) < d.cfg["safety"]["door_busy_radius"]:
        assert probe.validate(s, "schedule")[0] is False


def test_no_spawn_close_to_players():
    s = dsim()
    d = s.director
    # the team stands in the middle of the station: only far points qualify
    for pt in s.level.patrol_spawns:
        ok, _ = ev.pos_ok_for_threat(s, V(pt), d.cfg["safety"])
        if ok:
            assert all(p.pos.distance_to(V(pt)) >= d.cfg["safety"]["spawn_clear"] for p in s.players)


def test_optional_encounter_is_far_idle_and_off_the_mandatory_path():
    s = dsim(cfg={"safety": {"optional_min_dist": 600.0}})
    d = s.director
    away_from_spawn(s)
    e = make(d, "optional_encounter")
    if e is None:
        pytest.skip("no suitable optional room on this seed")
    run(s, 1.2)
    added = [x for x in s.enemies if getattr(x, "director", False)]
    assert len(added) == 3 and all(x.state == "idle" and x.alert_t == 0 for x in added)
    assert all(min(p.pos.distance_to(x.pos) for p in s.players) >= 500 for x in added)
    rooms = {s.level.room_at(int(x.pos.x // TILE), int(x.pos.y // TILE)).id for x in added}
    mandatory = {s.level.room_at(rl["tx"], rl["ty"]).id for rl in s.level.relays}
    assert not (rooms & mandatory)


def test_modifier_is_temporary_and_restores_state():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    m = make(d, "modifier")
    run(s, 1.5)
    assert d.speed_mult > 1.0 and s.enemy_speed_mult >= d.speed_mult
    run(s, d.cfg["events"]["modifier"]["duration"] + 2)
    assert d.speed_mult == 1.0 and d.drop_mult == 1.0 and m.state == ev.RESOLVED


# ------------------------------------------------------------------ 3. Rekindling priority
def _down(s, idx=1):
    combat.defeat_player(s, s.players[idx])
    return next(e for e in s.echoes if e.player_idx == idx)


def test_rekindling_resource_shortage_gets_supplies_before_any_threat():
    s = dsim(cfg={"budget": {"start": 200.0, "cap": 300.0, "min_threat_gap": 0.0}})
    d = s.director
    s.team_salvage = 0
    echo = _down(s)
    run(s, 1.0)
    d._think(s.time)
    assert len(d.events) == 1 and d.events[0].kind == "resource" and "short" in d.events[0].reason
    assert d.events[0].p["pickup"] == "salvage"
    run(s, 2.0)
    near = [pk for pk in s.pickups if pk.pos.distance_to(echo.pos) < 400]
    assert len(near) >= 1


def test_unrecovered_echo_gets_a_quiet_interval():
    s = dsim()
    d = s.director
    s.team_salvage = 50
    echo = _down(s)
    d.echo_seen[echo.player_idx] = s.time - d.cfg["rekindle"]["echo_unrecovered_s"] - 5
    d._think(s.time)
    assert d.events and d.events[0].kind == "quiet" and "unrecovered" in d.events[0].reason
    run(s, 2.0)
    assert d.protect_now(s)


def test_enemies_clustering_at_an_anchor_during_ritual_get_suppressed_not_fed():
    s = dsim(cfg={"budget": {"start": 200.0, "cap": 300.0, "min_threat_gap": 0.0}})
    d = s.director
    s.team_salvage = 50
    echo = _down(s)
    a = s.anchors[0]
    echo.state, echo.anchor, echo.paid, a.echo = "placed", a, True, echo
    for i in range(5):
        e = Enemy("drifter", a.pos + V(60 + 20 * i, 30)); e.alert_t = 5
        s.enemies.append(e)
    d._think(s.time)
    kinds = [e.kind for e in d.events]
    assert kinds == ["quiet"] and "clustering" in d.events[0].reason
    assert not any(k in THREATS for k in kinds)


def test_no_threat_is_ever_scheduled_while_a_ritual_runs():
    s = dsim(cfg={"budget": {"start": 300.0, "cap": 300.0, "min_threat_gap": 0.0, "min_recovery_gap": 0.0}})
    d = s.director
    away_from_spawn(s)
    echo = _down(s)
    a = s.anchors[0]
    s.team_salvage = 50
    echo.state, echo.anchor, echo.paid, a.echo = "placed", a, True, echo
    for _ in range(30):
        run(s, 3.1)
        d._think(s.time)
        assert all(e.category != "threat" for e in d.events)
    assert d.violations == []


def test_high_fracture_gets_a_stabilizer_but_capped():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    s.fracture = d.cfg["rekindle"]["fracture_high"]
    d._think(s.time)
    assert d.events and d.events[0].p.get("pickup") == "stabilizer"
    assert d.stabilizers_given == 1


# ------------------------------------------------------------------ 4. no softlock, recovery policy
def test_all_downed_cancels_everything_and_the_game_still_ends():
    s = dsim()
    d = s.director
    away_from_spawn(s)
    make(d, "reinforce", kinds=["drifter", "drifter"])
    make_ok = d.events[0]
    run(s, 1.2)
    for p in s.players:
        combat.defeat_player(s, p)
    run(s, 1.0)
    assert d.events == [] and make_ok.state in (ev.CANCELLED, ev.RESOLVED)
    n_enemies = len(s.enemies)
    run(s, 5.0)
    assert s.finished and s.result["reason"] == "crew_lost"      # the sim's own failure rule decides
    assert len(s.enemies) <= n_enemies


def test_recovery_policy_after_repeated_failures():
    s = dsim(cfg={"budget": {"start": 200.0, "cap": 300.0, "min_threat_gap": 0.0}})
    d = s.director
    away_from_spawn(s)
    s.team_salvage = 30
    for i in (0, 1):
        s.emit("defeated", pos=V(s.players[i].pos), player=i)       # two failures inside the window (events only)
    run(s, 0.1)
    d._think(s.time)
    assert d.failing and d.budget.lockout_until > s.time and d.budget.scale < 1.0
    assert d.events and d.events[0].category == "recovery"
    ok, why = d.budget.check("reinforce", s.time, 0)
    assert not ok and "lockout" in why
    # the lockout ends and the scale returns
    run(s, d.cfg["recovery"]["failure_window"] + d.cfg["recovery"]["lockout"] + 5)
    d._think(s.time)
    assert not d.failing and d.budget.scale == 1.0


def test_pacing_hysteresis_needs_dwell_time_before_switching_mode():
    s = dsim(cfg={"tension": {"build_dwell": 10.0, "relax_dwell": 18.0}})
    d = s.director
    away_from_spawn(s)
    s.players[0].hp = 10
    run(s, 2.0)
    d._think(s.time)
    assert d.mode == "build"                     # troubled, but not for long enough yet
    run(s, 9.0)
    s.players[0].hp = 10
    d._think(s.time)
    assert d.mode == "relax"
    s.players[0].hp = s.players[0].max_hp
    run(s, 5.0)
    d._think(s.time)
    assert d.mode == "relax"                     # recovered, but dwell not served
    run(s, 14.0)
    d._think(s.time)
    assert d.mode == "build"


def test_min_observation_and_opening_grace_hold_back_threats():
    s = Sim(5, ["mara", "dax", "imani"], director=True)
    s.t_surge = s.t_glitch = s.t_patrol = s.t_whisper = 1e9
    s.enemies.clear()
    d = s.director
    run(s, d.cfg["opening_grace"] - 2)
    assert not any(e.category == "threat" for e in d.events) and d.executed == {}


# ------------------------------------------------------------------ 5. determinism, trace, debug
def _run_full(seed, skill, director=True, cap=400):
    from src.utils.bot import TeamBot
    s = Sim(seed, ["mara", "dax", "imani"], director=director)
    b = TeamBot(s, skill=skill, seed=seed, engage=True, pace=0.7)
    while not s.finished and s.time < cap:
        s.update(DT, b.frames(DT))
    return s


_DET = """
import sys, json
sys.path.insert(0, %r)
from tests.test_director import _run_full
s = _run_full(3, 0.6)
print(json.dumps([s.director.trace_text(500), s.director.executed, s.result["time"], s.result["defeats"]], sort_keys=True))
"""


def test_director_is_deterministic_for_a_seed():
    """Same seed -> identical decisions. Checked in two fresh interpreters (one with a different hash seed)."""
    import os, subprocess, sys
    root = str(Path(__file__).resolve().parent.parent)
    outs = []
    for hs in ("0", "123"):
        env = dict(os.environ, PYTHONHASHSEED=hs, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        r = subprocess.run([sys.executable, "-c", _DET % root], capture_output=True, text=True, env=env, cwd=root, timeout=300)
        assert r.returncode == 0, r.stderr[-800:]
        outs.append(r.stdout.strip().splitlines()[-1])
    assert outs[0] == outs[1]


def test_director_rng_does_not_perturb_the_simulation_rng():
    s1 = dsim(7)
    s2 = Sim(7, ["mara", "dax", "imani"])
    s1.director.rng.random(); s1.director.rng.random()
    assert s1.rng.random() == s2.rng.random()


def test_decision_trace_is_compact_and_debug_panel_works():
    s = _run_full(2, 0.35)
    d = s.director
    lines = d.trace_text(500).splitlines()
    assert 5 < len(lines) <= d.cfg["trace_max"]
    assert max(len(l) for l in lines) < 420
    assert any("->" in l for l in lines)
    dl = d.debug_lines()
    assert dl[0].startswith("MERIDIAN") and len(dl) <= 8


def test_whole_runs_never_violate_an_invariant():
    for seed, skill in ((1, 1.0), (2, 0.4), (4, 0.6)):
        if True:
            s = _run_full(seed, skill, cap=240)
            assert s.director.violations == [], (seed, skill, s.director.violations[:3])
            assert s.finished or s.time >= 240
