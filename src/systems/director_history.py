"""MERIDIAN per-expedition history: outcomes, pattern tendencies and compact decision traces, persisted as JSON.
Used to start the next expedition with a small, bounded prior about the crew's habits."""
import json
import os
import time

MAX_RUNS = 40
VERSION = 1
PATTERNS = ["route", "rush", "split", "hoarding", "resurrection_reliance", "ranged_dominance", "melee_dominance"]


def _clean_run(r):
    if not isinstance(r, dict) or not isinstance(r.get("exp"), int) or not isinstance(r.get("status"), str):
        return None
    out = {"exp": r["exp"], "status": r["status"], "seed": r.get("seed") if isinstance(r.get("seed"), int) else 0}
    for k in ("time", "damage_per_min"):
        v = r.get(k)
        out[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
    for k in ("defeats", "revivals", "decisions"):
        v = r.get(k)
        out[k] = v if isinstance(v, int) and not isinstance(v, bool) else 0
    pc = r.get("patterns")
    out["patterns"] = {k: round(float(v), 3) for k, v in pc.items() if k in PATTERNS and isinstance(v, (int, float))} if isinstance(pc, dict) else {}
    ad = r.get("adapted")
    out["adapted"] = [a for a in ad if a in PATTERNS] if isinstance(ad, list) else []
    ev = r.get("events")
    out["events"] = {k: v for k, v in ev.items() if isinstance(k, str) and isinstance(v, int)} if isinstance(ev, dict) else {}
    tr = r.get("trace")
    out["trace"] = [t for t in tr if isinstance(t, str)][-160:] if isinstance(tr, list) else []
    return out


class History:
    def __init__(self, path=None):
        self.path = path
        self.runs = []
        self.recovered = False
        self.load()

    def load(self):
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self._quarantine()
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("runs"), list):
            self._quarantine()
            return
        self.runs = [c for c in (_clean_run(r) for r in raw["runs"]) if c][-MAX_RUNS:]

    def _quarantine(self):
        self.recovered = True
        try:
            self.path.replace(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}"))
        except OSError:
            pass

    def save(self):
        if self.path is None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"version": VERSION, "runs": self.runs}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def add(self, run):
        c = _clean_run(run)
        if c:
            self.runs.append(c)
            self.runs = self.runs[-MAX_RUNS:]
        return c

    def prior(self, pattern, cap=0.15, last_n=4):
        """Small bounded prior in [0, cap]: how often the pattern was strong in recent expeditions, reduced if the crew
        adapted to it. It can speed detection but never triggers a counter alone (the director requires current evidence)."""
        recent = self.runs[-last_n:]
        if not recent:
            return 0.0
        strong = sum(1 for r in recent if r["patterns"].get(pattern, 0.0) >= 0.6)
        adapted = sum(1 for r in recent if pattern in r["adapted"])
        v = cap * (strong - 0.5 * adapted) / len(recent)
        return max(0.0, min(cap, v))

    def last_run(self):
        return self.runs[-1] if self.runs else None
