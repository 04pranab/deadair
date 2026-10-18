"""Top-down map renderer with 2.5D animated characters. Reads simulation state only."""
import math
import random

import pygame

from src.config import BAL
from src.settings import C_AMBER, C_CYAN, C_GREEN, C_RED, LOGICAL_H, LOGICAL_W, PLAYER_COLORS, TILE
from src.ui import anim, draw
from src.ui import maprender, story_fx
from src.ui.view import Camera, circle_pts
from src.utils.assets import get_assets
from src.world.level import MAP_H, MAP_W

V = pygame.Vector2
CRATE_TILE = {73: 73, 85: 85, 72: 72, 84: 84}
DARK_TINT = None


class WorldView:
    def __init__(self, sim, debug=False):
        self.sim = sim
        self.A = get_assets()
        self.cam = Camera()
        self.t = 0.0
        self.debug = debug
        self.dark = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        self.darkness = 150 if sim.modifier != "blackout" else 215
        self.light_scale = 1.0 if sim.modifier != "blackout" else 0.65
        self.labels = []
        self.map = maprender.bake(sim.level)
        self.cams, self.residues = story_fx.build_dressing(sim)
        self.fx_events = []           # visual-only events raised by the renderer (e.g. a residue dissolving)
        self.jitter = {}
        self.snap_camera()

    # ------------------------------------------------------------------ camera
    def _focus(self):
        ps = [p for p in self.sim.players if p.alive] or list(self.sim.players)
        c = V(0, 0)
        for p in ps:
            c += p.pos
        c = c / len(ps)
        av = self.sim.overlord.avatar
        if av is not None and not av.dead and self.sim.overlord.stage == 2:
            pull = (av.pos - c) * 0.4                 # in the finale the camera leans toward what is hunting you...
            if pull.length() > 220:
                pull.scale_to_length(220)             # ...but never so far that a living player leaves the screen
            c = c + pull
        return c

    def snap_camera(self):
        self.cam.focus_on(self._focus())

    def update(self, dt):
        self.t += dt
        self.cam.focus_on(self._focus(), smooth=6, dt=dt)

    def player_color(self, p):
        return PLAYER_COLORS[p.idx % len(PLAYER_COLORS)]

    def S(self, wpos, z=0.0):
        return self.cam.to_screen(wpos.x, wpos.y, z)

    def on_screen(self, s, m=100):
        return -m < s[0] < LOGICAL_W + m and -m < s[1] < LOGICAL_H + m + 60

    # ------------------------------------------------------------------ drawing primitives
    def tile(self, surf, idx, wpos, tint=None, flip=False, dy=0.0, size=None, alpha=255):
        img = self.A.tile(idx, size, tint, flip)
        s = self.S(wpos)
        if alpha < 255:
            img = img.copy()
            img.set_alpha(alpha)
        surf.blit(img, (s[0] - img.get_width() / 2, s[1] - img.get_height() / 2 - dy))

    def ground_ellipse(self, surf, wpos, r, color, alpha=90, width=0, fill=True):
        c = self.S(wpos)
        r = int(r)
        if r < 2 or r > 1500:
            return
        s = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
        if fill:
            pygame.draw.circle(s, color + (alpha,), (r + 4, r + 4), r)
        pygame.draw.circle(s, color + (min(255, alpha + 120),), (r + 4, r + 4), r, width or 2)
        surf.blit(s, (c[0] - r - 4, c[1] - r - 4))

    def ground_poly(self, surf, world_pts, color, alpha, outline=3):
        pts = [self.cam.to_screen(x, y) for x, y in world_pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0 = min(xs) - 4, min(ys) - 4
        w, h = int(max(xs) - x0) + 8, int(max(ys) - y0) + 8
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        loc = [(x - x0, y - y0) for x, y in pts]
        pygame.draw.polygon(s, color + (alpha,), loc)
        if outline:
            pygame.draw.polygon(s, color + (255,), loc, outline)
        surf.blit(s, (x0, y0))

    def shadow(self, surf, wpos, r=12, alpha=90):
        c = self.S(wpos)
        s = pygame.Surface((int(r * 2.6), int(r * 1.3)), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0, 0, 0, alpha), s.get_rect())
        surf.blit(s, (c[0] - s.get_width() / 2, c[1] - s.get_height() / 2 + 2))

    # ------------------------------------------------------------------ main draw
    def draw(self, surf, fx):
        sim = self.sim
        self.labels = []
        self.cam.shake = fx.shake_offset(self.t)
        ox, oy = self.cam.offset()
        surf.fill((8, 8, 14))
        surf.blit(self.map, (ox, oy))

        self._ground(surf)
        story_fx.draw_cameras(self, surf)
        story_fx.draw_residues(self, surf)
        story_fx.draw_overlord_ground(self, surf)
        self.jitter = story_fx.host_jitter(self)

        items = []
        for d in sim.doors:
            items.append((d.center.y + 24, 1, "door", d))
        for c in sim.covers:
            items.append((c.pos.y, 1, "cover", c))
        for c in sim.crates:
            items.append((c.pos.y, 1, "crate", c))
        for r in sim.relays:
            items.append((r.pos.y, 1, "relay", r))
        for lg in sim.logs:
            items.append((lg.pos.y, 1, "log", lg))
        for f in sim.faults:
            items.append((f.pos.y, 1, "fault", f))
        for a in sim.anchors:
            items.append((a.pos.y, 1, "anchor", a))
        for b in sim.barricades:
            items.append((b.pos.y, 1, "barricade", b))
        for pk in sim.pickups:
            items.append((pk.pos.y, 1, "pickup", pk))
        for e in sim.echoes:
            items.append((e.pos.y, 2, "echo", e))
        for e in sim.enemies:
            items.append((e.pos.y, 2, "enemy", e))
        for p in sim.players:
            items.append((p.pos.y, 2, "player", p))
        for b in sim.bullets:
            items.append((b.pos.y, 3, "bullet", b))
        for c in sim.overlord.conduits:
            items.append((c.pos.y, 1, "conduit", c))
        for m in sim.machines:
            items.append((m.pos.y, 1, "machine", m))
        for pp in sim.rift.papers:
            items.append((pp.pos.y + 30, 2, "paper", pp))
        items.append((sim.extract_pos.y - 60, 1, "gate", None))
        if not sim.core_collected:
            items.append((sim.core_pos.y, 1, "core", None))
        items.sort(key=lambda i: (i[0], i[1]))
        draw_fn = {"door": self._d_door, "cover": self._d_cover, "crate": self._d_crate,
                   "relay": self._d_relay, "log": self._d_log, "fault": self._d_fault, "anchor": self._d_anchor, "barricade": self._d_barricade,
                   "pickup": self._d_pickup, "echo": self._d_echo, "enemy": self._d_enemy, "player": self._d_player,
                   "bullet": self._d_bullet, "gate": self._d_gate, "core": self._d_core,
                   "conduit": lambda sf, c: story_fx.draw_conduit(self, sf, c),
                   "machine": lambda sf, m: story_fx.draw_machine(self, sf, m),
                   "paper": lambda sf, pp: story_fx.draw_paper(self, sf, pp)}
        for _, _, kind, obj in items:
            draw_fn[kind](surf, obj)

        story_fx.draw_rift(self, surf)
        self._lighting(surf)
        self._motes(surf)
        story_fx.draw_mark(self, surf)
        self._telegraphs(surf)
        fx.draw(surf, self.cam)
        for lab in self.labels:
            lab(surf)
        self._offscreen_arrows(surf)
        if self.debug:
            self._debug(surf)

    # ------------------------------------------------------------------ ground layer
    def _ground(self, surf):
        sim = self.sim
        for h in sim.floor_hazards:
            r = h.rect
            if h.state == "idle":
                col, a = C_AMBER, 40
            elif h.state == "warning":
                col, a = C_AMBER, 70 + int(90 * (0.5 + 0.5 * math.sin(self.t * 18)))
            else:
                col, a = (110, 190, 255), 140 + int(70 * math.sin(self.t * 40))
            self.ground_poly(surf, [(r.left, r.top), (r.right, r.top), (r.right, r.bottom), (r.left, r.bottom)], col, a, 3)
        for a in sim.anchors:
            col = C_CYAN if a.online else (110, 110, 125)
            pulse = 0.5 + 0.5 * math.sin(a.pulse * 3)
            self.ground_ellipse(surf, a.pos, BAL.ritual.radius, col, int(26 + 30 * pulse), 3)
        p = sim.extract_pos
        col = C_GREEN if sim.objective_done else C_RED
        self.ground_ellipse(surf, p, BAL.mission.extract_radius, col, 40, 3)
        if sim.extract_progress > 0:
            self.ground_ellipse(surf, p, BAL.mission.extract_radius * sim.extract_progress, col, 90, 2)

    # ------------------------------------------------------------------ standing things
    def _d_door(self, surf, d):
        if d.broken:
            return
        s0 = self.S(d.center)
        if not self.on_screen(s0, 140):
            return
        horiz = d.spec.horizontal_wall
        opened = d.kind != "barrier" and d.open > 0.5 and d.lock_t <= 0
        flicker = d.warn_t > 0 and int(self.t * 14) % 2 == 0
        tint = (255, 120, 120) if (d.lock_t > 0 or flicker) else None
        if d.crew_lock:
            tint = (120, 200, 255)
        if d.sealed:
            tint = (150, 40, 50)
        for (cx, cy) in d.cells:
            wp = V((cx + 0.5) * TILE, (cy + 0.5) * TILE)
            if d.kind == "barrier":
                self.tile(surf, 118, wp, tint)
            elif opened:
                self.tile(surf, 117, wp, (120, 120, 130), alpha=120)
            else:
                self.tile(surf, 46 if horiz else 44, wp, tint)
        if d.kind == "barrier" and d.hp < 160:
            frac = max(0.0, d.hp / 160)
            self.labels.append(lambda s, c=s0, f=frac: (pygame.draw.rect(s, (30, 30, 40), (c[0] - 24, c[1] - 40, 48, 5)),
                                                        pygame.draw.rect(s, C_AMBER, (c[0] - 24, c[1] - 40, int(48 * f), 5))))
        if story_fx.draw_door_state(self, surf, d, s0):
            pass
        elif d.lock_t > 0:
            self.labels.append(lambda s, c=s0: draw.text(s, "LOCKED", (c[0], c[1] - 34), 18, C_RED, "center"))

    def on_screen(self, s, m=100):
        return -m < s[0] < LOGICAL_W + m and -m < s[1] < LOGICAL_H + m

    def _d_cover(self, surf, c):
        if self.on_screen(self.S(c.pos)):
            self.shadow(surf, c.pos + V(0, 12), 16, 70)
            self.tile(surf, c.tile, c.pos)

    def _d_crate(self, surf, c):
        if self.on_screen(self.S(c.pos)):
            self.shadow(surf, c.pos + V(0, 12), 18, 70)
            self.tile(surf, c.tile, c.pos, (120, 120, 130) if c.opened else None)

    def _d_relay(self, surf, r):
        s = self.S(r.pos)
        if not self.on_screen(s):
            return
        self.tile(surf, 99 if r.online else 75, r.pos, size=TILE + 8)
        self.labels.append(lambda sf, r=r, s=s: self._relay_label(sf, r, s))

    def _relay_label(self, surf, r, s):
        if not r.online and r.progress > 0:
            pygame.draw.rect(surf, (30, 30, 40), (s[0] - 24, s[1] - 40, 48, 6))
            pygame.draw.rect(surf, C_GREEN, (s[0] - 24, s[1] - 40, int(48 * r.progress), 6))
        draw.text(surf, f"RELAY {r.id + 1}", (s[0], s[1] + 30), 16, C_GREEN if r.online else C_RED, "center")

    def _d_fault(self, surf, f):
        s = self.S(f.pos)
        if not self.on_screen(s) or f.repaired:
            return
        self.tile(surf, 129 if int(self.t * 3) % 2 == 0 else 91, f.pos, size=TILE)
        self.labels.append(lambda sf, f=f, s=s: (draw.text(sf, "POWER FAULT", (s[0], s[1] + 30), 16, C_AMBER, "center"),
                                                 pygame.draw.rect(sf, (30, 30, 40), (s[0] - 24, s[1] - 38, 48, 6)),
                                                 pygame.draw.rect(sf, C_AMBER, (s[0] - 24, s[1] - 38, int(48 * f.progress), 6))))

    def _d_log(self, surf, lg):
        if self.on_screen(self.S(lg.pos)):
            self.tile(surf, 112, lg.pos, (150, 150, 165) if lg.read else None)

    def _d_anchor(self, surf, a):
        s = self.S(a.pos)
        if not self.on_screen(s, 160):
            return
        self.tile(surf, 130, a.pos, None if a.online else (110, 110, 125), size=TILE + 16, dy=2 + 2 * math.sin(a.pulse * 2))
        self.labels.append(lambda sf, a=a, s=s: draw.text(sf, f"ANCHOR {a.id + 1}" + ("" if a.online else " (OFFLINE)"), (s[0], s[1] + 34),
                                                          18, C_CYAN if a.online else (140, 140, 150), "center"))

    def _d_barricade(self, surf, b):
        self.tile(surf, 124, b.pos, (150, 230, 255), size=TILE)
        s = self.S(b.pos)
        frac = max(0.0, b.hp / BAL.abilities.barricade.hp)
        self.labels.append(lambda sf, s=s, f=frac: (pygame.draw.rect(sf, (30, 30, 40), (s[0] - 18, s[1] - 34, 36, 4)),
                                                    pygame.draw.rect(sf, C_CYAN, (s[0] - 18, s[1] - 34, int(36 * f), 4))))

    def _d_pickup(self, surf, pk):
        if not self.on_screen(self.S(pk.pos)):
            return
        bob = math.sin(self.t * 5 + pk.pos.x) * 3
        self.shadow(surf, pk.pos + V(0, 8), 8, 60)
        if pk.kind == "salvage":
            self.tile(surf, 114, pk.pos, size=26, dy=8 + bob)
        else:
            self.tile(surf, 130, pk.pos, size=32, dy=10 + bob)

    def _d_core(self, surf, _):
        pos = self.sim.core_pos
        s = self.S(pos)
        if self.on_screen(s, 120):
            sim = self.sim
            if sim.exposed:
                pulse = 0.5 + 0.5 * math.sin(self.t * 4)
                g = self.A.glow("circle_b", int(150 + 40 * pulse), (170, 20, 50), 1.0)
                surf.blit(g, (s[0] - g.get_width() / 2, s[1] - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
                self.tile(surf, 123, pos, (255, 90, 110), size=TILE + 18, dy=math.sin(self.t * 3) * 2)
                surf.blit(self.A.icon("video", 28, (255, 80, 100)), (s[0] - 14, s[1] - 58))
                ov = sim.overlord
                if ov.sever > 0:
                    self.labels.append(lambda sf, s=s, v=ov.sever: (pygame.draw.rect(sf, (30, 30, 40), (s[0] - 30, s[1] - 70, 60, 7)),
                                                                    pygame.draw.rect(sf, (255, 80, 100), (s[0] - 30, s[1] - 70, int(60 * v), 7))))
            else:
                self.tile(surf, 123, pos, size=TILE + 8, dy=math.sin(self.t * 3) * 2)

    def _d_gate(self, surf, _):
        sim = self.sim
        pos = sim.extract_pos
        if not self.on_screen(self.S(pos), 200):
            return
        img = self.A.kit_raw("gate-door" if sim.objective_done else "gate-lasers", "modular", 150)
        s = self.S(pos)
        surf.blit(img, (s[0] - 75, s[1] - 120))
        col = C_GREEN if sim.objective_done else C_RED
        self.labels.append(lambda sf, s=s, col=col, ok=sim.objective_done: draw.text(
            sf, "EXTRACTION" if ok else "EXTRACTION SEALED", (s[0], s[1] + 44), 20, col, "center"))

    def _d_bullet(self, surf, b):
        s = self.S(b.pos, 22)
        if not self.on_screen(s):
            return
        col = (255, 235, 160) if b.friendly else (255, 90, 80)
        tail = self.S(b.pos - b.vel.normalize() * 20, 22)
        pygame.draw.line(surf, col, tail, s, 3)
        pygame.draw.circle(surf, (255, 255, 255), (int(s[0]), int(s[1])), 3)
        self.shadow(surf, b.pos, 3, 60)

    def _d_echo(self, surf, e):
        s = self.S(e.pos)
        if e.state == "done" or not self.on_screen(s):
            return
        p = self.sim.players[e.player_idx]
        float_z = 14 + math.sin(e.pulse * 3) * 4
        self.shadow(surf, e.pos, 10, 50)
        look = anim.Look("fall" if e.state != "carried" else "hold2", False, float_z, tint=(150, 220, 255), add=(0, 50, 90), alpha=175)
        anim.draw_look(surf, s, p.sprite, look, 0.9)
        pg = self.A.particle("circle_02", 64, C_CYAN)
        pg.set_alpha(150 + int(70 * math.sin(e.pulse * 4)))
        surf.blit(pg, (s[0] - 32, s[1] - 62), special_flags=pygame.BLEND_RGB_ADD)
        self.labels.append(lambda sf, e=e, s=s: self._echo_label(sf, e, s))

    def _echo_label(self, surf, e, s):
        if e.state in ("placed", "ritual"):
            r = 30
            sc = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
            pygame.draw.arc(sc, (170, 235, 255, 255), sc.get_rect().inflate(-8, -8), math.pi / 2,
                            math.pi / 2 + math.tau * max(0.02, e.progress), 6)
            surf.blit(sc, (s[0] - r - 4, s[1] - 70 - r))
        draw.text(surf, f"ECHO P{e.player_idx + 1}" + ("" if e.paid else f" ({e.cost})"), (s[0], s[1] - 84), 16, C_CYAN, "center")

    def _d_enemy(self, surf, e):
        s = self.S(e.pos)
        if not self.on_screen(s):
            return
        self.shadow(surf, e.pos, e.radius + 2, 100)
        spec = e.spec
        look = anim.enemy_look(e, self.t, self.sim.time)
        if e.kind == "overlord":
            story_fx.draw_avatar_overlay(self, surf, e)
        elif getattr(e, "hunt", False):
            self.ground_ellipse(surf, e.pos, e.radius + 14, C_RED, 28, 3)
        rect = anim.draw_look(surf, s, spec.sprite, look, spec.scale)
        if e.kind == "overlord":
            return
        if e.hp < e.max_hp or e.state == "windup":
            self.labels.append(lambda sf, e=e, r=rect: self._enemy_label(sf, e, r))

    def _enemy_label(self, surf, e, r):
        w = int(30 * max(0.8, e.spec.scale))
        x, y = int(r.centerx - w / 2), int(r.top - 8)
        if e.hp < e.max_hp:
            pygame.draw.rect(surf, (30, 20, 25), (x, y, w, 4))
            pygame.draw.rect(surf, C_RED, (x, y, int(w * e.hp / e.max_hp), 4))
        if e.state == "windup":
            draw.text(surf, "!", (r.centerx, y - 14), 30, C_RED, "center")

    def _d_player(self, surf, p):
        s = self.S(p.pos)
        if not self.on_screen(s):
            return
        if p.state == "host":
            story_fx.draw_host(self, surf, p)
            return
        jit = self.jitter.get(p.idx, 0.0)
        if jit:
            s = (s[0] + math.sin(self.t * 70) * jit, s[1] + math.cos(self.t * 83) * jit * 0.5)
        col = PLAYER_COLORS[p.idx % len(PLAYER_COLORS)]
        self.shadow(surf, p.pos, p.radius + 2, 100 if p.alive else 40)
        if p.alive:
            pygame.draw.ellipse(surf, col, pygame.Rect(s[0] - 18, s[1] - 7, 36, 14), 2)
        look = anim.player_look(p, self.t, self.sim.time)
        rect = anim.draw_look(surf, s, p.sprite, look)
        self.labels.append(lambda sf, p=p, r=rect, s=s, col=col: self._player_label(sf, p, r, s, col))
        if p.alive:
            tip = self.S(p.pos + p.facing * 42)
            pygame.draw.circle(surf, col, (int(tip[0]), int(tip[1])), 4)
            pygame.draw.circle(surf, (255, 255, 255), (int(tip[0]), int(tip[1])), 4, 1)

    def _player_label(self, surf, p, rect, s, col):
        draw.text(surf, f"P{p.idx + 1}", (rect.centerx, rect.top - 10), 18, col, "center")
        if p.interact_target:
            oy = 14 + 20 * p.idx
            draw.text(surf, f"P{p.idx + 1} " + p.interact_target.replace("INTERACT", "E"), (s[0], s[1] + oy), 17, col, "center", maxw=320)
            if p.interact_progress > 0:
                pygame.draw.rect(surf, (30, 30, 40), (s[0] - 24, s[1] + oy + 12, 48, 5))
                pygame.draw.rect(surf, C_CYAN, (s[0] - 24, s[1] + oy + 12, int(48 * min(1, p.interact_progress)), 5))

    # ------------------------------------------------------------------ lighting
    def blackout_factor(self):
        d = self.sim.director
        if d is None or d.blackout <= 0:
            return 0.0
        elapsed = d.blackout_total - d.blackout
        return max(0.0, min(1.0, elapsed / 2.0, d.blackout / 2.0))

    def _lights(self):
        sim = self.sim
        k = self.light_scale
        bf = self.blackout_factor()
        L = []
        for p in sim.players:
            if p.state == "host":
                L.append((p.pos, 150, (255, 40, 60), 1.0))
                continue
            L.append((p.pos, int(330 * k * (1 - 0.72 * bf)) if p.alive else int(90 * k), (255, 255, 255) if p.alive else C_CYAN, 1.0 if p.alive else 0.5))
        for c in sim.overlord.conduits:
            L.append((c.pos, 140, C_GREEN if c.ready else (70, 70, 90), 0.8))
        for e in sim.enemies:
            if e.kind == "overlord":
                L.append((e.pos, 260, (255, 50, 80), 0.9))
            elif getattr(e, "hunt", False):
                L.append((e.pos, 120, (255, 60, 60), 0.7))
        for a in sim.anchors:
            L.append((a.pos, 170, C_CYAN if a.online else (90, 90, 110), 0.8))
        for r in sim.relays:
            L.append((r.pos, 100, C_GREEN if r.online else C_RED, 0.8))
        for lg in sim.logs:
            L.append((lg.pos, 80, C_AMBER, 0.6))
        L.append((sim.extract_pos, 170, C_GREEN if sim.objective_done else C_RED, 0.8))
        for h in sim.floor_hazards:
            if h.state != "idle":
                L.append((V(h.rect.center), 130, (120, 190, 255) if h.state == "active" else C_AMBER, 0.9))
        for e in sim.echoes:
            L.append((e.pos, 90, C_CYAN, 0.6))
        for t in sim.telegraphs:
            L.append((t.pos, int(t.radius * 1.8) + 50, C_RED, 0.8))
        for b in sim.bullets:
            L.append((b.pos, 60, (255, 235, 160) if b.friendly else (255, 90, 80), 0.6))
        return L

    _soft = {}

    def _soft_light(self, w):
        """A radial falloff with no visible rim (the supplied masks end in a hard edge). Built once per size from concentric rings."""
        img = self._soft.get(w)
        if img is None:
            img = pygame.Surface((w, w), pygame.SRCALPHA)
            c, R = w / 2, w / 2
            steps = 40
            for i in range(steps):
                k = i / (steps - 1)                       # 0 at the rim, 1 at the centre
                a = int(255 * (k * k * (3 - 2 * k)))      # smoothstep: gentle at both ends
                pygame.draw.circle(img, (255, 255, 255, a), (c, c), R * (1 - k) + 1)
            self._soft[w] = img
        return img

    def dread(self):
        """0..1: how wrong the station feels. Fracture, MERIDIAN's escalation, a loose Host and the Avatar all push it up.
        It only changes the grade (colour of the dark, drifting embers, light breathing); it never changes a rule."""
        sim = self.sim
        d = sim.director
        k = 0.06 * min(10, getattr(sim, "fracture", 0))
        if d is not None:
            k += 0.25 * max(0.0, min(1.0, d.esc - 1.0))
        if sim.host is not None:
            k += 0.25
        if sim.overlord.stage == 2:
            k += 0.3
        return max(0.0, min(1.0, k))

    def _motes(self, surf):
        """Drifting dust that turns to rising embers as dread grows. World-anchored, so it parallaxes with the camera."""
        dread = self.dread()
        n = int(26 + 34 * dread)
        ox, oy = self.cam.offset()
        layer = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        col = (int(150 + 105 * dread), int(170 - 90 * dread), int(210 - 150 * dread))
        for i in range(n):
            h1 = (i * 2654435761) & 0xFFFFFF
            h2 = (i * 40503 + 977) & 0xFFFF
            depth = 0.55 + 0.45 * ((h1 >> 3) % 100) / 100.0
            speed_y = -(6 + 22 * dread) * depth
            x = ((h1 % 1600) + math.sin(self.t * 0.4 + i) * 18 + ox * depth) % (LOGICAL_W + 40) - 20
            y = (((h2 % 900) + self.t * speed_y + oy * depth)) % (LOGICAL_H + 40) - 20
            a = int((40 + 70 * ((h1 >> 7) % 100) / 100.0) * (0.6 + 0.4 * math.sin(self.t * 1.7 + i * 1.3)))
            r = 1 + (i % 3 == 0) + (dread > 0.5 and i % 5 == 0)
            pygame.draw.circle(layer, col + (max(0, a),), (int(x), int(y)), r)
        surf.blit(layer, (0, 0))

    def _lighting(self, surf):
        A = self.A
        d = self.dark
        bf = self.blackout_factor()
        fl = story_fx.rift_flicker(self)
        dr = self.dread()
        d.fill((int(5 + 20 * dr), int(7 - 3 * dr), int(16 - 6 * dr), int(min(252, (self.darkness + (252 - self.darkness) * bf * 0.93) + 90 * max(0.0, fl)))))
        if self.sim.exposed:
            d.fill((18, 0, 4, 0), special_flags=pygame.BLEND_RGBA_ADD)
        lights = self._lights()
        prepared = []
        for pos, r, col, k in lights:
            s = self.S(pos)
            r = r * (1 + 0.05 * dr * math.sin(self.t * 6 + pos.x * 0.01))        # the light breathes when the station is wrong
            w = max(16, int(1.8 * r / 8) * 8)
            h = w
            if -w < s[0] < LOGICAL_W + w and -h < s[1] < LOGICAL_H + h:
                prepared.append((s, w, h, col, k))
        for s, w, h, col, k in prepared:
            img = self._soft_light(w)
            d.blit(img, (s[0] - w / 2, s[1] - h / 2), special_flags=pygame.BLEND_RGBA_SUB)
        surf.blit(d, (0, 0))
        for s, w, h, col, k in prepared:
            if col == (255, 255, 255):
                continue
            g = A.glow("circle_b", w, tuple(int(c * k * 0.30) // 8 * 8 for c in col), 1.0)
            surf.blit(g, (s[0] - w / 2, s[1] - h / 2), special_flags=pygame.BLEND_RGB_ADD)

    # ------------------------------------------------------------------ telegraphs
    def _telegraphs(self, surf):
        sim = self.sim
        for t in sim.telegraphs:
            k = 1 - t.t / t.total
            s = self.S(t.pos)
            if story_fx.draw_telegraph(self, surf, t):
                continue
            if t.kind == "surge":
                self.ground_ellipse(surf, t.pos, t.radius, C_AMBER, int(40 + 70 * k), 3)
                self.ground_ellipse(surf, t.pos, max(4, t.radius * k), C_RED, 30, 3)
                surf.blit(self.A.icon("warning", 28, C_AMBER), (s[0] - 14, s[1] - 40))
            else:
                self.ground_ellipse(surf, t.pos, 44 + 8 * math.sin(self.t * 12), C_RED, 40, 3)
                surf.blit(self.A.icon("exclamation", 30, C_RED), (s[0] - 15, s[1] - 44))
                draw.text(surf, f"{t.t:0.1f}", (s[0], s[1] + 18), 18, C_RED, "center")
        for e in sim.enemies:
            if e.dead or e.state != "windup":
                continue
            k = 1 - e.timer / max(0.01, e.spec.windup)
            beh = e.spec.behavior
            if beh == "ranged":
                n = e.spec.get("burst", 1)
                sl = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
                for i in range(n):
                    off = (i - (n - 1) / 2) * e.spec.get("spread", 0.0)
                    p1, p2 = self.S(e.pos), self.S(e.pos + e.aim_dir.rotate_rad(off) * 420)
                    pygame.draw.line(sl, (255, 60, 60, int(90 + 140 * k)), p1, p2, 3)
                surf.blit(sl, (0, 0))
            elif beh == "melee":
                reach = e.spec.melee_range + 12
                ang = math.atan2(e.aim_dir.y, e.aim_dir.x)
                pts = [(e.pos.x, e.pos.y)] + [(e.pos.x + math.cos(ang + o) * reach * 1.4, e.pos.y + math.sin(ang + o) * reach * 1.4)
                                              for o in (-0.7, -0.35, 0, 0.35, 0.7)]
                self.ground_poly(surf, pts, C_RED, int(60 + 100 * k), 2)
            else:
                r = e.spec.slam_radius
                self.ground_ellipse(surf, e.pos, r, C_RED, int(40 + 90 * k), 3)
                self.ground_ellipse(surf, e.pos, max(4, r * k), (255, 200, 120), 20, 2)

    def _offscreen_arrows(self, surf):
        for p in self.sim.players:
            s = self.S(p.pos)
            if 0 <= s[0] <= LOGICAL_W and 0 <= s[1] <= LOGICAL_H:
                continue
            col = PLAYER_COLORS[p.idx % len(PLAYER_COLORS)]
            c = V(min(max(s[0], 28), LOGICAL_W - 28), min(max(s[1] + 38 * p.idx, 120), LOGICAL_H - 28))   # idx offset: arrows never stack
            pygame.draw.circle(surf, (10, 14, 26), (int(c.x), int(c.y)), 16)
            pygame.draw.circle(surf, col, (int(c.x), int(c.y)), 16, 3)
            draw.text(surf, f"P{p.idx + 1}", c, 18, col, "center")

    def _debug(self, surf):
        for e in self.sim.enemies:
            pygame.draw.polygon(surf, (255, 0, 255), circle_pts(self.S(e.pos), e.radius, 20), 1)
        for p in self.sim.players:
            pygame.draw.polygon(surf, (0, 255, 255), circle_pts(self.S(p.pos), p.radius, 20), 1)
        for r in self.sim.solids.dyn:
            pts = [self.cam.to_screen(x, y) for x, y in ((r.left, r.top), (r.right, r.top), (r.right, r.bottom), (r.left, r.bottom))]
            pygame.draw.polygon(surf, (255, 255, 0), pts, 1)
