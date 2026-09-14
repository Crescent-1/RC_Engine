"""Fixes from the 2026-09-14 step-by-step code review."""
import argparse
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.llm import CostLedger, MockLLMClient  # noqa: E402
from rc_engine.models import NoveltyReport, RealizedStructure, SeedEssay  # noqa: E402

TEXT = "[PASSAGE]\n\nbody\n\n[QUESTIONS]\n\nQ1. x\n"


# ---- 1 + 2: export ---------------------------------------------------------------

def _store(tmp_path):
    from rc_engine.history import HistoryStore
    h = HistoryStore(str(tmp_path / "export.db"))
    rows = [("RC-A", "approved", "green"), ("RC-R", "rejected_novelty", ""),
            ("RC-F", "needs_review", "red"), ("RC-G", "needs_review", "green")]
    for rc_id, status, verdict in rows:
        h.insert_rc_set(rc_id=rc_id, tier="hard", rc_text=TEXT, status=status,
                        judge={"verdict": "x"}, solver=None, avg=8.0, blueprint_id=None,
                        compliance_f1=0.8, novelty_composite=0.6, total_cost=0.1,
                        essay_doc_id=None, essay_url=None, domain="d", embedding=None,
                        attempts=1)
        if verdict:
            h.conn.execute("UPDATE rc_sets SET similarity_verdict=? WHERE rc_id=?", (verdict, rc_id))
    h.conn.commit()
    h.close()
    return str(tmp_path / "export.db")


def test_export_writes_only_shipped_sets_and_moves_stale_copies(tmp_path, monkeypatch):
    from rc_engine import cli
    db = _store(tmp_path)
    out, flagged, superseded = tmp_path / "out", tmp_path / "out" / "flagged", tmp_path / "old"
    flagged.mkdir(parents=True)
    (out / "RC-F.txt").write_text("stale green copy", encoding="utf-8")        # now red
    (flagged / "RC-G.txt").write_text("stale red copy", encoding="utf-8")       # now green
    args = argparse.Namespace(db=db, status=None, out=str(out), flagged_out=str(flagged),
                              superseded_out=str(superseded), client=None)
    assert cli.cmd_export(args) == 0
    assert (out / "RC-A.txt").exists() and (out / "RC-G.txt").exists()
    assert (flagged / "RC-F.txt").exists()
    assert not (out / "RC-R.txt").exists() and not (flagged / "RC-R.txt").exists()
    assert not (out / "RC-F.txt").exists() and not (flagged / "RC-G.txt").exists()
    moved = sorted(p.name for p in superseded.rglob("*.txt"))
    assert moved == ["RC-F.txt", "RC-G.txt"]                  # moved, not deleted
    args.status = "rejected_novelty"                          # still exportable on request
    assert cli.cmd_export(args) == 0 and (out / "RC-R.txt").exists()


# ---- 3 + 4: answerability and solver completeness route to review -------------

@pytest.fixture
def ship(tmp_path, monkeypatch):
    from rc_engine.history import HistoryStore
    from rc_engine.pipeline import RCPipeline
    from test_voice_plan import compose
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.registry import ComponentRegistry
    registry = ComponentRegistry()
    history = HistoryStore(str(tmp_path / "ship.db"))
    composer = BlueprintComposer(registry, history, CompatibilityRules(registry), MockLLMClient())
    bp = compose(composer)
    history.record_blueprint(bp, "composed")
    pipe = RCPipeline(history, MockLLMClient(), embed=False)
    monkeypatch.setattr(pipe.novelty, "score", lambda *a, **kw: NoveltyReport("pass"))
    monkeypatch.setattr("rc_engine.pipeline.judge_rc", lambda *a, **kw:
                        {"average": 10, "verdict": "approve", "scores": {}})
    monkeypatch.setattr("rc_engine.pipeline.length_bias_report", lambda *a:
                        dict(biased=False, warnings=[], correct_longest_count=0,
                             has_thesis_question=False, thesis_correct_longest=False))
    read = RealizedStructure(f1=1, argument_schema=bp.argument_schema_id,
                             rhetorical_moves=bp.move_plan, middle_beats_ok=True)

    def run(solve, answerability=None):
        monkeypatch.setattr("rc_engine.pipeline.blind_solve", lambda *a: solve)
        if answerability is not None:
            monkeypatch.setattr("rc_engine.qa_checks.check_answerability",
                                lambda *a, **kw: answerability)
        return pipe._questions_and_ship(bp, " ".join(["word"] * 525), read,
                                        CostLedger(10), [], SeedEssay(), {}, "RC-T")
    yield run
    history.close()


FULL = {"verdict": "ok", "disputes": [], "comparable": True, "answered": 8}


def test_a_clean_complete_set_still_approves(ship):
    assert ship(FULL, answerability=[]).status == "approved"


