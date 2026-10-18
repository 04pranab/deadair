"""Heads-up display: player panels, objective, Fracture, salvage, minimap, message feed, log reader."""
import math

import pygame

from src.config import BAL
from src.systems import overlord as O
from src.settings import C_AMBER, C_CYAN, C_DIM, C_GREEN, C_RED, C_TEXT, LOGICAL_H, LOGICAL_W, PLAYER_COLORS, TILE
from src.ui import draw
from src.utils.assets import get_assets
from src.world.level import FLOOR, MAP_H, MAP_W

V = pygame.Vector2
ABILITY_ICON = {"barricade": "wrench", "charge": "forward", "stim": "plus"}
ABILITY_NAME = {"barricade": "Barricade", "charge": "Charge", "stim": "Stim Pulse"}


class Hud:
    def __init__(self, sim):
        self.sim = sim
        self.A = get_assets()
        self.feed = []          # [speaker, text, ttl]
        self.mini = self._bake_minimap()
        self.explored = set()
        self.log_open = None
        self.banner = None      # (text, ttl, color)

    def say(self, who, text, ttl=5.0):
        self.feed.append([who, text, ttl])
        self.feed = self.feed[-4:]

    def show_banner(self, text, color=C_AMBER, ttl=2.5):
        self.banner = [text, ttl, color]

    def update(self, dt):
        for f in self.feed:
            f[2] -= dt
        self.feed = [f for f in self.feed if f[2] > 0]
        if self.banner:
            self.banner[1] -= dt
            if self.banner[1] <= 0:
                self.banner = None

    def _bake_minimap(self):
        s = 3
        surf = pygame.Surface((MAP_W * s, MAP_H * s), pygame.SRCALPHA)
        for y in range(MAP_H):
            for x in range(MAP_W):
                if self.sim.level.grid[y][x] == FLOOR:
                    surf.fill((60, 90, 130, 200), (x * s, y * s, s, s))
        return surf

    def draw(self, surf, t, cam=None):
        sim = self.sim
        self._players(surf)
        self._top(surf, t)
        self._minimap(surf)
        if cam is not None:
            self._guides(surf, t, cam)
        self._coach(surf, t)
        self._feed(surf)
        if self.banner:
            text, ttl, col = self.banner
            size = 44
            while size > 22 and draw.font(size).size(text)[0] > 600:      # fits between the left panels and the minimap
                size -= 2
            bw = min(620, draw.font(size).size(text)[0] + 40)
            back = pygame.Surface((bw, size + 16), pygame.SRCALPHA)
            back.fill((8, 6, 14, int(150 * min(1, ttl / 0.6))))
            surf.blit(back, (LOGICAL_W // 2 - 20 - bw // 2, 170 - (size + 16) // 2))
            draw.text(surf, text, (LOGICAL_W // 2 - 20, 170), size, col, "center", alpha=int(255 * min(1, ttl / 0.6)))
        if self.log_open:
            self._log(surf)

    def _players(self, surf):
        y = 12
        for p in self.sim.players:
            col = PLAYER_COLORS[p.idx % len(PLAYER_COLORS)]
            r = pygame.Rect(12, y, 300, 84)
            draw.panel(surf, r)
            pygame.draw.rect(surf, col, (r.x, r.y + 6, 5, r.h - 12))
            if p.state == "host":
                draw.draw_char(surf, "Zombie", "idle", (r.x + 34, r.y + 58), 0.95, False, (255, 90, 90), 255)
            else:
                draw.draw_char(surf, p.sprite, "idle" if p.alive else "fall", (r.x + 34, r.y + 58), 0.95,
                               False, None if p.alive else (120, 200, 255), 255 if p.alive else 150)
            draw.text(surf, f"P{p.idx + 1}  {p.name}", (r.x + 64, r.y + 8), 22, col)
            if p.alive:
                draw.bar(surf, r.x + 64, r.y + 30, 150, p.hp / p.max_hp, "blue" if p.hp > p.max_hp * 0.35 else "red", 14)
                draw.text(surf, f"{int(p.hp)}", (r.x + 222, r.y + 29), 18, C_TEXT)
                if p.weakened:
                    draw.text(surf, "WEAKENED", (r.x + 250, r.y + 8), 16, (200, 120, 255))
                ab = BAL.roles[p.role].ability
                frac = 1 - p.ability_cd / max(0.01, p.ability_max)
                self.A.icon(ABILITY_ICON[ab], 24)
                surf.blit(self.A.icon(ABILITY_ICON[ab], 24, C_GREEN if frac >= 1 else C_DIM), (r.x + 64, r.y + 52))
                draw.bar(surf, r.x + 92, r.y + 58, 70, frac, "blue", 10)
                draw.text(surf, ABILITY_NAME[ab], (r.x + 166, r.y + 54), 16, C_DIM)
                dfrac = 1 - p.dodge_cd / BAL.player.dodge_cooldown
                pygame.draw.rect(surf, (20, 25, 40), (r.x + 64, r.y + 74, 70, 4))
                pygame.draw.rect(surf, C_CYAN if dfrac >= 1 else C_DIM, (r.x + 64, r.y + 74, int(70 * dfrac), 4))
                draw.text(surf, "dodge", (r.x + 140, r.y + 68), 14, C_DIM)
            elif p.state == "host":
                self._host_panel(surf, p, r)
            else:
                draw.text(surf, "DOWN - recover Echo", (r.x + 64, r.y + 32), 22, C_CYAN)
                dc = max(0.0, p.ghost_disrupt_cd)
                draw.text(surf, "Echo pulse " + ("ready" if dc <= 0 else f"{dc:0.0f}s"), (r.x + 64, r.y + 56), 18, C_DIM)
            y += 92

    def _top(self, surf, t):
        sim = self.sim
        lines = self.objective_lines()
        # the panel grows with the number of goal lines instead of letting them run into the Fracture row
        r = pygame.Rect(LOGICAL_W // 2 - 270, 10, 540, 52 + 22 * len(lines))
        draw.panel(surf, r)
        for i, (txt, col, sz) in enumerate(lines):
            draw.text(surf, txt, (r.centerx, r.y + 6 + i * 22), sz, col, "midtop", maxw=r.w - 24)
        ry = r.bottom - 36
        fr = sim.fracture / BAL.fracture.max
        draw.text(surf, f"FRACTURE {sim.fracture}/{BAL.fracture.max}", (r.x + 14, ry), 20, C_RED if sim.fracture >= 3 else C_TEXT)
        draw.bar(surf, r.x + 150, ry + 2, 130, fr, "red", 14)
        surf.blit(self.A.icon("cart", 24, C_AMBER), (r.x + 300, ry - 2))
        draw.text(surf, f"{int(sim.team_salvage)} salvage", (r.x + 328, ry), 22, C_AMBER, maxw=110)
        m, s = divmod(int(sim.time), 60)
        draw.text(surf, f"{m:02d}:{s:02d}", (r.right - 14, ry), 22, C_TEXT, "topright")
        echoes = [e for e in sim.echoes if e.state in ("dropped", "carried")]
        if echoes:
            cost = echoes[0].cost
            draw.text(surf, f"Rekindling cost: {cost} salvage", (r.centerx, r.bottom + 6), 20, C_CYAN, "midtop")

    # ------------------------------------------------------------------ objectives, coach, guides
    def objective_lines(self):
        """Layered goals: the normal mission always; once MERIDIAN is exposed, a second line to stop it."""
        sim = self.sim
        if not sim.objective_done:
            main = (f"OBJECTIVE  Restore life support: relays {sim.relays_done}/{len(sim.relays)}", C_TEXT, 22)
        else:
            main = ("OBJECTIVE  Reach the Escape Dock and extract", C_GREEN, 22)
        out = [main]
        ov = sim.overlord
        if not sim.exposed:
            out.append(("Optional: Archive Core secured" if sim.core_collected else "Optional: recover the Archive Core",
                        C_GREEN if sim.core_collected else C_AMBER, 19))
        elif sim.host is not None:
            out.append((f"STOP MERIDIAN  Put down the Host  {int(max(0, sim.host.hp))}/{int(sim.host.max_hp)}", (255, 90, 100), 20))
        elif ov.stage == 0:
            out.append(("STOP MERIDIAN  Sever its Core in the Archive (hold E)", (255, 90, 100), 20))
        elif ov.stage == 2:
            learned = ", ".join(f"{k.upper()} x{v}" for k, v in sorted(ov.adapted.items()) if v > 0)
            line = f"MERIDIAN CANNOT BE DESTROYED  Phase {ov.phase}/3: hurt it, buy time, extract" if O.cfg()["avatar"].get("invincible") else f"STOP MERIDIAN  Phase {ov.phase}/3: overload conduits, then strike the Avatar"
            out.append((line, (255, 90, 100), 20))
            if learned:
                out.append((f"It has learned to resist: {learned}. Vary your attacks.", C_AMBER, 18))
        if sim.rift.phase == "open":
            left = sum(1 for pp in sim.rift.papers if pp.state != "gone")
            out.append((f"RIFT  {left} paper(s) left  {max(0, int(sim.rift.window_end - sim.time))}s: burn or tear them", (190, 90, 255), 18))
        return out

    def coach_text(self):
        """One short line that says what to do right now. Reads state only."""
        sim = self.sim
        crew = [p for p in sim.players if p.alive]
        h = sim.host
        if h is not None and h.host is not None:
            hs = h.host
            if hs.charge >= 1.0 and hs.summon_cd <= 0:
                return "HOST: hold E away from doors to SUMMON the horde"
            return "HOST: Claw=fire  Lunge=dodge  Mark=ability  tap E at a locked door"
        down = [p for p in sim.players if p.state == "down"]
        if sim.rift.phase == "open" and not down:
            if any(p.paper is not None for p in crew):
                return "You hold a paper: hold E at an Incinerator to burn it (or hold E anywhere to tear it)"
            return "A Rift scattered the papers: find one, press E to take it. It may name someone"
        if sim.fracture >= 6:
            return "The Fracture is high: repair relays or grab a stabilizer"
        if down:
            e = next((e for e in sim.echoes if e.state in ("dropped", "carried")), None)
            if e is not None:
                return "Carry the Echo to an ANCHOR, place it, then hold E to Rekindle (costs salvage)" if e.state == "carried" or e.paid else "Pick up the Echo (E) and pay salvage at an anchor to Rekindle"
        iso = getattr(sim.director, "flags", set()) if sim.director else set()
        if len(crew) >= 2 and "isolated_once" in iso:
            for p in crew:
                if min((q.pos.distance_to(p.pos) for q in crew if q is not p), default=0) > 1000:
                    return "You were taken from the team. Find them."
        if sim.exposed and sim.crew_lock_enabled and sim.host is not None:
            return "Hold E at a door to lock it. A Host must win a click contest to break it"
        if not sim.objective_done:
            nxt = [r for r in sim.relays if not r.online]
            if nxt:
                return "Follow the green arrow: hold E at a relay to bring it online"
        else:
            return "Everyone to the dock: hold position to extract"
        return ""

    def _coach(self, surf, t):
        txt = self.coach_text()
        if not txt:
            return
        w = draw.font(20).size(txt)[0] + 36
        r = pygame.Rect(LOGICAL_W // 2 - w // 2, LOGICAL_H - 138, w, 30)
        draw.panel(surf, r, alpha=150)
        draw.text(surf, txt, (r.centerx, r.y + 4), 20, C_TEXT, "midtop")

    def _guides(self, surf, t, cam):
        """Edge arrows to what matters now. Only for objects that are off screen."""
        sim = self.sim
        targets = []
        crew = [p for p in sim.players if p.alive]
        me = crew[0].pos if crew else None
        if me is None:
            return
        if not sim.objective_done:
            near = [r for r in sim.relays if not r.online]
            if near:
                r = min(near, key=lambda r: r.pos.distance_to(me))
                targets.append((r.pos, C_GREEN, "RELAY"))
        else:
            targets.append((sim.extract_pos, C_GREEN, "DOCK"))
        for e in sim.echoes:
            if e.state in ("dropped",):
                targets.append((e.pos, C_CYAN, "ECHO"))
        if sim.exposed:
            if sim.overlord.stage == 0 and sim.host is None:
                targets.append((sim.core_pos, (255, 90, 100), "CORE"))
            for c in sim.overlord.conduits:
                if c.ready:
                    targets.append((c.pos, C_GREEN, "CONDUIT"))
        if sim.host is not None:
            targets.append((sim.host.pos, (255, 60, 70), "HOST"))
        for e in sim.enemies:
            if getattr(e, "hunt", False) and not e.dead:
                targets.append((e.pos, C_RED, "HUNTER"))
        merged = {}                                       # one arrow per kind of thing: the nearest, with a count
        for pos, col, label in targets:
            cur = merged.get(label)
            if cur is None:
                merged[label] = [pos, col, label, 1]
            else:
                cur[3] += 1
                if pos.distance_to(me) < cur[0].distance_to(me):
                    cur[0] = pos
        placed = []
        for pos, col, label, cnt in merged.values():
            if cnt > 1:
                label = f"{label} x{cnt}"
            s = cam.to_screen(pos.x, pos.y)
            if 340 < s[0] < LOGICAL_W - 60 and 130 < s[1] < LOGICAL_H - 110:
                continue
            c = V(LOGICAL_W / 2, LOGICAL_H / 2 + 10)
            d = V(s) - c
            if d.length_squared() < 1:
                continue
            k = min((LOGICAL_W / 2 - 360) / max(1e-3, abs(d.x)), (LOGICAL_H / 2 - 130) / max(1e-3, abs(d.y)))
            p = c + d * min(1.0, k)
            if p.x > LOGICAL_W - 360 and p.y < 230:
                p.y = 230
            for q in placed:                                  # never stack two arrows on the same spot
                if p.distance_to(q) < 46:
                    p = V(p.x, p.y + 46) if p.y < LOGICAL_H / 2 else V(p.x, p.y - 46)
            placed.append(V(p))
            ang = math.atan2(d.y, d.x)
            pts = [(p.x + math.cos(ang) * 18, p.y + math.sin(ang) * 18), (p.x + math.cos(ang + 2.5) * 14, p.y + math.sin(ang + 2.5) * 14),
                   (p.x + math.cos(ang - 2.5) * 14, p.y + math.sin(ang - 2.5) * 14)]
            pulse = 0.65 + 0.35 * math.sin(t * 6)
            pygame.draw.polygon(surf, tuple(int(c_ * pulse) for c_ in col), pts)
            pygame.draw.polygon(surf, (255, 255, 255), pts, 1)
            lp = p - V(math.cos(ang), math.sin(ang)) * 26 - V(0, 22 if len(placed) % 2 else 0)
            lp = V(min(max(lp.x, 60), LOGICAL_W - 60), min(max(lp.y, 140), LOGICAL_H - 120))
            draw.text(surf, label, lp, 14, col, "center")

    def _host_panel(self, surf, p, r):
        """The Host's own panel: health, whether its Veil holds, and the horde charge."""
        from src.systems import host as H
        h = p.host
        draw.text(surf, "YOU ARE THE HOST", (r.x + 64, r.y + 28), 20, (255, 90, 100), maxw=r.w - 76)
        draw.bar(surf, r.x + 64, r.y + 50, 150, max(0.0, p.hp) / p.max_hp, "red", 10)
        up = H.veil_up(self.sim, p)
        draw.text(surf, "VEIL" if up else ("BROKEN" if h.veil_down_t > 0 else "OPEN"), (r.x + 222, r.y + 47), 15,
                  (150, 230, 255) if up else (255, 220, 120), maxw=r.right - r.x - 228)
        sc = min(1.0, h.charge)
        draw.text(surf, "HORDE", (r.x + 64, r.y + 63), 14, C_DIM)
        pygame.draw.rect(surf, (20, 25, 40), (r.x + 112, r.y + 66, 100, 8))
        pygame.draw.rect(surf, (255, 60, 70) if sc >= 1 else (150, 60, 80), (r.x + 112, r.y + 66, int(100 * sc), 8))

    def _minimap(self, surf):
        sim = self.sim
        s = 3
        w, h = MAP_W * s, MAP_H * s
        x0, y0 = LOGICAL_W - w - 14, 12
        draw.panel(surf, pygame.Rect(x0 - 6, y0 - 6, w + 12, h + 12))
        surf.blit(self.mini, (x0, y0))

        def pt(pos):
            return (int(x0 + pos.x / TILE * s), int(y0 + pos.y / TILE * s))
        for r in sim.relays:
            pygame.draw.rect(surf, C_GREEN if r.online else C_RED, (*pt(r.pos), 4, 4))
        for a in sim.anchors:
            pygame.draw.circle(surf, C_CYAN if a.online else C_DIM, pt(a.pos), 3, 1)
        pygame.draw.rect(surf, C_GREEN if sim.objective_done else (150, 60, 60), (*pt(sim.extract_pos), 6, 6), 1)
        for e in sim.echoes:
            pygame.draw.circle(surf, C_CYAN, pt(e.pos), 3)
        for pp in getattr(sim.rift, "papers", []):             # Rift papers: violet diamonds (decoys look identical on purpose)
            if pp.state in ("gone", "carried"):
                continue
            x, y = pt(pp.pos)
            pygame.draw.polygon(surf, (200, 120, 255), [(x, y - 3), (x + 3, y), (x, y + 3), (x - 3, y)])
        for p in sim.players:
            pygame.draw.circle(surf, PLAYER_COLORS[p.idx % len(PLAYER_COLORS)], pt(p.pos), 3 if p.alive else 2, 0 if p.alive else 1)

    def _feed(self, surf):
        y = LOGICAL_H - 24 - 30 * len(self.feed)
        for who, text, ttl in self.feed:
            a = int(255 * min(1, ttl / 0.8))
            col = C_AMBER if who in ("STATION AI", "UNKNOWN", "MERIDIAN") else C_CYAN
            if who == "MERIDIAN":
                col = (255, 120, 110)
            lw = draw.font(22).size(f"{who}:")[0]
            x0 = LOGICAL_W // 2 - 400
            draw.text(surf, f"{who}:", (x0, y), 22, col, alpha=a)
            draw.text(surf, text, (x0 + 14 + lw, y), 22, C_TEXT, alpha=a, maxw=800 - 14 - lw)
            y += 30

    def _log(self, surf):
        lg = self.log_open
        dim = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        surf.blit(dim, (0, 0))
        lines = draw.wrap_text(lg["text"], 28, 712)
        r = pygame.Rect(0, 0, 760, 150 + 34 * len(lines))
        r.center = (LOGICAL_W // 2, LOGICAL_H // 2)
        draw.panel(surf, r, alpha=240)
        draw.text(surf, lg["title"].upper(), (r.x + 24, r.y + 18), 34, C_AMBER, maxw=r.w - 48)
        draw.text(surf, f"Source: {lg['source']}   Thread: {lg['thread']}", (r.x + 24, r.y + 56), 20, C_DIM, maxw=r.w - 48)
        y = r.y + 96
        for line in lines:
            draw.text(surf, line, (r.x + 24, y), 28, C_TEXT)
            y += 34
        draw.text(surf, "Press any action key to close", (r.centerx, r.bottom - 14), 20, C_DIM, "midbottom")
