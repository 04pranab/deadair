"""REKINDLING: Echo recovery, placement on an anchor, the channelled ritual, revival and Fracture."""
import pygame

from src.config import BAL

V = pygame.Vector2
R = BAL.ritual


def echo_cost(sim):
    cost = R.base_cost + R.cost_per_fracture * sim.fracture - sim.upgrade_level("efficiency")
    return max(2, int(cost))


def pickup_echo(sim, p, echo):
    """Carrier takes a dropped (or placed) Echo. Returns True on success."""
    if not p.alive or p.carry is not None or echo.state not in ("dropped", "placed", "ritual"):
        return False
    if echo.state in ("placed", "ritual") and echo.anchor is not None:
        echo.anchor.echo = None
        echo.anchor = None
        echo.progress = 0.0
    echo.state = "carried"
    echo.carrier = p
    p.carry = echo
    sim.emit("echo_pickup", pos=V(echo.pos), player=p.idx)
    return True


def drop_echo(sim, p):
    e = p.carry
    if e is None:
        return
    e.state = "dropped"
    e.carrier = None
    e.pos = V(p.pos)
    p.carry = None
    sim.emit("echo_drop", pos=V(e.pos))


def try_place(sim, p, anchor):
    """Place the carried Echo on the anchor. Returns (ok, reason)."""
    e = p.carry
    if e is None:
        return False, "no echo"
    if not anchor.online:
        sim.emit("ritual_denied", pos=V(anchor.pos), reason="anchor offline")
        return False, "anchor offline"
    if anchor.echo is not None:
        sim.emit("ritual_denied", pos=V(anchor.pos), reason="anchor busy")
        return False, "anchor busy"
    cost = echo_cost(sim)
    if not e.paid:
        if sim.team_salvage < cost:
            sim.emit("ritual_denied", pos=V(anchor.pos), reason=f"need {cost} salvage")
            return False, "insufficient salvage"
        sim.team_salvage -= cost
        e.paid = True
        e.cost = cost
        sim.emit("salvage_spent", pos=V(anchor.pos), amount=cost)
    e.state = "placed"
    e.carrier = None
    e.anchor = anchor
    e.pos = V(anchor.pos)
    anchor.echo = e
    p.carry = None
    sim.emit("echo_placed", pos=V(anchor.pos), player=e.player_idx)
    return True, ""


def _channel_rate(sim, anchor):
    """Revival progress per second contributed by channelers; also sets anchor.channelers."""
    chans = [p for p in sim.players if p.alive and p.channeling and p.pos.distance_to(anchor.pos) <= R.radius]
    anchor.channelers = len(chans)
    if not chans:
        return 0.0
    mults = []
    for p in chans:
        m = BAL.roles[p.role].get("ritual_mult", 1.0)
        mults.append(m)
    mults.sort(reverse=True)
    total = mults[0] + 0.5 * sum(mults[1:])
    fingers = 1.0 / (1.0 - 0.12 * sim.upgrade_level("fingers"))
    return total * fingers / R.duration


def disrupted(sim, anchor):
    for e in sim.enemies:
        if not e.dead and e.kind == "warden" and e.pos.distance_to(anchor.pos) <= BAL.enemies.warden.disrupt_radius:
            return True
    return False


def revive(sim, echo):
    p = sim.players[echo.player_idx]
    if echo.state == "done" or p.state != "down":
        echo.state = "done"
        return False   # no duplicate resurrection
    anchor = echo.anchor
    spot = None
    for off in [(0, 52), (52, 0), (-52, 0), (0, -52), (40, 40), (-40, 40), (40, -40), (-40, -40)]:
        c = anchor.pos + V(off)
        if sim.solids.free_at(c, p.radius):
            spot = c
            break
    p.pos = spot if spot is not None else V(anchor.pos)
    p.state = "alive"
    p.hp = p.max_hp * BAL.player.revive_hp_fraction
    p.weak_t = BAL.player.weakened_time
    p.iframes = 1.5
    p.carry = None
    anchor.echo = None
    echo.state = "done"
    echo.anchor = None
    sim.revivals += 1
    sim.add_fracture(BAL.fracture.per_revival)
    sim.emit("revived", pos=V(p.pos), player=p.idx)
    return True


def update(sim, dt):
    # carried echoes follow their carrier
    for e in sim.echoes:
        e.pulse += dt
        if e.state == "carried":
            if e.carrier is None or not e.carrier.alive:
                e.state = "dropped"
                e.carrier = None
            else:
                e.pos = e.carrier.pos - e.carrier.facing * 20 + V(0, -6)
    solo_assist(sim, dt)
    for a in sim.anchors:
        a.pulse += dt
        e = a.echo
        if e is None:
            a.channelers = 0
            continue
        rate = _channel_rate(sim, a)
        if getattr(e, "auto", False):
            rate = 1.0 / R.solo_auto_duration
            a.channelers = 1
        warden = disrupted(sim, a)
        if rate > 0 and not warden:
            e.progress = min(1.0, e.progress + rate * dt)
            e.state = "ritual"
        else:
            if warden and rate > 0:
                sim.disrupt_msg_t -= dt
                if sim.disrupt_msg_t <= 0:
                    sim.disrupt_msg_t = 2.0
                    sim.emit("ritual_disrupted", pos=V(a.pos))
            decay = R.decay_rate * (1.5 if warden else 1.0) / R.duration
            e.progress = max(0.0, e.progress - decay * dt)
            if e.progress == 0 and e.state == "ritual":
                e.state = "placed"
        if e.progress >= 1.0:
            revive(sim, e)
    sim.echoes = [e for e in sim.echoes if e.state != "done"]


def solo_assist(sim, dt):
    """Accessibility option: a lone player's Echo is carried to the nearest anchor and rekindled automatically."""
    if not sim.solo_assist or len(sim.players) != 1:
        return
    p = sim.players[0]
    if p.alive:
        return
    p.down_t += dt
    if p.down_t < 2.5:
        return
    echo = next((e for e in sim.echoes if e.player_idx == p.idx and e.state == "dropped"), None)
    if echo is None:
        return
    anchors = [a for a in sim.anchors if a.online and a.echo is None]
    cost = echo_cost(sim)
    if not anchors or (sim.team_salvage < cost and not echo.paid):
        sim.fail("crew_lost")
        return
    a = min(anchors, key=lambda a: a.pos.distance_to(echo.pos))
    if not echo.paid:
        sim.team_salvage -= cost
        echo.paid = True
        echo.cost = cost
        sim.emit("salvage_spent", pos=V(a.pos), amount=cost)
    echo.state = "placed"
    echo.anchor = a
    echo.pos = V(a.pos)
    echo.auto = True
    a.echo = echo
    sim.emit("echo_placed", pos=V(a.pos), player=echo.player_idx)
