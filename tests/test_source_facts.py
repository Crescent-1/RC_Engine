"""cat-pyq-f1: source-supported facts (plan section 6), 2026-09-13.

The source excerpt below is invented for these tests. Adversarial fixtures from
the plan: an accurate substring used in a false claim, a denied or qualified
source claim, a misattributed quotation, altered figures, short and missing
seeds, and resumed plans. Elite receives none of this (also pinned by the
elite golden run with cat-pyq-f1 on the side in test_generation_policy.py).
"""
import copy
import json
import os
import random
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.generation_policy import get_policy  # noqa: E402
from rc_engine.policy_catalog import CAT_PYQ_F1  # noqa: E402
from rc_engine.source_facts import (FACT_BEATS, MAX_FACTS, digest, facts_block,  # noqa: E402
                                    replace_unsupported_beats, retained_excerpt,
                                    supported_claims, unsupported, validate)

EXCERPT = (
    "The Harbour Board's 2021 survey found that ferry delays fell by 18 percent after the "
    "timetable change. Officials denied that the new berths had caused any flooding. According "
    "to engineer Maya Okafor, the dredging \"may have narrowed the channel more than the models "
    "predicted\". The board did not publish the raw tide readings. Residents estimated that "
    "about 300 households moved inland over the decade.")
SEED = SimpleNamespace(text=EXCERPT, url="https://example.org/harbour", doc_id="doc-harbour")
F1 = get_policy(CAT_PYQ_F1)

VALID = {"span": "ferry delays fell by 18 percent after the timetable change",
         "claim": "Ferry delays fell by 18 percent after the timetable change.",
         "attribution": "the Harbour Board's 2021 survey", "qualification": ""}
QUOTE = {"span": "the dredging \"may have narrowed the channel more than the models predicted\"",
         "claim": "The dredging \"may have narrowed the channel more than the models predicted\".",
         "attribution": "engineer Maya Okafor", "qualification": ""}


def _one(cand):
    facts, reasons = validate([cand], SEED)
    return facts, reasons


def test_structurally_sound_facts_survive_with_evidence():
    facts, reasons = validate([VALID, QUOTE], SEED)
    assert reasons == [] and [f["id"] for f in facts] == ["SF1", "SF2"]
    excerpt = retained_excerpt(EXCERPT)
    for f in facts:
        assert f["excerpt_digest"] == digest(excerpt)
        assert f["source_url"] == SEED.url and f["doc_id"] == SEED.doc_id
        norm = excerpt.replace("“", '"').replace("”", '"')
        assert norm[f["start"]:f["end"]] == f["span"]


@pytest.mark.parametrize("name,mutate,reason", [
    ("altered figure", lambda c: c.update(claim="Ferry delays fell by 28 percent after the timetable change."),
     "figure"),
    ("accurate substring, negation inverted",
     lambda c: c.update(span="The board did not publish the raw tide readings.",
                        claim="The board published the raw tide readings.", attribution=""),
     "negation"),
    ("denied source claim restated as fact",
     lambda c: c.update(span="Officials denied that the new berths had caused any flooding.",
                        claim="The new berths caused flooding.", attribution=""),
     "negation"),
    ("qualification dropped",
     lambda c: c.update(span=QUOTE["span"], claim="The dredging narrowed the channel more than "
                        "the models predicted.", attribution="engineer Maya Okafor"),
     "qualification"),
    ("misattributed quotation",
     lambda c: c.update(span=QUOTE["span"], claim=QUOTE["claim"], attribution="engineer Tomas Lind"),
     "attribution"),
    ("quotation altered",
     lambda c: c.update(span=QUOTE["span"], attribution="engineer Maya Okafor",
                        claim="Okafor said the dredging \"may have narrowed the channel far more\"."),
     "quotes"),
    ("invented span", lambda c: c.update(span="ferry delays tripled after the timetable change"),
     "not in the retained excerpt"),
    ("name the source never gives",
     lambda c: c.update(claim="Minister Arjun Rao said ferry delays fell by 18 percent after the "
                              "timetable change."), "name"),
])
def test_adversarial_candidates_are_rejected(name, mutate, reason):
    cand = copy.deepcopy(VALID)
    mutate(cand)
    facts, reasons = _one(cand)
    assert facts == [] and reason in reasons[0], (name, reasons)


def test_short_and_missing_seeds_yield_no_facts():
    for text in ("", None, "Two words."):
        facts, reasons = validate([VALID], SimpleNamespace(text=text, url="", doc_id=""))
        assert facts == []
    assert validate([VALID], SimpleNamespace(text="", url="", doc_id=""))[1] == [
        "no retained seed excerpt"]


