"""MERIDIAN observation and rules: rolling statistics over real game state, tension, and pattern detection with
confidence, evidence, hysteresis and adaptation recognition. Deterministic; reads the sim, never changes it."""
from collections import deque

import pygame

V = pygame.Vector2
PATTERNS = ["route", "rush", "split", "hoarding", "resurrection_reliance", "ranged_dominance", "melee_dominance"]


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


class Obs:
    """A frozen snapshot used for one decision (so one observation yields at most one threat)."""
    pass


class Observer:
    def __init__(self, sim, cfg):
        self.sim, self.cfg = sim, cfg
        self.win = cfg["window"]
        self.tc = cfg["tension"]
        self.kills = deque()          # (t, kind, dist)
        self.hits = deque()           # (t, amount, player)
        self.rooms = deque()          # (t, room_id)
        self.cross = deque()          # (t, door_index)
        self.spread = deque()         # (t, spread, alive)
        self.salv = deque()           # (t, salvage)
        self.spends = deque()         # t
        self.shots = deque()
        self.defeats = deque()        # t
        self.revivals = 0
        self.defeats_total = 0
        self.tension = 0.0
        self.last_room = None
        self.prev_room = None
        self.last_room_t = -99.0
        self._zone = set()
        self.last_cross_t = -99.0
        self.last_cross_door = -1
        self.last_sample = -99.0
        self.dmg_total = 0.0

    # ------------------------------------------------------------------ events (called from Sim.emit)
    def on_event(self, ev, now):
        n = ev["name"]
        if n == "enemy_died":
            alive = [p for p in self.sim.players if p.alive]
            d = min((p.pos.distance_to(ev["pos"]) for p in alive), default=999.0)
            self.kills.append((now, ev.get("kind", "?"), d))
        elif n == "player_hit":
            self.hits.append((now, ev.get("amount", 0), ev.get("player", -1)))
            self.dmg_total += ev.get("amount", 0)
        elif n == "defeated":
            self.defeats.append(now)
            self.defeats_total += 1
        elif n == "revived":
            self.revivals += 1
        elif n == "salvage_spent":
            self.spends.append(now)
        elif n == "shoot" and ev.get("friendly"):
            self.shots.append(now)

    # ------------------------------------------------------------------ per frame (cheap): door crossings
    def frame(self, now):
        sim = self.sim
        for p in sim.players:
            if not p.alive:
                continue
            for i, d in enumerate(sim.doors):
                key = (p.idx, i)
                near = p.pos.distance_to(d.center) < 56
                if near and key not in self._zone:
                    self._zone.add(key)
                    # one team crossing per door passage: several players using the same door within 2 s count once
                    if d.kind == "normal" and (now - self.last_cross_t > 2.0 or i != self.last_cross_door):
                        self.cross.append((now, i))
                        self.last_cross_t = now
                        self.last_cross_door = i
                elif not near and key in self._zone and p.pos.distance_to(d.center) > 90:
                    self._zone.discard(key)

    # ------------------------------------------------------------------ 1 Hz sampling
    def sample(self, now):
        sim = self.sim
        self.last_sample = now
        alive = [p for p in sim.players if p.alive]
        if alive:
            sp = max((a.pos.distance_to(b.pos) for a in alive for b in alive), default=0.0)
            self.spread.append((now, sp, len(alive)))
            c = sum((p.pos for p in alive), V(0, 0)) / len(alive)
            room = sim.level.room_at(int(c.x // 48), int(c.y // 48))
            rid = room.id if room else self.last_room
            if rid is not None and rid != self.last_room:
                # stepping back into the room just left within 8 s is border jitter, not a new room
                if not (rid == self.prev_room and now - self.last_room_t < 8.0):
                    self.rooms.append((now, rid))
                self.prev_room, self.last_room, self.last_room_t = self.last_room, rid, now
        self.salv.append((now, sim.team_salvage))
        # tension: nearby weighted threats, recent damage, and low health
        r = self.tc["radius"]
        w = self.tc["weights"]
        near = 0.0
        for e in sim.enemies:
            if e.dead:
                continue
            if any(p.alive and p.pos.distance_to(e.pos) < r for p in sim.players):
                near += w.get(e.kind, 0.6)
        dmg10 = sum(a for t, a, _ in self.hits if now - t <= 10.0)
        hp = [p.hp / p.max_hp for p in alive] or [0.0]
        raw = clamp(0.5 * clamp(near / 8.0) + 0.3 * clamp(dmg10 / (45.0 * max(1, len(alive)))) + 0.2 * (1 - sum(hp) / len(hp)))
        a = self.tc["ema"]
        self.tension = self.tension * (1 - a) + raw * a
        self._prune(now)

    def _prune(self, now):
        lim = now - max(self.win, 150.0)
        for dq in (self.kills, self.hits, self.rooms, self.cross, self.spread, self.salv):
            while dq and dq[0][0] <= lim:
                dq.popleft()
        for dq in (self.spends, self.shots, self.defeats):
            while dq and dq[0] <= lim:
                dq.popleft()

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, now):
        sim = self.sim
        o = Obs()
        o.t = now
        o.players = list(sim.players)
        o.alive = [p for p in sim.players if p.alive]
        hp = [p.hp / p.max_hp for p in o.alive] or [0.0]
        o.hp_mean = sum(hp) / len(hp)
        o.hp_min = min(hp)
        o.down = len(sim.players) - len(o.alive) - sum(1 for p in sim.players if p.state == "host")
        o.centroid = (sum((p.pos for p in o.alive), V(0, 0)) / len(o.alive)) if o.alive else None
        o.enemies = [e for e in sim.enemies if not e.dead]
        o.chasing = sum(1 for e in o.enemies if e.alert_t > 0)
        o.tension = self.tension
        w = self.win
        o.dmg_10 = sum(a for t, a, _ in self.hits if now - t <= 10.0)
        o.dmg_60 = sum(a for t, a, _ in self.hits if now - t <= w)
        k = [x for x in self.kills if now - x[0] <= 120.0]
        o.kills_n = len(k)
        o.far_n = sum(1 for x in k if x[2] >= self.cfg["patterns"]["ranged_dominance"]["far"])
        o.near_n = sum(1 for x in k if x[2] <= self.cfg["patterns"]["melee_dominance"]["near"])
        o.kills_60 = sum(1 for x in self.kills if now - x[0] <= w)
        o.rooms_60 = sum(1 for t, _ in self.rooms if now - t <= w)
        pw = self.cfg["patterns"]["route"]["window"]
        crosses = [i for t, i in self.cross if now - t <= pw]
        o.crossings = len(crosses)
        counts = {}
        for i in crosses:
            counts[i] = counts.get(i, 0) + 1
        o.top_door, o.top_door_n = (max(counts.items(), key=lambda kv: (kv[1], -kv[0])) if counts else (None, 0))
        sp = [(s, n) for t, s, n in self.spread if now - t <= w and n >= 2]
        o.spread_n = len(sp)
        dist = self.cfg["patterns"]["split"]["distance"]
        o.spread_over = sum(1 for s, _ in sp if s >= dist)
        o.spread_mean = sum(s for s, _ in sp) / len(sp) if sp else 0.0
        o.salvage = sim.team_salvage
        o.salv_samples = [(t, s) for t, s in self.salv if now - t <= w]
        o.spent_recent = any(now - t <= w for t in self.spends)
        o.revivals = self.revivals
        o.defeats_total = self.defeats_total
        o.defeats_win = sum(1 for t in self.defeats if now - t <= self.cfg["recovery"]["failure_window"])
        o.alert_enemies = o.chasing
        return o


# ======================================================================== pattern detection
class PatternState:
    def __init__(self, name):
        self.name = name
        self.conf = 0.0
        self.raw = 0.0
        self.active = False
        self.on_streak = 0
        self.off_streak = 0
        self.evidence = []
        self.samples = 0
        self.counters = 0
        self.last_counter_t = -1e9
        self.conf_at_counter = None
        self.counter_t = None
        self.adapted = False
        self.max_conf = 0.0


def raw_confidences(o, cfg, cost_ref):
    """pattern -> (raw confidence, evidence strings, sample count). Pure function of the snapshot."""
    P = cfg["patterns"]
    out = {}

    c = P["route"]
    n = o.top_door_n
    conf = clamp((n - 2) / 3.0) if n >= c["min_samples"] else 0.0
    out["route"] = (conf, [f"door #{o.top_door} crossed {n}x in {c['window']:.0f}s"] if n else [], n)

    c = P["rush"]
    rooms = o.rooms_60
    kpr = o.kills_60 / rooms if rooms else 9.0
    if rooms >= c["rooms"] - 1 and rooms >= c["min_samples"]:
        conf = 0.45 * clamp((rooms - (c["rooms"] - 1)) / 2.0) + 0.35 * clamp(1 - kpr / c["kills_per_room"]) + 0.2 * clamp(o.chasing / 4.0)
    else:
        conf = 0.0
    out["rush"] = (conf, [f"{rooms} rooms in 60s, {o.kills_60} kills, {o.chasing} hostiles chasing"], rooms)

    c = P["split"]
    if o.spread_n >= c["min_samples"]:
        frac = o.spread_over / o.spread_n
        conf = clamp((frac - 0.3) / 0.5)
        ev = [f"{frac:.0%} of {o.spread_n}s apart over {c['distance']:.0f}px, mean {o.spread_mean:.0f}px"]
    else:
        conf, ev = 0.0, []
    out["split"] = (conf, ev, o.spread_n)

    c = P["hoarding"]
    thr = c["multiple"] * cost_ref
    ss = o.salv_samples
    if len(ss) >= c["min_samples"] and not o.spent_recent:
        frac = sum(1 for _, s in ss if s >= thr) / len(ss)
        conf = frac * clamp(0.5 + (o.salvage - thr) / (2 * thr)) if frac > 0.8 else 0.0
        ev = [f"{o.salvage} salvage held (>= {thr:.0f}) with no spending for the whole window"]
    else:
        conf, ev = 0.0, []
    out["hoarding"] = (conf, ev, len(ss))

    c = P["resurrection_reliance"]
    conf = clamp(o.revivals / c["revivals"]) if o.revivals >= c["min_samples"] else 0.0
    out["resurrection_reliance"] = (conf, [f"{o.revivals} revivals, {o.defeats_total} defeats this expedition"], o.revivals)

    c = P["ranged_dominance"]
    n = o.kills_n
    if n >= c["min_samples"]:
        share = o.far_n / n
        conf = clamp((share - (c["share"] - 0.25)) / 0.25) * clamp(n / (1.5 * c["min_samples"]))
        ev = [f"{o.far_n}/{n} kills from >= {c['far']:.0f}px"]
    else:
        conf, ev = 0.0, []
    out["ranged_dominance"] = (conf, ev, n)

    c = P["melee_dominance"]
    if n >= c["min_samples"]:
        share = o.near_n / n
        conf = clamp((share - (c["share"] - 0.25)) / 0.25) * clamp(n / (1.5 * c["min_samples"]))
        ev = [f"{o.near_n}/{n} kills from <= {c['near']:.0f}px"]
    else:
        conf, ev = 0.0, []
    out["melee_dominance"] = (conf, ev, n)
    return out


def update_patterns(states, o, cfg, cost_ref, history=None, adapt_log=None):
    """Advance every PatternState from a snapshot (hysteresis: confirm and clear need consecutive thinks).
    Returns the list of patterns that were newly recognised as adapted."""
    P = cfg["patterns"]
    raw = raw_confidences(o, cfg, cost_ref)
    adapted_now = []
    for name, (conf, ev, n) in raw.items():
        st = states[name]
        pc = P[name]
        prior = history.prior(name, P["prior_cap"]) if history else 0.0
        if conf >= 0.5 * pc["on"] and n >= pc["min_samples"]:
            conf = clamp(conf + prior)           # prior helps only when current evidence exists
        st.raw, st.conf, st.evidence, st.samples = conf, conf, ev, n
        st.max_conf = max(st.max_conf, conf)
        if conf >= pc["on"]:
            st.on_streak += 1
            st.off_streak = 0
        elif conf < pc["off"]:
            st.off_streak += 1
            st.on_streak = 0
        # between off and on: hold the current state (hysteresis band)
        if not st.active and st.on_streak >= P["confirm_thinks"]:
            st.active = True
        elif st.active and st.off_streak >= P["clear_thinks"]:
            st.active = False
        # adaptation: a counter was applied, and the crew's behaviour changed (confidence fell clearly, pattern cleared)
        if st.counter_t is not None and not st.adapted:
            if not st.active and st.conf_at_counter is not None and st.conf_at_counter - st.conf >= P["adapt_drop"] \
                    and o.t - st.counter_t <= 150.0:
                st.adapted = True
                adapted_now.append(name)
    return adapted_now
