"""Collision against the tile grid and dynamic solid rectangles, plus line of sight."""
import pygame

from src.settings import TILE
from src.world.level import FLOOR, MAP_H, MAP_W


class Solids:
    def __init__(self, level):
        self.w, self.h = MAP_W, MAP_H
        self.static = [[(level.grid[y][x] != FLOOR) or level.blocked[y][x] for x in range(MAP_W)] for y in range(MAP_H)]
        self.dyn = []          # list of pygame.Rect, rebuilt by the sim every step
        self.dyn_owner = []    # parallel list of owning objects (door / barricade)

    def set_dynamic(self, pairs):
        self.dyn = [r for r, _ in pairs]
        self.dyn_owner = [o for _, o in pairs]

    def tile_solid(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= self.w or ty >= self.h:
            return True
        return self.static[ty][tx]

    def rect_hits_tiles(self, r):
        for ty in range(max(0, r.top // TILE), min(self.h - 1, (r.bottom - 1) // TILE) + 1):
            for tx in range(max(0, r.left // TILE), min(self.w - 1, (r.right - 1) // TILE) + 1):
                if self.static[ty][tx]:
                    return True
        return r.left < 0 or r.top < 0 or r.right > self.w * TILE or r.bottom > self.h * TILE

    def rect_hits_dyn(self, r, ignore=None):
        for i, d in enumerate(self.dyn):
            if d.colliderect(r) and self.dyn_owner[i] is not ignore:
                return self.dyn_owner[i]
        return None

    def blocked_rect(self, r, ignore=None):
        return self.rect_hits_tiles(r) or self.rect_hits_dyn(r, ignore) is not None

    def point_solid(self, x, y, ignore=None):
        if self.tile_solid(int(x // TILE), int(y // TILE)):
            return True
        for i, d in enumerate(self.dyn):
            if d.collidepoint(x, y) and self.dyn_owner[i] is not ignore:
                return True
        return False

    def move(self, pos, delta, half, ignore=None):
        """Axis-separated AABB movement. Returns (new_pos, hit_x, hit_y, hit_owner)."""
        x, y = pos.x, pos.y
        hit_x = hit_y = False
        owner = None
        r = pygame.Rect(0, 0, int(half * 2), int(half * 2))
        if delta.x:
            nx = x + delta.x
            r.center = (round(nx), round(y))
            if self.blocked_rect(r, ignore):
                hit_x = True
                owner = self.rect_hits_dyn(r, ignore) or owner
            else:
                x = nx
        if delta.y:
            ny = y + delta.y
            r.center = (round(x), round(ny))
            if self.blocked_rect(r, ignore):
                hit_y = True
                owner = self.rect_hits_dyn(r, ignore) or owner
            else:
                y = ny
        return pygame.Vector2(x, y), hit_x, hit_y, owner

    def los(self, a, b, step=14):
        d = b - a
        dist = d.length()
        if dist < 1:
            return True
        n = int(dist // step) + 1
        for i in range(1, n):
            p = a + d * (i / n)
            if self.point_solid(p.x, p.y):
                return False
        return True

    def free_at(self, pos, half, ignore=None):
        r = pygame.Rect(0, 0, int(half * 2), int(half * 2))
        r.center = (round(pos.x), round(pos.y))
        return not self.blocked_rect(r, ignore)
