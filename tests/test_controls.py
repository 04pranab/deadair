"""Rebinding and mouse aim: loading is forgiving, saving round-trips, the Controls screen refuses conflicts, and the mouse aims."""
import json

import pygame
import pytest

from src.utils import input_map as im
from src.systems.commands import InputFrame


@pytest.fixture(autouse=True)
def savedir(tmp_path, monkeypatch):
    pygame.init()
    monkeypatch.setenv("DEADAIR_SAVE_DIR", str(tmp_path))
    return tmp_path


def ev(t, **kw):
    return pygame.event.Event(t, **kw)


# ------------------------------------------------------------------ files
def test_bad_values_fall_back_to_defaults(savedir):
    (savedir / "controls.json").write_text(json.dumps({
        "keyboard": [{"fire": "not-a-key", "up": "t"}],
        "mouse": {"aim": "yes", "set": 9, "fire": "mouse9", "dodge": "mouse2"},
        "pad": {"fire": -3, "dodge": "x", "ability": 4}}))
    k, m, p = im.load_bindings(), im.load_mouse(), im.load_pad()
    assert k[0]["fire"] == im.DEFAULT_KEYS[0]["fire"] and k[0]["up"] == "t"
    assert m["aim"] is True and m["set"] == 0 and m["fire"] == "mouse1" and m["dodge"] == "mouse2"
    assert p["fire"] == 5 and p["dodge"] == 1 and p["ability"] == 4


def test_corrupt_file_gives_defaults(savedir):
    (savedir / "controls.json").write_text("{nope")
    assert im.load_mouse() == im.DEFAULT_MOUSE and im.load_pad() == im.DEFAULT_PAD


def test_save_round_trip(savedir):
    keys = [dict(d) for d in im.DEFAULT_KEYS]
    keys[0]["fire"] = "space"
    mouse = dict(im.DEFAULT_MOUSE, dodge="mouse2", ability="", set=2)
    pad = dict(im.DEFAULT_PAD, fire=4)
    assert im.save_config(keys, mouse, pad)
    assert im.load_bindings()[0]["fire"] == "space"
    assert im.load_mouse() == mouse and im.load_pad() == pad


# ------------------------------------------------------------------ mouse aim
class Held:
    def __init__(self, *down):
        self.down = set(down)

    def __call__(self, n=3):
        return tuple((i + 1) in self.down for i in range(n))


def manager(monkeypatch, set_index=0, mouse=(900, 360), origin=(640, 360), held=()):
    monkeypatch.setattr(pygame.mouse, "get_pressed", Held(*held))
    return im.InputManager([im.Device("kb", set_index)], mouse_pos=lambda: mouse, aim_origin=lambda i: origin)


def test_mouse_does_nothing_until_it_is_touched(monkeypatch):
    m = manager(monkeypatch, held=(1,))
    f = m.frames()[0]
    assert (f.aim_x, f.aim_y) == (0, 0) and not f.fire


def test_mouse_aims_at_the_cursor_and_left_click_fires(monkeypatch):
    m = manager(monkeypatch, held=(1,))
    m.handle_event(ev(pygame.MOUSEMOTION, pos=(900, 360), rel=(5, 0), buttons=(0, 0, 0)))
    f = m.frames()[0]
    assert f.aim_x == pytest.approx(1.0) and f.aim_y == pytest.approx(0.0) and f.fire
    m2 = manager(monkeypatch, mouse=(640, 100))
    m2.mouse_used = True
    f = m2.frames()[0]
    assert f.aim_y == pytest.approx(-1.0)


def test_cursor_on_top_of_the_player_keeps_the_last_aim(monkeypatch):
    m = manager(monkeypatch, mouse=(642, 362))
    m.mouse_used = True
    f = m.frames()[0]
    assert (f.aim_x, f.aim_y) == (0, 0)


def test_mouse_buttons_are_edge_triggered_and_rebindable(monkeypatch):
    m = manager(monkeypatch)
    m.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0)))
    assert m.frames()[0].dodge is True and m.frames()[0].dodge is False
    m.mouse["ability"], m.mouse["interact"] = "", "mouse2"
    m.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=2, pos=(0, 0)))
    f = m.frames()[0]
    assert f.ability is False and f.interact is True


def test_only_the_owning_keyboard_gets_the_mouse(monkeypatch):
    m = manager(monkeypatch, set_index=1, held=(1,))          # mouse belongs to keyboard 1, this player is keyboard 2
    m.handle_event(ev(pygame.MOUSEMOTION, pos=(900, 360), rel=(5, 0), buttons=(0, 0, 0)))
    f = m.frames()[0]
    assert (f.aim_x, f.aim_y) == (0, 0) and not f.fire


def test_mouse_aim_can_be_switched_off(monkeypatch, savedir):
    im.save_config([dict(d) for d in im.DEFAULT_KEYS], dict(im.DEFAULT_MOUSE, aim=False), dict(im.DEFAULT_PAD))
    m = manager(monkeypatch, held=(1,))
    m.handle_event(ev(pygame.MOUSEMOTION, pos=(900, 360), rel=(5, 0), buttons=(0, 0, 0)))
    f = m.frames()[0]
    assert (f.aim_x, f.aim_y) == (0, 0) and not f.fire


