"""MERIDIAN threat/recovery budget: points, per-kind cooldowns and limits, simultaneous-threat cap, recovery gaps, and the
recovery policy that backs off after repeated failures. Pure data; no pygame, no game objects."""


class Budget:
    def __init__(self, cfg, events_cfg):
        self.cfg = cfg
        self.ev = events_cfg
        self.points = float(cfg["start"])
        self.cap = float(cfg["cap"])
        self.regen = float(cfg["regen_per_s"])
        self.last_cast = {}            # kind -> time
        self.count = {}                # kind -> executed or scheduled this expedition
        self.last_threat_t = -1e9
        self.last_recovery_t = -1e9
        self.lockout_until = -1e9      # recovery policy: no threats until then
        self.scale = 1.0               # group size scale (recovery policy)
        self.regen_scale = 1.0
        self.esc = 1.0                 # escalation: the shift gets harder as it goes on
        self.extra_threats = 0
        self.gap_floor = 10.0

    def tick(self, dt):
        self.points = min(self.cap, self.points + self.regen * self.regen_scale * self.esc * dt)

    # ------------------------------------------------------------------ queries
    def cost(self, kind):
        return float(self.ev[kind]["cost"])

    def category(self, kind):
        return self.ev[kind]["category"]

    def check(self, kind, now, active_threats):
        """-> (ok, reason). Does not mutate."""
        spec = self.ev[kind]
        if self.count.get(kind, 0) >= spec["limit"]:
            return False, f"{kind}: expedition limit {spec['limit']} reached"
        if now - self.last_cast.get(kind, -1e9) < spec["cooldown"]:
            return False, f"{kind}: cooldown {spec['cooldown'] - (now - self.last_cast.get(kind, -1e9)):.0f}s"
        if spec["category"] == "threat":
            if now < self.lockout_until:
                return False, f"{kind}: recovery lockout {self.lockout_until - now:.0f}s"
            if active_threats >= self.cfg["max_simultaneous_threats"] + self.extra_threats:
                return False, f"{kind}: {active_threats} threats already active"
            gap = max(self.gap_floor, self.cfg["min_threat_gap"] / self.esc)
            if now - self.last_threat_t < gap:
                return False, f"{kind}: min threat gap {gap - (now - self.last_threat_t):.0f}s"
            if now - self.last_recovery_t < self.cfg["min_recovery_gap"] and self.last_recovery_t > -1e8:
                return False, f"{kind}: recovery interval {self.cfg['min_recovery_gap'] - (now - self.last_recovery_t):.0f}s"
            if self.points < spec["cost"]:
                return False, f"{kind}: budget {self.points:.0f}<{spec['cost']}"
        return True, ""

    # ------------------------------------------------------------------ mutation
    def commit(self, kind, now):
        spec = self.ev[kind]
        self.last_cast[kind] = now
        self.count[kind] = self.count.get(kind, 0) + 1
        if spec["category"] == "threat":
            self.points = max(0.0, self.points - spec["cost"])
            self.last_threat_t = now
        elif spec["category"] == "recovery":
            self.last_recovery_t = now
        else:
            self.points = max(0.0, self.points - spec["cost"])

    def refund(self, kind, now):
        """A scheduled event was cancelled before it had any effect: give back the cost and the slot."""
        spec = self.ev[kind]
        if spec["category"] != "recovery":
            self.points = min(self.cap, self.points + spec["cost"])
        self.count[kind] = max(0, self.count.get(kind, 1) - 1)
        if spec["category"] == "threat":
            self.last_threat_t = -1e9
        self.last_cast[kind] = -1e9

    def apply_failure_policy(self, now, defeats_in_window, rcfg):
        """After repeated failures: lock threats out for a while, shrink groups, slow the budget."""
        if defeats_in_window >= rcfg["failure_streak"]:
            if now >= self.lockout_until:
                self.lockout_until = now + rcfg["lockout"]
            self.scale = rcfg["size_scale"]
            self.regen_scale = rcfg["regen_scale"]
            return True
        if now >= self.lockout_until:
            self.scale = 1.0
            self.regen_scale = 1.0
        return False
