"""Interactions, objectives, pickups, extraction and results."""
import pygame

from src.config import BAL
from src.systems import ritual

V = pygame.Vector2
M = BAL.mission
IR = BAL.player.interact_range


def hold_rate(sim, holders, mult_key="repair_mult"):
    """Progress per second for relay/extract style holds. Several holders add at half rate."""
    mults = sorted((BAL.roles[p.role].get(mult_key, 1.0) for p in holders), reverse=True)
    if not mults:
        return 0.0
    total = mults[0] + 0.5 * sum(mults[1:])
    return total / (1.0 - 0.12 * sim.upgrade_level("fingers"))


def update_interactions(sim, frames, dt):
    from src.systems import overlord
    relay_holders = {}
    for p in sim.players:
        p.channeling = False
        p.interact_target = None
        p.interact_progress = 0.0
        p.last_hazard_tick = max(0.0, p.last_hazard_tick - dt)
        if not p.alive:
            continue
        f = frames.get(p.idx)
        pressed = bool(f and f.interact)
        held = bool(f and f.interact_held)
        _player_interact(sim, p, pressed, held, relay_holders)
    overlord.update(sim, relay_holders, dt)
    for f in sim.faults:
        holders = relay_holders.get(("fault", id(f)), [])
        if holders and not f.repaired:
            f.progress = min(1.0, f.progress + hold_rate(sim, holders) / sim.director.cfg["fault"]["hold_time"] * dt)
            if f.progress >= 1.0:
                f.repaired = True
                sim.emit("fault_repaired", pos=V(f.pos))
        elif not f.repaired:
            f.progress = max(0.0, f.progress - 0.4 * dt)
    # relay progress: holders advance it, otherwise it decays
    for r in sim.relays:
        if r.online:
            continue
        holders = relay_holders.get(r.id, [])
        if holders:
            r.progress = min(1.0, r.progress + hold_rate(sim, holders) / M.relay_hold_time * dt)
            r.active = True
            if r.progress >= 1.0:
                _relay_online(sim, r)
        else:
            r.progress = max(0.0, r.progress - M.relay_decay / M.relay_hold_time * dt)
            r.active = False


def _player_interact(sim, p, pressed, held, relay_holders):
    # 1. Rekindling: channel a placed Echo
    for a in sim.anchors:
        if a.echo is not None and p.pos.distance_to(a.pos) <= BAL.ritual.radius:
            p.interact_target = "Hold INTERACT: channel Rekindling"
            p.interact_progress = a.echo.progress
            if held and p.carry is None:
                p.channeling = True
            return
    # 2. carrying: place on anchor, or drop
    if p.carry is not None:
        near = [a for a in sim.anchors if p.pos.distance_to(a.pos) <= IR + 30]
        if near:
            a = min(near, key=lambda a: a.pos.distance_to(p.pos))
            p.interact_target = "INTERACT: place Echo" if a.online else "Anchor offline"
            if pressed:
                ritual.try_place(sim, p, a)
            return
    # 3. hold-type: relays
    if p.carry is None:
        for r in sim.relays:
            if not r.online and p.pos.distance_to(r.pos) <= IR + 16:
                p.interact_target = "Hold INTERACT: repair relay"
                p.interact_progress = r.progress
                if held:
                    relay_holders.setdefault(r.id, []).append(p)
                return
    # 3b. power faults created by the director: hold to reroute
    if p.carry is None:
        for f in sim.faults:
            if not f.repaired and f.active and p.pos.distance_to(f.pos) <= IR + 16:
                p.interact_target = "Hold INTERACT: reroute power"
                p.interact_progress = f.progress
                if held:
                    relay_holders.setdefault(("fault", id(f)), []).append(p)
                return
    # 3c. the finale: sever MERIDIAN's Core, overload conduits
    if p.carry is None:
        from src.systems import overlord
        tgt = overlord.interact_targets(sim, p)
        if tgt is not None:
            label, prog, key = tgt
            p.interact_target = label
            p.interact_progress = prog
            if held and key is not None:
                relay_holders.setdefault(key, []).append(p)
            return
    # 3d. Rift papers and machines
    from src.systems import rift as _rift, machines as _mach
    tgt = _rift.interact_target(sim, p)
    if tgt is not None:
        label, prog, kind, obj = tgt
        p.interact_target, p.interact_progress = label, prog
        if kind == "take" and pressed:
            _rift.take(sim, p, obj)
        return
    ht = _mach.hold_target(sim, p)
    if ht is not None:
        p.interact_target, p.interact_progress = ht[0], ht[1]
        return
    mm = _mach.nearest(sim, p.pos, None, IR + 10) if p.carry is None else None
    if mm is not None and mm.kind != "incinerator":
        p.interact_target = _mach.label(sim, mm, p)
        if pressed:
            _mach.use(sim, mm, p)
        return
    # 4. tap-type interactables, nearest wins
    cands = []
    if p.carry is None:
        for e in sim.echoes:
            if e.state in ("dropped", "placed", "ritual") and p.pos.distance_to(e.pos) <= BAL.ritual.echo_pickup_range:
                cands.append((p.pos.distance_to(e.pos) - 20, "echo", e))
    if sim.core_pos is not None and not sim.core_collected and not sim.exposed and p.pos.distance_to(sim.core_pos) <= IR:
        cands.append((p.pos.distance_to(sim.core_pos) - 10, "core", None))
    for lg in sim.logs:
        if p.pos.distance_to(lg.pos) <= IR:
            cands.append((p.pos.distance_to(lg.pos), "log", lg))
    for c in sim.crates:
        if not c.opened and p.pos.distance_to(c.pos) <= IR:
            cands.append((p.pos.distance_to(c.pos), "crate", c))
    if cands:
        cands.sort(key=lambda t: t[0])
        _, kind, obj = cands[0]
        label = {"echo": "INTERACT: pick up Echo", "core": "INTERACT: take Archive Core",
                 "log": "INTERACT: read terminal" if not getattr(obj, "read", False) else "INTERACT: re-read terminal",
                 "crate": "INTERACT: open crate"}[kind]
        p.interact_target = label
        if pressed:
            if kind == "echo":
                ritual.pickup_echo(sim, p, obj)
            elif kind == "core":
                _take_core(sim, p)
            elif kind == "log":
                _read_log(sim, p, obj)
            elif kind == "crate":
                _open_crate(sim, p, obj)
        return
    if pressed and p.carry is not None:
        ritual.drop_echo(sim, p)


