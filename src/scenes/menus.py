"""Main menu, co-op setup, settings, armory (persistent upgrades) and chronicle (discovered clues)."""
import pygame

from src.config import BAL
from src.scenes.base import ListMenu, Scene, draw_backdrop, window_to_logical
from src.settings import C_AMBER, C_CYAN, C_DIM, C_GREEN, C_RED, C_TEXT, LOGICAL_H, LOGICAL_W, LOCAL_PLAYERS, PLAYER_COLORS, RESOLUTIONS
from src.systems.story import StoryBook
from src.ui import draw
from src.utils import input_map


class MenuScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.setup_players = 2
        self.menu = ListMenu(game, [
            ["Start Expedition", self.start, True],
            ["Local Co-op Setup", lambda: game.change(CoopSetupScene(game)), True],
            ["Armory", lambda: game.change(ArmoryScene(game)), True],
            ["Chronicle", lambda: game.change(ChronicleScene(game)), True],
            ["Settings", lambda: game.change(SettingsScene(game)), True],
            ["Quit", self.quit, True],
        ], top=250)

    def start(self):
        from src.scenes.play import PlayScene
        cfg = getattr(self.game, "coop_config", None) or default_coop(self.game, 1)
        self.game.change(PlayScene(self.game, cfg["roles"], cfg["devices"]))

    def quit(self):
        self.game.running = False

    def handle_event(self, ev):
        self.menu.handle_event(ev)

    def draw(self, surf):
        draw_backdrop(surf, self.t)
        self.menu.draw(surf)
        cfg = getattr(self.game, "coop_config", None)
        n = len(cfg["roles"]) if cfg else 1
        draw.text(surf, f"Squad: {n} player{'s' if n > 1 else ''}   |   Banked salvage: {self.game.save.data['bank']}",
                  (LOGICAL_W // 2, 640), 24, C_DIM, "center")
        if self.game.save.recovered:
            draw.text(surf, "Save file was unreadable and has been reset (old copy kept).", (LOGICAL_W // 2, 670), 20, C_RED, "center")
        draw.text(surf, "Art: Kenney (kenney.nl), CC0 1.0. Vertical slice: SHIFT ZERO.", (LOGICAL_W // 2, 700), 18, C_DIM, "center")


ROLES = ["mara", "dax", "imani"]


def default_coop(game, n):
    pads = pygame.joystick.get_count()
    devices = []
    for i in range(n):
        devices.append(input_map.Device("kb", i))
    return {"roles": [ROLES[i % 3] for i in range(n)], "devices": devices}


class CoopSetupScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        cfg = getattr(game, "coop_config", None) or default_coop(game, 2)
        self.roles = list(cfg["roles"])
        self.devs = [(d.kind, d.index) for d in cfg["devices"]]
        self.bind = input_map.load_bindings()
        self.row = 0   # 0 = player count, 1..n = player rows, n+1 = start, n+2 = back

    def n(self):
        return len(self.roles)

    def rows(self):
        return self.n() + 3

    def cycle_device(self, i, d):
        options = [("kb", k) for k in range(4)] + [("pad", j) for j in range(pygame.joystick.get_count())]
        cur = options.index(self.devs[i]) if self.devs[i] in options else 0
        self.devs[i] = options[(cur + d) % len(options)]

    def start(self):
        used = set()
        for d in self.devs:
            if d in used:
                self.warn = "Each player needs a different input device."
                return
            used.add(d)
        from src.scenes.play import PlayScene
        devices = [input_map.Device(k, i) for k, i in self.devs]
        self.game.coop_config = {"roles": list(self.roles), "devices": devices}
        self.game.change(PlayScene(self.game, list(self.roles), devices))

    warn = ""

    def handle_event(self, ev):
        if ev.type != pygame.KEYDOWN:
            return
        k = ev.key
        if k == pygame.K_ESCAPE:
            self.back()
        elif k in (pygame.K_UP, pygame.K_w):
            self.row = (self.row - 1) % self.rows()
        elif k in (pygame.K_DOWN, pygame.K_s):
            self.row = (self.row + 1) % self.rows()
        elif k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
            d = 1 if k in (pygame.K_RIGHT, pygame.K_d) else -1
            if self.row == 0:
                n = min(LOCAL_PLAYERS, max(1, self.n() + d))
                while len(self.roles) < n:
                    i = len(self.roles)
                    self.roles.append(ROLES[i % 3])
                    used = set(self.devs)
                    self.devs.append(next(x for x in [("kb", j) for j in range(4)] if x not in used))
                self.roles, self.devs = self.roles[:n], self.devs[:n]
            elif 1 <= self.row <= self.n():
                i = self.row - 1
                self.roles[i] = ROLES[(ROLES.index(self.roles[i]) + d) % 3]
        elif k in (pygame.K_TAB,) and 1 <= self.row <= self.n():
            self.cycle_device(self.row - 1, 1)
        elif k in (pygame.K_RETURN, pygame.K_SPACE):
            if self.row == self.n() + 1:
                self.start()
            elif self.row == self.n() + 2:
                self.back()
            elif 1 <= self.row <= self.n():
                self.cycle_device(self.row - 1, 1)

    def back(self):
        self.game.coop_config = {"roles": list(self.roles), "devices": [input_map.Device(k, i) for k, i in self.devs]}
        self.game.change(MenuScene(self.game))

    def draw(self, surf):
        draw_backdrop(surf, self.t, title=False, sub="LOCAL CO-OP SETUP")
        y = 120
        draw.panel(surf, pygame.Rect(120, y, LOGICAL_W - 240, 56), 200, border=C_CYAN if self.row == 0 else (70, 110, 160))
        draw.text(surf, f"Players:  < {self.n()} >   (1-{LOCAL_PLAYERS} local; online is planned, not implemented)", (150, y + 15), 28)
        y += 72
        for i in range(self.n()):
            col = PLAYER_COLORS[i]
            r = pygame.Rect(120, y, LOGICAL_W - 240, 96)
            draw.panel(surf, r, 200, border=C_CYAN if self.row == i + 1 else (70, 110, 160))
            spec = BAL.roles[self.roles[i]]
            draw.draw_char(surf, spec.sprite, "hold1" if int(self.t * 2) % 2 == 0 else "idle", (r.x + 50, r.y + r.h - 6), 0.9)
            draw.text(surf, f"P{i + 1}  < {spec.name}, {spec.title} >", (r.x + 100, r.y + 10), 28, col)
            ab = BAL.roles[self.roles[i]].ability
            desc = {"barricade": "Ability: Barricade. Fixer: repairs 1.6x faster.",
                    "charge": "Ability: Charge. Breaks barriers, staggers enemies. Guards ritual allies.",
                    "stim": "Ability: Stim Pulse. Heals nearby allies. Rekindling 1.5x faster."}[ab]
            draw.text(surf, desc, (r.x + 100, r.y + 42), 20, C_DIM)
            kind, idx = self.devs[i]
            if kind == "kb":
                mo = input_map.load_mouse()
                extra = ("  |  " + input_map.describe_mouse(mo)) if mo["aim"] and mo["set"] == idx else ""
                draw.text(surf, f"Keyboard {idx + 1}: " + input_map.describe(self.bind[idx]) + extra, (r.x + 100, r.y + 66), 18, C_TEXT, maxw=r.w - 120)
            else:
                draw.text(surf, f"Gamepad {idx + 1}: left stick move, right stick aim, A interact, B dodge, X ability, RB fire", (r.x + 100, r.y + 66), 18, C_TEXT)
            y += 104
        draw.button(surf, pygame.Rect(LOGICAL_W // 2 - 220, y + 10, 200, 50), "Start", self.row == self.n() + 1)
        draw.button(surf, pygame.Rect(LOGICAL_W // 2 + 20, y + 10, 200, 50), "Back", self.row == self.n() + 2)
        draw.text(surf, "Up/Down select   Left/Right change   Enter/Tab cycle input device", (LOGICAL_W // 2, LOGICAL_H - 40), 20, C_DIM, "center")
        if self.warn:
            draw.text(surf, self.warn, (LOGICAL_W // 2, LOGICAL_H - 70), 22, C_RED, "center")


class SettingsScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.sel = 0

    def entries(self):
        s = self.game.save.settings
        a = self.game.audio
        e = [
            ("Fullscreen (F11)", "ON" if s["fullscreen"] else "OFF", "fullscreen"),
            ("Window resolution", "%dx%d" % RESOLUTIONS[s["resolution"]], "resolution"),
            ("Screen shake", "ON" if s["shake"] else "OFF", "shake"),
            ("Solo auto-Rekindle (1 player)", "ON" if s["solo_assist"] else "OFF", "solo_assist"),
            ("Story scenes (hold any key to skip)", "ON" if s["cinematics"] else "OFF", "cinematics"),
            ("Debug overlay (F3 in game)", "ON" if s["debug"] else "OFF", "debug"),
            ("Controls: keys, mouse, gamepad", "", "controls"),
        ]
        if a.available:
            e.append(("Volume", f"{int(s['volume'] * 100)}%", "volume"))
        else:
            e.append(("Volume", "n/a: no audio files supplied", None))
        e.append(("Back", "", "back"))
        return e

    def change(self, key, d=1):
        s = self.game.save.settings
        if key == "fullscreen":
            s["fullscreen"] = not s["fullscreen"]
            self.game.apply_display()
        elif key == "resolution":
            s["resolution"] = (s["resolution"] + d) % len(RESOLUTIONS)
            if not s["fullscreen"]:
                self.game.apply_display()
        elif key in ("shake", "solo_assist", "debug", "cinematics"):
            s[key] = not s[key]
        elif key == "volume":
            s["volume"] = round(min(1.0, max(0.0, s["volume"] + 0.1 * d)), 2)
            self.game.audio.set_volume(s["volume"])
        elif key == "controls":
            self.game.change(ControlsScene(self.game))
        elif key == "back":
            self.game.save.save()
            self.game.change(MenuScene(self.game))
        self.game.save.save()

    def handle_event(self, ev):
        e = self.entries()
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.change("back")
            elif ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(e)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(e)
            elif ev.key in (pygame.K_LEFT, pygame.K_a):
                if e[self.sel][2]:
                    self.change(e[self.sel][2], -1)
            elif ev.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_RETURN, pygame.K_SPACE):
                if e[self.sel][2]:
                    self.change(e[self.sel][2], 1)

    def draw(self, surf):
        draw_backdrop(surf, self.t, title=False, sub="SETTINGS")
        for i, (name, val, key) in enumerate(self.entries()):
            r = pygame.Rect(260, 130 + i * 64, LOGICAL_W - 520, 52)
            draw.panel(surf, r, 200, border=C_CYAN if i == self.sel else (70, 110, 160))
            draw.text(surf, name, (r.x + 20, r.y + 14), 28, C_TEXT if key else C_DIM)
            draw.text(surf, val, (r.right - 20, r.y + 14), 28, C_CYAN if key else C_DIM, "topright")
        draw.text(surf, "Rebind keys, mouse buttons and gamepad buttons in Controls", (LOGICAL_W // 2, LOGICAL_H - 40), 18, C_DIM, "center")


RESERVED_KEYS = {pygame.K_ESCAPE, pygame.K_F3, pygame.K_F11}
ACTION_LABEL = {"up": "Move up", "down": "Move down", "left": "Move left", "right": "Move right", "fire": "Fire",
                "dodge": "Dodge / Host lunge", "ability": "Ability / Host mark", "interact": "Interact (hold)"}
TABS = ["Keyboard 1", "Keyboard 2", "Keyboard 3", "Keyboard 4", "Mouse", "Gamepad"]


class ControlsScene(Scene):
    """Rebind everything: four keyboard sets, the mouse (aim and buttons) and the gamepad buttons.
    Up/Down choose a row, Left/Right switch tab (on the tab row) or change a value, Enter then press the new key or click the new
    button. Esc cancels a capture, Backspace clears a mouse button. Saved at once to controls.json; applies to the next expedition."""

    def __init__(self, game):
        super().__init__(game)
        self.keys = input_map.load_bindings()
        self.mouse = input_map.load_mouse()
        self.pad = input_map.load_pad()
        self.tab = 0
        self.row = 0                 # 0 = the tab strip, then the rows of the tab
        self.capture = None          # the action being bound
        self.msg = ""

    # ---- structure
    def rows(self):
        if self.tab < 4:
            return [(a, ACTION_LABEL[a], self.keys[self.tab][a].upper()) for a in input_map.ACTIONS] + [("reset", "Reset this keyboard to defaults", ""), ("back", "Back", "")]
        if self.tab == 4:
            out = [("m_aim", "Aim with the mouse", "ON" if self.mouse["aim"] else "OFF"),
                   ("m_set", "Mouse belongs to", f"Keyboard {self.mouse['set'] + 1}")]
            for a in ("fire", "dodge", "ability", "interact"):
                out.append(("m_" + a, ACTION_LABEL[a], self.mouse[a].upper() if self.mouse[a] else "none"))
            return out + [("reset", "Reset mouse to defaults", ""), ("back", "Back", "")]
        out = [("p_" + a, ACTION_LABEL[a], input_map.PAD_NAMES.get(self.pad[a], f"button {self.pad[a]}")) for a in ("fire", "dodge", "ability", "interact")]
        return out + [("reset", "Reset gamepad to defaults", ""), ("back", "Back", "")]

    def row_rect(self, i):
        return pygame.Rect(240, 160 + i * 40, LOGICAL_W - 480, 34)

    def tab_rect(self, i):
        w = (LOGICAL_W - 240) // len(TABS)
        return pygame.Rect(120 + i * w, 110, w - 8, 44)

    def save(self):
        keys = [{a: self.keys[i][a] for a in input_map.ACTIONS} for i in range(4)]
        if not input_map.save_config(keys, self.mouse, self.pad):
            self.msg = "Could not write controls.json (is the save folder writable?)"

    # ---- editing
    def _set_key(self, code):
        if code in RESERVED_KEYS:
            self.msg = "Esc, F3 and F11 are reserved"
            return
        name = input_map.key_name(code)
        try:
            if pygame.key.key_code(name) != code:
                raise ValueError
        except (ValueError, pygame.error):
            self.msg = "That key cannot be saved by name"
            return
        a = self.capture
        mine = self.keys[self.tab]
        for si, st in enumerate(self.keys):
            for oa in input_map.ACTIONS:
                if st[oa] == name and (si, oa) != (self.tab, a):
                    if si == self.tab:                        # inside one set the keys swap
                        mine[oa], mine[a] = mine[a], name
                        self.msg = f"Swapped with {ACTION_LABEL[oa]}"
                        self.capture = None
                        self.save()
                        return
                    self.msg = f"{name.upper()} is already Keyboard {si + 1}: {ACTION_LABEL[oa]}"
                    return
        mine[a] = name
        self.msg = ""
        self.capture = None
        self.save()

    def _set_mouse(self, button):
        a = self.capture[2:]
        name = f"mouse{button}"
        for oa in ("fire", "dodge", "ability", "interact"):
            if self.mouse[oa] == name and oa != a:
                self.mouse[oa], self.mouse[a] = self.mouse[a], name
                self.msg = f"Swapped with {ACTION_LABEL[oa]}"
                break
        else:
            self.mouse[a] = name
            self.msg = ""
        self.capture = None
        self.save()

    def _set_pad(self, button):
        a = self.capture[2:]
        for oa in self.pad:
            if self.pad[oa] == button and oa != a:
                self.pad[oa], self.pad[a] = self.pad[a], button
                self.msg = f"Swapped with {ACTION_LABEL[oa]}"
                break
        else:
            self.pad[a] = button
            self.msg = ""
        self.capture = None
        self.save()

    def activate(self):
        key = self.rows()[self.row - 1][0]
        if key == "back":
            self.game.change(SettingsScene(self.game))
        elif key == "reset":
            if self.tab < 4:
                self.keys[self.tab] = dict(input_map.DEFAULT_KEYS[self.tab])
            elif self.tab == 4:
                self.mouse = dict(input_map.DEFAULT_MOUSE)
            else:
                self.pad = dict(input_map.DEFAULT_PAD)
            self.msg = "Reset"
            self.save()
        elif key == "m_aim":
            self.mouse["aim"] = not self.mouse["aim"]
            self.save()
        elif key == "m_set":
            self.mouse["set"] = (self.mouse["set"] + 1) % 4
            self.save()
        else:
            self.capture = key
            self.msg = ""

    def handle_event(self, ev):
        if self.capture is not None:
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.capture = None
                elif self.capture.startswith("m_"):
                    if ev.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                        self.mouse[self.capture[2:]] = ""
                        self.capture = None
                        self.save()
                    else:
                        self.msg = "Click a mouse button (Backspace unbinds)"
                elif self.capture.startswith("p_"):
                    self.msg = "Press a gamepad button"
                else:
                    self._set_key(ev.key)
            elif ev.type == pygame.MOUSEBUTTONDOWN and self.capture.startswith("m_"):
                self._set_mouse(ev.button)
            elif ev.type == pygame.JOYBUTTONDOWN and self.capture.startswith("p_"):
                self._set_pad(ev.button)
            return
        n = len(self.rows()) + 1
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.game.change(SettingsScene(self.game))
            elif ev.key in (pygame.K_UP, pygame.K_w):
                self.row = (self.row - 1) % n
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.row = (self.row + 1) % n
            elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
                d = 1 if ev.key in (pygame.K_RIGHT, pygame.K_d) else -1
                if self.row == 0:
                    self.tab = (self.tab + d) % len(TABS)
                else:
                    k = self.rows()[self.row - 1][0]
                    if k in ("m_aim", "m_set"):
                        self.activate()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and self.row > 0:
                self.activate()
        elif ev.type == pygame.MOUSEMOTION:
            p = window_to_logical(self.game, ev.pos)
            for i in range(len(self.rows())):
                if self.row_rect(i + 1).collidepoint(p):
                    self.row = i + 1
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = window_to_logical(self.game, ev.pos)
            for i in range(len(TABS)):
                if self.tab_rect(i).collidepoint(p):
                    self.tab, self.row = i, 0
                    return
            for i in range(len(self.rows())):
                if self.row_rect(i + 1).collidepoint(p):
                    self.row = i + 1
                    self.activate()
                    return

    def draw(self, surf):
        draw_backdrop(surf, self.t, title=False, sub="CONTROLS")
        for i, name in enumerate(TABS):
            r = self.tab_rect(i)
            draw.panel(surf, r, 220 if i == self.tab else 120, border=C_CYAN if (i == self.tab and self.row == 0) else ((120, 180, 230) if i == self.tab else (60, 90, 130)))
            draw.text(surf, name, r.center, 22, C_TEXT if i == self.tab else C_DIM, "center", maxw=r.w - 12)
        for i, (key, label, val) in enumerate(self.rows()):
            r = self.row_rect(i + 1)
            sel = self.row == i + 1
            draw.panel(surf, r, 210, border=C_CYAN if sel else (70, 110, 160))
            draw.text(surf, label, (r.x + 16, r.y + 4), 24, C_TEXT, maxw=r.w - 260)
            if self.capture == key:
                draw.text(surf, "press...", (r.right - 16, r.y + 4), 24, C_AMBER, "topright")
            elif val:
                draw.text(surf, val, (r.right - 16, r.y + 4), 24, C_CYAN, "topright", maxw=240)
        hint = {4: "Mouse aims toward the cursor once you move it. Left click fires by default.",
                5: "Fire also works on the right trigger. Untested on real hardware."}.get(self.tab, "One key per action. A key used by another keyboard cannot be reused.")
        draw.text(surf, hint, (LOGICAL_W // 2, LOGICAL_H - 70), 20, C_DIM, "center", maxw=LOGICAL_W - 120)
        draw.text(surf, "Up/Down row   Left/Right tab   Enter rebind   Esc cancel / back   (applies to the next expedition)", (LOGICAL_W // 2, LOGICAL_H - 40), 18, C_DIM, "center", maxw=LOGICAL_W - 120)
        if self.msg:
            draw.text(surf, self.msg, (LOGICAL_W // 2, LOGICAL_H - 100), 22, C_AMBER, "center", maxw=LOGICAL_W - 120)


class ArmoryScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.sel = 0
        self.keys = list(BAL.upgrades.keys())
        self.msg = ""

    def handle_event(self, ev):
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.game.change(MenuScene(self.game))
        elif ev.key in (pygame.K_UP, pygame.K_w):
            self.sel = (self.sel - 1) % len(self.keys)
        elif ev.key in (pygame.K_DOWN, pygame.K_s):
            self.sel = (self.sel + 1) % len(self.keys)
        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
            k = self.keys[self.sel]
            self.msg = "Purchased." if self.game.save.buy(k) else "Not enough banked salvage, or already maxed."

    def draw(self, surf):
        draw_backdrop(surf, self.t, title=False, sub="ARMORY")
        draw.text(surf, f"Banked salvage: {self.game.save.data['bank']}", (LOGICAL_W // 2, 110), 32, C_AMBER, "center")
        for i, k in enumerate(self.keys):
            spec = BAL.upgrades[k]
            lvl = self.game.save.upgrades.get(k, 0)
            r = pygame.Rect(240, 170 + i * 110, LOGICAL_W - 480, 92)
            draw.panel(surf, r, 200, border=C_CYAN if i == self.sel else (70, 110, 160))
            draw.text(surf, f"{spec['name']}  (level {lvl}/{spec['max']})", (r.x + 20, r.y + 12), 30, C_TEXT)
            draw.text(surf, spec["desc"], (r.x + 20, r.y + 50), 22, C_DIM)
            cost = f"{self.game.save.upgrade_cost(k)} salvage" if lvl < spec["max"] else "MAX"
            draw.text(surf, cost, (r.right - 20, r.y + 30), 28, C_AMBER, "topright")
        draw.text(surf, self.msg or "Enter: buy   Esc: back. Upgrades apply to every expedition.", (LOGICAL_W // 2, LOGICAL_H - 50), 22, C_DIM, "center")


class ChronicleScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.story = StoryBook()
        self.known = game.save.data["clues"]
        self.page = 0

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.game.change(MenuScene(self.game))
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self.page += 1
            elif ev.key in (pygame.K_LEFT, pygame.K_a):
                self.page = max(0, self.page - 1)

    def draw(self, surf):
        draw_backdrop(surf, self.t, title=False, sub="CHRONICLE")
        entries = [self.story.logs[c] for c in self.known if c in self.story.logs]
        ded = self.story.unlocked_deductions(self.known)
        draw.text(surf, f"Pieces found: {len(entries)}/{len(self.story.logs)}   Deductions: {len(ded)}/{len(self.story.deductions)}",
                  (LOGICAL_W // 2, 100), 26, C_AMBER, "center")
        items = [("log", e) for e in entries] + [("ded", d) for d in ded]
        per = 3
        self.page = min(self.page, max(0, (len(items) - 1) // per))
        y = 140
        if not items:
            draw.text(surf, "Nothing recorded yet. Read terminals during an expedition.", (LOGICAL_W // 2, 300), 28, C_DIM, "center")
        for kind, it in items[self.page * per:(self.page + 1) * per]:
            r = pygame.Rect(180, y, LOGICAL_W - 360, 150)
            draw.panel(surf, r, 210, border=C_AMBER if kind == "ded" else (70, 110, 160))
            if kind == "log":
                draw.text(surf, it["title"], (r.x + 16, r.y + 10), 28, C_CYAN)
                draw.text(surf, it["source"] + "  |  thread: " + it["thread"], (r.x + 16, r.y + 40), 18, C_DIM)
                text = it["text"]
            else:
                draw.text(surf, "DEDUCTION", (r.x + 16, r.y + 10), 28, C_AMBER)
                text = it["text"]
            yy = r.y + 68
            for line in draw.wrap_text(text, 22, r.w - 32)[:3]:
                draw.text(surf, line, (r.x + 16, yy), 22, C_TEXT)
                yy += 26
            y += 162
        draw.text(surf, "Left/Right: page   Esc: back", (LOGICAL_W // 2, LOGICAL_H - 30), 20, C_DIM, "center")
