"""f2 regressions: original evidence and incomplete factual audits, 2026-09-14.

All source prose is invented. Mock verdicts exercise routing, not a claim that
Python or a mocked LLM proves semantic entailment.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from rc_engine import config
from rc_engine.compliance import ComplianceAuditor
from rc_engine.generation_policy import get_policy
from rc_engine.llm import MockLLMClient
from rc_engine.models import Blueprint, ParagraphPlan, SeedEssay
from rc_engine.policy_catalog import CAT_PYQ_F2
from rc_engine.registry import ComponentRegistry
from rc_engine.source_facts import audit_evidence, facts_block, supported_claims, validate
from test_source_facts import EXCERPT, _pipeline

SOURCE = "The trial recorded 20 successes and 80 failures among participants."
REVERSED = "The trial recorded 80 successes and 20 failures among participants."


def evidence(claim=SOURCE):
    seed = SimpleNamespace(text="The preliminary report stated: " + SOURCE,
                           url="https://example.org/trial", doc_id="invented-trial")
    facts, reasons = validate([{"span": SOURCE, "claim": claim}], seed, strict=True)
    assert not reasons
    return facts


def audit(claim=SOURCE):
    return {"fact_trace_complete": True,
            "source_fact_checks": [{"fact_id": "SF1", "entailed": True,
                                    "attribution_ok": True, "qualification_ok": True}],
            "fact_trace": [{"claim": claim, "support": "source_fact",
                            "fact_ids": ["SF1"], "attribution_ok": True}]}


def blueprint():
    bp = Blueprint(blueprint_id="BP_fact_audit", tier="hard", schema_version="2.0",
                   family_id="F12", persona_id="P01", ending_id="E07", rhythm_id="T01",
                   revelation_id="R02", distractor_profile_id="D01", topology_id="QT01",
                   instability=0.5, aperture="x", generation_policy=CAT_PYQ_F2)
    bp.movement = [ParagraphPlan(1, "A", (100, 100), "mixed")]
    bp.revelation_detail = {"planned_para": 1}
    bp.source_facts = evidence()
    return bp


def test_reversed_numbers_do_not_become_the_auditors_source_of_truth():
    facts = evidence(REVERSED)  # passes structural checks, but is NOT entailed
    block = facts_block(facts, evidence=True)
    assert SOURCE in block and REVERSED in block
    assert "preliminary report" in block and "UNVERIFIED" in block
    data = audit(REVERSED)
    data["source_fact_checks"][0]["entailed"] = False
    trace, issues = audit_evidence(data, facts, REVERSED)
    assert issues and trace[0]["support"] == "unsupported"
    assert not supported_claims(trace, facts, strict=True)
    bp = blueprint()
    bp.source_facts = facts
    scored = ComplianceAuditor(None, ComponentRegistry())._score(
        data, REVERSED, bp, [], trace_facts=True)
    assert scored.unsupported_claims and scored.directives


def test_explicit_complete_supported_audit_can_suppress_only_its_claim():
    facts = evidence()
    trace, issues = audit_evidence(audit(), facts, SOURCE)
    assert not issues
    assert supported_claims(trace, facts, strict=True) == [SOURCE]
    unvalidated = audit()["fact_trace"]
    assert supported_claims(unvalidated, facts, strict=True) == []


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("fact_trace"),
    lambda d: d.update(fact_trace=None),
    lambda d: d.update(fact_trace={}),
    lambda d: d["fact_trace"].append(None),
    lambda d: d.pop("fact_trace_complete"),
    lambda d: d.update(fact_trace_complete="true"),
    lambda d: d.update(fact_trace_complete=False),
    lambda d: d.pop("source_fact_checks"),
    lambda d: d.update(source_fact_checks=[]),
    lambda d: d.update(source_fact_checks="checked"),
    lambda d: d["source_fact_checks"].append(copy.deepcopy(d["source_fact_checks"][0])),
    lambda d: d["source_fact_checks"][0].update(fact_id="SF99"),
    lambda d: d["source_fact_checks"][0].pop("entailed"),
    lambda d: d["source_fact_checks"][0].update(entailed="true"),
    lambda d: d["fact_trace"][0].pop("attribution_ok"),
    lambda d: d["fact_trace"][0].update(attribution_ok="true"),
    lambda d: d["fact_trace"][0].update(attribution_ok=False),
    lambda d: d["fact_trace"][0].update(fact_ids="SF1"),
    lambda d: d["fact_trace"][0].update(fact_ids=["SF99"]),
    lambda d: d["fact_trace"][0].update(claim="Words absent from the passage."),
])
def test_partial_and_malformed_audits_cannot_pass(mutate):
    data = audit()
    mutate(data)
    _, issues = audit_evidence(data, evidence(), SOURCE)
    assert issues


def test_missing_evidence_and_late_unsupported_rows_are_not_ignored():
    facts = evidence()
    facts[0].pop("context")
    assert audit_evidence(audit(), facts, SOURCE)[1]
    data = audit()
    data["fact_trace"] *= 20
    data["fact_trace"].append({"claim": REVERSED, "fact_ids": [],
                               "support": "unsupported", "attribution_ok": False})
    trace, issues = audit_evidence(data, evidence(), SOURCE + " " + REVERSED)
    assert len(trace) == 21 and any(i["claim"] == REVERSED for i in issues)


def test_no_facts_and_no_claims_requires_explicit_completed_empty_results():
    assert audit_evidence({}, [], "A hypothetical scene.")[1]
    assert audit_evidence({"fact_trace_complete": True, "fact_trace": [],
                           "source_fact_checks": []}, [], "A hypothetical scene.") == ([], [])


@pytest.mark.parametrize("reply,truncated", [("not JSON", False), ("{}", False),
                                              (json.dumps(audit()), True)])
def test_invalid_or_truncated_model_reply_is_an_incomplete_audit(reply, truncated):
    class Reply:
        def call(self, *args, **kwargs):
            return reply, truncated

    scored = ComplianceAuditor(Reply(), ComponentRegistry()).audit(SOURCE, blueprint(), None)
    assert any(u["support"] == "audit_incomplete" for u in scored.unsupported_claims)


def test_f1_policy_and_evidence_format_are_preserved():
    assert not get_policy("cat-pyq-f1").strict_source_fact_audit
    assert get_policy(CAT_PYQ_F2).strict_source_fact_audit
    seed = SimpleNamespace(text=SOURCE, url="", doc_id="")
    facts, _ = validate([{"span": SOURCE, "claim": SOURCE}], seed)
    assert "context" not in facts[0]
    assert "ORIGINAL EVIDENCE" not in facts_block(facts)
    assert "ORIGINAL-EVIDENCE AUDIT" not in get_policy("cat-pyq-f1").system_extensions["compliance"]


@pytest.mark.parametrize("fault", ["missing_trace", "missing_attribution", "bad_source_claim"])
def test_f2_incomplete_or_false_audit_routes_to_review(tmp_path, monkeypatch, fault):
    pipe, history, _ = _pipeline(tmp_path, monkeypatch, policy=CAT_PYQ_F2)
    original = MockLLMClient._compliance

    def broken(self, ctx):
        out = json.loads(original(self, ctx))
        if fault == "missing_trace":
            out.pop("fact_trace", None)
        elif fault == "missing_attribution":
            out["fact_trace"] = [{"claim": ctx["passage"].split(".")[0],
                                  "fact_ids": ["SF1"], "support": "source_fact"}]
        else:
            assert out["source_fact_checks"]
            out["source_fact_checks"][0]["entailed"] = False
        return json.dumps(out)

    monkeypatch.setattr(MockLLMClient, "_compliance", broken)
    monkeypatch.setattr(config, "PASSAGE_WORD_MIN", 1)
    monkeypatch.setattr(config, "PASSAGE_WORD_MAX", 10**6)
    result = pipe.generate_one("medium", SeedEssay(url="u", text=EXCERPT))
    assert result.status == "needs_review", result.notes
    assert any("source facts:" in n and "routed to needs_review" in n for n in result.notes)
    history.close()


def test_f2_original_evidence_reaches_both_models_and_survives_resume(tmp_path, monkeypatch):
    from rc_engine.question_engine import QuestionEngineError
    pipe, history, llm = _pipeline(tmp_path, monkeypatch, policy=CAT_PYQ_F2)
    real = pipe.qengine.build

    def fail(*args, **kwargs):
        raise QuestionEngineError("forced question interruption")

    monkeypatch.setattr(pipe.qengine, "build", fail)
    result = pipe.generate_one("hard", SeedEssay(url="u", text=EXCERPT))
    assert result.status == "failed_questions", result.notes
    stored = history.conn.execute("SELECT blueprint_json FROM blueprints WHERE blueprint_id=?",
                                  (result.blueprint_id,)).fetchone()[0]
    bp = Blueprint.from_json(stored)
    assert bp.source_facts and all(f["span"] in f["context"] for f in bp.source_facts)
    for stage in ("render", "compliance"):
        call = [c for c in llm.calls if c[0] == stage][-1]
        for f in bp.source_facts:
            assert json.dumps(f["span"], ensure_ascii=False) in call[2]
            assert json.dumps(f["context"], ensure_ascii=False) in call[2]
    start = len(llm.calls)
    monkeypatch.setattr(pipe.qengine, "build", real)
    resumed = pipe.resume_questions(result.blueprint_id)
    assert resumed.status in config.SHIPPING_STATUSES, resumed.notes
    assert not any(c[0] in ("refine", "render") for c in llm.calls[start:])
    again = history.conn.execute("SELECT blueprint_json FROM blueprints WHERE blueprint_id=?",
                                 (result.blueprint_id,)).fetchone()[0]
    assert Blueprint.from_json(again).source_facts == bp.source_facts
    history.close()
