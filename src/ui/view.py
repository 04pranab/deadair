"""Top-down camera. The map is drawn flat; only the characters use the 2.5D side-view pose sprites.
Screen == world (no rotation), so input needs no remapping."""
import math

import pygame

from src.settings import LOGICAL_H, LOGICAL_W, TILE

V = pygame.Vector2
CHAR_SCALE = 0.6        # 80x110 character poses -> 48x66 px (about one tile wide)


def world_dir_to_screen(v):
    n = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / n, v[1] / n)


class Camera:
    def __init__(self):
        self.origin = V(0, 0)
        self.shake = (0, 0)

    def focus_on(self, wpos, smooth=None, dt=0.0):
        if smooth is None:
            self.origin = V(wpos)
        else:
            self.origin += (V(wpos) - self.origin) * min(1.0, smooth * dt)

    def to_screen(self, wx, wy, z=0.0):
        return (wx - self.origin.x + LOGICAL_W / 2 + self.shake[0], wy - self.origin.y + LOGICAL_H / 2 - z + self.shake[1])

    def vec(self, p, z=0.0):
        return self.to_screen(p.x, p.y, z)

    def offset(self):
        return (LOGICAL_W / 2 - self.origin.x + self.shake[0], LOGICAL_H / 2 - self.origin.y + self.shake[1])

    def visible_tiles(self, margin=1):
        x0 = int((self.origin.x - LOGICAL_W / 2) // TILE) - margin
        x1 = int((self.origin.x + LOGICAL_W / 2) // TILE) + margin
        y0 = int((self.origin.y - LOGICAL_H / 2) // TILE) - margin
        y1 = int((self.origin.y + LOGICAL_H / 2) // TILE) + margin
        return x0, x1, y0, y1


def circle_pts(center_screen, r, n=32):
    cx, cy = center_screen
    return [(cx + math.cos(2 * math.pi * i / n) * r, cy + math.sin(2 * math.pi * i / n) * r) for i in range(n)]