def test_an_unanswerable_question_routes_to_review(ship):
    rows = [{"q": 7, "answerable": False, "unique": True, "contenders": [], "note": "gap"}]
    res = ship(FULL, answerability=rows)
    assert res.status == "needs_review"
    assert any("answerability: 1 question(s) flagged" in n for n in res.notes)


@pytest.mark.parametrize("solve,why", [
    ({"verdict": "solver_error", "disputes": []}, "reply unusable"),
    ({"verdict": "ok", "disputes": [], "comparable": False, "answered": 5}, "answered 5 of"),
])
def test_an_incomplete_blind_solve_routes_to_review(ship, solve, why):
    res = ship(solve, answerability=[])
    assert res.status == "needs_review"
    assert any(why in n for n in res.notes), res.notes


def test_blind_solve_reads_string_question_numbers_and_skips_junk():
    from rc_engine.models import Blueprint
    from rc_engine.quality import blind_solve

    class Llm(MockLLMClient):
        def _solver(self, ctx):
            return json.dumps({"answers": ["junk", {"q": "1", "answer": "A"},
                                           {"q": 2, "answer": "C"}, {"q": True, "answer": "B"}]})

    bp = Blueprint(blueprint_id="b", tier="hard", schema_version="2.0", family_id="F12",
                   persona_id="P01", ending_id="E07", rhythm_id="T01", revelation_id="R02",
                   distractor_profile_id="D01", topology_id="QT01", instability=0.5, aperture="x")
    qdata = {"letters": ["A", "B"], "questions": [
        {"q": 1, "stem": "s", "correct": "A", "options": {k: {"text": k} for k in "ABCD"}},
        {"q": 2, "stem": "s", "correct": "B", "options": {k: {"text": k} for k in "ABCD"}}]}
    out = blind_solve(Llm(), CostLedger(1.0), bp, "passage", qdata)
    assert out["answered"] == 2 and out["comparable"] is True
    assert [d["q"] for d in out["disputes"]] == [2]


# ---- 5: restricted seed draws never go seedless --------------------------------

def test_restricted_provider_skips_the_slot_instead_of_running_seedless():
    from rc_engine.pipeline import run_slot

    def provider(tier, exclude_ids=None, avoid_kinds=None):
        return None, None
    provider.restricted = True
    calls = []

    class Pipe:
        embed = False

        def generate_one(self, *a, **k):
            calls.append(a)

    assert run_slot(Pipe(), "hard", 1, 1, provider, set(), spent=lambda: 0.0,
                    max_usd=1.0, keep=lambda *a: None) is False
    assert calls == []


# ---- 7: compliance tolerates malformed auditor replies ---------------------------

def test_compliance_score_survives_malformed_fields_and_skips_partial_curves():
    from rc_engine.compliance import ComplianceAuditor
    from rc_engine.models import Blueprint, ParagraphPlan
    from rc_engine.registry import ComponentRegistry
    bp = Blueprint(blueprint_id="b", tier="hard", schema_version="2.0", family_id="F12",
                   persona_id="P01", ending_id="E07", rhythm_id="T01", revelation_id="R02",
                   distractor_profile_id="D01", topology_id="QT01", instability=0.5, aperture="x")
    bp.movement = [ParagraphPlan(1, "A", (100, 100), "mixed"), ParagraphPlan(2, "B", (100, 100), "mixed")]
    bp.revelation_detail = {"planned_para": 1}
    data = {"paragraphs": ["not an object", {"function_guess": "B", "matches_plan": True}],
            "commitment_curve": [0.2, "high"], "traps_present": None,
            "forbidden_tics_found": "none", "thesis_first_visible_para": 1}
    scored = ComplianceAuditor(None, ComponentRegistry())._score(data, "p one\n\np two", bp, [])
    assert scored.matches == [False, True]
    assert not any("ended at commitment" in d for d in scored.directives)   # curve incomplete
    assert scored.forbidden_tics_found == []


# ---- 8: layout no longer weighs on the composite when the gate is off ------------

def test_topology_drops_out_of_the_composite_when_not_gated(monkeypatch):
    from rc_engine.novelty import NoveltyScorer
    scorer = NoveltyScorer.__new__(NoveltyScorer)
    s = {"movement_levenshtein": 0.1, "movement_bigram_jaccard": 0.1,
         "move_signature_sim": 0.1, "curve_similarity": 0.1,
         "rhythm_cosine": 0.1, "stylometry_sim": 0.1, "embedding_cosine": 0.1,
         "topology_similarity": 1.0, "distractor_jsd": 0.25}
    monkeypatch.setattr(config, "TOPOLOGY_GATE_ENFORCE", True)
    gated = scorer._composite(dict(s), 0.1, True)
    monkeypatch.setattr(config, "TOPOLOGY_GATE_ENFORCE", False)
    lenient = scorer._composite(dict(s), 0.1, True)
    assert lenient < gated
