"""The blinded pilot review pack (plan section 7), 2026-09-13."""
import csv
import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "cat_pyq"))

from rc_engine import config  # noqa: E402
from rc_engine.history import HistoryStore  # noqa: E402
from rc_engine.llm import MockLLMClient  # noqa: E402
from rc_engine.pipeline import RCPipeline, run_batch  # noqa: E402
from pilot_review_pack import blind, build  # noqa: E402


def _ship(db, policy, counts, monkeypatch):
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": policy, "hard": policy, "elite": ""})
    h = HistoryStore(db)
    run_batch(RCPipeline(h, MockLLMClient(), embed=False, rng=random.Random(4)), counts, None,
              max_usd=10.0)
    h.close()


def test_pack_is_blind_mixed_and_keyed(tmp_path, monkeypatch):
    db = str(tmp_path / "pilot.db")
    _ship(db, "", {"medium": 2, "hard": 2}, monkeypatch)
    _ship(db, "cat-pyq-q1", {"medium": 2, "hard": 2}, monkeypatch)
    out = tmp_path / "pack"
    summary = build(db, str(out), "cat-pyq-q1", "AA", baseline=0, seed=1)
    assert summary["pilot"] == 4 and summary["sets"] == 8
    key = json.loads((out / "KEY_do_not_open.json").read_text(encoding="utf-8"))
    assert {v["policy"] for v in key.values()} == {"cat-pyq-q1", "legacy"}
    for sid in key:
        text = (out / "sets" / f"{sid}.txt").read_text(encoding="utf-8")
        assert "RC-" not in text and "[Inspired by:" not in text and "cat-pyq" not in text
    rows = list(csv.DictReader(open(out / "review_sheet.csv", encoding="utf-8")))
    negated = [r for r in rows if r["check"].startswith("negated")]
    pilot_sets = {s for s, v in key.items() if v["policy"] == "cat-pyq-q1"}
    assert {r["set"] for r in negated} == pilot_sets      # mock legacy stems carry no NOT/EXCEPT
    assert all(not r["verdict"] for r in rows)


def test_pack_refuses_to_write_inside_the_repository(tmp_path):
    with pytest.raises(SystemExit):
        build(str(tmp_path / "none.db"), os.path.join(ROOT, "pilot_pack"), "cat-pyq-q1", "AA", 0, 1)


def test_blind_strips_ids_and_source_line():
    text = "[PASSAGE]\n\nRC-HARD-260913-0001 prose\n[Inspired by: \"x\", u]\n"
    assert blind(text) == "[PASSAGE]\n\n[set] prose\n"
