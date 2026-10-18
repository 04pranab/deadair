"""Story scenes: always skippable, never touch the simulation, hidden-director rule respected, every shot renders."""
import pygame
import pytest

from src.game import Game
from src.scenes.cinematic import SKIP_HOLD, CinematicScene, scripts
from src.ui import cine_art


@pytest.fixture(scope="module")
def game():
    return Game()


def test_every_shot_has_a_known_painter_and_lines_fit_inside_it():
    for key, sc in scripts().items():
        for shot in sc["shots"]:
            assert shot["art"] in cine_art.ART, (key, shot["art"])
            assert shot["dur"] >= 3.0
            assert all(0 <= ln["t"] < shot["dur"] - 1.0 for ln in shot.get("lines", [])), (key, shot["art"])
            assert all(len(ln["text"]) <= 96 for ln in shot.get("lines", [])), "story text stays short"


def test_every_shot_renders_at_start_middle_and_end(game):
    for key, sc in scripts().items():
        for i, shot in enumerate(sc["shots"]):
            for f in (0.0, 0.5, 0.99):
                s = CinematicScene(game, key, None)
                s.idx, s.st = i, shot["dur"] * f
                s.draw(game.logical)


def test_intro_keeps_the_director_hidden_and_reveal_names_it():
    def text(key):
        return " ".join(ln["text"] + ln.get("who", "") for sh in scripts()[key]["shots"] for ln in sh.get("lines", []))
    assert "MERIDIAN" not in text("intro")
    assert "MERIDIAN" in text("reveal") and "KEEP THE CREW" in text("reveal")


def test_scene_runs_to_the_end_by_itself_and_hands_over(game):
    nxt = object()
    s = CinematicScene(game, "lost", nxt)
    game.change(s)
    for _ in range(int(60 * (sum(sh["dur"] for sh in s.shots) + 2))):
        s.update(1 / 60)
    assert game.scene is nxt


def test_holding_any_key_skips_and_a_tap_does_not(game):
    nxt = object()
    s = CinematicScene(game, "reveal", nxt)
    game.change(s)
    s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    s.update(SKIP_HOLD * 0.4)
    s.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
    s.update(0.1)
    assert game.scene is not nxt
    s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    for _ in range(int(60 * (SKIP_HOLD + 0.2))):
        s.update(1 / 60)
    assert game.scene is nxt


def test_escape_skips_immediately(game):
    nxt = object()
    s = CinematicScene(game, "intro", nxt)
    game.change(s)
    s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert game.scene is nxt


def test_playscene_freezes_the_sim_during_a_scene_and_respects_the_setting(game):
    from src.scenes.menus import default_coop
    from src.scenes.play import PlayScene
    from src.systems import host
    cfg = default_coop(game, 2)
    sc = PlayScene(game, ["mara", "dax"], cfg["devices"], seed=3)
    game.change(sc)
    sc.update(1 / 60)
    assert isinstance(game.scene, CinematicScene)           # intro
    t0 = sc.sim.time
    for _ in range(600):
        game.scene.update(1 / 60)
        if game.scene is sc:
            break
    assert sc.sim.time == t0                                # the world did not advance while the scene played
    host.convert(sc.sim, sc.sim.players[0])
    sc.update(1 / 60)
    assert isinstance(game.scene, CinematicScene)           # the reveal
    game.change(sc)
    host.cure(sc.sim, sc.sim.players[0])
    host.convert(sc.sim, sc.sim.players[0])
    sc.update(1 / 60)
    assert game.scene is sc                                 # the reveal plays once per run
    game.save.settings["cinematics"] = False
    sc2 = PlayScene(game, ["mara", "dax"], cfg["devices"], seed=4)
    game.change(sc2)
    sc2.update(1 / 60)
    assert game.scene is sc2
    game.save.settings["cinematics"] = True
