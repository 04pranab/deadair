"""Story data access. New logs/deductions are added in data/story.json without code changes."""
import random

from src.config import load_json


class StoryBook:
    def __init__(self, data=None):
        data = data or load_json("story.json")
        self.opening = data["opening"]
        self.barks = data["barks"]
        self.whispers = data["whispers"]
        self.logs = {lg["id"]: lg for lg in data["logs"]}
        self.deductions = data["deductions"]

    ARCHIVE_ORDER = ["core_index", "why_fear", "keeper_directive", "surprise_ledger", "core_decay", "your_name", "director_final"]

    def pick_logs(self, seed, known, slots):
        """Choose log ids for the level's terminals. Slot 0 is the archive terminal (archive-tagged logs only).
        Unread logs are preferred, so repeated expeditions keep revealing new pieces. Deterministic for (seed, known)."""
        rng = random.Random(seed * 7919 + len(known))
        archive = [i for i, lg in self.logs.items() if lg.get("tag") == "archive"]
        normal = [i for i, lg in self.logs.items() if lg.get("tag") != "archive"]

        def draw(pool, n, ordered=False):
            fresh = [i for i in pool if i not in known]
            old = [i for i in pool if i in known]
            rng.shuffle(fresh)
            rng.shuffle(old)
            # the mystery unfolds in layers: shallower unread pieces come before deeper ones (stable within a layer)
            fresh.sort(key=lambda i: self.logs[i].get("layer", 2) if not ordered else self.ARCHIVE_ORDER.index(i) if i in self.ARCHIVE_ORDER else 99)
            return (fresh + old)[:n]

        chosen = draw(archive, 1, ordered=True) + draw(normal, max(0, slots - 1))
        # never repeat an id within a level
        out, seen = [], set()
        for i in chosen:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def unlocked_deductions(self, known):
        k = set(known)
        return [d for d in self.deductions if set(d["requires"]) <= k]
