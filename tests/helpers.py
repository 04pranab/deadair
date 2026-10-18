import pygame

from src.systems.commands import InputFrame
from src.world.sim import Sim

V = pygame.Vector2
DT = 1 / 60


def quiet_sim(seed=5, roles=("mara", "dax", "imani"), **kw):
    """A sim with no roaming enemies and no scheduled pressure, for rule tests."""
    s = Sim(seed, list(roles), **kw)
    s.enemies.clear()
    s.t_wave = 1e9
    s.t_surge = s.t_glitch = s.t_patrol = s.t_whisper = 1e9
    return s


def run(sim, seconds, frames=None, each=None):
    n = int(seconds / DT)
    for _ in range(n):
        f = frames() if callable(frames) else frames
        sim.update(DT, f)
        if each:
            each(sim)
        if sim.finished:
            break


def press(**kw):
    return InputFrame(**kw)


def put(sim, idx, pos):
    sim.players[idx].pos = V(pos)


def dsim(seed=5, roles=("mara", "dax", "imani"), cfg=None, directory=None, think=False, **kw):
    """A sim with MERIDIAN attached, no roaming enemies and no Fracture timers. By default the director does not think on its own:
    tests call sim.director._think(sim.time) at the moment they want a decision. cfg overrides data/director.json keys."""
    over = {"min_observation": 0.0, "opening_grace": 0.0}
    over.update(cfg or {})
    s = Sim(seed, list(roles), director=True, director_dir=directory, director_cfg=over, **kw)
    s.enemies.clear()
    s.t_surge = s.t_glitch = s.t_patrol = s.t_whisper = 1e9
    if not think:
        s.director.t_think = 1e12
    return s
