"""Batch-scaling guarantees (2026-09-02).

Three things a larger or parallel batch depends on:
  * a transient API error is retried with backoff, not turned into a dead batch;
  * the novelty window does not score new renders against sets that will
    never ship (solver_dispute) or were themselves rejected as duplicates;
  * every attempt's cost survives the process, so paid waste can be measured.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config                                   # noqa: E402
from rc_engine.history import HistoryStore                      # noqa: E402
from rc_engine.llm import APIExhausted, call_with_backoff       # noqa: E402
from rc_engine.models import Fingerprint, RCResult              # noqa: E402


# --------------------------------------------------------------- backoff

class _Transient(Exception):
    pass


class _Status(Exception):
    def __init__(self, code, msg="boom"):
        super().__init__(msg)
        self.status_code = code


def _status_of(e):
    return getattr(e, "status_code", None)


def test_backoff_retries_a_transient_error_then_returns_the_result():
    calls, naps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise _Transient("rate limited")
        return "ok"

    out = call_with_backoff(fn, transient=(_Transient,), sleep=naps.append,
                            label="t", retries=5)
    assert out == "ok"
    assert len(calls) == 3
    assert len(naps) == 2
    # exponential: the second wait is at least the first one's base
    assert naps[1] >= config.API_BACKOFF_BASE_S * 2
    assert all(n <= config.API_BACKOFF_MAX_S * 1.25 for n in naps)


def test_backoff_retries_5xx_by_status_and_gives_up_as_api_exhausted():
    naps = []

    def fn():
        raise _Status(529, "overloaded")

    with pytest.raises(APIExhausted):
        call_with_backoff(fn, status_of=_status_of, sleep=naps.append,
                          label="t", retries=3)
    assert len(naps) == 3, "must sleep once per retry before giving up"


def test_backoff_never_retries_a_quota_or_credit_error():
    naps = []

    def fn():
        raise _Status(429, "Your credit balance is too low")

    with pytest.raises(APIExhausted):
        call_with_backoff(fn, status_of=_status_of, sleep=naps.append, retries=5)
    assert naps == [], "waiting cannot fix an empty balance"

    def fn402():
        raise _Status(402, "payment required")

    with pytest.raises(APIExhausted):
        call_with_backoff(fn402, status_of=_status_of, sleep=naps.append, retries=5)
    assert naps == []


def test_backoff_leaves_non_transient_errors_alone():
    naps = []

    def fn():
        raise _Status(400, "bad request")

    with pytest.raises(_Status):
        call_with_backoff(fn, status_of=_status_of, sleep=naps.append, retries=5)
    assert naps == []


# ------------------------------------------------------- novelty window

def _fp(rc_id: str) -> Fingerprint:
    return Fingerprint(
        rc_id=rc_id, blueprint_id="bp-" + rc_id, persona_id="P01",
        movement_string="A>B>C", commitment_curve=[0.1, 0.4, 0.8],
        rhythm_vector=[5.0, 30.0, 0.5, 20.0, 8.0, 0.1, 0.2, 0.1],
        topology_signature=[], trap_histogram={}, letter_sequence="ABCDAB",
        stylometry={"the": 0.05}, embedding=None)


def _rc_row(h: HistoryStore, rc_id: str, status: str) -> None:
    h.insert_rc_set(rc_id=rc_id, tier="hard", rc_text="x", status=status,
                    judge={"scores": {}, "average": 0.0, "verdict": "n/a"},
                    solver=None, avg=0.0, blueprint_id="bp-" + rc_id,
                    compliance_f1=1.0, novelty_composite=0.6, total_cost=0.1,
                    essay_doc_id=None, essay_url=None, domain=None,
                    embedding=None, attempts=1)


@pytest.fixture
def store():
    d = tempfile.mkdtemp()
    h = HistoryStore(os.path.join(d, "t.db"))
    yield h
    h.close()


def test_window_hides_disputed_and_rejected_sets_but_keeps_legacy_rows(store):
    for rc_id, status in [("RC-A", "approved"), ("RC-B", "needs_review"),
                          ("RC-C", "solver_dispute"), ("RC-D", "rejected_novelty")]:
        store.record_fingerprint(_fp(rc_id))
        _rc_row(store, rc_id, status)
    store.record_fingerprint(_fp("RC-LEGACY"))       # no rc_sets row: backfill

    live = {fp.rc_id for fp in store.fingerprint_window(100)}
    assert live == {"RC-A", "RC-B", "RC-LEGACY"}

    everything = {fp.rc_id for fp in store.fingerprint_window(100, include_quarantined=True)}
    assert everything == {"RC-A", "RC-B", "RC-C", "RC-D", "RC-LEGACY"}, \
        "audit/reporting paths must still see the whole corpus"

    comp = store.window_composition(100)
    assert comp["live"] == 3
    assert comp["mix"] == {"approved": 1, "needs_review": 1, "no_rc_row": 1}
    assert comp["hidden_by_status"] == 2


def test_window_exclusion_is_config_driven(store, monkeypatch):
    store.record_fingerprint(_fp("RC-C"))
    _rc_row(store, "RC-C", "solver_dispute")
    monkeypatch.setattr(config, "NOVELTY_WINDOW_EXCLUDE_STATUSES", ())
    assert {fp.rc_id for fp in store.fingerprint_window(100)} == {"RC-C"}


# --------------------------------------------------------- attempts table

def test_attempts_are_recorded_and_summarised_by_batch(store):
    ship = RCResult("RC-HARD-1", "bp1", "hard", "approved", cost_usd=0.20,
                    novelty_composite=0.6, compliance_f1=0.9)
    paid = RCResult(None, "bp2", "hard", "rejected_novelty", cost_usd=0.09,
                    notes=["passage novelty: rhythm_cosine 0.93 vs RC-X"])
    free = RCResult(None, "", "hard", "rejected_novelty", cost_usd=0.0,
                    notes=["movement precheck exhausted recomposes"])
    store.record_attempt("B0", "elite", 1, 1, ship)   # an earlier batch
    store.record_attempt("B1", "hard", 1, 1, free)
    store.record_attempt("B1", "hard", 1, 2, paid)
    store.record_attempt("B1", "hard", 1, 3, ship)

    rows = store.conn.execute(
        "SELECT batch_id, slot, attempt_no, status, cost_usd, reason FROM attempts "
        "WHERE batch_id='B1' ORDER BY attempt_no").fetchall()
    assert [r[3] for r in rows] == ["rejected_novelty", "rejected_novelty", "approved"]
    assert rows[1][5].startswith("passage novelty")

    summary = store.attempt_summary(5)
    assert [s["batch_id"] for s in summary] == ["B1", "B0"], "newest batch first"
    b1 = summary[0]
    assert (b1["attempts"], b1["shipped"]) == (3, 1)
    assert (b1["paid_rejects"], b1["free_rejects"]) == (1, 1)
    assert b1["paid_waste"] == pytest.approx(0.09)
    assert b1["spend"] == pytest.approx(0.29)


def test_run_batch_records_every_attempt(store, monkeypatch):
    """The batch loop, not just the store: a rejected attempt and the shipped
    retry both land in the table under one batch id."""
    from rc_engine import pipeline as pl

    outcomes = iter([
        RCResult(None, "bp1", "hard", "rejected_novelty", cost_usd=0.05,
                 notes=["passage novelty: x"]),
        RCResult("RC-HARD-9", "bp2", "hard", "needs_review", cost_usd=0.2),
    ])

    class _Pipe:
        history = store

        def generate_one(self, tier, seed, ban_families=None, ban_movements=None):
            return next(outcomes)

    monkeypatch.setattr(config, "TIER_BUDGET_USD", {"hard": 0.22, "medium": 0.12,
                                                    "elite": 0.30})
    results = pl.run_batch(_Pipe(), {"hard": 1}, seed_provider=None, max_usd=5.0)
    assert [r.status for r in results] == ["rejected_novelty", "needs_review"]

    rows = store.conn.execute(
        "SELECT batch_id, attempt_no, status FROM attempts ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0][0] == rows[1][0], "one batch id for the whole run"
    assert [r[1] for r in rows] == [1, 2]