def test_the_sim_faces_the_explicit_aim():
    from tests.helpers import dsim
    s = dsim(5, ["mara"])
    for _ in range(5):
        s.update(1 / 60, {0: InputFrame(aim_x=0.0, aim_y=-1.0)})
    assert s.players[0].facing.y < -0.9


def test_gamepad_buttons_follow_the_binding():
    class FakePad:
        def get_instance_id(self):
            return 7
    m = im.InputManager([im.Device("pad", 0)])
    m.pads[0] = FakePad()
    m.pad = dict(im.DEFAULT_PAD, dodge=3)
    m.handle_event(ev(pygame.JOYBUTTONDOWN, instance_id=7, button=1))
    assert m.pending[0]["dodge"] is False                     # the old button no longer dodges
    m.handle_event(ev(pygame.JOYBUTTONDOWN, instance_id=7, button=3))
    assert m.pending[0]["dodge"] is True


# ------------------------------------------------------------------ the Controls screen
class FakeGame:
    def __init__(self):
        self.scene = None

    def change(self, s):
        self.scene = s


def screen():
    from src.scenes.menus import ControlsScene
    return ControlsScene(FakeGame())


def key(code):
    return ev(pygame.KEYDOWN, key=code, mod=0, unicode="", scancode=0)


def start_capture(sc, action):
    sc.row = 1 + [r[0] for r in sc.rows()].index(action)
    sc.handle_event(key(pygame.K_RETURN))
    assert sc.capture == action


def test_rebind_a_key_and_it_persists():
    sc = screen()
    start_capture(sc, "fire")
    sc.handle_event(key(pygame.K_SPACE))
    assert sc.keys[0]["fire"] == "space" and sc.capture is None
    assert im.load_bindings()[0]["fire"] == "space"


def test_rebinding_to_a_key_in_the_same_set_swaps():
    sc = screen()
    old_fire, old_dodge = sc.keys[0]["fire"], sc.keys[0]["dodge"]
    start_capture(sc, "fire")
    sc.handle_event(key(pygame.key.key_code(old_dodge)))
    assert sc.keys[0]["fire"] == old_dodge and sc.keys[0]["dodge"] == old_fire


def test_a_key_owned_by_another_keyboard_is_refused():
    sc = screen()
    start_capture(sc, "fire")
    sc.handle_event(key(pygame.K_UP))                         # keyboard 2's up
    assert sc.keys[0]["fire"] == im.DEFAULT_KEYS[0]["fire"] and sc.capture == "fire" and "Keyboard 2" in sc.msg


def test_reserved_keys_cannot_be_bound_and_escape_cancels():
    sc = screen()
    start_capture(sc, "fire")
    sc.handle_event(key(pygame.K_F11))
    assert sc.keys[0]["fire"] == im.DEFAULT_KEYS[0]["fire"] and sc.capture == "fire"
    sc.handle_event(key(pygame.K_ESCAPE))
    assert sc.capture is None


def test_mouse_tab_binds_swaps_and_unbinds_buttons():
    sc = screen()
    sc.tab = 4
    start_capture(sc, "m_fire")
    sc.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0)))      # dodge held mouse3 by default: swap
    assert sc.mouse["fire"] == "mouse3" and sc.mouse["dodge"] == "mouse1"
    start_capture(sc, "m_ability")
    sc.handle_event(key(pygame.K_BACKSPACE))
    assert sc.mouse["ability"] == ""
    assert im.load_mouse() == sc.mouse


def test_mouse_aim_toggle_and_owner_cycle():
    sc = screen()
    sc.tab = 4
    sc.row = 1
    sc.handle_event(key(pygame.K_RETURN))
    assert sc.mouse["aim"] is False
    sc.row = 2
    sc.handle_event(key(pygame.K_RIGHT))
    assert sc.mouse["set"] == 1 and im.load_mouse()["set"] == 1


def test_gamepad_tab_binds_buttons():
    sc = screen()
    sc.tab = 5
    start_capture(sc, "p_dodge")
    sc.handle_event(ev(pygame.JOYBUTTONDOWN, instance_id=0, button=3))
    assert sc.pad["dodge"] == 3 and im.load_pad()["dodge"] == 3


def test_reset_restores_defaults_for_the_tab():
    sc = screen()
    start_capture(sc, "fire")
    sc.handle_event(key(pygame.K_SPACE))
    sc.row = 1 + [r[0] for r in sc.rows()].index("reset")
    sc.handle_event(key(pygame.K_RETURN))
    assert sc.keys[0] == im.DEFAULT_KEYS[0]


def test_every_tab_draws_without_overflow(tmp_path):
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from src.ui import draw
    pygame.init()
    surf = pygame.Surface((1280, 720))
    sc = screen()
    for t in range(6):
        sc.tab, sc.row = t, 1
        sc.msg = "x" * 40
        sc.draw(surf)
