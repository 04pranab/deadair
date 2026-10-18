"""The Rift: how the station decides who becomes the Host.

Three separate stages, each testable on its own:

 1. ELIGIBILITY  Player actions build "taint" (being rekindled, falling, being folded away, reading terminals, using a machine
    that looks back, every relay brought online feeds it). A player is eligible only above a threshold and when not warded.
    Time never appears in the formula. The progress-tied relay term guarantees eligibility is reachable (never impossible).
 2. RIFT        The Director may open a Rift. It tears open near the crew (telegraphed), then scatters PAPERS to distant, separated
    places. A selection Rift scatters one named paper per eligible player; an ordinary Rift scatters blanks that look the same
    from afar. Papers reveal what they are only when someone gets close, so the crew cannot assume a Rift means a Host.
    Counterplay: pick a paper up and burn it at an Incinerator (fast) or tear it by hand (slow).
 3. SELECTION   When the window ends, among the papers still intact and whose owners are still eligible, one is chosen with a
    seeded weighted draw (weight grows with taint but everyone eligible keeps a real chance). If none remain, the Rift fails and
    the crew is rewarded. A blank Rift left alone scars the station (+Fracture).

Deterministic: all randomness uses the simulation's rng (or an injected one in tests)."""
import math

import pygame

from src.config import BAL, load_json

V = pygame.Vector2
_CFG = None


def cfg():
    global _CFG
    if _CFG is None:
        _CFG = load_json("rift.json")
    return _CFG


class Paper:
    def __init__(self, pid, owner, pos):
        self.id = pid
        self.owner = owner            # player idx for a selection paper, None for a blank
        self.pos = V(pos)
        self.home = V(pos)
        self.state = "free"           # free | carried | gone
        self.carrier = None
        self.read = False             # someone has been close enough to read it
        self.flash = 0.0
        self.age = 0.0


class RiftState:
    def __init__(self):
        self.phase = None             # None | "tear" | "open"
        self.select = False
        self.t = 0.0
        self.window_end = 0.0
        self.seam = V(0, 0)
        self.papers = []
        self.shifts_left = 0
        self.next_shift = 0.0
        self.shift = None             # (paper, new_pos, fire_t)
        self.next_id = 1
        self.last_select_end = -1e9
        self.last_end = -1e9
        self.history = []             # compact record of resolved rifts (for tests, debug, results)
        self.exposure_log = []
        self.tell_until = 0.0         # an imminent Rift is being telegraphed (identical for both kinds)


def crew(sim):
    return [p for p in sim.players if p.alive]


# ------------------------------------------------------------------ stage 1: eligibility
def observe(sim, ev):
    """Evidence from real game events. Called from Sim.emit."""
    c = cfg()["taint"]
    n = ev["name"]
    add = None
    if n == "revived":
        add = (ev["player"], c["revived"])
    elif n == "defeated":
        add = (ev["player"], c["defeated"])
    elif n == "teleport":
        add = (ev["player"], c["teleport"])
    elif n == "gauge_used":
        add = (ev["player"], c["gauge"])
    elif n == "log_read" and ev.get("first") and ev.get("player") is not None:
        add = (ev["player"], c["log_read"])
    elif n == "relay_online":
        for p in sim.players:
            if p.alive:
                p.taint = min(c["cap"], p.taint + c["relay"])
        return
    if add is not None and 0 <= add[0] < len(sim.players):
        p = sim.players[add[0]]
        p.taint = min(c["cap"], p.taint + add[1])


def tick_taint(sim, dt):
    from src.systems import machines
    c = cfg()["taint"]
    for p in sim.players:
        if p.alive and p.taint > 0 and machines.in_ward(sim, p.pos):
            p.taint = max(0.0, p.taint - c["ward_decay_per_s"] * dt)


def eligible(sim, p):
    from src.systems import machines
    e = cfg()["eligibility"]
    return bool(p.alive and p.taint >= e["min_taint"] and p.resist_t <= 0 and not machines.in_ward(sim, p.pos))


def eligible_players(sim):
    return [p for p in sim.players if eligible(sim, p)]


def evidence_total(sim):
    return sum(p.taint for p in sim.players if p.alive)


