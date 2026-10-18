"""MERIDIAN: a deterministic, rule-based adaptive game director (no machine learning).

It observes real game state, detects repeated play patterns with evidence and confidence, and spends a threat/recovery budget
on events the game actually supports. Safety invariants are enforced twice: when an event is scheduled and again at the
instant it would take effect. Every decision leaves a compact trace line."""
import copy
import math
import os
import random
from collections import deque

import pygame

from src.config import BAL, load_json
from src.systems import director_events as ev
from src.systems import director_surprises as sp
from src.systems.director_budget import Budget
from src.systems.director_history import History
from src.systems.director_memory import Memory
from src.systems.director_rules import PATTERNS, Observer, PatternState, clamp, update_patterns

V = pygame.Vector2
THREATS = ["reinforce", "flank", "hazard", "route_closure", "power_failure", "optional_encounter", "modifier",
           "isolate", "blackout", "seal", "hunter", "ambush"]
SPECIAL = ["rift", "rift_select", "false_tell"]
ev.EVENT_CLASSES.update(sp.SURPRISE_CLASSES)


def load_config(overrides=None):
    cfg = copy.deepcopy(load_json("director.json"))
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


class Director:
    def __init__(self, sim, cfg=None, memory=None, history=None, story=None, log_path=None, passive=False):
        self.sim = sim
        self.passive = passive          # observe and measure only (used for the fixed-pacing baseline)
        self.series = []                # (t, tension, hp_mean, hp_min, down) once per sample
        self.cfg = cfg or load_config()
        self.rng = random.Random((sim.seed * 0x9E3779B1) ^ 0xD1EC7)       # own RNG: never perturbs the simulation's
        self.budget = Budget(self.cfg["budget"], self.cfg["events"])
        self.observer = Observer(sim, self.cfg)
        self.patterns = {n: PatternState(n) for n in PATTERNS}
        self.memory = memory if memory is not None else Memory(None)
        self.history = history if history is not None else History(None)
        self.story = ev.StoryEngine(self, story)
        self.log_path = log_path
        self.events = []
        self.next_id = 1
        self.flags = set()
        self.quiet_until = -1.0
        self.speed_mult = 1.0
        self.drop_mult = 1.0
        self.comp_bias = None
        self.heading = None
        self._pos_hist = deque(maxlen=10)
        self.mode, self.mode_since = "build", 0.0
        self.obs_id = 0
        self.t_think = self.cfg["think_interval"]
        self.t_sample = 0.0
        self.t_inv = 1.0
        self.trace = deque(maxlen=self.cfg["trace_max"])
        self.violations = []
        self.spawn_log = []
        self.sched_per_obs = {}
        self.executed = {}
        self.cancelled = {}
        self.exp_id = 0
        self.echo_seen = {}
        self.stabilizers_given = 0
        self.last_kinds = deque(maxlen=3)
        self.pattern_logged = set()
        self.failing = False
        self.finished = False
        self.last_obs = None
        self._hz_prev = {}
        self._cleared_all = False
        self.decisions = 0
        self.damage_at_start = 0.0
        self.enabled = True
        self.blackout = 0.0              # seconds of blackout left (0 = lights on)
        self.blackout_total = 0.0
        self.sealed_doors = 0
        self.last_quiet_end = -1e9
        self.revealed = False            # the crew knows MERIDIAN exists
        self.hosts_made = 0
        self.esc = 1.0
        self.last_host_end = -1e9
        self.intent = []

    # ------------------------------------------------------------------ lifecycle
    def begin(self):
        self.exp_id = self.memory.begin_expedition() if not self.passive else 0
        self.note(f"expedition {self.exp_id} seed {self.sim.seed} players {len(self.sim.players)}")
        last = self.history.last_run()
        if last:
            self.note(f"previous: {last['status']} defeats {last['defeats']} patterns {last['patterns']}")

    def note(self, text):
        self.trace.append(f"t={self.sim.time:5.1f} {text}")

    def remember(self, rtype, text, importance=2, entities=()):
        self.memory.record(self.exp_id, rtype, text, importance, entities, t=self.sim.time)

    def _room_name(self, pos):
        r = self.sim.level.room_at(int(pos.x // 48), int(pos.y // 48))
        return r.name if r else "station"

    # ------------------------------------------------------------------ game events (from Sim.emit)
    def on_event(self, e):
        n = e["name"]
        if n == "director" or self.finished:
            return
        self.observer.on_event(e, self.sim.time)
        if self.passive:
            return
        sim = self.sim
        if n == "defeated":
            p = sim.players[e["player"]]
            self.echo_seen.setdefault(e["player"], sim.time)
            self.remember("defeated", f"{p.name} fell in the {self._room_name(e['pos'])}.", 3,
                          [f"player:{p.name.split()[0]}", f"room:{self._room_name(e['pos'])}"])
        elif n == "revived":
            p = sim.players[e["player"]]
            self.echo_seen.pop(e["player"], None)
            self.remember("revived", f"{p.name} was rekindled.", 3, [f"player:{p.name.split()[0]}"])
        elif n == "relay_online":
            self.remember("relay", f"Relay {e['done']}/{e['total']} restored.", 2, [f"room:{self._room_name(e['pos'])}"])
        elif n == "host_born":
            first = not self.revealed
            self.revealed = True
            sim.exposed = True
            sim.crew_lock_enabled = True
            self.flags.add("host_born")
            if first:
                self.flags.add("director_revealed")
                self.note("REVEAL the crew now knows MERIDIAN exists")
        elif n == "host_cured":
            self.last_host_end = sim.time
            p = sim.players[e["player"]]
            self.remember("host_cured", f"{p.name} was freed from the Host.", 5, [f"player:{e['player']}"])
        elif n == "mission_end":
            self._finish(e)
        self.story.on_game_event(e)

    # ------------------------------------------------------------------ per frame
    def update(self, dt):
        sim = self.sim
        if sim.finished or self.finished:
            return
        now = sim.time
        self.observer.frame(now)
        E = self.cfg["escalation"]
        self.esc = 1.0 + (E["cap"] - 1.0) * clamp(now / E["ramp_s"], 0.0, 1.0)
        if self.revealed:
            self.esc *= self.cfg["reveal"]["esc_boost"]
        self.budget.esc = 1.0 if self.passive else self.esc
        self.budget.extra_threats = 1 if (now >= E["third_threat_after"] and not self.passive) else 0
        self.budget.gap_floor = E["min_gap_floor"]
        # blackout is driven by its event; tick the remaining time down here as well so renderers can fade
        if self.blackout > 0:
            self.blackout = max(0.0, self.blackout - dt)
        self.budget.tick(dt)
        self.t_sample -= dt
        if self.t_sample <= 0:
            self.t_sample = self.cfg["sample_interval"]
            self.observer.sample(now)
            self._update_heading()
            al = [p for p in sim.players if p.alive]
            hp = [p.hp / p.max_hp for p in al] or [0.0]
            if len(self.series) < 6000:
                self.series.append((round(now, 1), round(self.observer.tension, 3), sum(hp) / len(hp), min(hp), len(sim.players) - len(al)))
        if self.passive:
            return
        self._run_events(dt)
        if not any(p.alive for p in sim.players):
            self._stand_down()
            return
        self._cleared_all = False
        self.t_think -= dt
        if self.t_think <= 0:
            self.t_think = self.cfg["think_interval"]
            self._think(now)
        self.t_inv -= dt
        if self.t_inv <= 0:
            self.t_inv = 1.0
            self.story.tick(now)
            self._check_invariants(now)

    # ------------------------------------------------------------------ foresight (what the Gauge reads)
    def forecast(self, n=3):
        """The kinds this Director is genuinely leaning toward: events already scheduled first, then its last ranked
        candidates. A true reading of its present intent (not a promise: the next think may change its mind)."""
        out = [e.kind for e in self.events if e.state in (ev.SCHEDULED, ev.ACTIVE) and e.kind not in ("quiet", "resource")]
        for k in getattr(self, "intent", []):
            if k not in out and k not in ("quiet", "resource"):
                out.append(k)
        return out[:n] if out else ["quiet"]

    def plausible_wrong(self, kind, rng):
        pool = [k for k in THREATS + ["rift"] if k != kind]
        return pool[rng.randrange(len(pool))]

    def _update_heading(self):
        c = self.obs_centroid(self.sim)
        if c is None:
            return
        self._pos_hist.append(V(c))
        if len(self._pos_hist) >= 6:
            d = self._pos_hist[-1] - self._pos_hist[0]
            self.heading = d.normalize() if d.length() > 60 else None

    def obs_centroid(self, sim):
        al = [p for p in sim.players if p.alive]
        if not al:
            return None
        return sum((p.pos for p in al), V(0, 0)) / len(al)

    # ------------------------------------------------------------------ safety predicates
    def protect_now(self, sim):
        """The Rekindling (and any recovery window) takes priority: no new threats while it is active or a quiet interval runs."""
        if not any(p.alive for p in sim.players):
            return True
        return ev.ritual_active(sim) or sim.time < self.quiet_until

    def pending_added(self):
        n = 0
        for e in self.events:
            if e.state in (ev.SCHEDULED, ev.ACTIVE) and isinstance(e, ev._SpawnBase) and not getattr(e, "spawned", False):
                n += len(e.p["kinds"])
        return n

    def room_for(self, sim, n):
        alive = sum(1 for e in sim.enemies if not e.dead)
        added = sum(1 for e in sim.enemies if not e.dead and getattr(e, "director", False))
        pend = self.pending_added()
        return (alive + pend + n <= BAL.enemy_common.max_alive) and (added + pend + n <= self.cfg["budget"]["max_alive_added"])

    def active_threats(self):
        return sum(1 for e in self.events if e.state in (ev.SCHEDULED, ev.ACTIVE) and e.category == "threat")

    def door_candidates(self, sim):
        c = self.obs_centroid(sim)
        if c is None:
            return []
        out = []
        for i, d in enumerate(sim.doors):
            dist = d.center.distance_to(c)
            if d.kind != "normal" or dist < 200 or dist > 1000:
                continue
            ahead = 0.0
            if self.heading is not None:
                v = d.center - c
                ahead = V(v).normalize().dot(self.heading) if v.length_squared() else 0.0
            out.append((-(ahead), dist, i))
        out.sort()
        return [i for _, _, i in out]

    # ------------------------------------------------------------------ event execution
    def _run_events(self, dt):
        sim = self.sim
        for e in list(self.events):
            if e.state == ev.SCHEDULED and sim.time >= e.start_at:
                ok, why = e.validate(sim, "execute")          # revalidate at execution time
                if not ok:
                    e.cancel(sim, why)
                    self._count(self.cancelled, e.kind)
                    self.budget.refund(e.kind, sim.time)
                    self.note(f"CANCEL {e.label()} before start: {why}")
                    continue
                e.start(sim)
                self._count(self.executed, e.kind)
                self.note(f"START  {e.label()} ({e.reason})")
            elif e.state == ev.ACTIVE:
                if e.category == "threat" and e.kind in ("reinforce", "flank", "optional_encounter") and ev.ritual_active(sim) \
                        and not getattr(e, "spawned", True):
                    e.cancel(sim, "ritual started")
                    self._count(self.cancelled, e.kind)
                    self.note(f"CANCEL {e.label()} while active: ritual started")
                    continue
                e.on_tick(sim, dt)
                if getattr(e, "aborted", False):
                    e.cancel(sim, "aborted at execution")
                    self._count(self.cancelled, e.kind)
                    continue
                if e.finished(sim):
                    e.resolve(sim)
                    self.note(f"END    {e.label()}")
        self.events = [e for e in self.events if e.state in (ev.SCHEDULED, ev.ACTIVE)]

    def _stand_down(self):
        """Nobody is alive: cancel everything pending and spawn nothing, so the sim's own failure rule decides the ending."""
        if self._cleared_all:
            return
        self._cleared_all = True
        for e in list(self.events):
            e.cancel(self.sim, "no living players")
            self._count(self.cancelled, e.kind)
        self.events = []
        self.note("stand down: no living players")

    @staticmethod
    def _count(d, k):
        d[k] = d.get(k, 0) + 1

    # ------------------------------------------------------------------ thinking
    def _think(self, now):
        sim = self.sim
        cfg = self.cfg
        self.obs_id += 1
        o = self.observer.snapshot(now)
        self.last_obs = o
        if now < cfg["min_observation"]:
            return
        cost_ref = BAL.ritual.base_cost + sim.fracture
        adapted = update_patterns(self.patterns, o, cfg, cost_ref, self.history)
        for name in adapted:
            self.flags.add("adapted_any")
            self.note(f"ADAPT  crew adapted to our '{name}' counter (conf {self.patterns[name].conf:.2f})")
            self.remember("adapted", f"The crew stopped relying on {name}.", 3, [f"pattern:{name}"])
        for name, st in self.patterns.items():
            if st.active and name not in self.pattern_logged:
                self.pattern_logged.add(name)
                self.remember("pattern", f"Pattern recognised: {name}.", 2, [f"pattern:{name}"])
        self.failing = self.budget.apply_failure_policy(now, o.defeats_win, cfg["recovery"])
        self._update_mode(o, now)
        needs = self._rekindle_needs(o, now)
        # scheduled threats that would now pressure a Rekindling are cancelled before they start
        if ev.ritual_active(sim):
            for e in self.events:
                if e.state == ev.SCHEDULED and e.category == "threat":
                    e.cancel(sim, "ritual active")
                    self._count(self.cancelled, e.kind)
                    self.budget.refund(e.kind, now)
                    self.note(f"CANCEL {e.label()} scheduled: ritual active")
        cands, rejected = self._candidates(o, needs, now)
        self.intent = []
        for c in sorted(cands, key=lambda c: -c[0]):
            if c[1] not in self.intent:
                self.intent.append(c[1])
        choice = None
        if cands:
            top = max(c[0] for c in cands)
            best = [c for c in cands if c[0] >= top - 1e-9]
            choice = best[self.rng.randrange(len(best))] if len(best) > 1 else best[0]
        self.decisions += 1
        line = (f"#{self.obs_id} {self.mode[:1].upper()} T={o.tension:.2f} B={self.budget.points:.0f} hp={o.hp_mean:.2f} "
                f"pat[{self._pattern_str()}]")
        if choice:
            score, kind, params, reason = choice
            line += f" -> {kind} ({reason})"
            self._schedule(kind, params, reason, now)
        else:
            line += " -> hold"
        if rejected:
            line += " | rej " + "; ".join(rejected[:3])
        self.note(line)
        if now > 25.0 and self.obs_id % 10 == 0:
            self.story.maybe_callback(now)

    def _pattern_str(self):
        parts = [f"{n[:5]} {st.conf:.2f}{'*' if st.active else ''}" for n, st in self.patterns.items() if st.conf >= 0.2 or st.active]
        return ",".join(parts) or "-"

    def _update_mode(self, o, now):
        t = self.cfg["tension"]
        trouble = o.hp_min < t["trouble_hp"] or o.down > 0
        dwell = now - self.mode_since
        if self.mode == "build":
            if (o.tension >= t["relax_enter"] or trouble) and dwell >= t["build_dwell"]:
                self.mode, self.mode_since = "relax", now
                self.note(f"MODE   -> relax (T={o.tension:.2f} trouble={trouble})")
        else:
            if o.tension < t["relax_exit"] and not trouble and dwell >= t["relax_dwell"]:
                self.mode, self.mode_since = "build", now
                self.note(f"MODE   -> build (T={o.tension:.2f})")

    # ------------------------------------------------------------------ Rekindling priority
    def _rekindle_needs(self, o, now):
        sim, rk = self.sim, self.cfg["rekindle"]
        needs = {"shortage": 0, "unrecovered": 0.0, "pressure": False, "fracture": sim.fracture >= rk["fracture_high"], "near": None}
        open_echoes = [e for e in sim.echoes if e.state in ("dropped", "carried", "placed", "ritual")]
        for e in open_echoes:
            self.echo_seen.setdefault(e.player_idx, now)
            if not e.paid and e.state in ("dropped", "carried"):
                short = e.cost - sim.team_salvage
                if short > needs["shortage"]:
                    needs["shortage"] = short
                    needs["near"] = V(e.pos)
            if e.state in ("dropped", "carried"):
                needs["unrecovered"] = max(needs["unrecovered"], now - self.echo_seen[e.player_idx])
        for pidx in list(self.echo_seen):
            if not any(e.player_idx == pidx for e in open_echoes) and sim.players[pidx].alive:
                self.echo_seen.pop(pidx, None)
        # enemies clustering around an anchor that is in use (or about to be)
        for a in sim.anchors:
            in_use = a.echo is not None or any(e.state == "carried" and e.pos.distance_to(a.pos) < 700 for e in open_echoes)
            if not in_use:
                continue
            n = sum(1 for e in sim.enemies if not e.dead and e.pos.distance_to(a.pos) < rk["cluster_radius"])
            if n >= rk["cluster_count"] or (a.echo is not None and n >= 1 and any(en.alert_t > 0 and en.pos.distance_to(a.pos) < 450 for en in sim.enemies if not en.dead)):
                needs["pressure"] = True
        return needs

    # ------------------------------------------------------------------ candidates
    def _candidates(self, o, needs, now):
        sim, cfg, B = self.sim, self.cfg, self.budget
        cands, rejected = [], []
        ritual = ev.ritual_active(sim)

        def consider(kind, params, base, reason):
            cls = ev.EVENT_CLASSES[kind]
            probe = cls(0, self, params, now + params.get("delay", 0.0), cfg["events"][kind].get("duration", 0.0), reason, self.obs_id)
            ok, why = B.check(kind, now, self.active_threats())
            if ok:
                ok, why = probe.validate(sim, "schedule")
            if not ok:
                rejected.append(f"{kind}:{why}")
                return
            cands.append((base * self.rng.uniform(0.95, 1.05), kind, params, reason))

        rk = cfg["rekindle"]
        # 1. Rekindling priority (always considered first, regardless of pacing)
        if needs["shortage"] > 0:
            n = int(min(4, needs["shortage"] + 1))
            consider("resource", {"pickup": "salvage", "n": n, "near": needs["near"], "ring": (140, 300),
                                  "say": "Salvage signature detected near the recovery route."}, 100.0, f"Rekindling short by {needs['shortage']:.0f}")
        if needs["pressure"]:
            consider("quiet", {"say": "Hostile activity near the anchor is being suppressed. Hurry."}, 95.0, "enemies clustering at an anchor")
        if needs["unrecovered"] > rk["echo_unrecovered_s"]:
            consider("quiet", {"say": "Station interference is easing. The Echo is still out there."}, 90.0, f"Echo unrecovered {needs['unrecovered']:.0f}s")
        if needs["fracture"] and self.stabilizers_given < rk["max_stabilizers"]:
            consider("resource", {"pickup": "stabilizer", "n": 1, "ring": (200, 380),
                                  "say": "A stabilizer canister was left nearby."}, 80.0, f"Fracture {sim.fracture}")
        if cands:
            return cands, rejected
        if ritual:
            return cands, rejected               # never add anything to an active ritual
        if o.alive == [] or not o.alive:
            return cands, rejected

        trouble = o.hp_min < cfg["tension"]["trouble_hp"] or o.down > 0
        if self.failing:
            consider("quiet", {"say": "The station draws breath. Recover."}, 70.0, "recovery policy after repeated failures")
            if sim.team_salvage < 8:
                consider("resource", {"pickup": "salvage", "n": 3, "ring": (200, 400), "say": "Supplies appeared nearby."}, 60.0, "recovery policy: supplies")
            return cands, rejected

        if self.mode == "relax" or trouble:
            if trouble:
                consider("quiet", {"say": "The station draws breath. Recover."}, 50.0 + 20 * (1 - o.hp_min), f"players in trouble (hp {o.hp_min:.2f}, down {o.down})")
            if o.hp_mean < 0.7 and "hoarding" not in self._active() and "resurrection_reliance" not in self._active():
                consider("resource", {"pickup": "salvage", "n": 2, "ring": (180, 380)}, 30.0 + 20 * (1 - o.hp_mean), "relax: supplies")
            return cands, rejected

        # 2. build mode: threats scored by pattern counters, variety and situation
        if now < cfg["opening_grace"]:
            return cands, rejected
        from src.systems import rift as R
        rc = R.cfg()
        if self.rng.random() < rc["eligibility"]["chance_per_think"]:
            # Host selection is requested only from evidence (taint, relays, crew state): rift.select_ready, never the clock
            consider("rift_select", {"lead": cfg["events"]["rift_select"]["lead"]}, 140.0,
                     f"Rift pressure {R.pressure(sim, now):.2f}: the evidence says the Rift should choose")
            if cands:
                return cands, rejected
        if self.rng.random() < cfg["false_tell"]["chance_per_think"] * self.esc:
            consider("false_tell", {"lead": cfg["false_tell"]["lead"]}, 12.0, "MERIDIAN lies")
        if self.rng.random() < 0.18:
            consider("rift", {"lead": cfg["events"]["rift"]["lead"]}, 40.0, "ordinary Rift (no selection)")
        counters = self._counter_multipliers(now)
        low = cfg["tension"]["relax_exit"]
        size = int(clamp(round((2 + 0.8 * len(o.alive) + now / 150.0) * B.scale * self.esc), 2, cfg["safety"]["max_group"]))
        for kind in THREATS:
            spec = cfg["events"][kind]
            w = spec["weight"] * 10.0
            m, why = counters.get(kind, (1.0, None))
            w *= m
            if kind in self.last_kinds:
                w *= 0.55
            w *= 1.0 + max(0.0, low - o.tension)            # a quieter moment invites more pressure
            reason = f"counter {why}" if why else "pacing"
            params = {"warn": spec["warn"], "duration": spec.get("duration", 0.0)}
            if kind in ("reinforce", "flank"):
                n = size if kind == "reinforce" else max(2, size - 1)
                if why == "split":
                    n = max(2, int(n * 0.7))
                bias = "ranged" if kind == "flank" or why in ("rush", "melee_dominance") else ("melee" if why == "ranged_dominance" else self.comp_bias)
                params["kinds"] = self._compose(n, bias, now)
                params["pattern"] = why
            elif kind in ("route_closure", "seal"):
                params["door"] = o.top_door if why == "route" else None
                params["pattern"] = why
            elif kind == "hunter":
                params["kinds"] = ["brute"]
                params["pattern"] = why
            elif kind == "ambush":
                n = int(clamp(size + 2, 4, cfg["safety"]["max_group"] + 2))
                params["kinds"] = self._compose(n, "ranged" if why in ("rush", "ranged_dominance") else self.comp_bias, now)
                params["sides"] = 3 if len(o.alive) > 1 else 2
                params["pattern"] = why
                if 0.0 <= now - self.last_quiet_end <= cfg["ambush"]["quiet_window"]:
                    w *= 2.4                                # the false calm: strike right after a quiet interval
                    params["reason_tag"] = "false calm"
            elif kind in ("hazard", "power_failure", "modifier", "optional_encounter", "isolate", "blackout"):
                params["pattern"] = why
            if kind in ("isolate", "blackout", "seal", "hunter", "ambush"):
                w *= 1.0 + (self.esc - 1.0) * cfg["escalation"]["surprise_boost"]
            consider(kind, params, w, reason)
        for bias, pats in (("melee", ["ranged_dominance"]), ("ranged", ["melee_dominance", "rush"])):
            for pn in pats:
                if pn in counters.get("_active", ()):
                    m, why = counters.get("composition", (1.0, None))
                    consider("composition", {"bias": bias, "pattern": pn}, cfg["events"]["composition"]["weight"] * 10.0 * m, f"counter {pn}")
                    break
        # a small supply opportunity when the crew is low on salvage and not hoarding or leaning on revives
        if sim.team_salvage < cost_ref_floor(sim) and not (self._active() & {"hoarding", "resurrection_reliance"}):
            consider("resource", {"pickup": "salvage", "n": 2, "ring": (220, 420)}, 6.0, "opportunity: low salvage")
        return cands, rejected

    def _active(self):
        return {n for n, st in self.patterns.items() if st.active and not st.adapted}

    def _counter_multipliers(self, now):
        """kind -> (multiplier, pattern) from the strongest applicable active pattern. Counters are bounded: at most
        `max_counters` per pattern per expedition, with a cooldown, and none once the crew has adapted."""
        P = self.cfg["patterns"]
        out = {}
        act = []
        for name, st in self.patterns.items():
            if not st.active or st.adapted or st.counters >= P["max_counters"] or now - st.last_counter_t < P["counter_cooldown"]:
                continue
            act.append(name)
            for kind, m in self.cfg["counters"].get(name, {}).items():
                m2 = 1.0 + (m - 1.0) * st.conf               # scaled by confidence: weak evidence, weak counter
                if kind not in out or m2 > out[kind][0]:
                    out[kind] = (m2, name)
        out["_active"] = act
        # suppress resource opportunities handled by callers; hoarding suppresses nothing else
        return out

    def _compose(self, n, bias, now):
        c = self.cfg["composition"]
        table = dict(c["base"])
        if bias == "ranged":
            table = dict(c["ranged_bias"])
        elif bias == "melee":
            table = dict(c["melee_bias"])
        if now < c["brute_after"]:
            table.pop("brute", None)
        kinds, weights = list(table), list(table.values())
        return [self.rng.choices(kinds, weights)[0] for _ in range(n)]

    # ------------------------------------------------------------------ scheduling
    def _schedule(self, kind, params, reason, now):
        spec = self.cfg["events"][kind]
        if self.sched_per_obs.get(self.obs_id, 0) >= 1:      # one event per observation: no chain escalation
            self.note(f"REFUSE {kind}: already scheduled one event for observation #{self.obs_id}")
            return None
        delay = params.get("delay", 1.0 if spec["category"] != "recovery" else 0.5)
        e = ev.EVENT_CLASSES[kind](self.next_id, self, params, now + delay, spec.get("duration", 0.0), reason, self.obs_id)
        self.next_id += 1
        ok, why = e.validate(self.sim, "schedule")
        if not ok:
            self.note(f"REFUSE {kind}: {why}")
            return None
        self.sched_per_obs[self.obs_id] = self.sched_per_obs.get(self.obs_id, 0) + 1
        self.budget.commit(kind, now)
        self.events.append(e)
        if kind in ("reinforce", "flank", "route_closure", "power_failure", "hazard", "optional_encounter", "modifier", "composition",
                    "isolate", "blackout", "seal", "hunter", "ambush", "rift", "rift_select"):
            self.last_kinds.append(kind)
        pat = params.get("pattern")
        if pat and pat in self.patterns:
            st = self.patterns[pat]
            st.counters += 1
            st.last_counter_t = now
            st.counter_t = now
            st.conf_at_counter = st.conf
            self.note(f"COUNTER {pat} (conf {st.conf:.2f}; evidence: {'; '.join(st.evidence)}) -> {kind}")
        if kind == "resource" and params.get("pickup") == "stabilizer":
            self.stabilizers_given += 1
        return e

    # ------------------------------------------------------------------ invariants
    def _check_invariants(self, now):
        sim, cfg = self.sim, self.cfg
        v = []
        if self.active_threats() > cfg["budget"]["max_simultaneous_threats"] + self.budget.extra_threats:   # escalation raises the cap by a documented 1
            v.append(f"{self.active_threats()} simultaneous threats")
        added = sum(1 for e in sim.enemies if not e.dead and getattr(e, "director", False))
        if added > cfg["budget"]["max_alive_added"]:
            v.append(f"{added} director enemies alive")
        for e in self.events:
            if isinstance(e, ev.RouteClosureEvent) and e.state == ev.ACTIVE and getattr(e, "locked", False):
                if not ev.connectivity_ok(sim):
                    v.append(f"{e.label()}: mandatory target unreachable while closed")
        for hz in sim.floor_hazards:
            if getattr(hz, "director", False):
                prev = self._hz_prev.get(id(hz), "idle")
                if hz.state == "active" and prev not in ("warning", "active"):
                    v.append("director hazard went active without a warning")
                self._hz_prev[id(hz)] = hz.state
        for s in self.spawn_log:
            if s.get("checked"):
                continue
            s["checked"] = True
            if s["min_player_dist"] < cfg["safety"]["spawn_clear"] - 1:
                v.append(f"spawn {s['dist']:.0f}px from a player")
            if s["ritual"]:
                v.append("spawn during an active ritual")
            if s["alive_before"] + s["n"] > BAL.enemy_common.max_alive:
                v.append(f"spawn of {s['n']} with {s['alive_before']} alive exceeds the cap")
            if s["warn"] < cfg["safety"]["min_warn"] - 1e-6:
                v.append(f"spawn warning only {s['warn']:.1f}s")
        for oid, n in self.sched_per_obs.items():
            if n > 1:
                v.append(f"observation {oid} scheduled {n} events")
        for msg in v:
            self.violations.append((round(now, 1), msg))
            self.note(f"VIOLATION {msg}")

    # ------------------------------------------------------------------ end of expedition
    def _finish(self, e):
        if self.finished or self.passive:
            return
        self.finished = True
        sim = self.sim
        for ev_ in list(self.events):
            ev_.cancel(sim, "expedition ended")
        self.events = []
        status = e["status"]
        res = sim.result or {}
        self.remember("extracted" if status == "extracted" else "failed",
                      "The crew extracted." if status == "extracted" else f"The crew was lost ({e.get('reason', '')}).",
                      4 if status != "extracted" else 3, [f"seed:{sim.seed}"])
        mins = max(1e-6, sim.time / 60.0)
        run = {"exp": self.exp_id, "status": status, "seed": sim.seed, "time": round(sim.time, 1), "defeats": sim.defeats,
               "revivals": sim.revivals, "decisions": self.decisions, "damage_per_min": round(self.observer.dmg_total / mins, 1),
               "patterns": {n: st.max_conf for n, st in self.patterns.items()},
               "adapted": [n for n, st in self.patterns.items() if st.adapted],
               "events": dict(self.executed), "trace": list(self.trace)[-120:]}
        self.history.add(run)
        self.memory.save()
        self.history.save()
        if self.log_path or os.environ.get("DEADAIR_DIRECTOR_LOG"):
            try:
                path = self.log_path or (os.environ.get("DEADAIR_DIRECTOR_LOG_PATH") or "director_trace.log")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"=== expedition {self.exp_id} seed {sim.seed} {status} ===\n" + "\n".join(self.trace) + "\n")
            except OSError:
                pass

    # ------------------------------------------------------------------ debug
    def debug_lines(self):
        o = self.last_obs
        lines = [f"MERIDIAN {self.mode} T={self.observer.tension:.2f} budget={self.budget.points:.0f} "
                 f"threats={self.active_threats()} quiet={'Y' if self.sim.time < self.quiet_until else 'n'} fail={'Y' if self.failing else 'n'}",
                 "patterns: " + (self._pattern_str() or "-"),
                 "events: " + (", ".join(f"{e.label()}:{e.state[:3]}" for e in self.events) or "-")]
        lines += list(self.trace)[-4:]
        return lines

    def trace_text(self, n=40):
        return "\n".join(list(self.trace)[-n:])


def cost_ref_floor(sim):
    return 1.5 * (BAL.ritual.base_cost + sim.fracture)