def _open_crate(sim, p, c):
    c.opened = True
    gain = c.salvage
    sim.team_salvage += gain
    sim.salvage_found += gain
    sim.emit("loot", pos=V(c.pos), amount=gain)


def _read_log(sim, p, lg):
    first = not lg.read
    lg.read = True
    sim.current_log = lg.log_id
    if lg.log_id not in sim.logs_read:
        sim.logs_read.append(lg.log_id)
    sim.emit("log_read", log_id=lg.log_id, first=first, pos=V(lg.pos), player=p.idx)


def _take_core(sim, p):
    sim.core_collected = True
    sim.team_salvage += M.core_salvage_bonus
    sim.salvage_found += M.core_salvage_bonus
    sim.emit("core_taken", pos=V(sim.core_pos), amount=M.core_salvage_bonus)


def _relay_online(sim, r):
    r.online = True
    r.progress = 1.0
    sim.relays_done += 1
    sim.add_fracture(-1)             # repair objectives stabilise the station
    if sim.relays_done == 1:
        for a in sim.anchors:        # first restored relay brings the second anchor online
            if not a.online:
                a.online = True
                sim.emit("anchor_online", pos=V(a.pos))
                break
    sim.emit("relay_online", pos=V(r.pos), done=sim.relays_done, total=len(sim.relays))
    if sim.relays_done >= len(sim.relays):
        sim.objective_done = True
        sim.emit("objective_complete")


def update_pickups(sim, dt):
    for pk in sim.pickups:
        pk.age += dt
        for p in sim.players:
            if p.alive and p.pos.distance_to(pk.pos) < p.radius + 18:
                pk.dead = True
                if pk.kind == "salvage":
                    sim.team_salvage += pk.value
                    sim.salvage_found += pk.value
                    sim.emit("salvage_pickup", pos=V(pk.pos), amount=pk.value)
                else:
                    sim.add_fracture(-BAL.fracture.stabilizer_pickup)
                    sim.stabilizers_found += 1
                    sim.emit("stabilizer_pickup", pos=V(pk.pos))
                break
    sim.pickups = [pk for pk in sim.pickups if not pk.dead]


def update_extraction(sim, dt):
    if not sim.objective_done:
        sim.extract_progress = 0.0
        return
    alive = [p for p in sim.players if p.alive]
    if not alive:
        return
    inside = all(p.pos.distance_to(sim.extract_pos) <= M.extract_radius for p in alive)
    if inside:
        sim.extract_progress += dt / M.extract_hold_time
        if sim.extract_progress >= 1.0:
            sim.finish("extracted")
    else:
        sim.extract_progress = max(0.0, sim.extract_progress - dt / M.extract_hold_time)


def check_failure(sim, dt):
    if any(p.alive for p in sim.players):
        sim.all_down_t = 0.0
        return
    if sim.solo_assist and len(sim.players) == 1:
        return   # ritual.solo_assist decides
    sim.all_down_t += dt
    if sim.all_down_t >= 3.0:
        sim.fail("crew_lost")
