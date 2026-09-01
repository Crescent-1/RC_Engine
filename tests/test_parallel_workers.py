"""Parallel workers (2026-09-02): what keeps N concurrent renders honest.

  * in-flight reservations ban a sibling's skeleton before compose;
  * the ship lock is exclusive, and a dead worker's lock is broken;
  * a set whose sibling shipped first is rejected at the locked recheck;
  * run_parallel ships the batch, records every attempt, and cleans up.
"""

import os
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config                                   # noqa: E402
from rc_engine.history import HistoryStore                      # noqa: E402
from rc_engine.llm import MockLLMClient                         # noqa: E402
from rc_engine.pipeline import RCPipeline                       # noqa: E402


@pytest.fixture
def db_path():
    return os.path.join(tempfile.mkdtemp(), "par.db")


@pytest.fixture
def store(db_path):
    h = HistoryStore(db_path)
    yield h
    h.close()


class _BP:
    def __init__(self, family, movement, topic="t"):
        self.family_id, self.movement_string, self.topic = family, movement, topic


class _Seed:
    def __init__(self, doc_id):
        self.doc_id = doc_id


# ------------------------------------------------------- in-flight bans

def test_inflight_bans_cover_other_workers_only_and_release(store):
    store.reserve_inflight("wA", _BP("F01", "A>B>C"), _Seed("d1"))
    store.reserve_inflight("wB", _BP("F07", "C>B>A"), _Seed("d2"))

    seen_by_c = store.inflight_bans(exclude_worker="wC")
    assert seen_by_c["families"] == {"F01", "F07"}
    assert seen_by_c["movements"] == {"A>B>C", "C>B>A"}
    assert seen_by_c["seeds"] == {"d1", "d2"}

    seen_by_a = store.inflight_bans(exclude_worker="wA")
    assert seen_by_a["families"] == {"F07"}, "a worker never bans itself"

    store.reserve_inflight("wA", _BP("F02", "B>A"), None)     # recompose replaces
    assert store.inflight_bans("wC")["families"] == {"F02", "F07"}

    store.release_inflight("wA")
    assert store.inflight_bans("wC")["families"] == {"F07"}
    store.clear_inflight()
    assert store.inflight_bans("wC")["families"] == set()


def test_stale_inflight_rows_are_ignored(store, monkeypatch):
    store.reserve_inflight("wDead", _BP("F01", "A>B"), None)
    monkeypatch.setattr(config, "INFLIGHT_STALE_MIN", 0)
    assert store.inflight_bans("wC")["families"] == set()


# ------------------------------------------------------------ ship lock

def test_ship_lock_is_exclusive_across_connections(db_path):
    order: list[str] = []
    a_holds = threading.Event()

    def holder():
        h = HistoryStore(db_path)
        with h.ship_lock():
            order.append("a-in")
            a_holds.set()
            time.sleep(0.6)
            order.append("a-out")
        h.close()

    def waiter():
        a_holds.wait(5)
        h = HistoryStore(db_path)
        with h.ship_lock():
            order.append("b-in")
        h.close()

    ta, tb = threading.Thread(target=holder), threading.Thread(target=waiter)
    ta.start(); tb.start(); ta.join(10); tb.join(10)
    assert order == ["a-in", "a-out", "b-in"]
    assert not os.path.exists(HistoryStore(db_path)._ship_lock_path())


def test_ship_lock_breaks_a_dead_workers_lock(store, monkeypatch):
    path = store._ship_lock_path()
    with open(path, "w") as f:
        f.write("0")
    old = time.time() - 7200
    os.utime(path, (old, old))
    monkeypatch.setattr(config, "SHIP_LOCK_STALE_S", 600)
    t0 = time.time()
    with store.ship_lock():
        assert time.time() - t0 < 5, "stale lock must be broken, not waited on"
    assert not os.path.exists(path)


def test_ship_lock_disabled_is_a_no_op(store):
    with store.ship_lock(enabled=False):
        assert not os.path.exists(store._ship_lock_path())


# --------------------------------------------- pipeline in parallel mode

def _family_of(store, blueprint_id):
    return store.conn.execute("SELECT family_id FROM blueprints WHERE blueprint_id=?",
                              (blueprint_id,)).fetchone()[0]


def test_parallel_pipeline_reserves_and_siblings_ban_it(store):
    a = RCPipeline(store, MockLLMClient(), embed=False, parallel=True, worker_id="wA")
    res_a = a.generate_one("hard")
    assert res_a.rc_id, res_a.notes
    fam_a = _family_of(store, res_a.blueprint_id)
    # generate_one leaves the reservation up; the worker slot releases it
    assert fam_a in store.inflight_bans(exclude_worker="wB")["families"]

    b = RCPipeline(store, MockLLMClient(), embed=False, parallel=True, worker_id="wB")
    res_b = b.generate_one("hard")
    assert res_b.rc_id, res_b.notes
    assert _family_of(store, res_b.blueprint_id) != fam_a, \
        "the sibling's family was in flight and must not be re-drawn"


