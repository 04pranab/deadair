"""Drawing helpers: text, character sprites with a body pivot, UI bars and panels."""
import math

import pygame

from src.settings import C_DIM, C_TEXT
from src.utils.assets import get_assets

V = pygame.Vector2
_fonts = {}


def font(size):
    f = _fonts.get(size)
    if f is None:
        f = pygame.font.Font(None, size)
        _fonts[size] = f
    return f


_text_cache = {}


def fit_size(s, size, maxw, min_size=14):
    """The largest font size <= size at which s fits in maxw pixels (never below min_size)."""
    while size > min_size and font(size).size(s)[0] > maxw:
        size -= 1
    return size


def ellipsize(s, size, maxw):
    f = font(size)
    if f.size(s)[0] <= maxw:
        return s
    while len(s) > 1 and f.size(s + "...")[0] > maxw:
        s = s[:-1]
    return s.rstrip() + "..."


def text(surf, s, pos, size=24, color=C_TEXT, anchor="topleft", shadow=True, alpha=255, maxw=None):
    """maxw: never wider than this many pixels: shrink the font first (down to 14), then cut with an ellipsis."""
    if maxw is not None:
        size = fit_size(s, size, maxw)
        s = ellipsize(s, size, maxw)
    key = (s, size, color, shadow)
    img = _text_cache.get(key)
    if img is None:
        f = font(size)
        base = f.render(s, True, color)
        if shadow:
            sh = f.render(s, True, (0, 0, 0))
            img = pygame.Surface((base.get_width() + 2, base.get_height() + 2), pygame.SRCALPHA)
            img.blit(sh, (2, 2))
            img.blit(base, (0, 0))
        else:
            img = base
        if len(_text_cache) > 600:
            _text_cache.clear()
        _text_cache[key] = img
    if alpha < 255:
        img = img.copy()
        img.set_alpha(alpha)
    r = img.get_rect()
    setattr(r, anchor, (int(pos[0]), int(pos[1])))
    # text that would cross a screen edge is slid back inside (never clipped): the cheap global fix for edge overflow
    sw, sh = surf.get_size()
    if r.w < sw - 16 and (r.left < 6 or r.right > sw - 6 or r.top < 2 or r.bottom > sh - 2) and r.x > -sw and r.x < 2 * sw:
        r.clamp_ip(pygame.Rect(6, 2, sw - 12, sh - 4))
    surf.blit(img, r)
    return r


def wrap_text(s, size, width):
    f = font(size)
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.size(t)[0] <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_char(surf, name, pose, pos, scale=1.0, flip=False, tint=None, alpha=255, add=None):
    """Draw a supplied platformer-character pose with its feet at pos (used for portraits and menus)."""
    A = get_assets()
    img = A.pose(name, pose, round(0.6 * scale, 3), flip, tint, add, alpha)
    r = img.get_rect(midbottom=(int(pos[0]), int(pos[1])))
    surf.blit(img, r)
    return r


def bar(surf, x, y, w, frac, palette="blue", h=18, back=(15, 20, 32)):
    """Health/energy bar built from the supplied UI bar pieces."""
    A = get_assets()
    frac = max(0.0, min(1.0, frac))
    pygame.draw.rect(surf, back, (x, y, w, h), border_radius=h // 2)
    fw = int(w * frac)
    if fw >= 6:
        mid = pygame.transform.smoothscale(A.ui(palette, "bar_round_large_m"), (max(1, fw - 2 * (h // 2)), h))
        l = pygame.transform.smoothscale(A.ui(palette, "bar_round_large_l"), (h // 2, h))
        r = pygame.transform.smoothscale(A.ui(palette, "bar_round_large_r"), (h // 2, h))
        surf.blit(l, (x, y))
        surf.blit(mid, (x + h // 2, y))
        surf.blit(r, (x + h // 2 + mid.get_width(), y))
    pygame.draw.rect(surf, (60, 75, 100), (x, y, w, h), 1, border_radius=h // 2)


def panel(surf, rect, alpha=170, color=(10, 14, 26), border=(70, 110, 160)):
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, color + (alpha,), s.get_rect(), border_radius=8)
    pygame.draw.rect(s, border + (230,), s.get_rect(), 2, border_radius=8)
    surf.blit(s, rect.topleft)


def button(surf, rect, label, selected=False, enabled=True):
    A = get_assets()
    pal = "blue" if selected else "red"
    img = A.ui("blue", "button_square_header_large_rectangle") if selected else A.ui("blue", "button_square_header_small_rectangle")
    img = pygame.transform.smoothscale(img, rect.size)
    if not enabled:
        img = img.copy()
        img.fill((90, 90, 90, 255), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(img, rect.topleft)
    col = (20, 30, 50) if enabled else (90, 90, 100)
    text(surf, label, rect.center, 30, col, "center", shadow=False)
    if selected:
        pygame.draw.rect(surf, (80, 200, 255), rect.inflate(6, 6), 2, border_radius=4)
