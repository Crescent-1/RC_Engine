"""Per-policy reporting and re-reads (plan 7.5 and the section 3 follow-up), 2026-09-13.

  - every attempt records its generation policy, including attempts that died
    before a blueprint existed;
  - `policy-report` never pools policies or tiers, and reads closure as three
    classes (a neutral exposition is not a refusal);
  - `move-audit` re-reads each set with the vocabulary of the policy its plan
    was composed under, never with today's legacy vocabulary.
"""
import argparse
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.history import HistoryStore  # noqa: E402
from rc_engine.llm import MockLLMClient  # noqa: E402
from rc_engine.models import RCResult, SeedEssay  # noqa: E402
from rc_engine.pipeline import RCPipeline, run_batch  # noqa: E402
from rc_engine.policy_catalog import CAT_PYQ_Q1  # noqa: E402
from rc_engine.policy_report import closure_class, collect  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "report.db")


def _batch(db, counts, policy, monkeypatch):
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": policy, "hard": policy, "elite": ""})
    history = HistoryStore(db)
    pipe = RCPipeline(history, MockLLMClient(), embed=False, rng=random.Random(11))
    results = run_batch(pipe, counts, None, max_usd=10.0)
    history.close()
    return results


def test_attempts_record_policy_even_without_a_blueprint(db, monkeypatch):
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": CAT_PYQ_Q1, "hard": CAT_PYQ_Q1, "elite": ""})
    h = HistoryStore(db)
    h.record_attempt("b1", "hard", 1, 1, RCResult(None, "", "hard", "failed_composition"))
    h.record_attempt("b1", "elite", 1, 1, RCResult(None, "", "elite", "failed_composition"))
    rows = h.conn.execute("SELECT tier, generation_policy FROM attempts ORDER BY id").fetchall()
    assert rows == [("hard", CAT_PYQ_Q1), ("elite", "")]
    h.close()


def test_report_separates_policy_and_tier(db, monkeypatch):
    _batch(db, {"medium": 2, "hard": 2, "elite": 1}, CAT_PYQ_Q1, monkeypatch)
    _batch(db, {"hard": 2}, "", monkeypatch)
    h = HistoryStore(db)
    rows = {(r["tier"], r["policy"]): r for r in collect(h)}
    h.close()
    assert set(rows) == {("medium", CAT_PYQ_Q1), ("hard", CAT_PYQ_Q1),
                         ("elite", "legacy"), ("hard", "legacy")}
    pol, leg = rows[("hard", CAT_PYQ_Q1)], rows[("hard", "legacy")]
    assert pol["sets"] == 2 and leg["sets"] == 2
    assert pol["attempts"] >= 2 and leg["attempts"] >= 2
    assert sum(pol["negation"]["planned_by_task"].values()) == 4
    assert leg["negation"]["planned_by_task"] == {}
    assert pol["answerability"]["sets_measured"] == 2
    assert leg["answerability"]["sets_measured"] == 0
    assert pol["negation"]["negated_stem_share"] == 0.25      # mock stems: 2 of 8 carry EXCEPT


def test_closure_classes_keep_neutral_apart_from_refusal():
    assert closure_class("refusal_suspended") == "refusal"
    assert closure_class("refusal_dissolved") == "refusal"
    assert closure_class("exposition_neutral") == "neutral"
    assert closure_class("resolution_qualified") == "committed"
    assert closure_class("") == "unknown"


def test_move_audit_rereads_with_the_stored_policy(db, monkeypatch, capsys):
    from rc_engine import cli
    from rc_engine.compliance import ComplianceAuditor
    _batch(db, {"hard": 1}, CAT_PYQ_Q1, monkeypatch)
    _batch(db, {"hard": 1}, "", monkeypatch)
    h = HistoryStore(db)
    h.conn.execute("UPDATE fingerprints SET move_signature = ''")
    h.conn.commit()
    expected = {rc: (v or "legacy") for rc, v in h.policy_versions_by_rc_id().items()}
    h.close()
    seen = {}
    real = ComplianceAuditor.move_signature

    def spy(self, passage, ledger, tier="hard", policy=None):
        seen[passage[:40]] = policy.version or "legacy"
        return real(self, passage, ledger, tier, policy=policy)
    monkeypatch.setattr(ComplianceAuditor, "move_signature", spy)
    monkeypatch.setattr(cli, "_txt_dirs", lambda *a, **k: [])
    cli.main(["move-audit", "--db", db, "--dry-run", "--top", "3"])
    assert sorted(seen.values()) == sorted(expected.values()) == [CAT_PYQ_Q1, "legacy"]
