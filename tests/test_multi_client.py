"""Clients (2026-09-12): one DB, a fresh novelty window per client, and
structural exclusivity across all of them.

  * every pre-existing row migrates to the founding client, untouched;
  * a client's windows, usage counts, in-flight holds, attempts and resumable
    passages never see another client's rows;
  * argument skeletons, seed essays and rc ids are global: no two clients ever
    ship the same structure, and the database itself refuses it;
  * the global house-voice layer is an exact no-op while one client exists;
  * exports land in the client's own folder and hold only its sets.
"""

import argparse
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config                                   # noqa: E402
from rc_engine.history import HistoryStore, UnknownClientError  # noqa: E402
from rc_engine.models import Blueprint, Fingerprint, RCResult    # noqa: E402

FOUNDING = config.FOUNDING_CLIENT_ID


@pytest.fixture
def db_path():
    return os.path.join(tempfile.mkdtemp(), "clients.db")


@pytest.fixture
def stores(db_path):
    a = HistoryStore(db_path)
    a.add_client("BB", "Second institute")
    b = HistoryStore(db_path, "BB")
    yield a, b
    a.close()
    b.close()


def _bp(bid, family="F01", persona="P01", topology="QT01", tier="hard", topic=""):
    bp = Blueprint(blueprint_id=bid, tier=tier,
                   schema_version=config.BLUEPRINT_SCHEMA_VERSION,
                   family_id=family, persona_id=persona, ending_id="E01",
                   rhythm_id="R01", revelation_id="V01", distractor_profile_id="D01",
                   topology_id=topology, instability=0.5, aperture="closed")
    bp.topic = topic
    return bp


def _fp(rc_id, moves=""):
    return Fingerprint(
        rc_id=rc_id, blueprint_id="bp-" + rc_id, persona_id="P01",
        movement_string="A>B>C", commitment_curve=[0.1, 0.4, 0.8],
        rhythm_vector=[5.0, 30.0, 0.5, 20.0, 8.0, 0.1, 0.2, 0.1],
        topology_signature=[], trap_histogram={}, letter_sequence="ABCDAB",
        stylometry={"the": 0.05}, embedding=None, move_signature=moves)


def _ship(h, bp, rc_id, seed=None, moves=""):
    h.record_blueprint(bp, "composed")
    h.insert_rc_set(rc_id=rc_id, tier=bp.tier, rc_text="x", status="approved",
                    judge={"scores": {}, "average": 8.0, "verdict": "approve"},
                    solver=None, avg=8.0, blueprint_id=bp.blueprint_id,
                    compliance_f1=0.9, novelty_composite=0.6, total_cost=0.1,
                    essay_doc_id=seed, essay_url=None, domain=None,
                    embedding=None, attempts=1)
    h.record_fingerprint(_fp(rc_id, moves))
    h.mark_shipped(bp, rc_id)


def _composer(history):
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.llm import MockLLMClient
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    return BlueprintComposer(reg, history, CompatibilityRules(reg), MockLLMClient())


# ------------------------------------------------------------- migration

