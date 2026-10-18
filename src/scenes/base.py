import math

import pygame

from src.settings import C_BG, C_CYAN, C_DIM, LOGICAL_H, LOGICAL_W, TAGLINE, TITLE
from src.ui import draw
from src.utils.assets import get_assets

STATION_PIECES = ["floor-panel", "computer-wide", "container", "door-double", "table", "pipe-ring", "chair-armrest",
                  "display-wall", "structure-panel", "wall-door", "computer", "container-tall"]


class Scene:
    def __init__(self, game):
        self.game = game
        self.t = 0.0

    def handle_event(self, ev):
        pass

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        pass


def window_to_logical(game, pos):
    ww, wh = game.window.get_size()
    k = min(ww / LOGICAL_W, wh / LOGICAL_H)
    ox, oy = (ww - LOGICAL_W * k) / 2, (wh - LOGICAL_H * k) / 2
    return ((pos[0] - ox) / k, (pos[1] - oy) / k)


def draw_backdrop(surf, t, title=True, sub=None):
    """Dark gradient with drifting isometric station pieces (supplied space-station-kit previews)."""
    A = get_assets()
    surf.fill(C_BG)
    for i in range(0, LOGICAL_H, 4):
        k = i / LOGICAL_H
        pygame.draw.rect(surf, (int(8 + 10 * k), int(10 + 12 * k), int(20 + 22 * k)), (0, i, LOGICAL_W, 4))
    for i, name in enumerate(STATION_PIECES):
        img = A.station(name, 160)
        x = (i * 190 + t * 14) % (LOGICAL_W + 190) - 190
        y = 470 + 90 * math.sin(i * 1.7 + t * 0.35) + (i % 3) * 30
        im = img.copy()
        im.set_alpha(70)
        surf.blit(im, (x, y))
    glow = A.glow("circle_b", 640, (30, 60, 110))
    surf.blit(glow, (LOGICAL_W // 2 - 320, 40), special_flags=pygame.BLEND_RGB_ADD)
    if title:
        draw.text(surf, TITLE, (LOGICAL_W // 2, 110), 150, (235, 245, 255), "center")
        draw.text(surf, TAGLINE, (LOGICAL_W // 2, 195), 34, C_CYAN, "center")
    if sub:
        draw.text(surf, sub, (LOGICAL_W // 2, 40), 44, (235, 245, 255), "center")


class ListMenu:
    """Vertical button list with keyboard and mouse support. items: list of [label, callback, enabled]."""

    def __init__(self, game, items, top=280, w=420, h=52, gap=12):
        self.game, self.items, self.sel = game, items, 0
        self.top, self.w, self.h, self.gap = top, w, h, gap

    def rect(self, i):
        return pygame.Rect((LOGICAL_W - self.w) // 2, self.top + i * (self.h + self.gap), self.w, self.h)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.items)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.items)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate(self.sel)
        elif ev.type == pygame.MOUSEMOTION:
            p = window_to_logical(self.game, ev.pos)
            for i in range(len(self.items)):
                if self.rect(i).collidepoint(p):
                    self.sel = i
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = window_to_logical(self.game, ev.pos)
            for i in range(len(self.items)):
                if self.rect(i).collidepoint(p):
                    self.sel = i
                    self._activate(i)

    def _activate(self, i):
        label, cb, enabled = self.items[i][:3]
        if enabled:
            cb()

    def draw(self, surf):
        for i, (label, cb, enabled) in enumerate(self.items):
            draw.button(surf, self.rect(i), label, i == self.sel, enabled)
