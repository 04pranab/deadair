"""Headless batch playtest of bot-driven expeditions. Usage: python tools/batch_playtest.py <first_seed> <count> [skill] [players]"""
import collections
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.bot import TeamBot  # noqa: E402
from src.world.sim import Sim  # noqa: E402


def run_one(seed, skill, roles, max_minutes=15, **kw):
    s = Sim(seed, roles, **kw)
    bot = TeamBot(s, skill=skill, seed=seed)
    n = 0
    while not s.finished and n < 60 * 60 * max_minutes:
        s.update(1 / 60, bot.frames(1 / 60))
        s.drain_events()
        n += 1
    return s


def main():
    first, count = int(sys.argv[1]), int(sys.argv[2])
    skill = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    roles = ["mara", "dax", "imani", "mara"][:n]
    c = collections.Counter()
    tot = collections.defaultdict(float)
    for seed in range(first, first + count):
        s = run_one(seed, skill, roles)
        r = s.result or {"status": "timeout", "time": s.time, "defeats": s.defeats, "revivals": s.revivals, "kills": s.kills, "optional_done": False}
        c[r["status"]] += 1
        for k in ("time", "defeats", "revivals", "kills"):
            tot[k] += r[k]
    print(dict(c), {k: round(v / count, 1) for k, v in tot.items()})


if __name__ == "__main__":
    main()
