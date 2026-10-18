"""Painters for the story scenes. Everything is drawn from the supplied Kenney art (character poses, station pieces, light masks)
plus procedural rings, scanlines and tint. A painter draws one shot: paint(surf, art, st, dur, params, seed).
All painters are pure functions of time, so a shot can be skipped or re-rendered (for screenshots) at any moment."""
import math
import random

import pygame

from src.settings import C_AMBER, C_CYAN, C_RED, LOGICAL_H, LOGICAL_W
from src.utils.assets import get_assets

W, H = LOGICAL_W, LOGICAL_H
V = pygame.Vector2
PIECES = ["floor-panel", "computer-wide", "container", "door-double", "table", "pipe-ring", "chair-armrest"]
_cache = {}


def _vignette():
    if "vig" not in _cache:
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(24):
            a = int(34 * (1 - i / 24.0) ** 2)
            pygame.draw.ellipse(s, (0, 0, 0, 0), (0, 0, 0, 0))
            pygame.draw.rect(s, (0, 0, 0, a), (i * 12, i * 7, W - 2 * i * 12, H - 2 * i * 7), 12, border_radius=40)
        _cache["vig"] = s
    return _cache["vig"]


def _grad(surf, top, bot):
    for y in range(0, H, 6):
        k = y / H
        pygame.draw.rect(surf, tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)), (0, y, W, 6))


def _glow(surf, name, size, color, pos, a=1.0):
    A = get_assets()
    g = A.glow(name, int(size), tuple(int(c * a) for c in color))
    surf.blit(g, g.get_rect(center=(int(pos[0]), int(pos[1]))), special_flags=pygame.BLEND_RGB_ADD)


