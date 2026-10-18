"""DEAD AIR: SHIFT ZERO. Run with:  python main.py"""
import argparse
import sys

from src.game import Game
from src.scenes.menus import MenuScene
from src.utils import input_map


def main(argv=None):
    ap = argparse.ArgumentParser(description="DEAD AIR: SHIFT ZERO")
    ap.add_argument("--frames", type=int, default=None, help="exit after N frames (smoke test)")
    ap.add_argument("--play", action="store_true", help="skip the menu and start an expedition")
    ap.add_argument("--players", type=int, default=1, help="local players for --play (1-4)")
    args = ap.parse_args(argv)
    input_map.write_default_controls()
    game = Game()
    from src.scenes.menus import default_coop
    if args.play:
        from src.scenes.play import PlayScene
        cfg = default_coop(game, max(1, min(4, args.players)))
        game.coop_config = cfg
        game.change(PlayScene(game, cfg["roles"], cfg["devices"]))
    else:
        game.change(MenuScene(game))
    game.run(max_frames=args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
