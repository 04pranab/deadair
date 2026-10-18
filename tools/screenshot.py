"""Render real gameplay frames headlessly (bot-driven) to PNG files for visual inspection.
Usage: SDL_VIDEODRIVER=dummy python tools/screenshot.py <seed> <out_dir> <t1,t2,...> [players]"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame  # noqa: E402

from src.game import Game  # noqa: E402
from src.scenes.menus import MenuScene, default_coop  # noqa: E402
from src.scenes.play import PlayScene  # noqa: E402
from src.utils.bot import TeamBot  # noqa: E402


def main():
    seed, out, times = int(sys.argv[1]), Path(sys.argv[2]), [float(x) for x in sys.argv[3].split(",")]
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    out.mkdir(parents=True, exist_ok=True)
    g = Game()
    cfg = default_coop(g, n)
    scene = PlayScene(g, ["mara", "dax", "imani"][:n], cfg["devices"], seed=seed)
    bot = TeamBot(scene.sim)
    scene.input.frames = lambda: bot.frames(1 / 60)
    g.change(scene)
    t, i = 0.0, 0
    while i < len(times) and not scene.sim.finished:
        scene.update(1 / 60)
        t += 1 / 60
        if t >= times[i]:
            scene.draw(g.logical)
            pygame.image.save(g.logical, str(out / f"play_{seed}_{int(times[i]):03d}.png"))
            i += 1
    menu = MenuScene(g)
    menu.t = 3.0
    menu.draw(g.logical)
    pygame.image.save(g.logical, str(out / "menu.png"))


if __name__ == "__main__":
    main()
