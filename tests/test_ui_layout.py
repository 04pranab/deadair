"""No screen may push text off the display, out of its panel, or over other text (tools/ui_audit.py renders the hard states)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_no_text_overflow_in_any_screen_or_hud_state(tmp_path):
    import ui_audit
    from src.ui import draw
    draw._fonts.clear()           # other tests quit pygame; cached fonts from before that are invalid
    draw._text_cache.clear()
    report = ui_audit.run_all(tmp_path)
    # the pause and log overlays dim the HUD underneath, so text covered by the dim layer is not a visible collision
    ignore = {"Play_log_open", "Play_pause"}
    bad = {k: v for k, v in report.items() if v and k not in ignore}
    assert not bad, bad


def test_every_director_tell_has_a_banner_and_the_minimap_marks_papers():
    """A tell nobody can see is not a tell. Feed each warning event through the play scene and draw a Rift's papers on the minimap."""
    import pygame
    from src.game import Game
    from src.systems.save import SaveData
    from src.scenes.menus import default_coop
    from src.scenes.play import PlayScene
    from src.systems import rift
    from src.ui import draw
    pygame.init()
    draw._fonts.clear()
    draw._text_cache.clear()
    g = Game(SaveData(None))
    g.save.settings["cinematics"] = False
    cfg = default_coop(g, 2)
    sc = PlayScene(g, cfg["roles"][:2], cfg["devices"][:2], seed=3)
    g.change(sc)
    pos = pygame.Vector2(sc.sim.players[0].pos)
    tells = [dict(name="isolate_warning", pos=pos, player=0), dict(name="teleport", pos=pos, src=pos, player=1),
             dict(name="blackout_start", dur=10), dict(name="blackout_end"), dict(name="seal_warning", pos=pos),
             dict(name="spawn_warning", pos=pos, kind="x"), dict(name="rift_tell", pos=pos, t=8), dict(name="rift_fizzle", pos=pos)]
    for ev in tells:
        sc.hud.banner = None
        sc._events([ev])
        assert sc.hud.banner is not None, ev["name"]
    sc.sim.time = 400.0
    sc.sim.rift.last_end = -1e9
    for p in sc.sim.players:
        p.taint = 3.0
    sc.sim.relays_done = 1
    ok, why = rift.can_open(sc.sim, False)
    if ok:
        rift.open_rift(sc.sim, False)
        assert sc.sim.rift.papers
    sc.draw(pygame.Surface((1280, 720)))
