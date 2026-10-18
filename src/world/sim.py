"""Headless, deterministic simulation of one expedition. The renderer only reads this state."""
import random

import pygame

from src.config import BAL
from src.entities.models import (Anchor, Barricade, Cover, Crate, Door, Enemy, FloorHazard, LogTerminal,
                                 Pickup, Player, Relay)
from src.settings import TILE
from src.systems import ai, combat, fracture, host, machines, mission, nav, rift, ritual
from src.systems.commands import InputFrame
from src.systems.overlord import OverlordState
from src.systems.rift import RiftState
from src.systems.physics import Solids
from src.systems.story import StoryBook
from src.world.level import generate, tile_center

V = pygame.Vector2
P = BAL.player
IDLE = InputFrame()


class Sim:
    def __init__(self, seed, roles, modifier=None, upgrades=None, known_logs=(), solo_assist=True, story=None, level=None,
                 director=False, director_dir=None, director_cfg=None):
        Enemy._next = 0               # per-simulation ids: runs with the same seed must be identical
        self.director = None          # attached at the end of __init__ when enabled
        self.faults = []
        self.host = None
        self.hosts_made = 0
        self.horde_idx, self.horde_t = None, 0.0
        self.summon_queue, self.summon_t, self.summon_origin = [], 0.0, pygame.Vector2()
        self.crew_lock_enabled = False
        self.exposed = False          # the crew knows MERIDIAN exists
        self.overlord = OverlordState()
        self.rift = RiftState()
        self.machines = []
        self.known_logs = set(known_logs)
        self.seed = seed
        self.rng = random.Random(seed * 2654435761 % (2 ** 32))
        self.level = level or generate(seed, modifier)
        self.modifier = self.level.modifier
        self.upgrades = dict(upgrades or {})
        self.story = story or StoryBook()
        self.solo_assist = solo_assist
        self.solids = Solids(self.level)
        self.events = []
        self.time = 0.0
        self.result = None
        self.finished = False

        lvl = self.level
        bonus_hp = 10 * self.upgrade_level("plating")
        self.players = [Player(i, r, lvl.spawn_points[i % len(lvl.spawn_points)], bonus_hp) for i, r in enumerate(roles)]
        self.doors = [Door(d) for d in lvl.doors]
        self.crates = [Crate(p["tx"], p["ty"], p["tile"], p["salvage"]) for p in lvl.props if p["kind"] == "crate"]
        self.covers = [Cover(p["tx"], p["ty"], p["tile"]) for p in lvl.props if p["kind"] == "cover"]
        self.relays = [Relay(r["id"], r["tx"], r["ty"]) for r in lvl.relays]
        ids = self.story.pick_logs(self.seed, set(known_logs), len(lvl.logs))
        self.logs = [LogTerminal(lg["slot"], lg["tx"], lg["ty"], ids[lg["slot"] % len(ids)]) for lg in lvl.logs]
        self.anchors = [Anchor(a["id"], a["tx"], a["ty"], a["online"]) for a in lvl.anchors]
        self.floor_hazards = [FloorHazard(h) for h in lvl.floor_hazards]
        self.pickups = [Pickup("stabilizer", tile_center(s["tx"], s["ty"])) for s in lvl.stabilizers]
        self.machines = [machines.Machine(m["id"], m["kind"], tile_center(m["tx"], m["ty"]), m.get("room")) for m in lvl.machines]
        self.core_pos = V(tile_center(*lvl.core))
        self.extract_pos = V(tile_center(*lvl.extraction))
        self.enemies = [Enemy(s["type"], s["pos"]) for s in lvl.enemy_spawns]
        self.bullets, self.echoes, self.barricades, self.telegraphs = [], [], [], []
        self.pending_spawns = []

        # shared state
        self.team_salvage = M_START
        self.salvage_found = 0
        self.fracture = BAL.modifiers[self.modifier].get("start_fracture", 0)
        self.max_fracture = self.fracture
        self.revivals = self.defeats = self.kills = 0
        self.relays_done = 0
        self.objective_done = False
        self.core_collected = False
        self.extract_progress = 0.0
        self.stabilizers_found = 0
        self.logs_read = []
        self.current_log = None
        self.all_down_t = 0.0
        self.disrupt_msg_t = 0.0
        self.wave_no = 0
        self.nav_t = 0.0
        self.nav_fields = {}
        F, Mi = BAL.fracture, BAL.mission
        self.t_surge, self.t_glitch = 4.0, 8.0
        self.t_patrol, self.t_whisper = 10.0, 12.0
        self.t_wave = Mi.pressure_interval
        self.enemy_speed_mult = 1.0
        self._refresh_speed()
        self._rebuild_dynamic()
        self.emit("mission_start")
        if director:
            self._attach_director(director_dir, director_cfg, director)

    def _attach_director(self, directory, cfg_overrides, director=True):
        """MERIDIAN replaces the fixed pressure-wave timer; Fracture complications stay as game rules."""
        from src.systems.director import Director, load_config
        from src.systems.director_history import History
        from src.systems.director_memory import Memory
        mem = Memory(directory / "director_memory.json") if directory else Memory(None)
        hist = History(directory / "director_history.json") if directory else History(None)
        passive = director == "passive"
        self.director = Director(self, load_config(cfg_overrides), mem, hist, passive=passive)
        if not passive:
            self.t_wave = 1e9           # MERIDIAN replaces the fixed pressure-wave timer
        self.director.begin()

    # ------------------------------------------------------------------ helpers
    def upgrade_level(self, key):
        return int(self.upgrades.get(key, 0))

    def emit(self, name, **data):
        data["name"] = name
        self.events.append(data)
        rift.observe(self, data)
        if self.director is not None:
            self.director.on_event(data)

    def drain_events(self):
        ev, self.events = self.events, []
        return ev

    def _refresh_speed(self):
        F = BAL.fracture
        self.enemy_speed_mult = F.speed_boost if self.fracture >= F.speed_boost_from else 1.0
        if self.director is not None:
            self.enemy_speed_mult *= self.director.speed_mult

    def add_fracture(self, n):
        old = self.fracture
        self.fracture = max(0, min(BAL.fracture.max, self.fracture + n))
        self.max_fracture = max(self.max_fracture, self.fracture)
        self._refresh_speed()
        if self.fracture != old:
            self.emit("fracture_changed", level=self.fracture, delta=self.fracture - old)

    def finish(self, status, reason=""):
        if self.finished:
            return
        self.finished = True
        banked = self.team_salvage if status in ("extracted", "director_destroyed") else self.team_salvage // 4
        self.result = {
            "status": status, "reason": reason, "seed": self.seed, "modifier": self.modifier,
            "time": round(self.time, 2), "salvage": int(self.team_salvage), "banked": int(banked),
            "salvage_found": self.salvage_found, "revivals": self.revivals, "defeats": self.defeats,
            "kills": self.kills, "optional_done": bool(self.core_collected), "relays": self.relays_done,
            "relays_total": len(self.relays), "fracture_max": self.max_fracture,
            "logs": list(self.logs_read), "roles": [p.role for p in self.players],
        }
        self.emit("mission_end", status=status, reason=reason)

    def fail(self, reason):
        self.finish("failed", reason)

    def _rebuild_dynamic(self):
        pairs = [(d.rect, d) for d in self.doors if d.solid]
        pairs += [(b.rect, b) for b in self.barricades]
        self.solids.set_dynamic(pairs)

    # ------------------------------------------------------------------ main step
    def update(self, dt, frames=None):
        if self.finished:
            return
        frames = frames or {}
        self.time += dt
        self._rebuild_dynamic()
        self._update_doors(dt)
        self._rebuild_dynamic()
        nav.update_fields(self, dt)
        for p in self.players:
            self._update_player(p, frames.get(p.idx, IDLE), dt)
        mission.update_interactions(self, frames, dt)
        host.update_doors(self, frames, dt)
        host.update_horde(self, dt)
        host.update_summon(self, dt)
        machines.update(self, frames, dt)
        rift.update(self, frames, dt)
        ritual.update(self, dt)
        ai.update_enemies(self, dt)
        combat.update_bullets(self, dt)
        fracture.update(self, dt)
        if self.director is not None:
            self.director.update(dt)
        mission.update_pickups(self, dt)
        mission.update_extraction(self, dt)
        mission.check_failure(self, dt)
        self._cleanup(dt)

    def _cleanup(self, dt):
        self.enemies = [e for e in self.enemies if not e.dead]
        self.bullets = [b for b in self.bullets if not b.dead]
        for b in self.barricades:
            b.life -= dt
            if b.life <= 0:
                b.dead = True
        gone = [b for b in self.barricades if b.dead]
        if gone:
            for b in gone:
                self.emit("barricade_gone", pos=V(b.pos))
            self.barricades = [b for b in self.barricades if not b.dead]

    # ------------------------------------------------------------------ doors
    def _update_doors(self, dt):
        movers = [p.pos for p in self.players] + [e.pos for e in self.enemies if not e.dead]
        for d in self.doors:
            if d.broken:
                continue
            if d.kind == "barrier":
                continue
            want_open = d.lock_t <= 0 and any(m.distance_to(d.center) < TILE * 1.9 for m in movers)
            if d.lock_t > 0:
                want_open = False
                d.open = max(0.0, d.open - 4 * dt)
            else:
                d.open = min(1.0, d.open + 5 * dt) if want_open else max(0.0, d.open - 3 * dt)
                # never close on top of someone
                if not want_open and d.open < 0.7:
                    r = d.rect.inflate(24, 24)
                    if any(r.collidepoint(m.x, m.y) for m in movers):
                        d.open = max(d.open, 0.7)

    # ------------------------------------------------------------------ players
    def _update_player(self, p, f, dt):
        p.fire_cd = max(0.0, p.fire_cd - dt)
        p.dodge_cd = max(0.0, p.dodge_cd - dt)
        p.ability_cd = max(0.0, p.ability_cd - dt)
        p.iframes = max(0.0, p.iframes - dt)
        p.weak_t = max(0.0, p.weak_t - dt)
        p.flash = max(0.0, p.flash - dt)
        p.recoil = max(0.0, p.recoil - dt)
        p.ghost_disrupt_cd = max(0.0, p.ghost_disrupt_cd - dt)
        p.resist_t = max(0.0, p.resist_t - dt)
        if p.state == "host":
            host.update_host(self, p, f, dt)
            return
        move = V(f.mx, f.my)
        if move.length_squared() > 1:
            move = move.normalize()
        if not p.alive:
            self._update_ghost(p, f, move, dt)
            return
        aim = V(f.aim_x, f.aim_y)
        if aim.length_squared() > 0.09:
            p.facing = aim.normalize()
        elif not f.fire and move.length_squared() > 0.01:
            p.facing = move.normalize()
        speed = P.speed * (P.carry_speed_mult if p.carry is not None else 1.0) * (P.weakened_speed_mult if p.weakened else 1.0) * (0.9 if p.paper is not None else 1.0)
        if f.dodge and p.dodge_cd <= 0 and p.dodge_t <= 0 and p.charge_t <= 0:
            p.dodge_dir = move.normalize() if move.length_squared() > 0.01 else V(p.facing)
            p.dodge_t = P.dodge_time
            p.dodge_cd = P.dodge_cooldown
            self.emit("dodge", pos=V(p.pos), dir=V(p.dodge_dir), player=p.idx)
        if f.ability:
            combat.use_ability(self, p)
        p.moving = False
        if p.charge_t > 0:
            combat.update_charge(self, p, dt)
            p.charge_t -= dt
            p.moving = True
        elif p.dodge_t > 0:
            p.dodge_t -= dt
            p.pos, _, _, _ = self.solids.move(p.pos, p.dodge_dir * P.dodge_speed * dt, p.radius)
            p.moving = True
        else:
            if move.length_squared() > 0.001:
                p.pos, _, _, _ = self.solids.move(p.pos, move * speed * dt, p.radius)
                p.moving = True
                p.walk_phase += speed * dt * 0.05
            if f.fire and p.fire_cd <= 0:
                combat.fire_player(self, p)
        self._separate_players(p)

    def _separate_players(self, p):
        for q in self.players:
            if q is p or not q.alive:
                continue
            d = p.pos - q.pos
            L = d.length()
            m = p.radius + q.radius
            if 0 < L < m:
                np_, _, _, _ = self.solids.move(p.pos, d / L * (m - L) * 0.5, p.radius)
                p.pos = np_

    def _update_ghost(self, p, f, move, dt):
        if f.ability:
            combat.ghost_disrupt(self, p)
        if move.length_squared() > 0.001:
            p.pos, _, _, _ = self.solids.move(p.pos, move * P.ghost_speed * dt, p.radius)
            p.facing = move.normalize()
        if not self.solo_assist or len(self.players) != 1:
            p.down_t += dt


M_START = BAL.mission.start_salvage
