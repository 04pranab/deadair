"""Local save data: settings, banked salvage, upgrades, run records, discovered clues. Corruption-safe."""
import json
import os
import time

from src.config import BAL
from src.settings import RESOLUTIONS, save_dir

VERSION = 1
MAX_RUNS = 60


def default_data():
    return {"version": VERSION,
            "settings": {"fullscreen": False, "resolution": 0, "shake": True, "volume": 0.8, "solo_assist": True, "debug": False, "cinematics": True},
            "bank": 0, "upgrades": {}, "runs": [], "clues": [], "seed_counter": int(time.time()) % 100000}


def _clean(raw):
    """Merge untrusted JSON into defaults, keeping only values of the right type and range."""
    d = default_data()
    if not isinstance(raw, dict):
        return d
    s = raw.get("settings")
    if isinstance(s, dict):
        for k, v in d["settings"].items():
            if k in s and isinstance(s[k], type(v)) and not (isinstance(v, bool) != isinstance(s[k], bool)):
                d["settings"][k] = s[k]
        d["settings"]["resolution"] = min(max(0, int(d["settings"]["resolution"])), len(RESOLUTIONS) - 1)
        d["settings"]["volume"] = min(1.0, max(0.0, float(d["settings"]["volume"])))
    if isinstance(raw.get("bank"), int) and raw["bank"] >= 0:
        d["bank"] = raw["bank"]
    up = raw.get("upgrades")
    if isinstance(up, dict):
        for k, spec in BAL.upgrades.items():
            v = up.get(k)
            if isinstance(v, int) and 0 <= v <= spec["max"]:
                d["upgrades"][k] = v
    if isinstance(raw.get("runs"), list):
        d["runs"] = [r for r in raw["runs"] if isinstance(r, dict) and "status" in r][-MAX_RUNS:]
    if isinstance(raw.get("clues"), list):
        d["clues"] = [c for c in raw["clues"] if isinstance(c, str)]
    if isinstance(raw.get("seed_counter"), int):
        d["seed_counter"] = raw["seed_counter"]
    return d


class SaveData:
    def __init__(self, path=None):
        self.path = path or (save_dir() / "save.json")
        self.recovered = False
        self.data = default_data()
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self._quarantine()
            return
        self.data = _clean(raw)

    def _quarantine(self):
        """Keep the unreadable file for inspection, then continue with defaults."""
        self.recovered = True
        self.data = default_data()
        try:
            self.path.replace(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}"))
        except OSError:
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    # -- accessors --
    @property
    def settings(self):
        return self.data["settings"]

    @property
    def upgrades(self):
        return self.data["upgrades"]

    def next_seed(self):
        self.data["seed_counter"] += 1
        return self.data["seed_counter"]

    def record_run(self, result):
        self.data["runs"].append({k: result[k] for k in ("status", "seed", "modifier", "time", "salvage", "banked", "revivals",
                                                         "defeats", "kills", "optional_done", "relays", "relays_total", "fracture_max")})
        self.data["runs"] = self.data["runs"][-MAX_RUNS:]
        self.data["bank"] += int(result["banked"])
        new = [c for c in result["logs"] if c not in self.data["clues"]]
        self.data["clues"].extend(new)
        self.save()
        return new

    def buy(self, key):
        spec = BAL.upgrades[key]
        lvl = self.data["upgrades"].get(key, 0)
        if lvl >= spec["max"] or self.data["bank"] < spec["cost"] * (lvl + 1):
            return False
        self.data["bank"] -= spec["cost"] * (lvl + 1)
        self.data["upgrades"][key] = lvl + 1
        self.save()
        return True

    def upgrade_cost(self, key):
        return BAL.upgrades[key]["cost"] * (self.data["upgrades"].get(key, 0) + 1)
