"""Character animation from the supplied pose frames: walk cycle, aim, hurt, dodge, carry, ritual, ghost.
The packs ship single poses (no sheets), so animation = frame selection + procedural bob/squash/lean."""
import math

import pygame

from src.ui.view import CHAR_SCALE, world_dir_to_screen
from src.utils.assets import get_assets

V = pygame.Vector2
WALK_FPS = 8.0


class Look:
    """What to draw for one character this frame."""
    __slots__ = ("pose", "flip", "bob", "sx", "sy", "tint", "add", "alpha", "lean")

    def __init__(self, pose="idle", flip=False, bob=0.0, sx=1.0, sy=1.0, tint=None, add=None, alpha=255, lean=0.0):
        self.pose, self.flip, self.bob, self.sx, self.sy = pose, flip, bob, sx, sy
        self.tint, self.add, self.alpha, self.lean = tint, add, alpha, lean


def facing_info(world_facing):
    """-> (flip, looking_away) from a world-space facing vector."""
    sx, sy = world_dir_to_screen((world_facing.x, world_facing.y))
    return sx < -0.05, (sy < -0.45 and abs(sx) < 0.8)


def _walk(phase, t):
    return "walk1" if int(phase * 1.0 + t * 0) % 2 == 0 else "walk2"


def player_look(p, t, sim_time):
    flip, away = facing_info(p.facing)
    bob = 0.0
    sx = sy = 1.0
    if not p.alive:
        return Look("fall", flip, 6 + math.sin(t * 3 + p.idx) * 4, tint=(120, 200, 255), add=(0, 40, 70), alpha=125)
    tint = add = None
    alpha = 255
    if p.weakened:
        tint = (200, 170, 255)
    if p.flash > 0:
        add = (120, 120, 120)
    if p.iframes > 0 and int(t * 20) % 2 == 0:
        alpha = 130
    if p.charge_t > 0:
        return Look("slide", flip, 0, 1.15, 0.9, tint, add, alpha)
    if p.dodge_t > 0:
        return Look("duck", flip, 0, 1.2, 0.8, tint, add, 170)
    if p.flash > 0.08:
        return Look("hurt", flip, 0, 1, 1, tint, add, alpha)
    if p.ability_cd > p.ability_max - 0.4 and p.ability_max > 1:
        return Look("action1" if int(t * 14) % 2 == 0 else "action2", flip, 0, 1, 1, tint, add, alpha)
    if getattr(p, "channeling", False):
        return Look("cheer1" if int(t * 3) % 2 == 0 else "cheer2", flip, math.sin(t * 6) * 2, 1, 1, tint, add, alpha)
    if p.carry is not None:
        bob = abs(math.sin(p.walk_phase * 6)) * 3 if p.moving else 0
        return Look("hold2", flip, bob, 1, 1, tint, add, alpha)
    if p.recoil > 0 or p.fire_cd > 0.15:
        return Look("hold1", flip, 0, 1.0 + p.recoil, 1.0 - p.recoil, tint, add, alpha)
    if p.moving:
        frame = "walk1" if int(sim_time * WALK_FPS * 1.0) % 2 == 0 else "walk2"
        if away:
            frame = "back"
        bob = abs(math.sin(sim_time * WALK_FPS * math.pi)) * 3.5
        return Look(frame, flip, bob, 1, 1, tint, add, alpha, lean=2.0)
    pose = "back" if away else "idle"
    return Look(pose, flip, 0, 1.0, 1.0 + 0.025 * math.sin(t * 2.2 + p.idx), tint, add, alpha)


def enemy_look(e, t, sim_time):
    flip, away = facing_info(e.facing)
    tint = tuple(e.spec.tint) if e.spec.get("tint") else None
    add = None
    beh = e.spec.behavior
    if e.flash > 0:
        add = (140, 140, 140)
    if e.state == "stagger":
        return Look("hurt", flip, 0, 1, 1, tint, (0, 40, 90))
    if e.state == "windup":
        k = 1 - e.timer / max(0.01, e.spec.windup)
        pose = {"melee": "action1", "ranged": "hold1", "heavy": "cheer1"}[beh]
        flash = (int(90 * (0.5 + 0.5 * math.sin(t * 30))), 0, 0)
        return Look(pose, flip, 0, 1 + 0.1 * k, 1 - 0.08 * k, tint, flash)
    if e.state == "recover":
        pose = {"melee": "action2", "ranged": "idle", "heavy": "kick"}[beh]
        return Look(pose, flip, 0, 1, 1, tint, add)
    if e.state == "chase":
        frame = "walk1" if int(sim_time * WALK_FPS * (1.0 if beh != "heavy" else 0.6)) % 2 == 0 else "walk2"
        if away:
            frame = "back"
        bob = abs(math.sin(sim_time * WALK_FPS * math.pi * (1.0 if beh != "heavy" else 0.6))) * 3
        return Look(frame, flip, bob, 1, 1, tint, add)
    return Look("idle" if not away else "back", flip, 0, 1, 1.0 + 0.02 * math.sin(t * 2 + e.id), tint, add)


def draw_look(surf, screen_pos, char, look, scale=1.0):
    """Blit a character with feet at screen_pos."""
    A = get_assets()
    sc = CHAR_SCALE * scale
    img = A.pose(char, look.pose, round(sc, 3), look.flip, look.tint, look.add, look.alpha)
    w, h = img.get_size()
    if look.sx != 1.0 or look.sy != 1.0:
        img = pygame.transform.scale(img, (max(1, int(w * look.sx)), max(1, int(h * look.sy))))
        w, h = img.get_size()
    if look.lean:
        img = pygame.transform.rotate(img, -look.lean if not look.flip else look.lean)
        w, h = img.get_size()
    # feet sit at ~98% of the image height in the supplied poses
    surf.blit(img, (screen_pos[0] - w / 2, screen_pos[1] - h * 0.97 - look.bob))
    return pygame.Rect(screen_pos[0] - w / 2, screen_pos[1] - h - look.bob, w, h)


def hand_offset(world_facing, scale=1.0):
    """Screen offset from feet to the weapon hand (muzzle) for the given aim direction."""
    sx, sy = world_dir_to_screen((world_facing.x, world_facing.y))
    return (sx * 22 * scale, -34 * scale + sy * 8)
