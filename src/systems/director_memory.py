"""MERIDIAN persistent campaign memory (JSON). Records have ids, expedition ids, ordering, importance and entity ids.
Loading is safe against corrupt or partial data. Callbacks are built only from recorded events or authored lore."""
import json
import os
import time

MAX_RECORDS = 400
VERSION = 1
DECAY = 0.8            # recency weight per expedition of age
MAX_CALLBACK_USES = 2
CALLBACK_COOLDOWN_EXP = 2   # a record is not called back twice within this many expeditions


def _valid_record(r):
    if not isinstance(r, dict):
        return False
    if not isinstance(r.get("id"), str) or not isinstance(r.get("type"), str) or not isinstance(r.get("text"), str):
        return False
    for k in ("exp", "seq"):
        if not isinstance(r.get(k), int) or isinstance(r.get(k), bool) or r[k] < 0:
            return False
    if not isinstance(r.get("importance"), int) or not 1 <= r["importance"] <= 5:
        return False
    if not isinstance(r.get("entities"), list) or not all(isinstance(e, str) for e in r["entities"]):
        return False
    return True


class Memory:
    def __init__(self, path=None):
        self.path = path
        self.records = []
        self.expeditions = 0
        self.next_seq = 0
        self.callbacks_used = {}      # record id -> [uses, last_exp]
        self.recovered = False
        self.dropped = 0              # records discarded as invalid on load
        self.load()

    # ------------------------------------------------------------------ persistence
    def load(self):
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self._quarantine()
            return
        if not isinstance(raw, dict):
            self._quarantine()
            return
        recs = raw.get("records")
        if isinstance(recs, list):
            good = [r for r in recs if _valid_record(r)]
            self.dropped = len(recs) - len(good)
            seen, out = set(), []
            for r in good:
                if r["id"] in seen:
                    self.dropped += 1
                    continue
                seen.add(r["id"])
                r.setdefault("data", {})
                if not isinstance(r["data"], dict):
                    r["data"] = {}
                out.append(r)
            self.records = sorted(out, key=lambda r: (r["exp"], r["seq"]))[-MAX_RECORDS:]
        e = raw.get("expeditions")
        floor = max((r["exp"] for r in self.records), default=0)
        self.expeditions = e if isinstance(e, int) and not isinstance(e, bool) and e >= floor else floor
        ns = raw.get("next_seq")
        self.next_seq = max(ns if isinstance(ns, int) and not isinstance(ns, bool) else 0, max((r["seq"] for r in self.records), default=-1) + 1)
        cu = raw.get("callbacks_used")
        if isinstance(cu, dict):
            for k, v in cu.items():
                if isinstance(k, str) and isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v):
                    self.callbacks_used[k] = v

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
            tmp.write_text(json.dumps({"version": VERSION, "expeditions": self.expeditions, "next_seq": self.next_seq,
                                       "records": self.records, "callbacks_used": self.callbacks_used}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ recording
    def begin_expedition(self):
        self.expeditions += 1
        return self.expeditions

    def record(self, exp, rtype, text, importance=2, entities=(), t=0.0, data=None):
        rid = f"m{self.next_seq:06d}"
        r = {"id": rid, "exp": int(exp), "seq": self.next_seq, "type": rtype, "text": text,
             "importance": max(1, min(5, int(importance))), "entities": [str(e) for e in entities], "t": round(float(t), 1),
             "data": data or {}}
        self.next_seq += 1
        self.records.append(r)
        if len(self.records) > MAX_RECORDS:
            self._prune()
        return r

    def _prune(self):
        """Drop the lowest-value records (importance weighted by recency) down to the cap."""
        now = self.expeditions
        ranked = sorted(self.records, key=lambda r: self.weight(r, now))
        drop = {r["id"] for r in ranked[: len(self.records) - MAX_RECORDS]}
        self.records = [r for r in self.records if r["id"] not in drop]

    # ------------------------------------------------------------------ recall
    def weight(self, r, now_exp):
        age = max(0, now_exp - r["exp"])
        return r["importance"] * (DECAY ** age)

    def by_id(self, rid):
        for r in self.records:
            if r["id"] == rid:
                return r
        return None

    def query(self, rtype=None, exp=None, entity=None):
        out = [r for r in self.records if (rtype is None or r["type"] == rtype) and (exp is None or r["exp"] == exp)
               and (entity is None or entity in r["entities"])]
        return out

    def callback_candidates(self, rtype, now_exp, min_importance=1, exclude_exp=None):
        """Records usable for a callback: not from the running expedition, not over-used, not used recently."""
        out = []
        for r in self.records:
            if r["type"] != rtype or r["importance"] < min_importance or r["exp"] == exclude_exp:
                continue
            uses, last = self.callbacks_used.get(r["id"], [0, -999])
            if uses >= MAX_CALLBACK_USES or now_exp - last < CALLBACK_COOLDOWN_EXP:
                continue
            out.append(r)
        out.sort(key=lambda r: (-self.weight(r, now_exp), -r["seq"]))
        return out

    def mark_used(self, rid, now_exp):
        uses, _ = self.callbacks_used.get(rid, [0, -999])
        self.callbacks_used[rid] = [uses + 1, now_exp]

    def make_callback(self, template, now_exp, fmt_ctx=None):
        """Build a callback from a lore template and a recorded event. -> dict(text, source_ids, callback_id) or None.
        Only fills slots from the record itself (entities/data), never invents facts."""
        for r in self.callback_candidates(template["memory_type"], now_exp, template.get("min_importance", 1), exclude_exp=now_exp):
            slots = _slots_from_record(r)
            try:
                text = template["text"].format(**slots)
            except (KeyError, IndexError):
                continue
            self.mark_used(r["id"], now_exp)
            return {"text": text, "source_ids": [r["id"]], "callback_id": template["id"]}
        return None


def _slots_from_record(r):
    slots = {"name": "someone", "room": "station", "pattern": "a habit"}
    for e in r["entities"]:
        kind, _, val = e.partition(":")
        if kind == "player":
            slots["name"] = val
        elif kind == "room":
            slots["room"] = val
        elif kind == "pattern":
            slots["pattern"] = val.replace("_", " ")
    return slots