def _ease(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _scan(surf, st, strength=34):
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    for y in range(0, H, 4):
        s.fill((0, 0, 0, strength), (0, y, W, 1))
    surf.blit(s, (0, 0))
    y = int((st * 90) % (H + 80)) - 40
    pygame.draw.rect(surf, (40, 70, 110), (0, y, W, 2))


def _char(surf, name, pose, pos, scale, flip=False, tint=None, alpha=255, add=None):
    A = get_assets()
    img = A.pose(name, pose, round(scale, 3), flip, tint, add, alpha)
    surf.blit(img, img.get_rect(midbottom=(int(pos[0]), int(pos[1]))))


def _station(surf, st, dim=0.5):
    A = get_assets()
    _grad(surf, (4, 6, 14), (12, 16, 30))
    for i, name in enumerate(PIECES * 2):
        img = A.station(name, 190 + (i % 3) * 40).copy()
        img.set_alpha(int(80 * dim))
        x = (i * 210 - st * 16) % (W + 260) - 260
        y = 430 + 70 * math.sin(i * 1.7 + st * 0.3) + (i % 3) * 26
        surf.blit(img, (x, y))


def _led(surf, pos, st, color=C_RED, rate=0.7):
    on = (st * rate) % 1.0 < 0.5
    pygame.draw.circle(surf, color if on else (60, 20, 20), pos, 5)
    if on:
        _glow(surf, "circle_a", 90, color, pos, 0.7)


# ------------------------------------------------------------------ shots
def station(surf, st, dur, p, seed):
    _station(surf, st)
    _glow(surf, "circle_b", 620, (30, 55, 110), (W // 2 + 60 * math.sin(st * 0.2), 180), 0.8)
    for i, c in enumerate(("Player", "Female", "Soldier")):
        x = 260 + i * 70 + st * 10
        _char(surf, c, "walk1" if int(st * 4 + i) % 2 else "walk2", (x, 640), 1.5, tint=(70, 90, 120), alpha=210)
    _led(surf, (1120, 90), st)
    _led(surf, (160, 130), st + 0.3)


def dark(surf, st, dur, p, seed):
    _grad(surf, (2, 3, 8), (6, 8, 16))
    k = _ease(st / 2.5)
    _glow(surf, "circle_b", 420, (200, 40, 40), (W // 2, H // 2), 0.5 * k)
    _led(surf, (W // 2, H // 2), st, rate=0.5)


def tally(surf, st, dur, p, seed):
    """A wall of tally marks. `hidden`: it is half lost in the dark and uncounted; revealed, it is counted aloud: 4,812."""
    hidden = p.get("hidden", False)
    _grad(surf, (8, 8, 12), (18, 16, 22))
    rng = random.Random(seed)
    k = _ease(st / (dur * 0.8))
    total = 4812
    shown = int(total * k) if not hidden else int(total * 0.02 + 70 * k)
    cols, rows = 34, 18
    n = 0
    for gy in range(rows):
        for gx in range(cols):
            if n >= shown // 6 + 1:
                break
            x, y = 40 + gx * 36, 80 + gy * 34
            a = 90 if hidden else 150
            for t in range(4):
                pygame.draw.line(surf, (a, a, a - 20), (x + t * 6, y), (x + t * 6, y + 22), 2)
            pygame.draw.line(surf, (a, a, a - 20), (x - 3, y + 18), (x + 24, y + 4), 2)
            n += 1
    if not hidden:
        txt = f"{shown:,}"
        f = pygame.font.Font(None, 150)
        img = f.render(txt, True, (235, 235, 240))
        surf.blit(img, img.get_rect(center=(W // 2, H // 2 - 20)))
        if k > 0.98:
            _glow(surf, "circle_a", 260, C_RED, (W // 2, H // 2 + 60), 0.6 + 0.3 * math.sin(st * 6))
            f2 = pygame.font.Font(None, 40)
            surf.blit(f2.render("CURRENT", True, C_RED), (W // 2 - 70, H // 2 + 52))
    else:
        _glow(surf, "circle_c", 560, (60, 50, 20), (400 + 300 * math.sin(st * 0.4), 300), 0.6)


def crew(surf, st, dur, p, seed):
    A = get_assets()
    _station(surf, st, 0.7)
    cam = (W - 200, 120)
    pygame.draw.rect(surf, (30, 36, 50), (cam[0] - 30, cam[1] - 18, 60, 36), border_radius=6)
    _led(surf, cam, st, rate=1.4)
    for i, c in enumerate(("Player", "Female", "Soldier", "Adventurer")):
        x = 160 + i * 150 + st * 40
        _char(surf, c, "walk1" if int(st * 5 + i) % 2 else "walk2", (x, 620), 1.7, tint=(120, 140, 170))
    # the camera beam follows the lead character
    lead = (160 + 3 * 150 + st * 40, 560)
    beam = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.polygon(beam, (255, 70, 60, 40), [cam, (lead[0] - 90, 640), (lead[0] + 90, 640)])
    surf.blit(beam, (0, 0))


def eye(surf, st, dur, p, seed):
    """MERIDIAN's eye: concentric rings that turn, an iris that opens as it speaks, scanlines. It never blinks; it closes once."""
    _grad(surf, (2, 3, 8), (8, 10, 20))
    cx, cy = W // 2, H // 2 - 20
    angry = p.get("angry", False)
    closing = p.get("closing", False)
    col = C_RED if angry else (C_CYAN if not p.get("calm") else (120, 200, 255))
    open_k = _ease(st / 2.2)
    if closing:
        open_k = 1.0 - _ease((st - dur * 0.45) / (dur * 0.5))
    _glow(surf, "circle_b", 900, col, (cx, cy), 0.32 * open_k)
    for r in range(7):
        rad = 60 + r * 34
        w = 2 if r % 2 else 4
        ang = st * (0.4 + r * 0.1) * (1 if r % 2 else -1)
        for a0 in range(0, 360, 40):
            a1 = a0 + 24 + 10 * math.sin(st + r)
            rect = pygame.Rect(cx - rad, cy - int(rad * (0.55 + 0.4 * open_k)), rad * 2, int(rad * 2 * (0.55 + 0.4 * open_k)))
            pygame.draw.arc(surf, tuple(int(c * (0.4 + 0.5 * open_k)) for c in col), rect, math.radians(a0) + ang, math.radians(a1) + ang, w)
    iris = int(18 + 40 * open_k + (8 * math.sin(st * 3) if angry else 0))
    pygame.draw.circle(surf, (5, 5, 10), (cx, cy), iris)
    pygame.draw.circle(surf, col, (cx, cy), iris, 2)
    _glow(surf, "circle_a", iris * 3, col, (cx, cy), 0.9 * open_k)
    # tiny reflections of the crew in the pupil
    for i, c in enumerate(("Player", "Female", "Soldier")):
        _char(surf, c, "idle", (cx - 26 + i * 26, cy + 14), 0.22, tint=(160, 190, 230), alpha=int(160 * open_k))
    _scan(surf, st)


def walkers(surf, st, dur, p, seed):
    """The failed imprints: the same coat, a different face each time, walking. `rest`: one by one they lie down."""
    _station(surf, st, 0.35)
    rest = p.get("rest", False)
    n = 14
    for i in range(n):
        x = (W + 100) - ((i * 120 + st * 28) % (W + 260)) if not rest else 90 + i * 88
        y = 560 + (i % 3) * 22
        name = ("Zombie", "Adventurer", "Female", "Soldier", "Player")[i % 5]
        tint = (90, 110, 150)
        if rest:
            k = _ease((st - 0.5 - i * 0.25) / 1.2)
            pose = "fall" if k > 0.5 else "idle"
            _char(surf, name, pose, (x, y + 12 * k), 1.45, tint=tint, alpha=int(255 - 130 * k), flip=bool(i % 2))
        else:
            _char(surf, name, "walk1" if int(st * 3 + i) % 2 else "walk2", (x, y), 1.45, tint=tint, flip=True,
                  alpha=200)
    _glow(surf, "circle_b", 700, (40, 60, 120), (W // 2, 300), 0.6)


def host(surf, st, dur, p, seed):
    """A rift tears open. Papers scatter to the four corners of the station. One figure turns red."""
    _station(surf, st, 0.5)
    cx, cy = W // 2, 300
    k = _ease(st / 2.0)
    pygame.draw.line(surf, (255, 255, 255), (cx, cy - 190 * k), (cx + 14 * math.sin(st * 9), cy + 190 * k), 3)
    _glow(surf, "circle_a_streaks", int(520 * k), (200, 80, 255), (cx, cy), 0.8)
    rng = random.Random(seed)
    for i in range(14):
        a = rng.uniform(0, math.tau)
        d = _ease((st - 1.0) / 4.5) * rng.uniform(300, 700)
        x, y = cx + math.cos(a) * d * 1.5, cy + math.sin(a) * d * 0.7
        ang = st * rng.uniform(2, 6)
        pr = pygame.Surface((26, 34), pygame.SRCALPHA)
        pr.fill((230, 230, 235, 230))
        pygame.draw.line(pr, (70, 70, 80), (5, 9), (21, 9), 2)
        pygame.draw.line(pr, (70, 70, 80), (5, 17), (21, 17), 2)
        pr = pygame.transform.rotate(pr, math.degrees(ang))
        surf.blit(pr, pr.get_rect(center=(int(x), int(y))))
    turn = _ease((st - 3.0) / 3.0)
    for i, c in enumerate(("Player", "Female", "Soldier")):
        t = (int(120 + 135 * turn), int(140 - 90 * turn), int(170 - 120 * turn)) if i == 1 else (110, 130, 160)
        _char(surf, c, "idle", (330 + i * 310, 650), 2.0, tint=t)
    if turn > 0:
        _glow(surf, "circle_a", int(380 * turn), C_RED, (640, 560), 0.7)


def core(surf, st, dur, p, seed):
    """The Archive Core: warm, pulsing, wrong. `cracked`: it fails."""
    _grad(surf, (6, 4, 8), (22, 12, 10))
    cx, cy = W // 2, H // 2 - 20
    cracked = p.get("cracked", False)
    pulse = 0.75 + 0.25 * math.sin(st * (2.2 if not cracked else 7))
    col = (255, 170, 90)
    _glow(surf, "circle_b", int(760 * pulse), col, (cx, cy), 0.85 * (1 - (0.7 * _ease(st / dur) if cracked else 0)))
    pygame.draw.circle(surf, (255, 225, 170), (cx, cy), int(46 + 6 * pulse))
    for i in range(10):
        a = i * math.tau / 10 + st * 0.12
        pygame.draw.line(surf, (110, 60, 40), (cx + math.cos(a) * 70, cy + math.sin(a) * 70), (cx + math.cos(a) * 520, cy + math.sin(a) * 340), 2)
    if cracked:
        rng = random.Random(seed)
        for _ in range(9):
            a = rng.uniform(0, math.tau)
            ln = _ease(st / 3.0) * rng.uniform(60, 220)
            pygame.draw.line(surf, (20, 10, 8), (cx, cy), (cx + math.cos(a) * ln, cy + math.sin(a) * ln), 3)
    _scan(surf, st, 22)


def dawn(surf, st, dur, p, seed):
    k = _ease(st / dur)
    _grad(surf, (int(12 + 200 * k), int(14 + 190 * k), int(24 + 160 * k)), (int(30 + 220 * k), int(30 + 210 * k), int(40 + 190 * k)))
    _glow(surf, "circle_b", 900, (255, 235, 200), (W // 2, H // 2), k)
    for i, c in enumerate(("Player", "Female", "Soldier")):
        _char(surf, c, "cheer1" if int(st * 2) % 2 else "cheer2", (420 + i * 220, 640), 2.0, tint=(150 + int(100 * k), 160 + int(80 * k), 170))


ART = {"station": station, "dark": dark, "tally": tally, "crew": crew, "eye": eye, "walkers": walkers, "host": host, "core": core,
       "dawn": dawn}


def paint(surf, art, st, dur, params=None, seed=0):
    ART.get(art, dark)(surf, st, dur, params or {}, seed)
    surf.blit(_vignette(), (0, 0))
