"""Particles, screen shake and flashes driven by simulation events. Uses the supplied particle masks."""
import math
import random

import pygame

from src.settings import C_AMBER, C_CYAN, C_GREEN, C_RED
from src.utils.assets import get_assets

V = pygame.Vector2


class Particle:
    __slots__ = ("name", "pos", "vel", "life", "total", "s0", "s1", "color", "rot")

    def __init__(self, name, pos, vel, life, s0, s1, color):
        self.name, self.pos, self.vel = name, V(pos), V(vel)
        self.life = self.total = life
        self.s0, self.s1, self.color = s0, s1, color


class Fx:
    MAX = 400

    def __init__(self, shake_enabled=True):
        self.parts = []
        self.shake = 0.0
        self.flash = 0.0
        self.flash_color = (255, 60, 60)
        self.rings = []   # (pos, radius0, radius1, life, total, color)
        self.shake_enabled = shake_enabled
        self.hitstop = 0.0      # seconds the simulation is held on an impact frame
        self.tint = 0.0         # full-screen colour wash (phase changes, Veil breaks)
        self.tint_color = (255, 255, 255)
        self.rng = random.Random(1)

    def add(self, name, pos, vel=(0, 0), life=0.4, s0=16, s1=40, color=(255, 255, 255)):
        if len(self.parts) < self.MAX:
            self.parts.append(Particle(name, pos, vel, life, s0, s1, color))

    def burst(self, name, pos, n, speed, life, s0, s1, color):
        for _ in range(n):
            a = self.rng.uniform(0, math.tau)
            v = V(math.cos(a), math.sin(a)) * self.rng.uniform(speed * 0.4, speed)
            self.add(name, pos, v, life * self.rng.uniform(0.6, 1.2), s0, s1, color)

    def ring(self, pos, r0, r1, life, color):
        self.rings.append([V(pos), r0, r1, life, life, color])

    def kick(self, amount):
        if self.shake_enabled:
            self.shake = min(8.0, self.shake + amount)

    def stop(self, secs):
        if self.shake_enabled:                      # hit-stop follows the comfort setting: it is a jolt, not information
            self.hitstop = min(0.12, max(self.hitstop, secs))

    def wash(self, color, amount):
        self.tint_color, self.tint = color, max(self.tint, amount)

    def handle(self, ev):
        n = ev["name"]
        pos = ev.get("pos")
        if n == "shoot":
            col = (255, 230, 150) if ev["friendly"] else (255, 110, 90)
            self.add("muzzle_0%d" % self.rng.randint(1, 5), pos, ev["dir"] * 20, 0.09, 30, 44, col)
        elif n == "bullet_wall":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 3, 90, 0.25, 12, 20, (255, 210, 120))
        elif n == "enemy_hit":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 3, 110, 0.25, 14, 24, (255, 120, 90))
        elif n == "enemy_died":
            self.add("smoke_0%d" % self.rng.randint(1, 9), pos, (0, -20), 0.7, 26, 70, (140, 140, 160))
            self.add("flare_01", pos, (0, 0), 0.25, 30, 80, (255, 160, 90))
            self.kick(1.0)
        elif n == "player_hit":
            self.flash = max(self.flash, 0.22)
            self.flash_color = (255, 60, 60)
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 6, 140, 0.3, 14, 26, (255, 70, 70))
            self.kick(2.5)
        elif n == "defeated":
            self.burst("magic_0%d" % self.rng.randint(1, 5), pos, 8, 120, 0.8, 24, 60, C_CYAN)
            self.ring(pos, 10, 110, 0.7, C_CYAN)
            self.kick(4.0)
        elif n == "revived":
            self.burst("magic_0%d" % self.rng.randint(1, 5), pos, 14, 160, 1.0, 26, 70, (170, 230, 255))
            self.ring(pos, 10, 170, 0.9, (170, 230, 255))
            self.add("flare_01", pos, (0, 0), 0.6, 60, 200, (150, 220, 255))
        elif n == "echo_pickup" or n == "echo_placed":
            self.burst("twirl_0%d" % self.rng.randint(1, 3), pos, 4, 60, 0.6, 20, 44, C_CYAN)
        elif n == "relay_online":
            self.ring(pos, 10, 150, 0.8, C_GREEN)
            self.burst("star_0%d" % self.rng.randint(1, 9), pos, 8, 120, 0.7, 14, 30, C_GREEN)
        elif n == "surge_hit":
            self.ring(pos, 10, ev["radius"] + 20, 0.4, C_AMBER)
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 14, 220, 0.5, 18, 36, (255, 230, 120))
            self.add("flare_01", pos, (0, 0), 0.3, 60, 200, (255, 220, 120))
            self.kick(5.0)
        elif n == "slam":
            self.ring(pos, 10, ev["radius"], 0.35, C_RED)
            self.burst("smoke_0%d" % self.rng.randint(1, 9), pos, 6, 120, 0.7, 30, 70, (150, 130, 130))
            self.kick(5.0)
        elif n == "melee_strike":
            self.add("slash_0%d" % self.rng.randint(1, 4), pos, (0, 0), 0.15, 40, 56, (255, 120, 100))
        elif n in ("dodge", "charge"):
            self.add("trace_0%d" % self.rng.randint(1, 7), pos, (0, 0), 0.25, 40, 56, (170, 220, 255))
        elif n == "stim":
            self.ring(pos, 10, ev["radius"], 0.6, C_GREEN)
            self.burst("star_0%d" % self.rng.randint(1, 9), pos, 8, 80, 0.7, 14, 28, C_GREEN)
        elif n == "barricade":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 5, 100, 0.3, 14, 22, C_CYAN)
        elif n == "loot" or n == "salvage_pickup":
            self.burst("star_0%d" % self.rng.randint(1, 9), pos, 4, 80, 0.5, 12, 22, C_AMBER)
        elif n == "ghost_disrupt":
            self.ring(pos, 10, 110, 0.5, C_CYAN)
        elif n in ("barrier_hit", "barrier_broken"):
            self.burst("dirt_0%d" % self.rng.randint(1, 3), pos, 6, 120, 0.5, 18, 36, (200, 180, 150))
            if n == "barrier_broken":
                self.kick(4.0)
        elif n == "hazard_active":
            self.add("flare_01", pos, (0, 0), 0.25, 40, 90, (120, 190, 255))
        elif n == "enemies_arrive":
            self.ring(pos, 10, 90, 0.5, C_RED)
        else:
            self._story(n, ev, pos)

    def _story(self, n, ev, pos):
        """Host, Rift and MERIDIAN beats: every one has a windup cue, an impact frame and an aftermath."""
        RED, VIO, ICE = (255, 60, 70), (200, 120, 255), (170, 235, 255)
        if n == "host_claw":
            d = ev["dir"]
            self.add("slash_0%d" % self.rng.randint(1, 4), pos + d * 54, (0, 0), 0.2, 70, 110, RED)
            if ev["hit"]:
                self.stop(0.07)
                self.kick(3.5)
                self.burst("spark_0%d" % self.rng.randint(1, 7), pos + d * 60, 8, 200, 0.35, 16, 30, RED)
        elif n == "host_lunge":
            self.ring(pos, 10, 90, 0.3, RED)
            self.burst("smoke_0%d" % self.rng.randint(1, 9), pos, 4, 100, 0.5, 26, 60, (120, 80, 90))
            self.kick(1.5)
        elif n == "host_hit":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 4, 160, 0.3, 14, 26, (255, 190, 190))
            self.kick(1.0)
        elif n == "host_veil_broken":
            self.ring(pos, 20, 190, 0.5, ICE)
            self.burst("star_0%d" % self.rng.randint(1, 9), pos, 16, 260, 0.7, 16, 34, ICE)
            self.add("flare_01", pos, (0, 0), 0.4, 80, 260, ICE)
            self.wash(ICE, 0.35)
            self.stop(0.09)
            self.kick(5.0)
        elif n == "host_mark":
            self.ring(pos, 80, 14, 0.5, RED)
            self.kick(2.0)
        elif n == "host_summon":
            for i in range(3):
                self.ring(pos, 10, 260 + 60 * i, 0.9 + 0.2 * i, RED)
            self.burst("smoke_0%d" % self.rng.randint(1, 9), pos, 14, 220, 1.0, 40, 110, (110, 40, 60))
            self.wash(RED, 0.4)
            self.stop(0.1)
            self.kick(8.0)
        elif n == "host_born":
            self.ring(pos, 10, 300, 0.9, RED)
            self.add("flare_01", pos, (0, 0), 0.8, 100, 420, RED)
            self.wash(RED, 0.6)
            self.kick(8.0)
        elif n == "host_cured":
            self.ring(pos, 10, 240, 0.9, ICE)
            self.burst("magic_0%d" % self.rng.randint(1, 5), pos, 18, 180, 1.0, 24, 60, ICE)
            self.wash(ICE, 0.4)
        elif n in ("door_burst",):
            self.burst("dirt_0%d" % self.rng.randint(1, 3), pos, 10, 200, 0.6, 20, 50, (200, 170, 140))
            self.kick(5.0)
            self.stop(0.05)
        elif n == "rift_tear":
            self.ring(pos, 6, 120, 0.8, VIO)
            self.burst("twirl_0%d" % self.rng.randint(1, 3), pos, 10, 140, 0.9, 20, 50, VIO)
            self.wash(VIO, 0.25)
            self.kick(3.0)
        elif n == "rift_scatter":
            src = ev.get("src")
            self.burst("magic_0%d" % self.rng.randint(1, 5), pos, 6, 80, 0.6, 14, 30, VIO)
            if src is not None:
                for k in range(1, 6):                                # a streak of light from the seam to where the paper fell
                    self.add("trace_0%d" % self.rng.randint(1, 7), src + (pos - src) * (k / 6), (0, 0), 0.35 + 0.05 * k, 22, 34, VIO)
        elif n in ("rift_shift_warning",):
            self.ring(pos, 40, 8, 0.6, (255, 200, 90))
        elif n == "rift_shift":
            self.burst("magic_0%d" % self.rng.randint(1, 5), pos, 8, 120, 0.5, 14, 30, VIO)
        elif n == "paper_destroyed":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 10, 160, 0.5, 14, 28, (255, 150, 70))
            self.add("flare_01", pos, (0, 0), 0.3, 40, 120, (255, 170, 80))
        elif n == "rift_selected":
            self.ring(pos, 10, 360, 1.1, RED)
            self.wash(VIO, 0.5)
            self.stop(0.1)
            self.kick(8.0)
        elif n == "rift_closed":
            self.ring(pos, 100, 6, 0.7, VIO)
        elif n == "machine_glitch":
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 16, 220, 0.6, 16, 34, (255, 170, 70))
            self.ring(pos, 8, 110, 0.5, (255, 150, 60))
            self.kick(2.5)
        elif n == "machine_used":
            self.ring(pos, 8, 70, 0.4, (255, 230, 160))
        elif n == "breaker_surge":
            self.ring(pos, 10, 300, 0.6, (255, 90, 90))
            self.wash((255, 255, 255), 0.5)
            self.kick(4.0)
        elif n == "overlord_awake":
            self.ring(pos, 10, 420, 1.2, RED)
            self.wash(RED, 0.6)
            self.kick(8.0)
        elif n == "conduit_overload":
            self.ring(pos, 10, 200, 0.6, (255, 255, 255))
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 18, 300, 0.6, 18, 40, (255, 240, 200))
            self.add("flare_01", pos, (0, 0), 0.4, 80, 280, (255, 255, 255))
            self.wash((255, 255, 255), 0.45)
            self.stop(0.1)
            self.kick(7.0)
        elif n == "surprised":
            self.ring(pos, 20, 220, 0.5, (255, 255, 255))
            self.burst("star_0%d" % self.rng.randint(1, 9), pos, 12, 240, 0.6, 16, 34, (255, 255, 180))
            self.stop(0.08)
            self.kick(4.0)
        elif n == "doctrine_learned":
            self.ring(pos, 160, 10, 0.7, RED)
            self.kick(2.0)
        elif n == "foresight":
            self.ring(pos, 80, 12, 0.9, (255, 90, 90))
        elif n == "overlord_phase":
            for i in range(3):
                self.ring(pos, 10, 380 + 80 * i, 1.0 + 0.2 * i, RED)
            self.wash(RED, 0.7)
            self.stop(0.12)
            self.kick(8.0)
        elif n == "predecessors":
            self.wash(VIO, 0.4)
        elif n == "overlord_destroyed":
            for i in range(5):
                self.ring(pos, 10, 300 + 120 * i, 1.0 + 0.3 * i, (255, 255, 255) if i % 2 else RED)
            self.burst("flare_01", pos, 12, 260, 1.4, 60, 200, (255, 230, 200))
            self.burst("spark_0%d" % self.rng.randint(1, 7), pos, 40, 420, 1.2, 20, 50, (255, 230, 160))
            self.wash((255, 255, 255), 0.9)
            self.stop(0.12)
            self.kick(8.0)
        elif n == "teleport":
            self.ring(pos, 10, 140, 0.5, VIO)
            self.wash(VIO, 0.3)
        elif n == "isolate_warning":
            self.ring(pos, 90, 10, 0.7, VIO)

    def update(self, dt):
        self.shake = max(0.0, self.shake - 14 * dt)
        self.flash = max(0.0, self.flash - dt)
        self.tint = max(0.0, self.tint - dt * 1.3)
        out = []
        for p in self.parts:
            p.life -= dt
            if p.life > 0:
                p.pos += p.vel * dt
                p.vel *= max(0.0, 1 - 3 * dt)
                out.append(p)
        self.parts = out
        for r in self.rings:
            r[3] -= dt
        self.rings = [r for r in self.rings if r[3] > 0]

    def shake_offset(self, t):
        if self.shake <= 0:
            return (0, 0)
        return (math.sin(t * 91) * self.shake, math.cos(t * 77) * self.shake)

    def draw(self, surf, cam):
        A = get_assets()
        ox, oy = cam.offset()
        for p in self.parts:
            k = 1 - p.life / p.total
            size = max(2, int(p.s0 + (p.s1 - p.s0) * k))
            size = size // 4 * 4 or 4
            img = A.particle(p.name, size, p.color)
            a = int(255 * (1 - k))
            if a < 255:
                img = img.copy()
                img.fill((a, a, a, 255), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(img, (p.pos.x + ox - size / 2, p.pos.y + oy - size / 2), special_flags=pygame.BLEND_RGB_ADD)
        for pos, r0, r1, life, total, col in self.rings:
            k = 1 - life / total
            r = int(r0 + (r1 - r0) * k)
            a = int(220 * (1 - k))
            s = pygame.Surface((r * 2 + 6, r * 2 + 6), pygame.SRCALPHA)
            pygame.draw.circle(s, col + (a,), (r + 3, r + 3), r, 3)
            surf.blit(s, (pos.x + ox - r - 3, pos.y + oy - r - 3))

    def draw_screen(self, surf):
        """Full-screen cues: red edge pulse when a crew member is hurt, and a colour wash for the big beats."""
        from src.settings import LOGICAL_H, LOGICAL_W
        if self.flash > 0:
            a = int(120 * min(1.0, self.flash / 0.22))
            w = 46
            for i in range(4):                                   # an edge frame that thins inward
                band = pygame.Surface((LOGICAL_W, w), pygame.SRCALPHA) if i < 2 else pygame.Surface((w, LOGICAL_H), pygame.SRCALPHA)
                band.fill(self.flash_color + (a // 2,))
                pos = [(0, 0), (0, LOGICAL_H - w), (0, 0), (LOGICAL_W - w, 0)][i]
                surf.blit(band, pos)
        if self.tint > 0.02:
            wash = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
            wash.fill(self.tint_color + (int(150 * min(1.0, self.tint)),))
            surf.blit(wash, (0, 0))
