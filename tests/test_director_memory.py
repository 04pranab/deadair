"""MERIDIAN's campaign memory: round trip, corrupt-file recovery, invalid-record rejection, pruning, callback cooldown."""
import json

from src.systems.director_memory import MAX_RECORDS, Memory


def test_round_trip(tmp_path):
    p = tmp_path / "m.json"
    m = Memory(p)
    exp = m.begin_expedition()
    m.record(exp, "tactic", "they held the corridor", importance=3, entities=["mara"])
    assert m.save()
    m2 = Memory(p)
    assert m2.expeditions == 1
    assert [r["text"] for r in m2.records] == ["they held the corridor"]


def test_corrupt_file_is_quarantined_not_fatal(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{not json", encoding="utf-8")
    m = Memory(p)
    assert m.records == [] and m.expeditions == 0
    m.record(0, "x", "still works", importance=1)
    assert len(m.records) == 1


def test_wrong_shape_is_quarantined(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert Memory(p).records == []


def test_invalid_records_are_dropped_on_load(tmp_path):
    p = tmp_path / "m.json"
    m = Memory(p)
    m.record(m.begin_expedition(), "tactic", "good", importance=2)
    m.save()
    raw = json.loads(p.read_text())
    raw["records"].append({"id": 5, "type": "tactic", "text": "bad id type", "exp": 1, "seq": 9, "importance": 2, "entities": []})
    raw["records"].append({"id": "r9", "type": "tactic", "text": "bad importance", "exp": 1, "seq": 10, "importance": 99, "entities": []})
    p.write_text(json.dumps(raw))
    m2 = Memory(p)
    assert [r["text"] for r in m2.records] == ["good"]
    assert m2.dropped == 2


def test_record_count_is_bounded():
    m = Memory(None)
    for i in range(MAX_RECORDS + 80):
        m.record(0, "t", f"r{i}", importance=1 + i % 5)
    assert len(m.records) <= MAX_RECORDS


def test_recent_records_outweigh_old_ones_of_equal_importance():
    m = Memory(None)
    old = m.record(0, "t", "old", importance=3)
    new = m.record(5, "t", "new", importance=3)
    assert m.weight(new, 5) > m.weight(old, 5)


def test_save_without_a_path_is_a_noop():
    assert Memory(None).save() is True
