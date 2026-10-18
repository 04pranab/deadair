"""Headless batch simulation: MERIDIAN versus the fixed-pacing baseline on identical seeds and scripted-team skill levels.

Usage:  python tools/batch_sim.py [--seeds 8] [--skills 1.0,0.6,0.35] [--max-time 600] [--out batch.json] [--jobs 2]

Both arms run the same measuring apparatus (passive observer), so tension and recovery numbers are comparable. The baseline keeps the
game's original fixed pressure-wave timer; the MERIDIAN arm replaces it. The scripted teams are NOT humans: these numbers show
pacing and safety behaviour, and say nothing about whether the game is more fun."""
import argparse
import json
import os
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEAMS = {1.0: dict(engage=True, pace=1.0), 0.6: dict(engage=True, pace=0.7), 0.35: dict(engage=True, pace=0.55)}


def run_one(args):
    seed, skill, mode, max_time = args
    from src.utils.bot import TeamBot
    from src.world.sim import Sim
    d = "passive" if mode == "baseline" else True
    sim = Sim(seed, ["mara", "dax", "imani"], director=d)
    team = TEAMS.get(skill, dict(engage=True, pace=max(0.4, skill)))
    bot = TeamBot(sim, skill=skill, seed=seed, **team)
    while not sim.finished and sim.time < max_time:
        sim.update(1 / 60, bot.frames(1 / 60))
    dr = sim.director
    res = sim.result or {"status": "timeout", "time": round(sim.time, 1), "defeats": sim.defeats, "revivals": sim.revivals, "kills": sim.kills}
    series = dr.series
    n = max(1, len(series))
    tens = [s[1] for s in series] or [0.0]
    trouble_runs, cur = [], None
    for t, tn, hpm, hpmin, down in series:
        troubled = hpmin < 0.35 or down > 0
        if troubled and cur is None:
            cur = t
        elif not troubled and cur is not None:
            trouble_runs.append(t - cur)
            cur = None
    dmg = dr.observer.dmg_total
    mins = max(1e-6, sim.time / 60)
    defeat_ts = list(dr.observer.defeats)
    spiral = any(b - a < 60 for a, b in zip(defeat_ts, defeat_ts[1:]))
    return {"seed": seed, "skill": skill, "mode": mode, "status": res["status"], "time": res["time"], "defeats": res["defeats"],
            "revivals": res["revivals"], "kills": res["kills"], "dmg_per_min": round(dmg / mins, 1),
            "tension_mean": round(sum(tens) / n, 3), "tension_std": round(st.pstdev(tens), 3),
            "peak_frac": round(sum(1 for x in tens if x >= 0.5) / n, 3), "calm_frac": round(sum(1 for x in tens if x <= 0.15) / n, 3),
            "trouble_mean_s": round(sum(trouble_runs) / len(trouble_runs), 1) if trouble_runs else 0.0,
            "trouble_episodes": len(trouble_runs), "spiral": spiral,
            "executed": dict(dr.executed), "cancelled": dict(dr.cancelled), "violations": list(dr.violations),
            "events_per_min": round(sum(dr.executed.values()) / mins, 2), "decisions": dr.decisions}


def run_batch(seeds, skills, max_time=600, jobs=1):
    work = [(s, k, m, max_time) for s in seeds for k in skills for m in ("baseline", "meridian")]
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            return list(ex.map(run_one, work))
    return [run_one(w) for w in work]


def summarise(rows):
    out = {}
    for mode in ("baseline", "meridian"):
        rs = [r for r in rows if r["mode"] == mode]
        if not rs:
            continue
        ok = [r for r in rs if r["status"] == "extracted"]
        out[mode] = {
            "runs": len(rs), "completion": round(len(ok) / len(rs), 3),
            "time_mean": round(st.mean(r["time"] for r in rs), 1),
            "defeats_per_run": round(st.mean(r["defeats"] for r in rs), 2),
            "dmg_per_min": round(st.mean(r["dmg_per_min"] for r in rs), 1),
            "tension_mean": round(st.mean(r["tension_mean"] for r in rs), 3),
            "tension_std": round(st.mean(r["tension_std"] for r in rs), 3),
            "peak_frac": round(st.mean(r["peak_frac"] for r in rs), 3),
            "calm_frac": round(st.mean(r["calm_frac"] for r in rs), 3),
            "trouble_mean_s": round(st.mean(r["trouble_mean_s"] for r in rs), 1),
            "spiral_runs": sum(1 for r in rs if r["spiral"]),
            "events_per_min": round(st.mean(r["events_per_min"] for r in rs), 2),
            "violations": sum(len(r["violations"]) for r in rs)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--skills", default="1.0,0.6,0.35")
    ap.add_argument("--max-time", type=float, default=600.0)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    seeds = list(range(a.first_seed, a.first_seed + a.seeds))
    skills = [float(x) for x in a.skills.split(",")]
    rows = run_batch(seeds, skills, a.max_time, a.jobs)
    summ = summarise(rows)
    print(json.dumps(summ, indent=1))
    by_skill = {}
    for k in skills:
        by_skill[k] = summarise([r for r in rows if r["skill"] == k])
    print("\nper team skill (completion / defeats per run / dmg per min / peak_frac / trouble_mean_s / violations):")
    for k, s in by_skill.items():
        for m, v in s.items():
            print(f"  skill {k:<5} {m:<9} {v['completion']:.2f} {v['defeats_per_run']:.2f} {v['dmg_per_min']:6.1f} {v['peak_frac']:.2f} {v['trouble_mean_s']:5.1f} {v['violations']}")
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summ, "by_skill": {str(k): v for k, v in by_skill.items()}, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