def select_ready(sim, now):
    """May a selection Rift open? Pure function of game state (never of the clock alone)."""
    e = cfg()["eligibility"]
    r = sim.rift
    if sim.host is not None or sim.hosts_made >= e["max_hosts"]:
        return False, "host limit"
    if len(crew(sim)) < e["min_crew"]:
        return False, "not enough crew"
    if any(p.state == "down" for p in sim.players):
        return False, "someone is down"
    if sim.relays_done < e["min_relays"]:
        return False, "no relay online"
    if now - r.last_select_end < e["cooldown"]:
        return False, "cooldown"
    if not eligible_players(sim):
        return False, "nobody eligible"
    if evidence_total(sim) < e["min_total"]:
        return False, "not enough evidence"
    return True, ""


def pressure(sim, now):
    """0..1 'Rift pressure': how close the station is to a selection Rift. Shown through tells; never reveals who."""
    e = cfg()["eligibility"]
    top = max((p.taint for p in sim.players if p.alive), default=0.0)
    a = min(1.0, top / e["min_taint"])
    b = min(1.0, evidence_total(sim) / e["min_total"])
    c = min(1.0, sim.relays_done / max(1, e["min_relays"]))
    return round(a * b * c, 3)


# ------------------------------------------------------------------ stage 3: selection (pure, testable)
def choose_host(candidates, rng):
    """candidates: [(player, taint)] -> player. Weighted, seeded, every candidate keeps a real chance."""
    e = cfg()["eligibility"]
    if not candidates:
        return None
    ws = [e["base_weight"] + max(0.0, t) ** e["exponent"] for _, t in candidates]
    return candidates[_pick(rng, ws)][0]


def _pick(rng, ws):
    x = rng.random() * sum(ws)
    for i, w in enumerate(ws):
        x -= w
        if x <= 0:
            return i
    return len(ws) - 1


# ------------------------------------------------------------------ stage 2: the Rift event
def active(sim):
    return sim.rift.phase is not None


def _free_pos(sim, pos):
    return sim.solids.free_at(pos, 14)


