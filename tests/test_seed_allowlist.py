"""`generate --seed-ids`: a subject-restricted seed pool (2026-09-14)."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine.cli import _allowlist_seed_picker, _load_seed_ids  # noqa: E402

A = "49f3bf25-cf34-4618-9c79-b7dbb11ba747"
B = "557c4728-4d4e-4838-8520-79163559ea73"
C = "4eb92aa3-7938-46d6-833b-460d5911d111"


def test_seed_id_files_in_every_supported_shape(tmp_path):
    grouped = tmp_path / "g.json"
    grouped.write_text(json.dumps({"note": "x", "philosophy": {A: "one"},
                                   "literature": {B: "two", C: "three"}}), encoding="utf-8")
    assert _load_seed_ids(str(grouped)) == [A, B, C]
    flat = tmp_path / "f.json"
    flat.write_text(json.dumps([A, B, A]), encoding="utf-8")
    assert _load_seed_ids(str(flat)) == [A, B]
    lines = tmp_path / "l.txt"
    lines.write_text(f"# comment\n{A}\n\n{C}\n", encoding="utf-8")
    assert _load_seed_ids(str(lines)) == [A, C]


class _DB:
    def __init__(self, docs):
        self.docs = docs

    def get(self, ids, include):
        hit = [d for d in self.docs if d["id"] in ids]
        return {"ids": [d["id"] for d in hit], "documents": [d["text"] for d in hit],
                "metadatas": [d["meta"] for d in hit]}


def test_picker_only_returns_listed_unused_essays_and_respects_exclusions():
    db = _DB([
        {"id": A, "text": "a", "meta": {"used": False, "kind": "idea_essay"}},
        {"id": B, "text": "b", "meta": {"used": True, "kind": "idea_essay"}},
        {"id": C, "text": "c", "meta": {"used": False, "kind": "criticism"}},
        {"id": "not-listed-0000000000", "text": "z", "meta": {"used": False, "kind": "criticism"}},
    ])
    pick = _allowlist_seed_picker(db, [A, B, C])
    random.seed(1)
    seen = {pick()["id"] for _ in range(40)}
    assert seen == {A, C}                                    # never used, never unlisted
    assert pick(exclude_ids={A})["id"] == C
    assert pick(avoid_kinds=["idea_essay"])["id"] == C       # steered by kind
    assert pick(exclude_ids={C}, avoid_kinds=["idea_essay"])["id"] == A   # never dead-ends
    assert pick(exclude_ids={A, C}) is None
