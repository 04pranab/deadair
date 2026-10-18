"""Balance guard rails for MERIDIAN against scripted teams. Bots are not people: these catch regressions in pacing and safety,
and do not prove the game is fun or hard enough for humans."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def _run(seed, skill, mode, max_time=420):
    import batch_sim
    return batch_sim.run_one((seed, skill, mode, max_time))


def test_no_safety_violation_in_long_runs():
    for seed in (2, 4):
        r = _run(seed, 0.35, "meridian", 480)
        assert r["violations"] == [], r["violations"]


def test_director_acts_and_baseline_does_not():
    base = _run(1, 1.0, "baseline", 300)
    mer = _run(1, 1.0, "meridian", 300)
    assert base["events_per_min"] == 0.0
    assert mer["events_per_min"] > 0.5


def test_a_strong_team_is_not_wiped_out():
    r = _run(1, 1.0, "meridian", 420)
    assert r["status"] in ("extracted", "timeout", "director_destroyed") and r["defeats"] <= 1


def test_same_seed_same_decisions():
    a = _run(3, 0.6, "meridian", 200)
    b = _run(3, 0.6, "meridian", 200)
    assert a["executed"] == b["executed"] and a["time"] == b["time"]
