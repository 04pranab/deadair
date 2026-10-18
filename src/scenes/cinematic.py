"""Story scenes: non-interactive, data-driven (data/cinematics.json), always skippable.
Hold any key / button (or click) for ~0.7 s to skip the scene; Esc skips at once. The simulation never runs here: a scene shown mid-run
freezes the world and resumes it exactly."""
import pygame

from src.config import load_json
from src.scenes.base import Scene
from src.settings import C_AMBER, C_CYAN, C_DIM, C_TEXT, LOGICAL_H, LOGICAL_W
from src.ui import cine_art, draw

SKIP_HOLD = 0.7
_DATA = None


def scripts():
    global _DATA
    if _DATA is None:
        _DATA = load_json("cinematics.json")
    return _DATA


class CinematicScene(Scene):
    def __init__(self, game, key, then, seed=0):
        super().__init__(game)
        self.key = key
        self.shots = scripts()[key]["shots"]
        self.then = then              # a Scene instance, or a callable returning one
        self.seed = seed
        self.idx = 0
        self.st = 0.0
        self.held = set()
        self.hold_t = 0.0
        self.done = False
        self.fade = 0.0               # fade-in at the start of each shot

    # ---- control
    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.finish()
                return
            self.held.add(("k", ev.key))
        elif ev.type == pygame.KEYUP:
            self.held.discard(("k", ev.key))
        elif ev.type == pygame.JOYBUTTONDOWN:
            self.held.add(("j", ev.joy, ev.button))
        elif ev.type == pygame.JOYBUTTONUP:
            self.held.discard(("j", ev.joy, ev.button))
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self.held.add(("m", ev.button))
        elif ev.type == pygame.MOUSEBUTTONUP:
            self.held.discard(("m", ev.button))

    def finish(self):
        if self.done:
            return
        self.done = True
        nxt = self.then() if callable(self.then) else self.then
        self.game.change(nxt)

    def update(self, dt):
        super().update(dt)
        if self.done:
            return
        self.hold_t = self.hold_t + dt if self.held else max(0.0, self.hold_t - dt * 2)
        if self.hold_t >= SKIP_HOLD:
            self.finish()
            return
        self.st += dt
        if self.st >= self.shots[self.idx]["dur"]:
            self.idx += 1
            self.st = 0.0
            if self.idx >= len(self.shots):
                self.finish()

    # ---- drawing
    def draw(self, surf):
        if self.done and self.idx >= len(self.shots):
            self.idx = len(self.shots) - 1
        shot = self.shots[min(self.idx, len(self.shots) - 1)]
        cine_art.paint(surf, shot["art"], self.st, shot["dur"], shot.get("p"), self.seed + self.idx * 17)
        # fade in / out
        a = 0
        if self.st < 0.6:
            a = int(255 * (1 - self.st / 0.6))
        elif self.st > shot["dur"] - 0.5:
            a = int(255 * (self.st - (shot["dur"] - 0.5)) / 0.5)
        if a > 0:
            s = pygame.Surface((LOGICAL_W, LOGICAL_H))
            s.set_alpha(min(255, a))
            surf.blit(s, (0, 0))
        self._lines(surf, shot)
        if shot.get("card") and self.st > shot["dur"] - 3.2:
            draw.text(surf, shot["card"], (LOGICAL_W // 2, 110), 40, C_AMBER, "center")
        self._skip_hint(surf)

    def _lines(self, surf, shot):
        cur = None
        for ln in shot.get("lines", []):
            if self.st >= ln["t"]:
                cur = ln
        if cur is None:
            return
        age = self.st - cur["t"]
        txt = cur["text"]
        n = len(txt) if age > 1.6 else int(len(txt) * age / 1.6) + 1       # typed out
        who = cur.get("who")
        y = LOGICAL_H - 112
        box = pygame.Rect(140, y - 14, LOGICAL_W - 280, 92)
        draw.panel(surf, box, 150, color=(4, 6, 12), border=(50, 70, 100))
        if who:
            draw.text(surf, who, (box.x + 22, box.y + 10), 22, C_CYAN if who != "MERIDIAN" else (255, 120, 110))
        draw.text(surf, txt[:n], (box.x + 22, box.y + (38 if who else 24)), 30, C_TEXT)

    def _skip_hint(self, surf):
        x, y = LOGICAL_W - 70, LOGICAL_H - 40
        draw.text(surf, "hold any key: skip", (x - 30, y - 12), 18, C_DIM, "topright", shadow=False)
        if self.hold_t > 0:
            pygame.draw.arc(surf, C_AMBER, pygame.Rect(x - 14, y - 14, 28, 28), 0, 6.283 * min(1.0, self.hold_t / SKIP_HOLD), 4)
