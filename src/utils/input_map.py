"""Keyboard and gamepad input for up to six local players. Produces InputFrame objects for the sim."""
import json

import pygame

from src.settings import save_dir
from src.systems.commands import InputFrame

ACTIONS = ["up", "down", "left", "right", "fire", "dodge", "ability", "interact"]

DEFAULT_KEYS = [
    {"up": "w", "down": "s", "left": "a", "right": "d", "fire": "f", "dodge": "g", "ability": "r", "interact": "e"},
    {"up": "up", "down": "down", "left": "left", "right": "right", "fire": ".", "dodge": "/", "ability": ",", "interact": "right shift"},
    {"up": "i", "down": "k", "left": "j", "right": "l", "fire": "u", "dodge": "o", "ability": "p", "interact": "y"},
    {"up": "[8]", "down": "[5]", "left": "[4]", "right": "[6]", "fire": "[1]", "dodge": "[2]", "ability": "[3]", "interact": "[0]"},
]
DEADZONE = 0.25


def controls_path():
    return save_dir() / "controls.json"


DEFAULT_MOUSE = {"aim": True, "set": 0, "fire": "mouse1", "dodge": "mouse3", "ability": "mouse2", "interact": ""}
DEFAULT_PAD = {"fire": 5, "dodge": 1, "ability": 2, "interact": 0}
MOUSE_NAMES = ("mouse1", "mouse2", "mouse3", "mouse4", "mouse5")
PAD_NAMES = {0: "A", 1: "B", 2: "X", 3: "Y", 4: "LB", 5: "RB", 6: "Back", 7: "Start", 8: "L3", 9: "R3"}


def mouse_button(name):
    """'mouse1' -> 1, anything else (including '' = unbound) -> None."""
    return int(name[5:]) if isinstance(name, str) and name in MOUSE_NAMES else None


def _raw():
    try:
        raw = json.loads(controls_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load_mouse():
    m = dict(DEFAULT_MOUSE)
    raw = _raw().get("mouse")
    if isinstance(raw, dict):
        if isinstance(raw.get("aim"), bool):
            m["aim"] = raw["aim"]
        if isinstance(raw.get("set"), int) and not isinstance(raw.get("set"), bool) and 0 <= raw["set"] < 4:
            m["set"] = raw["set"]
        for a in ("fire", "dodge", "ability", "interact"):
            v = raw.get(a)
            if v == "" or v in MOUSE_NAMES:
                m[a] = v
    return m


def load_pad():
    p = dict(DEFAULT_PAD)
    raw = _raw().get("pad")
    if isinstance(raw, dict):
        for a in DEFAULT_PAD:
            v = raw.get(a)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 15:
                p[a] = v
    return p


def save_config(keys, mouse, pad):
    """Write all bindings. Returns True on success; a failed write leaves the old file untouched."""
    p = controls_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"keyboard": keys, "mouse": mouse, "pad": pad}, indent=2), encoding="utf-8")
        tmp.replace(p)
        return True
    except OSError:
        return False


def key_name(code):
    """pygame key code -> the name stored in controls.json (round-trips through pygame.key.key_code)."""
    return pygame.key.name(code)


def load_bindings():
    """Return 4 keyboard binding sets. Invalid or unknown key names fall back to defaults per action."""
    sets = [dict(d) for d in DEFAULT_KEYS]
    try:
        raw = json.loads(controls_path().read_text(encoding="utf-8"))
        for i, s in enumerate(raw.get("keyboard", [])[:4]):
            for a in ACTIONS:
                name = s.get(a)
                if isinstance(name, str):
                    try:
                        pygame.key.key_code(name)
                        sets[i][a] = name
                    except (ValueError, pygame.error):
                        pass
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return sets


def write_default_controls():
    p = controls_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(json.dumps({"keyboard": DEFAULT_KEYS}, indent=2), encoding="utf-8")
    except OSError:
        pass


def describe(binding):
    return " ".join(f"{a}:{binding[a].upper()}" for a in ("up", "down", "left", "right")) + \
        f"  fire:{binding['fire'].upper()} dodge:{binding['dodge'].upper()} ability:{binding['ability'].upper()} interact:{binding['interact'].upper()}"


def describe_mouse(m):
    if not m.get("aim"):
        return "mouse aim off"
    parts = [f"{a}:{m[a].upper()}" for a in ("fire", "dodge", "ability", "interact") if m.get(a)]
    return "mouse aims; " + " ".join(parts)


class Device:
    """A player's input source: ('kb', set_index) or ('pad', joystick_index)."""

    def __init__(self, kind, index):
        self.kind, self.index = kind, index

    def label(self):
        return f"Keyboard {self.index + 1}" if self.kind == "kb" else f"Gamepad {self.index + 1}"