def test_a_pre_client_db_migrates_every_row_to_the_founding_client(db_path):
    """The production DB predates clients. Opening it must hand every row to
    the founding client and change nothing it sees."""
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE rc_sets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, rc_id TEXT UNIQUE, tier TEXT,
        rc_text TEXT, judge_json TEXT, average_score REAL, status TEXT,
        essay_doc_id TEXT, essay_url TEXT, gen_input_tokens INTEGER,
        gen_output_tokens INTEGER, judge_input_tokens INTEGER,
        judge_output_tokens INTEGER, gen_cost_usd REAL, judge_cost_usd REAL,
        total_cost_usd REAL, attempts INTEGER, created_at TEXT)""")
    con.execute("""CREATE TABLE blueprints (
        blueprint_id TEXT PRIMARY KEY, rc_id TEXT, tier TEXT NOT NULL,
        family_id TEXT NOT NULL, persona_id TEXT NOT NULL, ending_id TEXT NOT NULL,
        rhythm_id TEXT NOT NULL, revelation_id TEXT NOT NULL,
        distractor_profile_id TEXT NOT NULL, topology_id TEXT NOT NULL,
        instability REAL, aperture TEXT, combo_hash TEXT NOT NULL,
        pair_hashes TEXT NOT NULL, blueprint_json TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL)""")
    con.execute("INSERT INTO rc_sets (rc_id, tier, status, created_at) "
                "VALUES ('RC-OLD-1', 'hard', 'approved', '2026-07-01')")
    con.execute("INSERT INTO blueprints VALUES ('BP-OLD', 'RC-OLD-1', 'hard', 'F01', "
                "'P01', 'E01', 'R01', 'V01', 'D01', 'QT01', 0.5, 'x', 'hash-old', "
                "'{}', '{}', 'shipped', '2026-07-01')")
    con.commit()
    con.close()

    h = HistoryStore(db_path)
    try:
        assert h.client_id == FOUNDING
        assert h.conn.execute("SELECT client_id FROM rc_sets").fetchall() == [(FOUNDING,)]
        assert h.conn.execute("SELECT client_id FROM blueprints").fetchall() == [(FOUNDING,)]
        assert [c["client_id"] for c in h.list_clients()] == [FOUNDING]
        assert h.recent_shipped_blueprints(10)[0]["combo_hash"] == "hash-old", \
            "the founding client still sees its whole history"
        assert h.exclusivity_audit()["unique_index"]
    finally:
        h.close()


def test_the_default_client_comes_from_config(db_path, monkeypatch):
    h = HistoryStore(db_path)
    h.add_client("BB")
    h.close()
    monkeypatch.setattr(config, "DEFAULT_CLIENT_ID", "BB")
    h = HistoryStore(db_path)
    assert h.client_id == "BB"
    h.close()


def test_an_unknown_client_is_an_error_never_an_empty_corpus(db_path):
    """An empty window auto-passes novelty; a typo must not buy that."""
    HistoryStore(db_path).close()
    with pytest.raises(UnknownClientError):
        HistoryStore(db_path, "typo")


def test_client_slugs_are_safe_folder_names_and_case_insensitively_unique(stores):
    a, _ = stores
    for bad in ("", "has space", "../x", "con", "x" * 33):
        with pytest.raises(ValueError):
            a.add_client(bad)
    with pytest.raises(ValueError):
        a.add_client("bb")        # Windows folders ignore case


# ------------------------------------------------------ per-client scope

def test_each_client_sees_only_its_own_corpus(stores):
    from rc_engine.seed_classify import genre_shares
    a, b = stores
    _ship(a, _bp("BP-A1", topic="a topic"), "RC-A1")
    a.conn.execute("UPDATE rc_sets SET seed_genre = 'criticism'")
    a.conn.commit()
    a.record_rendered_passage("BP-A1", "hard", "p", "{}", 0.9, None, None, None,
                              0.1, status="questions_failed")

    assert [f.rc_id for f in a.fingerprint_window(100)] == ["RC-A1"]
    assert a.usage_counts_trailing("family", 100) == {"F01": 1}
    assert a.recent_topics(12) == ["a topic"]
    assert a.load_rendered_passage("BP-A1") is not None

    assert b.fingerprint_window(100) == []
    assert b.fingerprint_window(100, include_quarantined=True) == []
    assert b.recent_shipped_blueprints(10) == []
    assert b.component_positions("family") == {}
    assert b.usage_counts_trailing("family", 100) == {}
    assert b.letter_sequences_trailing(20) == []
    assert b.recent_topics(12) == []
    assert b.shipped_blueprint_rows(10) == []
    assert b.shipped_blueprint_components(10) == []
    assert b.recent_seed_ids(12) == []
    assert b.recent_rc_texts().fetchall() == []
    assert b.window_composition(100)["live"] == 0
    assert genre_shares(a) == ({"criticism": 1.0}, 1)
    assert genre_shares(b) == ({}, 0)
    assert b.load_resumable_passages() == []
    assert b.load_rendered_passage("BP-A1") is None, \
        "resuming another client's passage would ship it into the wrong corpus"


def test_attempts_and_inflight_holds_are_per_client(stores):
    a, b = stores
    a.record_attempt("B-A", "hard", 1, 1,
                     RCResult("RC-A", "bp", "hard", "approved", cost_usd=0.2))
    assert [s["batch_id"] for s in a.attempt_summary(5)] == ["B-A"]
    assert b.attempt_summary(5) == []

    class _BP:
        family_id, movement_string, topic = "F01", "A>B", "t"
        component_ids = {"topology": "QT01"}

    a.reserve_inflight("wA", _BP(), None)
    assert b.inflight_bans("wB")["families"] == set()
    assert b.inflight_components("wB") == {}
    b.clear_inflight()
    assert a.inflight_bans("wZ")["families"] == {"F01"}, \
        "another client's batch starting must not wipe these reservations"


# ------------------------------------------------------------ global scope

def test_skeletons_seeds_and_rc_ids_are_global(stores):
    a, b = stores
    bp = _bp("BP-A1")
    _ship(a, bp, "RC-A1", seed="doc-1")
    assert bp.combo_hash in b.shipped_combo_hashes()
    assert b.combo_hash_taken(bp.combo_hash, "BP-B1")
    assert b.seed_shipped_to_other_client("doc-1")
    assert not a.seed_shipped_to_other_client("doc-1"), \
        "same-client seed reuse is left to the existing seed gates"
    assert a.generate_rc_id("hard") != b.generate_rc_id("hard")
    assert a._ship_lock_path() == b._ship_lock_path(), \
        "the ship-time exclusivity check must be atomic across clients"


def test_the_database_refuses_a_second_client_shipping_the_same_skeleton(stores):
    a, b = stores
    _ship(a, _bp("BP-A1"), "RC-A1")
    twin = _bp("BP-B1")              # identical components -> identical combo hash
    b.record_blueprint(twin, "composed")
    with pytest.raises(sqlite3.IntegrityError):
        b.mark_shipped(twin, "RC-B1")
    audit = a.exclusivity_audit()
    assert audit["shared_combo_hashes"] == [] and audit["shared_seeds"] == []


def test_a_skeleton_taken_since_compose_is_a_recorded_rejection_not_a_crash(stores):
    from rc_engine.llm import MockLLMClient
    from rc_engine.pipeline import RCPipeline
    _, b = stores
    pipe = RCPipeline(b, MockLLMClient(), embed=False)
    b.combo_hash_taken = lambda combo_hash, blueprint_id: True
    res = pipe.generate_one("hard")
    assert res.status == "rejected_novelty", res.notes
    assert any(n.startswith("exclusivity") for n in res.notes), res.notes
    row = b.conn.execute("SELECT client_id, status FROM rc_sets WHERE rc_id = ?",
                         (res.rc_id,)).fetchone()
    assert row == ("BB", "rejected_novelty")


# ------------------------------------------------ global house-voice layer

def test_global_house_voice_layer_is_an_exact_noop_with_one_client(db_path):
    a = HistoryStore(db_path)
    try:
        _ship(a, _bp("BP-A1"), "RC-A1", moves="SCENE_PARTICULAR|LEVEL_RELOCATION")
        comp = _composer(a)
        w = [1.0, 0.5]
        assert comp._global_pressure("family", ["F01", "F02"], w) is w
        assert comp._other_client_move_shares() == {}
    finally:
        a.close()


def test_what_other_clients_were_given_is_a_softer_draw(stores):
    a, b = stores
    _ship(a, _bp("BP-A1"), "RC-A1", moves="LEVEL_RELOCATION|SCENE_PARTICULAR")
    _ship(a, _bp("BP-A2", persona="P02"), "RC-A2", moves="LEVEL_RELOCATION")
    comp_b = _composer(b)
    assert comp_b._global_pressure("family", ["F01", "F02"], [1.0, 1.0]) == \
        pytest.approx([config.GLOBAL_DECAY_LAMBDA ** 2, 1.0])
    assert comp_b._other_client_move_shares() == \
        pytest.approx({"LEVEL_RELOCATION": 1.0, "SCENE_PARTICULAR": 0.5})
    assert comp_b._move_frequencies() == ({}, 0), "BB's own window is still fresh"
    assert _composer(a)._global_pressure("family", ["F01"], [1.0]) == [1.0]
    assert config.DECAY_LAMBDA < config.GLOBAL_DECAY_LAMBDA < 1.0, \
        "the global term must be softer than a client's own recency"


# ------------------------------------------------------------ CLI & exports

def test_exports_go_to_the_clients_own_folder():
    from rc_engine import cli
    assert cli._export_dir(FOUNDING, False) == "exported_rc_sets"
    assert cli._export_dir(FOUNDING, True) == "exported_rc_sets_dryrun"
    assert cli._export_dir("BB", False) == os.path.join("exported_rc_sets", "BB")
    assert cli._export_dir("BB", True) == os.path.join("exported_rc_sets_dryrun", "BB")
    assert cli._flagged_dir(FOUNDING, "exported_rc_sets") == config.FLAGGED_EXPORT_DIR
    assert cli._flagged_dir("BB", "out") == os.path.join("out", "flagged_similar")


def test_export_writes_only_that_clients_sets(tmp_path, stores, db_path):
    from rc_engine import cli
    a, b = stores
    _ship(a, _bp("BP-A1"), "RC-A1")
    _ship(b, _bp("BP-B1", family="F02"), "RC-B1")
    out = tmp_path / "BB"
    assert cli.cmd_export(argparse.Namespace(db=db_path, status=None, out=str(out),
                                             client="BB")) == 0
    assert sorted(os.listdir(out)) == ["RC-B1.txt"]


def test_backfill_defaults_never_reach_into_the_founding_clients_folders():
    from rc_engine import cli
    assert cli._txt_dirs(None, FOUNDING, ["exported_rc_sets"]) == ["exported_rc_sets"]
    assert cli._txt_dirs(None, "BB", ["exported_rc_sets"]) == []
    assert cli._txt_dirs(["mine"], "BB", ["exported_rc_sets"]) == ["mine"]


def test_cli_refuses_an_unknown_client(db_path, capsys):
    from rc_engine import cli
    HistoryStore(db_path).close()
    assert cli.main(["health", "--db", db_path, "--client", "typo"]) == 2
    assert "unknown client 'typo'" in capsys.readouterr().out


def test_client_add_and_list(db_path, capsys):
    from rc_engine import cli
    assert cli.main(["client", "add", "BB", "--name", "Second", "--db", db_path]) == 0
    assert cli.main(["client", "add", "bb", "--db", db_path]) == 2
    assert cli.main(["client", "list", "--db", db_path]) == 0
    out = capsys.readouterr().out
    assert "BB" in out and "Second" in out


def test_gui_reads_are_scoped_to_the_picked_client(stores, db_path, monkeypatch):
    from gui import db as gdb
    a, b = stores
    _ship(a, _bp("BP-A1"), "RC-A1")
    _ship(b, _bp("BP-B1", family="F02"), "RC-B1")
    monkeypatch.setenv("RC_ENGINE_DB", db_path)
    assert gdb.rc_list(None, None, client="BB")["total"] == 1
    assert gdb.rc_list(None, None, client=FOUNDING)["total"] == 1
    assert gdb.dashboard("BB")["total"] == 1
    assert [c["client_id"] for c in gdb.clients()] == [FOUNDING, "BB"]


# ---------------------------------------------------------------- workers

def test_run_parallel_ships_into_the_parents_client(db_path):
    from rc_engine.workers import run_parallel
    a = HistoryStore(db_path)
    a.add_client("BB")
    a.close()
    parent = HistoryStore(db_path, "BB")
    try:
        results = run_parallel(parent, {"hard": 2}, workers=2, db=db_path,
                               provider="claude", dry_run=True, embed=False,
                               seed_provider=None, max_usd=10.0)
        assert [r for r in results if r.rc_id], [(r.status, r.notes) for r in results]
        assert {r[0] for r in parent.conn.execute("SELECT client_id FROM rc_sets")} == {"BB"}
        assert {r[0] for r in parent.conn.execute("SELECT client_id FROM attempts")} == {"BB"}
    finally:
        parent.close()
