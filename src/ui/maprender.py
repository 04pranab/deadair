"""Bakes the static part of a level (floor, trim, walls, decor) into one surface from the supplied tiny-factory tiles."""
import random

import pygame

from src.settings import TILE
from src.utils.assets import get_assets
from src.world.level import FLOOR, MAP_H, MAP_W

VOID = (9, 8, 14)
FLOOR_TILES = [3] * 9 + [32, 32, 11]          # plain floor, debris, grating
WALL_TILES = [46, 47, 44, 45]
DECOR_TILES = [82, 105, 106, 83, 91, 129, 90]


def _is_floor(lvl, x, y):
    return 0 <= x < MAP_W and 0 <= y < MAP_H and lvl.grid[y][x] == FLOOR


def bake(lvl):
    A = get_assets()
    rng = random.Random(lvl.seed * 31 + 7)
    surf = pygame.Surface((MAP_W * TILE, MAP_H * TILE))
    surf.fill(VOID)
    for y in range(MAP_H):
        for x in range(MAP_W):
            px, py = x * TILE, y * TILE
            if lvl.grid[y][x] == FLOOR:
                surf.blit(A.tile(rng.choice(FLOOR_TILES)), (px, py))
                n, s = not _is_floor(lvl, x, y - 1), not _is_floor(lvl, x, y + 1)
                w, e = not _is_floor(lvl, x - 1, y), not _is_floor(lvl, x + 1, y)
                trim = None
                if n and w:
                    trim = 7
                elif n and e:
                    trim = 8
                elif s and w:
                    trim = 19
                elif s and e:
                    trim = 20
                elif n:
                    trim = 34
                elif s:
                    trim = 10
                elif w:
                    trim = 23
                elif e:
                    trim = 21
                if trim is not None:
                    surf.blit(A.tile(trim), (px, py))
            else:
                near = any(_is_floor(lvl, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if near:
                    surf.blit(A.tile(WALL_TILES[(x * 7 + y * 3) % 2 + (2 if (x + y) % 5 == 0 else 0)]), (px, py))
                    if _is_floor(lvl, x, y + 1) and rng.random() < 0.16:
                        surf.blit(A.tile(rng.choice(DECOR_TILES)), (px, py))
    return surf