def test_late_sibling_collision_is_rejected_at_the_locked_recheck(store):
    pipe = RCPipeline(store, MockLLMClient(), embed=False, parallel=True, worker_id="wA")
    real = pipe.novelty.score
    full_calls = []

    def score(fp, bp_sims, include_question_channels):
        rep = real(fp, bp_sims, include_question_channels)
        if include_question_channels:
            full_calls.append(1)
            if len(full_calls) == 2:            # the recheck under the lock
                rep.verdict = "reject_pairwise"
                rep.breached = ["rhythm_cosine 0.95 vs RC-SIBLING"]
        return rep

    pipe.novelty.score = score
    res = pipe.generate_one("hard")
    assert res.status == "rejected_novelty"
    assert any("late sibling novelty" in n for n in res.notes)
    assert len(full_calls) == 2
    row = store.conn.execute("SELECT status FROM rc_sets WHERE rc_id=?", (res.rc_id,)).fetchone()
    assert row[0] == "rejected_novelty"
    audit = store.conn.execute(
        "SELECT details FROM novelty_audits WHERE details LIKE 'late sibling:%'").fetchone()
    assert audit is not None
    assert not os.path.exists(store._ship_lock_path()), "lock released on the reject path too"


def test_sequential_pipeline_does_not_recheck_or_reserve(store):
    pipe = RCPipeline(store, MockLLMClient(), embed=False)
    real = pipe.novelty.score
    full_calls = []

    def score(fp, bp_sims, include_question_channels):
        if include_question_channels:
            full_calls.append(1)
        return real(fp, bp_sims, include_question_channels)

    pipe.novelty.score = score
    res = pipe.generate_one("hard")
    assert res.rc_id
    assert len(full_calls) == 1
    assert store.conn.execute("SELECT COUNT(*) FROM inflight").fetchone()[0] == 0


# ------------------------------------------------------------ run_parallel

def test_run_parallel_dry_run_ships_records_and_cleans_up(db_path):
    from rc_engine.workers import run_parallel

    parent = HistoryStore(db_path)
    results = run_parallel(parent, {"hard": 2, "medium": 1}, workers=2,
                           db=db_path, provider="claude", dry_run=True,
                           embed=False, seed_provider=None, max_usd=10.0)
    shipped = [r for r in results if r.rc_id and r.status in
               ("approved", "needs_review", "solver_dispute")]
    assert len(shipped) == 3, [(r.status, r.notes) for r in results]

    rows = parent.conn.execute(
        "SELECT batch_id, tier, slot FROM attempts ORDER BY id").fetchall()
    assert len(rows) == len(results)
    assert len({r[0] for r in rows}) == 1, "one batch id across workers"
    assert {(r[1], r[2]) for r in rows} == {("hard", 1), ("hard", 2), ("medium", 1)}
    assert parent.conn.execute("SELECT COUNT(*) FROM inflight").fetchone()[0] == 0
    assert parent.conn.execute("SELECT COUNT(*) FROM rc_sets").fetchone()[0] == 3
    parent.close()


def test_run_parallel_hands_each_slot_its_own_seeds_and_marks_used(db_path):
    from rc_engine.models import SeedEssay
    from rc_engine.workers import run_parallel

    used: list[tuple[str, str]] = []
    handed: list[str] = []
    pool = iter(f"doc{i}" for i in range(100))

    def seed_provider(tier, exclude_ids=None, avoid_kinds=None):
        doc = next(pool)
        assert doc not in (exclude_ids or ()), "a seed must never be handed out twice"
        handed.append(doc)
        seed = SeedEssay(doc_id=doc, url="u", title=f"T {doc}",
                         text="word " * 400, domain_hint="essay")
        return seed, (lambda rc_id, d=doc: used.append((d, rc_id)))

    parent = HistoryStore(db_path)
    results = run_parallel(parent, {"hard": 2}, workers=2, db=db_path,
                           provider="claude", dry_run=True, embed=False,
                           seed_provider=seed_provider, max_usd=10.0)
    shipped = [r for r in results if r.rc_id]
    assert len(shipped) == 2, [(r.status, r.notes) for r in results]
    assert len(handed) == 2 * config.PARALLEL_SEEDS_PER_SLOT
    assert len(set(handed)) == len(handed)
    assert len(used) == 2, "exactly the consumed seed of each shipped set is marked used"
    assert {rc for _, rc in used} == {r.rc_id for r in shipped}
    parent.close()
