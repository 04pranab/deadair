"""Scripted players used for automated playtests (tests/ and tools/playtest.py). Not part of normal play."""
import pygame

from src.config import BAL
from src.settings import TILE
from src.systems import nav
from src.systems.commands import InputFrame

V = pygame.Vector2


class TeamBot:
    """skill 1.0 = perfect aim and dodging; lower values add aim error, missed trigger time and no dodging."""

    def __init__(self, sim, skill=1.0, seed=0, engage=False, pace=1.0):
        import random
        self.skill = skill
        self.engage = engage      # stop and fight visible enemies instead of running past them
        self.pace = pace          # movement speed scale (human-like hesitation)
        self.rng = random.Random(seed)
        self.sim = sim
        self.fields = {}
        self.t = 0.0
        self.goals = {}

    def _field(self, goal_tile):
        f = self.fields.get(goal_tile)
        if f is None or self.t - f[0] > 0.6:
            dyn = nav.blocked_dynamic_tiles(self.sim)
            f = (self.t, nav.build_field(self.sim, goal_tile, dyn))
            self.fields[goal_tile] = f
        return f[1]

    def _goto(self, p, target, stop=30):
        d = target - p.pos
        if d.length() <= stop:
            return V(0, 0)
        gt = (int(target.x // TILE), int(target.y // TILE))
        field = self._field(gt)
        nxt = nav.next_step(field, p.pos)
        v = (V(nxt) - p.pos) if nxt else d
        if d.length() < 90 and self.sim.solids.los(p.pos, target):
            v = d
        return v.normalize() if v.length_squared() else V(0, 0)

    def _rift_duty(self, p):
        sim = self.sim
        if p.paper is not None:
            incs = [m for m in sim.machines if m.kind == "incinerator"]
            if not incs:
                return V(0, 0), False, True                    # no incinerator: tear it by hand
            m = min(incs, key=lambda m: m.pos.distance_to(p.pos))
            mv = self._goto(p, m.pos, 40)
            return mv, False, p.pos.distance_to(m.pos) < 80
        free = [pp for pp in sim.rift.papers if pp.state == "free"]
        if not free:
            return V(0, 0), False, False
        pp = min(free, key=lambda q: q.pos.distance_to(p.pos))
        mv = self._goto(p, pp.pos, 30)
        return mv, p.pos.distance_to(pp.pos) < 50, False

    def frames(self, dt):
        sim = self.sim
        self.t += dt
        out = {}
        alive = [p for p in sim.players if p.alive]
        # decide the high-level plan
        echo = next((e for e in sim.echoes if e.state in ("dropped", "carried", "placed", "ritual")), None)
        anchors = [a for a in sim.anchors if a.online]
        for p in sim.players:
            f = InputFrame()
            if p.state == "host":
                from src.systems import host as H
                out[p.idx] = H.brain(sim, p, self.rng)
                continue
            if not p.alive:
                out[p.idx] = f
                continue
            # combat: shoot the nearest visible enemy
            tgt, td = None, 1e9
            for e in sim.enemies:
                d = e.pos.distance_to(p.pos)
                if d < 420 and d < td and sim.solids.los(p.pos, e.pos):
                    tgt, td = e, d
            if tgt is not None:
                aim = (tgt.pos - p.pos)
                if self.skill < 1.0:
                    aim = aim.rotate(self.rng.uniform(-1, 1) * (1 - self.skill) * 50)
                f.aim_x, f.aim_y = aim.x, aim.y
                f.fire = self.skill >= 1.0 or self.rng.random() < 0.35 + 0.65 * self.skill
                if td < 150 and p.dodge_cd <= 0 and tgt.state == "windup" and self.rng.random() < self.skill ** 2:
                    f.dodge = True
                if p.role == "imani" and p.ability_cd <= 0 and any(q.hp < q.max_hp * 0.6 for q in alive):
                    f.ability = True
                if p.role == "dax" and p.ability_cd <= 0 and td < 140:
                    f.ability = True
            move = V(0, 0)
            holding = False
            pressed = False
            # ritual / echo logistics
            if echo is not None and anchors:
                a = min(anchors, key=lambda a: a.pos.distance_to(echo.pos))
                if echo.state == "dropped":
                    carrier = min(alive, key=lambda q: q.pos.distance_to(echo.pos))
                    if p is carrier and p.carry is None:
                        move = self._goto(p, echo.pos, 24)
                        if p.pos.distance_to(echo.pos) < 40:
                            pressed = True
                    else:
                        move = self._goto(p, p.pos, 1)
                elif echo.state == "carried":
                    if p.carry is echo:
                        a = min(anchors, key=lambda a: a.pos.distance_to(p.pos))
                        move = self._goto(p, a.pos, 40)
                        if p.pos.distance_to(a.pos) < 90:
                            pressed = True
                    elif a:
                        move = self._goto(p, a.pos, 80)
                elif echo.state in ("placed", "ritual"):
                    move = self._goto(p, echo.anchor.pos, 50)
                    if p.pos.distance_to(echo.anchor.pos) < 100:
                        holding = True
            elif sim.rift.phase == "open" and p is next((q for q in alive if q.carry is None), None):
                # Rift duty: one player fetches a paper and burns it at the nearest incinerator (what a careful crew does)
                move, pressed, holding = self._rift_duty(p)
            elif not sim.objective_done:
                rel = [r for r in sim.relays if not r.online]
                if rel:
                    r = min(rel, key=lambda r: r.pos.distance_to(p.pos))
                    # spread: higher index players take a different relay when possible
                    if len(rel) > 1 and p.idx % 2 == 1:
                        r = max(rel, key=lambda r: -r.pos.distance_to(p.pos)) if len(rel) == 1 else sorted(rel, key=lambda r: r.pos.distance_to(p.pos))[1]
                    move = self._goto(p, r.pos, 60)
                    if p.pos.distance_to(r.pos) < 70:
                        holding = True
            else:
                move = self._goto(p, sim.extract_pos, 50)
            if self.engage and tgt is not None and td < 330 and p.carry is None and not holding:
                move = V(0, 0)                         # hold position and shoot
            f.mx, f.my = move.x * self.pace, move.y * self.pace
            f.interact, f.interact_held = pressed, holding or pressed
            out[p.idx] = f
        return out