def test_at_most_eight_candidates_are_considered():
    many = [dict(VALID)] * (MAX_FACTS + 4)
    facts, reasons = validate(many, SEED)
    assert len(facts) == 1                         # duplicates collapse
    assert any("beyond the limit" in r for r in reasons)


def test_fact_beats_fall_back_when_facts_cannot_carry_them():
    plan = ["NEWS_DATA_HOOK", "STUDY_WALKTHROUGH", "MECHANISM_EXPLAINED", "EXPERT_AS_SPINE",
            "QUOTE_CLOSE"]
    out, notes = replace_unsupported_beats(plan, [], forbidden=set())
    assert out == ["ABSTRACT_CLAIM_OPEN", "MECHANISM_EXPLAINED", "AUTHORITY_QUOTED",
                   "BOUND_CONTINUATION"]
    assert len(notes) == 4 and not set(FACT_BEATS) & set(out)
    facts, _ = validate([VALID, QUOTE], SEED)
    kept, notes = replace_unsupported_beats(plan, facts, forbidden=set())
    assert kept == plan and notes == []           # two attributed facts, a figure and a quote


def test_trace_support_and_texture_suppression():
    from rc_engine.question_engine import texture_report
    facts, _ = validate([VALID], SEED)
    trace = [
        {"claim": "ferry delays fell by 18 percent", "fact_ids": ["SF1"], "support": "source_fact",
         "attribution_ok": True},
        {"claim": "Shannon worked at Bell Labs in 1948", "fact_ids": [], "support": "common_knowledge"},
        {"claim": "a 2019 study found 62% of claimants", "fact_ids": [], "support": "unsupported"},
        {"claim": "delays fell 18 percent, said the minister", "fact_ids": ["SF1"],
         "support": "source_fact", "attribution_ok": False},
        {"claim": "an invented id", "fact_ids": ["SF9"], "support": "source_fact"},
    ]
    bad = unsupported(trace, facts)
    assert [b["claim"][:6] for b in bad] == ["a 2019", "delays", "an inv"]
    ok = supported_claims(trace, facts)
    assert ok == ["ferry delays fell by 18 percent"]
    passage = "After the change, ferry delays fell by 18 percent. Later a 2019 study found 62% of claimants waited."
    warnings = texture_report(passage, None, ok)["warnings"]
    assert not any("18 percent" in w for w in warnings)
    assert any("62%" in w for w in warnings)          # same pattern, later match, not hidden
    assert any("2019 study" in w for w in warnings)
    # a whitelisted number elsewhere in the passage does not silence anything
    assert any("18 percent" in w for w in texture_report(
        "Rents rose 18 percent in a year.", None, ["delays fell by 12 percent"])["warnings"])


def test_auditor_turns_unsupported_claims_into_directives():
    from rc_engine.compliance import ComplianceAuditor
    from rc_engine.models import Blueprint, ParagraphPlan
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    bp = Blueprint(blueprint_id="BP_f", tier="hard", schema_version="2.0", family_id="F12",
                   persona_id="P01", ending_id="E07", rhythm_id="T01", revelation_id="R02",
                   distractor_profile_id="D01", topology_id="QT01", instability=0.5, aperture="x",
                   generation_policy=CAT_PYQ_F1)
    bp.movement = [ParagraphPlan(1, "A", (100, 100), "mixed")]
    bp.revelation_detail = {"planned_para": 1}
    bp.source_facts, _ = validate([VALID], SEED)
    data = {"paragraphs": [], "fact_trace": [
        {"claim": "a 2019 study found 62%", "fact_ids": [], "support": "unsupported"}]}
    realized = ComplianceAuditor(None, reg)._score(data, "a", bp, [], grants=[], trace_facts=True)
    assert realized.unsupported_claims and realized.fact_trace
    assert any("without support in SOURCE-SUPPORTED FACTS" in d for d in realized.directives)
    plain = ComplianceAuditor(None, reg)._score(data, "a", bp, [])
    assert plain.unsupported_claims == [] and plain.fact_trace == []


def _pipeline(tmp_path, monkeypatch, policy=CAT_PYQ_F1):
    from rc_engine.history import HistoryStore
    from rc_engine.llm import MockLLMClient
    from rc_engine.pipeline import RCPipeline

    class Spy(MockLLMClient):
        def __init__(self):
            self.calls = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append((stage, system, user, dict(context or {})))
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": policy, "hard": policy, "elite": ""})
    history = HistoryStore(str(tmp_path / "facts.db"))
    llm = Spy()
    return RCPipeline(history, llm, embed=False, rng=random.Random(8)), history, llm


