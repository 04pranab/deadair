"""Render one still per shot of every story scene to PNG (headless). Usage: python tools/cinematic_stills.py <out_dir>"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame  # noqa: E402

from src.game import Game  # noqa: E402
from src.scenes.cinematic import CinematicScene, scripts  # noqa: E402


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    g = Game()
    for key, sc in scripts().items():
        for i, shot in enumerate(sc["shots"]):
            s = CinematicScene(g, key, None)
            s.idx, s.st = i, shot["dur"] * 0.62
            s.draw(g.logical)
            pygame.image.save(g.logical, str(out / f"{key}_{i}_{shot['art']}.png"))
    print("done")


if __name__ == "__main__":
    main()