def pick_sites(sim, n, rng, avoid=()):
    """n positions in distinct rooms: far from the crew, far from each other, reachable, off busy ground."""
    from src.systems import nav
    from src.systems import director_events as ev
    c = cfg()["rift"]
    al = crew(sim)
    if not al:
        return []
    ctr = sum((p.pos for p in al), V(0, 0)) / len(al)
    start = (int(ctr.x // 48), int(ctr.y // 48))
    field = nav.build_field(sim, start, nav.blocked_dynamic_tiles(sim))
    rooms = [r for r in sim.level.rooms if r.id != sim.level.archive_room]
    rng.shuffle(rooms)
    out = []
    for r in rooms:
        cx, cy = r.center
        for dx, dy in ((0, 0), (2, 1), (-2, -1), (3, -2), (-3, 2)):
            pos = V((cx + dx) * 48 + 24, (cy + dy) * 48 + 24)
            if not _free_pos(sim, pos):
                continue
            if any(p.pos.distance_to(pos) < c["min_from_crew"] for p in al):
                continue
            if any(q.distance_to(pos) < c["min_separation"] for q in out):
                continue
            if any(not e.dead and e.pos.distance_to(pos) < c["enemy_clear"] for e in sim.enemies):
                continue
            t = (int(pos.x // 48), int(pos.y // 48))
            if t not in field:
                continue
            if any(pos.distance_to(a) < 200 for a in avoid):
                continue
            out.append(pos)
            break
        if len(out) >= n:
            break
    return out


def can_open(sim, select):
    if active(sim):
        return False, "a Rift is already open"
    if len(crew(sim)) < 1:
        return False, "no crew"
    n = len(eligible_players(sim)) if select else max(2, len(crew(sim)))
    if select and n == 0:
        return False, "nobody eligible"
    sites = pick_sites(sim, min(n, 6), _Probe(sim))
    if len(sites) < min(n, 2):
        return False, "no far, reachable places for the papers"
    return True, ""


class _Probe:
    """Deterministic, side-effect-free rng stand-in for validation (does not advance the sim rng)."""

    def __init__(self, sim):
        import random
        self._r = random.Random(sim.seed * 7919 + int(sim.time))

    def shuffle(self, x):
        self._r.shuffle(x)

    def random(self):
        return self._r.random()

    def uniform(self, a, b):
        return self._r.uniform(a, b)


def open_rift(sim, select, rng=None):
    c = cfg()["rift"]
    rng = rng or sim.rng
    r = sim.rift
    al = crew(sim)
    ctr = sum((p.pos for p in al), V(0, 0)) / len(al)
    r.phase, r.select, r.t = "tear", bool(select), c["tear_warn"]
    r.papers = []
    seam = None
    for ang in range(0, 360, 30):
        pos = ctr + V(math.cos(math.radians(ang)), math.sin(math.radians(ang))) * 520
        if _free_pos(sim, pos) and sim.solids.los(ctr, pos):
            seam = pos
            break
    r.seam = V(seam if seam is not None else ctr)
    sim.emit("rift_tear", pos=V(r.seam), t=r.t)          # identical cue for selection and ordinary Rifts
    return r


def _scatter(sim, rng):
    c = cfg()["rift"]
    r = sim.rift
    if r.select:
        # decoy blanks pad the count to the crew size so the number of papers never reveals who is eligible
        owners = [p.idx for p in eligible_players(sim)]
        owners += [None] * max(0, len(crew(sim)) - len(owners))
    else:
        owners = [None] * max(2, len(crew(sim)))
    sites = pick_sites(sim, len(owners), rng)
    if len(sites) < len(owners):
        owners = owners[:len(sites)]
    r.papers = []
    for own, pos in zip(owners, sites):
        pp = Paper(r.next_id, own, pos)
        r.next_id += 1
        r.papers.append(pp)
        sim.emit("rift_scatter", pos=V(pos), src=V(r.seam), paper=pp.id)
    n = len(r.papers)
    r.phase = "open"
    r.t = 0.0
    window = min(c["window_cap"], c["window_base"] + c["window_per_extra"] * max(0, n - 1))
    r.window_end = sim.time + window
    r.shifts_left = c["shifts"]
    r.next_shift = sim.time + c["shift_every"]
    r.shift = None
    sim.emit("rift_open", papers=n, window=window, select=r.select)


# ------------------------------------------------------------------ player interaction with papers
def nearby_paper(sim, p, rad):
    best, bd = None, 1e9
    for pp in sim.rift.papers:
        if pp.state == "free":
            d = pp.pos.distance_to(p.pos)
            if d < rad and d < bd:
                best, bd = pp, d
    return best


def interact_target(sim, p):
    """-> label, progress for the paper prompts, or None."""
    if not active(sim) or sim.rift.phase != "open":
        return None
    IR = BAL.player.interact_range
    if p.paper is None and p.carry is None:
        pp = nearby_paper(sim, p, IR + 14)
        if pp is not None:
            return ("INTERACT: take paper", 0.0, "take", pp)
    elif p.paper is not None:
        return ("Hold INTERACT: tear paper  |  tap: drop", p.paper_tear, "tear", p.paper)
    return None


def take(sim, p, pp):
    pp.state, pp.carrier = "carried", p
    pp.taken_at = sim.time
    p.paper = pp
    p.paper_tear = 0.0
    sim.emit("paper_taken", pos=V(pp.pos), player=p.idx, paper=pp.id)


def drop(sim, p):
    pp = p.paper
    if pp is None:
        return
    pp.state, pp.carrier = "free", None
    pp.pos = V(p.pos)
    p.paper = None
    p.paper_tear = 0.0
    sim.emit("paper_dropped", pos=V(pp.pos), player=p.idx, paper=pp.id)


def destroy(sim, pp, how):
    c = cfg()["rift"]
    if pp.state == "gone":
        return
    pp.state = "gone"
    if pp.carrier is not None:
        pp.carrier.paper = None
        pp.carrier.paper_tear = 0.0
        pp.carrier = None
    reward = c["burn_reward"] if how == "burn" else 0
    if not sim.rift.select and how == "burn":
        reward = c["blank_reward"]
    if reward:
        sim.team_salvage += reward
        sim.salvage_found += reward
    sim.emit("paper_destroyed", pos=V(pp.pos), paper=pp.id, how=how, owner=pp.owner, reward=reward)


# ------------------------------------------------------------------ update
def update(sim, frames, dt):
    tick_taint(sim, dt)
    r = sim.rift
    if r.phase is None:
        return
    rc = cfg()["rift"]
    if r.phase == "tear":
        r.t -= dt
        if r.t <= 0:
            _scatter(sim, sim.rng)
        return
    # open
    for pp in r.papers:
        pp.age += dt
        pp.flash = max(0.0, pp.flash - dt)
        if pp.state == "carried":
            c = pp.carrier
            if c is None or not c.alive:
                if c is not None:
                    drop(sim, c)
                else:
                    pp.state = "free"
            else:
                pp.pos = V(c.pos)
        elif pp.state == "free" and not pp.read:
            if any(p.pos.distance_to(pp.pos) < rc["read_radius"] for p in crew(sim)):
                pp.read = True
                pp.flash = 0.6
                sim.emit("paper_read", pos=V(pp.pos), paper=pp.id, owner=pp.owner)
    # hand-tearing
    for p in sim.players:
        if p.paper is None:
            continue
        f = frames.get(p.idx)
        if f is not None and f.interact_held and p.alive and not _at_incinerator(sim, p):
            p.paper_tear += dt / rc["tear_hold"]
            if p.paper_tear >= 1.0:
                destroy(sim, p.paper, "tear")
        else:
            p.paper_tear = max(0.0, p.paper_tear - dt * 0.5)
        if f is not None and f.interact and p.paper is not None and sim.time - getattr(p.paper, "taken_at", -9) > 0.3 and not _at_incinerator(sim, p):
            drop(sim, p)
    # the Rift shifts a paper somewhere else (telegraphed), a limited number of times
    if r.shift is not None:
        pp, newpos, t_fire = r.shift
        if sim.time >= t_fire:
            r.shift = None
            if pp.state == "free":
                src = V(pp.pos)
                pp.pos = V(newpos)
                pp.read = False
                sim.emit("rift_shift", pos=V(newpos), src=src, paper=pp.id)
    elif r.shifts_left > 0 and sim.time >= r.next_shift:
        free = [pp for pp in r.papers if pp.state == "free"]
        if free:
            pp = free[sim.rng.randrange(len(free))]
            sites = pick_sites(sim, 1, sim.rng, avoid=[q.pos for q in r.papers if q is not pp])
            if sites:
                r.shift = (pp, sites[0], sim.time + rc["shift_warn"])
                r.shifts_left -= 1
                sim.emit("rift_shift_warning", pos=V(pp.pos), paper=pp.id)
        r.next_shift = sim.time + rc["shift_every"]
    live = [pp for pp in r.papers if pp.state != "gone"]
    if sim.time >= r.window_end or not live:
        _resolve(sim)


def _at_incinerator(sim, p):
    from src.systems import machines
    return machines.nearest(sim, p.pos, "incinerator", 90) is not None


def burn_paper(sim, p):
    """Called by the Incinerator machine: burn the paper this player carries."""
    if p.paper is None:
        return False
    destroy(sim, p.paper, "burn")
    return True


def _resolve(sim):
    r = sim.rift
    e = cfg()["eligibility"]
    left = [pp for pp in r.papers if pp.state != "gone"]
    for pp in left:
        if pp.carrier is not None:
            pp.carrier.paper = None
            pp.carrier = None
        pp.state = "gone"
    info = {"t": round(sim.time, 1), "select": r.select, "papers": len(r.papers), "left": len(left), "chosen": None}
    chosen = None
    if r.select:
        cands = []
        for pp in left:
            if pp.owner is None:
                continue
            p = sim.players[pp.owner]
            if eligible(sim, p):
                cands.append((p, p.taint))
        chosen = choose_host(cands, sim.rng)
        if chosen is not None:
            from src.systems import host as H
            H.convert(sim, chosen, source="rift")
            info["chosen"] = chosen.idx
            sim.emit("rift_selected", pos=V(chosen.pos), player=chosen.idx)
        else:
            sim.emit("rift_failed", pos=V(r.seam), burned=len(r.papers) - len(left))
        r.last_select_end = sim.time
    else:
        if left:
            sim.add_fracture(cfg()["rift"]["blank_scar_fracture"])
        sim.emit("rift_closed", pos=V(r.seam), scarred=bool(left))
    r.history.append(info)
    r.phase, r.papers, r.shift = None, [], None
    r.last_end = sim.time
    for p in sim.players:
        p.paper = None
        p.paper_tear = 0.0