def test_mock_run_carries_facts_to_render_and_audit_and_not_to_exports_or_elite(tmp_path, monkeypatch):
    from rc_engine.models import SeedEssay
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    seed = SeedEssay(url=SEED.url, doc_id=None, title="Harbour", text=EXCERPT)
    res = pipe.generate_one("hard", seed)
    assert res.status in config.SHIPPING_STATUSES, res.notes
    raw = history.conn.execute("SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?",
                               (res.blueprint_id,)).fetchone()[0]
    bp = json.loads(raw)
    assert bp["source_facts"] and all(f["excerpt_digest"] for f in bp["source_facts"])
    render = [c for c in llm.calls if c[0] == "render"][-1]
    audit = [c for c in llm.calls if c[0] == "compliance"][-1]
    assert "SOURCE-SUPPORTED FACTS" in render[2] and "SOURCE-SUPPORTED FACTS block may" in render[1]
    assert audit[3]["source_facts"] == [f["id"] for f in bp["source_facts"]]
    assert "FACT TRACE" in audit[1]
    rc_text = history.conn.execute("SELECT rc_text FROM rc_sets WHERE rc_id = ?",
                                   (res.rc_id,)).fetchone()[0]
    for f in bp["source_facts"]:
        assert f["span"] not in rc_text.split("[PASSAGE]")[0]
        assert "excerpt_digest" not in rc_text and "SF1" not in rc_text

    start = len(llm.calls)
    elite = pipe.generate_one("elite", seed)
    ebp = json.loads(history.conn.execute("SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?",
                                          (elite.blueprint_id,)).fetchone()[0])
    assert ebp["source_facts"] == [] and ebp["source_fact_notes"] == []
    for stage, system, user, ctx in llm.calls[start:]:
        assert "SOURCE-SUPPORTED FACTS" not in user and "FACT TRACE" not in system
        assert "seed_excerpt" not in ctx and "source_facts" not in ctx
    assert sum(1 for c in llm.calls[start:] if c[0] == "refine") == 1   # no extra model call
    history.close()


def test_unsupported_claims_route_to_review(tmp_path, monkeypatch):
    from rc_engine.llm import MockLLMClient
    from rc_engine.models import SeedEssay
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    real = MockLLMClient._compliance

    def lying(self, ctx):
        out = json.loads(real(self, ctx))
        out["fact_trace"] = [{"claim": "a 2019 study found 62%", "fact_ids": [],
                              "support": "unsupported"}]
        return json.dumps(out)
    monkeypatch.setattr(MockLLMClient, "_compliance", lying)
    # make every other routing reason pass, so only the facts route can decide
    monkeypatch.setattr(config, "PASSAGE_WORD_MIN", 1)
    monkeypatch.setattr(config, "PASSAGE_WORD_MAX", 10**6)
    res = pipe.generate_one("medium", SeedEssay(url="u", text=EXCERPT))
    assert res.status == "needs_review", res.status
    assert any("unsupported factual claim" in n for n in res.notes)
    assert any("routed to needs_review" in n and "unsupported" in n for n in res.notes), res.notes
    history.close()


def test_resume_keeps_the_stored_facts_without_another_refine(tmp_path, monkeypatch):
    from rc_engine.models import SeedEssay
    from rc_engine.question_engine import QuestionEngineError
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    real = pipe.qengine.build
    state = {"fired": False}

    def fail_once(*a, **kw):
        if not state["fired"]:
            state["fired"] = True
            raise QuestionEngineError("forced")
        return real(*a, **kw)
    monkeypatch.setattr(pipe.qengine, "build", fail_once)
    res = pipe.generate_one("hard", SeedEssay(url="u", text=EXCERPT))
    assert res.status == "failed_questions"
    before = json.loads(history.conn.execute(
        "SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?", (res.blueprint_id,)).fetchone()[0])
    start = len(llm.calls)
    again = pipe.resume_questions(res.blueprint_id)
    assert again.status in config.SHIPPING_STATUSES, again.notes
    after = json.loads(history.conn.execute(
        "SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?", (res.blueprint_id,)).fetchone()[0])
    assert after["source_facts"] == before["source_facts"] and before["source_facts"]
    assert not any(c[0] in ("refine", "render") for c in llm.calls[start:])
    history.close()


def test_facts_block_says_so_when_nothing_survived():
    assert "none survived" in facts_block([])
    facts, _ = validate([QUOTE], SEED)
    block = facts_block(facts)
    assert "exact source wording" in block and "Maya Okafor" in block


def test_fact_beats_are_plannable_only_under_f1():
    s2 = get_policy("cat-pyq-s2")
    for beat in FACT_BEATS:
        assert beat in F1.move_vocabulary() and beat not in s2.move_vocabulary()
        assert any(beat in g for g in F1.move_groups().values())
