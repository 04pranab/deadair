"""Plain data entities. Behaviour lives in src/systems/*."""
import pygame

from src.config import BAL
from src.settings import TILE

V = pygame.Vector2


class Player:
    def __init__(self, idx, role, pos, max_hp_bonus=0):
        self.idx = idx
        self.role = role
        spec = BAL.roles[role]
        self.name = spec.name
        self.sprite = spec.sprite
        self.pos = V(pos)
        self.facing = V(1, 0)
        self.radius = BAL.player.radius
        self.max_hp = spec.hp + max_hp_bonus
        self.hp = float(self.max_hp)
        self.state = "alive"          # alive | down
        self.fire_cd = 0.0
        self.dodge_cd = 0.0
        self.dodge_t = 0.0
        self.dodge_dir = V(1, 0)
        self.ability_cd = 0.0
        self.ability_max = spec.ability_cooldown
        self.charge_t = 0.0
        self.charge_hit = set()
        self.iframes = 0.0
        self.weak_t = 0.0
        self.carry = None             # Echo being carried
        self.flash = 0.0
        self.recoil = 0.0
        self.walk_phase = 0.0
        self.moving = False
        self.interact_target = None   # label for HUD prompt
        self.interact_progress = 0.0
        self.ghost_disrupt_cd = 0.0
        self.down_t = 0.0
        self.defeats = 0
        self.kills = 0
        self.last_hazard_tick = 0.0
        self.host = None              # HostState while this player is the Director's Host (state == "host")
        self.lock_hold = 0.0
        self.lock_cool = 0.0
        self.taint = 0.0              # Rift evidence (see systems/rift.py)
        self.paper = None             # Rift paper being carried
        self.paper_tear = 0.0
        self.resist_t = 0.0           # Medic stim: resists a Host conversion while > 0

    @property
    def is_host(self):
        return self.state == "host"

    @property
    def alive(self):
        return self.state == "alive"

    @property
    def weakened(self):
        return self.weak_t > 0


class Enemy:
    _next = 0

    def __init__(self, kind, pos):
        Enemy._next += 1
        self.id = Enemy._next
        self.kind = kind
        spec = BAL.enemies[kind]
        self.spec = spec
        self.pos = V(pos)
        self.facing = V(-1, 0)
        self.hp = float(spec.hp)
        self.max_hp = float(spec.hp)
        self.radius = spec.radius
        self.state = "idle"           # idle | chase | windup | recover | stagger
        self.timer = 0.0
        self.cd = 0.0
        self.alert_t = 0.0
        self.stagger_t = 0.0
        self.flash = 0.0
        self.target = None
        self.aim_dir = V(1, 0)
        self.nav_dir = None
        self.los_t = 0.0
        self.has_los = False
        self.knock = V(0, 0)
        self.dead = False
        self.walk_phase = 0.0
        self.hazard_cd = 0.0


class Bullet:
    def __init__(self, pos, vel, damage, friendly, owner=None, life=1.0):
        self.pos = V(pos)
        self.vel = V(vel)
        self.damage = damage
        self.friendly = friendly
        self.owner = owner
        self.life = life
        self.dead = False
        self.radius = 4


class Echo:
    """Recoverable imprint of a defeated player (Rekindling)."""

    def __init__(self, player_idx, pos, cost):
        self.player_idx = player_idx
        self.pos = V(pos)
        self.state = "dropped"        # dropped | carried | placed | ritual | done
        self.carrier = None
        self.anchor = None
        self.progress = 0.0
        self.cost = cost
        self.paid = False
        self.pulse = 0.0


class Anchor:
    def __init__(self, aid, tx, ty, online):
        self.id = aid
        self.pos = V(tx * TILE + TILE // 2, ty * TILE + TILE // 2)
        self.online = online
        self.echo = None
        self.pulse = 0.0
        self.channelers = 0


class Door:
    def __init__(self, spec):
        self.spec = spec
        self.cells = spec.cells
        xs = [c[0] for c in spec.cells]
        ys = [c[1] for c in spec.cells]
        self.rect = pygame.Rect(min(xs) * TILE, min(ys) * TILE, (max(xs) - min(xs) + 1) * TILE, (max(ys) - min(ys) + 1) * TILE)
        self.center = V(self.rect.center)
        self.kind = spec.kind
        self.open = 0.0               # 0 closed .. 1 open
        self.hp = 160.0 if spec.kind == "barrier" else 0.0
        self.warn_t = 0.0             # glitch warning
        self.lock_t = 0.0             # glitch lock
        self.broken = False
        self.crew_lock = False        # locked by the crew (contestable by a Host)
        self.contest = 0.0            # Host click-contest progress 0..1
        self.sealed = False           # permanently sealed by MERIDIAN

    @property
    def solid(self):
        if self.broken:
            return False
        if self.kind == "barrier":
            return True
        return self.lock_t > 0 or self.open < 0.7


class Barricade:
    def __init__(self, pos, size, hp, life):
        self.pos = V(pos)
        self.rect = pygame.Rect(0, 0, size, size)
        self.rect.center = (round(pos.x), round(pos.y))
        self.hp = hp
        self.life = life
        self.dead = False


class Crate:
    def __init__(self, tx, ty, tile, salvage):
        self.pos = V(tx * TILE + TILE // 2, ty * TILE + TILE // 2)
        self.tx, self.ty, self.tile, self.salvage = tx, ty, tile, salvage
        self.opened = False


class Cover:
    def __init__(self, tx, ty, tile):
        self.pos = V(tx * TILE + TILE // 2, ty * TILE + TILE // 2)
        self.tx, self.ty, self.tile = tx, ty, tile


class Relay:
    def __init__(self, rid, tx, ty):
        self.id = rid
        self.pos = V(tx * TILE + TILE // 2, ty * TILE + TILE // 2)
        self.progress = 0.0
        self.online = False
        self.active = False


class LogTerminal:
    def __init__(self, slot, tx, ty, log_id):
        self.slot = slot
        self.pos = V(tx * TILE + TILE // 2, ty * TILE + TILE // 2)
        self.log_id = log_id
        self.read = False


class Pickup:
    def __init__(self, kind, pos, value=1):
        self.kind = kind              # salvage | stabilizer
        self.pos = V(pos)
        self.value = value
        self.dead = False
        self.age = 0.0


class FloorHazard:
    def __init__(self, spec):
        self.rect = pygame.Rect(spec["tx"] * TILE, spec["ty"] * TILE, spec["w"] * TILE, spec["h"] * TILE)
        self.phase = spec["phase"]
        self.state = "idle"           # idle | warning | active


class Telegraph:
    """A timed, visible warning that resolves into an effect (surge strike, patrol spawn, wave)."""

    def __init__(self, kind, pos, t, radius=0, payload=None):
        self.kind = kind
        self.pos = V(pos)
        self.t = t
        self.total = t
        self.radius = radius
        self.payload = payload
        self.dead = False


class Fault:
    """A repairable power fault created by the director's power-failure event (hold INTERACT to reroute)."""

    def __init__(self, pos, door_index):
        self.pos = V(pos)
        self.door_index = door_index
        self.progress = 0.0
        self.repaired = False
        self.active = False
