"""Asset loader. Everything is read from assets/ (copied from the supplied ZIPs)."""
import json
import math

import pygame

from src.config import ASSET_DIR


class Assets:
    def __init__(self):
        with open(ASSET_DIR / "manifest.json", encoding="utf-8") as f:
            self.manifest = json.load(f)
        self._raw = {}
        self._cache = {}

    def has(self, rel):
        return rel in self.manifest

    def raw(self, rel):
        if rel not in self.manifest:
            raise KeyError(f"asset not in manifest: {rel}")
        img = self._raw.get(rel)
        if img is None:
            img = pygame.image.load(str(ASSET_DIR / rel))
            img = img.convert_alpha() if pygame.display.get_surface() else img
            self._raw[rel] = img
        return img

    def _memo(self, key, make):
        v = self._cache.get(key)
        if v is None:
            v = make()
            self._cache[key] = v
        return v

    # --- top-down map tiles (tiny-factory, 16 px, drawn at TILE size) ------------------
    def tile(self, idx, size=None, tint=None, flip=False):
        from src.settings import TILE
        sz = size or TILE
        key = ("tile", idx, sz, tuple(tint) if tint else None, flip)

        def make():
            img = pygame.transform.scale(self.raw(f"hub/factory/tile_{idx:04d}.png"), (sz, sz))
            if flip:
                img = pygame.transform.flip(img, True, False)
            if tint:
                img = img.copy()
                img.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
            return img
        return self._memo(key, make)

    # --- decorative environment renders (space-station kit previews; menu backdrop, gate) ----
    def kit_raw(self, name, folder="station", size=96):
        return self._memo(("kr", folder, name, size), lambda: pygame.transform.smoothscale(self.raw(f"hub/{folder}/{name}.png"), (size, size)))

    # --- legacy kit (kept for the menu backdrop) (space-station kit previews, isometric renders) --------------
    def kit(self, name, folder="station", flip=False, tint=None, scale=None, alpha=255):
        KIT_SCALE = 1.5
        sc = scale or KIT_SCALE
        key = ("kit", folder, name, flip, tuple(tint) if tint else None, sc, alpha)

        def make():
            img = self.raw(f"hub/{folder}/{name}.png")
            img = pygame.transform.smoothscale(img, (int(64 * sc), int(64 * sc)))
            if flip:
                img = pygame.transform.flip(img, True, False)
            if tint:
                img = img.copy()
                img.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            return img
        return self._memo(key, make)

    # --- characters (platformer-characters poses, front-facing 80x110) ----------------
    def pose(self, char, pose, scale=0.5, flip=False, tint=None, add=None, alpha=255):
        key = ("pose", char, pose, scale, flip, tuple(tint) if tint else None, tuple(add) if add else None, alpha)

        def make():
            img = self.raw(f"chars2d/{char}/Poses/{char.lower()}_{pose}.png")
            img = pygame.transform.smoothscale(img, (int(80 * scale), int(110 * scale)))
            if flip:
                img = pygame.transform.flip(img, True, False)
            if tint or add or alpha < 255:
                img = img.copy()
                if tint:
                    img.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
                if add:
                    img.fill(add, special_flags=pygame.BLEND_RGB_ADD)
                if alpha < 255:
                    img.set_alpha(alpha)
            return img
        return self._memo(key, make)

    # --- fx ----------------------------------------------------------
    def particle(self, name, size, color=None):
        def make():
            img = pygame.transform.smoothscale(self.raw(f"fx/particles/{name}.png"), (size, size))
            if color:
                img = img.copy()
                img.fill(color + (255,), special_flags=pygame.BLEND_RGBA_MULT)
            return img.premul_alpha()   # additive use: transparent pixels must add nothing
        return self._memo(("p", name, size, tuple(color) if color else None), make)

    def light(self, name, size, color=None, squash=1.0):
        def make():
            img = pygame.transform.smoothscale(self.raw(f"fx/lights/{name}.png"), (size, max(2, int(size * squash))))
            if color:
                img = img.copy()
                img.fill(color + (255,), special_flags=pygame.BLEND_RGBA_MULT)
            return img
        return self._memo(("l", name, size, tuple(color) if color else None, squash), make)

    # --- ui ----------------------------------------------------------
    def glow(self, name, size, color, squash=1.0):
        """Premultiplied tinted light mask for additive blending (no square halos)."""
        def make():
            img = pygame.transform.smoothscale(self.raw(f"fx/lights/{name}.png"), (size, max(2, int(size * squash)))).copy()
            img.fill(color + (255,), special_flags=pygame.BLEND_RGBA_MULT)
            return img.premul_alpha()
        return self._memo(("g", name, size, tuple(color), squash), make)

    def icon(self, name, size=32, color=None):
        def make():
            img = pygame.transform.smoothscale(self.raw(f"ui/icons/{name}.png"), (size, size))
            if color:
                img = img.copy()
                img.fill(color + (255,), special_flags=pygame.BLEND_RGBA_MULT)
            return img
        return self._memo(("i", name, size, tuple(color) if color else None), make)

    def ui(self, palette, name):
        return self.raw(f"ui/{palette}/{name}.png")

    def station(self, name, size=128):
        return self._memo(("st", name, size), lambda: pygame.transform.scale(self.raw(f"hub/station/{name}.png"), (size, size)))


_assets = None


def get_assets():
    global _assets
    if _assets is None:
        _assets = Assets()
    return _assets