class InputManager:
    def __init__(self, devices, mouse_pos=None, aim_origin=None):
        """mouse_pos() -> cursor position in logical (1280x720) coordinates; aim_origin(i) -> where player i is on that screen.
        Both are optional: without them the mouse does nothing (tests, bots, menus)."""
        self.devices = devices
        self.mouse_pos, self.aim_origin = mouse_pos, aim_origin
        self.mouse = load_mouse()
        self.pad = load_pad()
        self.mouse_used = False           # the mouse takes over aiming only after the player touches it
        self.bindings = load_bindings()
        self.pending = [dict(dodge=False, ability=False, interact=False) for _ in devices]
        self.pads = {}
        for d in devices:
            if d.kind == "pad":
                try:
                    j = pygame.joystick.Joystick(d.index)
                    j.init()
                    self.pads[d.index] = j
                except pygame.error:
                    pass
        self.keycodes = []
        for d in devices:
            if d.kind == "kb":
                b = self.bindings[d.index]
                self.keycodes.append({a: pygame.key.key_code(b[a]) for a in ACTIONS})
            else:
                self.keycodes.append(None)

    def _mouse_owner(self):
        """Index into self.devices of the keyboard set that owns the mouse, or None."""
        if not self.mouse["aim"] or self.mouse_pos is None:
            return None
        for i, d in enumerate(self.devices):
            if d.kind == "kb" and d.index == self.mouse["set"]:
                return i
        return None

    def handle_event(self, ev):
        own = self._mouse_owner()
        if own is not None:
            if ev.type == pygame.MOUSEMOTION and (ev.rel[0] or ev.rel[1]):
                self.mouse_used = True
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                self.mouse_used = True
                for a in ("dodge", "ability", "interact"):
                    if mouse_button(self.mouse[a]) == ev.button:
                        self.pending[own][a] = True
        if ev.type == pygame.KEYDOWN:
            for i, d in enumerate(self.devices):
                kc = self.keycodes[i]
                if kc is None:
                    continue
                if ev.key == kc["dodge"]:
                    self.pending[i]["dodge"] = True
                elif ev.key == kc["ability"]:
                    self.pending[i]["ability"] = True
                elif ev.key == kc["interact"]:
                    self.pending[i]["interact"] = True
        elif ev.type == pygame.JOYBUTTONDOWN:
            for i, d in enumerate(self.devices):
                if d.kind == "pad" and ev.instance_id == self._iid(d.index):
                    for a in ("dodge", "ability", "interact"):
                        if ev.button == self.pad[a]:
                            self.pending[i][a] = True

    def _iid(self, index):
        j = self.pads.get(index)
        return j.get_instance_id() if j else -1

    def any_action_pressed(self):
        return any(any(p.values()) for p in self.pending)

    def frames(self):
        keys = pygame.key.get_pressed()
        out = {}
        for i, d in enumerate(self.devices):
            f = InputFrame()
            if d.kind == "kb":
                kc = self.keycodes[i]
                f.mx = (1 if keys[kc["right"]] else 0) - (1 if keys[kc["left"]] else 0)
                f.my = (1 if keys[kc["down"]] else 0) - (1 if keys[kc["up"]] else 0)
                f.fire = bool(keys[kc["fire"]])
                f.interact_held = bool(keys[kc["interact"]])
                if i == self._mouse_owner() and self.mouse_used:
                    held = pygame.mouse.get_pressed(5)
                    b = mouse_button(self.mouse["fire"])
                    f.fire = f.fire or bool(b and held[b - 1])
                    b = mouse_button(self.mouse["interact"])
                    f.interact_held = f.interact_held or bool(b and held[b - 1])
                    if self.aim_origin is not None:
                        o = self.aim_origin(i)
                        mp = self.mouse_pos()
                        if o is not None and mp is not None:
                            dx, dy = mp[0] - o[0], mp[1] - o[1]
                            n = (dx * dx + dy * dy) ** 0.5
                            if n > 10:                       # right on top of the player: keep the last aim
                                f.aim_x, f.aim_y = dx / n, dy / n
            else:
                j = self.pads.get(d.index)
                if j is not None:
                    def ax(n):
                        try:
                            v = j.get_axis(n)
                        except pygame.error:
                            v = 0.0
                        return v if abs(v) > DEADZONE else 0.0
                    f.mx, f.my = ax(0), ax(1)
                    f.aim_x, f.aim_y = ax(2), ax(3)
                    try:
                        f.fire = j.get_button(self.pad["fire"]) or ax(5) > 0.3 or j.get_button(7)
                        f.interact_held = bool(j.get_button(self.pad["interact"]))
                    except pygame.error:
                        pass
            p = self.pending[i]
            f.dodge, f.ability, f.interact = p["dodge"], p["ability"], p["interact"]
            p["dodge"] = p["ability"] = p["interact"] = False
            out[i] = f
        return out
