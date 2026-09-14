"""cat-pyq-f3: the passage keeps its seed essay's subject and kind (2026-09-14).

The seed prose below is invented. Mock verdicts exercise routing; they are not a
claim that a mocked model can judge whether a plan drifted.
"""
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.generation_policy import get_policy, policy_for_new_plan  # noqa: E402
from rc_engine.llm import CostLedger, MockLLMClient  # noqa: E402
from rc_engine.models import RCResult, SeedEssay  # noqa: E402
from rc_engine.policy_catalog import CAT_PYQ_F2, CAT_PYQ_F3  # noqa: E402

ESSAY = (
    "Virtue ethicists have long held that a good character is a settled disposition, "
    "not a string of admirable acts. The difficulty arrives with people whose acts we "
    "admire but whose reasons we cannot share: a nurse who tends the dying out of a "
    "conviction that suffering itself is redemptive. Is her compassion a virtue if its "
    "rationale is mistaken? Aristotle would ask whether she feels the right thing, at "
    "the right time, for the right reason; the third clause is where she fails. " * 3)
DRIFT = {"same_subject": False, "same_nature": False,
         "source_subject": "virtue and mistaken reasons",
         "plan_subject": "probate treatment of struck will clauses",
         "drift": "a virtue-ethics essay became a legal-evidence passage"}


def _pipeline(tmp_path, monkeypatch, policy=CAT_PYQ_F3, verdicts=None):
    from rc_engine.history import HistoryStore
    from rc_engine.pipeline import RCPipeline

    class Spy(MockLLMClient):
        def __init__(self):
            self.calls = []
            self.verdicts = list(verdicts or [])

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append((stage, system, user))
            return super().call(ledger, stage, model, max_tokens, system, user, context)

        def _seed_fidelity(self, ctx):
            if self.verdicts:
                v = self.verdicts.pop(0)
                return v if isinstance(v, str) else json.dumps(v)
            return super()._seed_fidelity(ctx)

    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": policy, "hard": policy, "elite": ""})
    monkeypatch.setattr(config, "PASSAGE_WORD_MIN", 1)
    monkeypatch.setattr(config, "PASSAGE_WORD_MAX", 10**6)
    tmp_path.mkdir(parents=True, exist_ok=True)
    history = HistoryStore(str(tmp_path / "fidelity.db"))
    llm = Spy()
    return RCPipeline(history, llm, embed=False, rng=random.Random(8)), history, llm


def _seed():
    return SeedEssay(doc_id=None, url="https://example.org/virtue",
                     title="Right acts, wrong reasons", text=ESSAY)


def _stages(llm):
    return [c[0] for c in llm.calls]


def test_f3_is_f2_plus_seed_fidelity_and_never_reaches_elite(monkeypatch):
    f2, f3 = get_policy(CAT_PYQ_F2), get_policy(CAT_PYQ_F3)
    assert f3.seed_fidelity and not f2.seed_fidelity
    assert not get_policy("").seed_fidelity
    assert f3.source_facts and f3.strict_source_fact_audit and f3.question_contracts
    assert f3.system_extensions["compliance"] == f2.system_extensions["compliance"]
    assert "SOURCE FIDELITY" in f3.system_extensions["refine"]
    assert "elite" not in f3.tiers
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": CAT_PYQ_F3, "hard": CAT_PYQ_F3, "elite": ""})
    assert policy_for_new_plan("elite").is_legacy


def test_refine_prompt_anchors_the_seed_only_under_f3(tmp_path, monkeypatch):
    for version, anchored in ((CAT_PYQ_F3, True), (CAT_PYQ_F2, False)):
        pipe, history, llm = _pipeline(tmp_path / version, monkeypatch, policy=version)
        seed = _seed()
        info = {"genre": "conceptual_essay", "domain": "philosophy",
                "one_line": "whether compassion with mistaken reasons is a virtue",
                "concrete_particulars": ["Aristotle"], "bipolar_dispute_available": True}
        bp = pipe.composer.compose("hard", seed, CostLedger(budget_usd=1.0),
                                   seed_info=info, topic_shape_id="TS04",
                                   policy=get_policy(version))
        user = [c for c in llm.calls if c[0] == "refine"][-1][2]
        if anchored:
            assert bp.seed["subject"] == info["one_line"]
            assert bp.seed["seed_domain"] == "philosophy"
            assert "SOURCE FIDELITY" in user and info["one_line"] in user
            assert "Aristotle" in user
            assert "adapt its domain" not in user
        else:
            assert "subject" not in bp.seed
            assert "SOURCE FIDELITY" not in user and "adapt its domain" in user
        history.close()


def test_collision_rerefine_keeps_the_subject_under_f3_only(tmp_path, monkeypatch):
    for version, anchored in ((CAT_PYQ_F3, True), (CAT_PYQ_F2, False)):
        pipe, history, llm = _pipeline(tmp_path / version, monkeypatch, policy=version)
        seed = _seed()
        bp = pipe.composer.compose("hard", seed, CostLedger(budget_usd=1.0),
                                   seed_info={"genre": "conceptual_essay"},
                                   topic_shape_id="TS04", policy=get_policy(version))
        pipe.composer.refine_only(bp, seed, CostLedger(budget_usd=1.0),
                                  avoid_topics=["an older topic"])
        user = [c for c in llm.calls if c[0] == "refine"][-1][2]
        assert ("Choose a DIFFERENT domain" in user) is not anchored
        assert ("Keep the source essay's subject" in user) is anchored
        history.close()


def test_plan_check_runs_before_render_and_passes_through(tmp_path, monkeypatch):
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    res = pipe.generate_one("hard", _seed())
    assert res.status in config.SHIPPING_STATUSES, res.notes
    stages = _stages(llm)
    assert "seed_fidelity" in stages
    assert stages.index("seed_fidelity") < stages.index("render")
    check = [c for c in llm.calls if c[0] == "seed_fidelity"][0][2]
    assert "Right acts, wrong reasons" in check and "CONTENT PLAN" in check
    assert any("plan keeps the seed's subject" in n for n in res.notes)
    history.close()


def test_drifted_plan_gets_one_directed_rerefine(tmp_path, monkeypatch):
    pipe, history, llm = _pipeline(tmp_path, monkeypatch, verdicts=[DRIFT])
    res = pipe.generate_one("hard", _seed())
    assert res.status in config.SHIPPING_STATUSES, res.notes
    refines = [c for c in llm.calls if c[0] == "refine"]
    assert len(refines) == 2
    assert "previous plan left the source essay" in refines[-1][2]
    assert "legal-evidence passage" in refines[-1][2]
    assert _stages(llm).count("seed_fidelity") == 2
    history.close()


@pytest.mark.parametrize("second", [
    DRIFT,
    {"same_subject": True, "same_nature": False, "drift": "criticism became an explainer"},
    '{"same_subject": "yes", "same_nature": true}',   # not a boolean: fails closed
    "not json at all",
])
def test_plan_that_stays_off_its_seed_is_rejected_before_render(tmp_path, monkeypatch, second):
    pipe, history, llm = _pipeline(tmp_path, monkeypatch, verdicts=[DRIFT, second])
    res = pipe.generate_one("medium", _seed())
    assert res.status == "rejected_seed_fidelity", res.notes
    assert "render" not in _stages(llm)
    status = history.conn.execute("SELECT status FROM blueprints WHERE blueprint_id=?",
                                  (res.blueprint_id,)).fetchone()[0]
    assert status == "rejected_seed_fidelity"
    history.close()


def test_f2_and_seedless_attempts_never_call_the_check(tmp_path, monkeypatch):
    pipe, history, llm = _pipeline(tmp_path / "f2", monkeypatch, policy=CAT_PYQ_F2,
                                   verdicts=[DRIFT, DRIFT])
    pipe.generate_one("hard", _seed())
    assert "seed_fidelity" not in _stages(llm)
    history.close()
    pipe, history, llm = _pipeline(tmp_path / "seedless", monkeypatch, verdicts=[DRIFT, DRIFT])
    res = pipe.generate_one("hard", SeedEssay())
    assert "seed_fidelity" not in _stages(llm)
    assert res.status != "rejected_seed_fidelity"
    history.close()


def test_rendered_passage_below_the_floor_is_rejected_before_questions(tmp_path, monkeypatch):
    from rc_engine import fingerprints, seed_fidelity
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    pipe.embed = True
    monkeypatch.setattr(fingerprints, "_embed", lambda text: None)   # novelty channel off
    monkeypatch.setattr(seed_fidelity, "passage_cosine", lambda s, p: 0.41)
    res = pipe.generate_one("hard", _seed())
    assert res.status == "rejected_seed_fidelity", res.notes
    assert "render" in _stages(llm) and "questions" not in _stages(llm)
    assert any("passage-seed cosine 0.410" in n for n in res.notes)
    history.close()

    pipe, history, llm = _pipeline(tmp_path / "ok", monkeypatch)
    pipe.embed = True
    monkeypatch.setattr(seed_fidelity, "passage_cosine", lambda s, p: 0.80)
    res = pipe.generate_one("hard", _seed())
    assert res.status in config.SHIPPING_STATUSES, res.notes
    history.close()


# ---- causes fixed at the source, not only rejected ----------------------------

def test_classifier_reports_carriable_shapes_only_when_given_a_menu():
    from rc_engine.registry import ComponentRegistry
    from rc_engine.seed_classify import CLASSIFY_SYSTEM, classify_seed, shape_menu

    class Spy(MockLLMClient):
        systems = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.systems.append(system)
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    llm, reg = Spy(), ComponentRegistry()
    plain = classify_seed(_seed(), llm, CostLedger(budget_usd=1.0), "hard")
    assert "carriable_shapes" not in plain and llm.systems[-1] == CLASSIFY_SYSTEM
    menu = shape_menu(reg, ["TS01", "TS04"])
    info = classify_seed(_seed(), llm, CostLedger(budget_usd=1.0), "hard", menu=menu)
    assert info["carriable_shapes"] == ["TS01", "TS04"]
    assert "CARRIABLE TOPIC SHAPES" in llm.systems[-1] and "One Object, Read Closely" in menu

    class Named(MockLLMClient):     # the first paid batch's reply shape: ids with names
        def _seed_classify(self, ctx):
            out = json.loads(super()._seed_classify(ctx))
            out.pop("shape_verdicts")
            out["carriable_shapes"] = ["TS01 The Conceptual Dispute", "TS16", "TS16 again", "x"]
            return json.dumps(out)

    named = classify_seed(_seed(), Named(), CostLedger(budget_usd=1.0), "hard", menu=menu)
    assert named["carriable_shapes"] == ["TS01", "TS16"]

    class Levels(MockLLMClient):    # three-level verdicts (label version sl3)
        def __init__(self, verdicts):
            self.verdicts = verdicts

        def _seed_classify(self, ctx):
            out = json.loads(super()._seed_classify(ctx))
            out["shape_verdicts"] = self.verdicts
            return json.dumps(out)

    many = {"TS01": "natural", "TS02": "natural", "TS03 Name": "natural", "TS04": "possible",
            "TS05": "no"}
    info = classify_seed(_seed(), Levels(many), CostLedger(budget_usd=1.0), "hard", menu=menu)
    assert info["carriable_shapes"] == ["TS01", "TS02", "TS03"]      # natural suffice
    few = {"TS01": "natural", "TS04": "possible", "TS05": "no"}
    info = classify_seed(_seed(), Levels(few), CostLedger(budget_usd=1.0), "hard", menu=menu)
    assert info["carriable_shapes"] == ["TS01", "TS04"] and info["shapes_reported"]


def test_only_shapes_the_essay_can_carry_are_drawn_under_seed_fidelity():
    from rc_engine.registry import ComponentRegistry
    from rc_engine.seed_classify import eligible_topic_shapes
    reg = ComponentRegistry()
    info = {"genre": "conceptual_essay", "bipolar_dispute_available": True,
            "carriable_shapes": ["TS01", "TS16"]}
    f3, f2 = get_policy(CAT_PYQ_F3), get_policy(CAT_PYQ_F2)
    assert eligible_topic_shapes(reg, info, f3) == ["TS01", "TS16"]
    assert "TS03" in eligible_topic_shapes(reg, info, f2)      # f2 unchanged
    # a carriable shape the genre filter excluded still beats a forced one
    info2 = {"genre": "criticism", "bipolar_dispute_available": True,
             "carriable_shapes": ["TS07"]}
    assert eligible_topic_shapes(reg, info2, f3) == ["TS07"]
    # nothing reported: the ordinary filters stand (never a dead end)
    none = {**info, "carriable_shapes": []}
    assert eligible_topic_shapes(reg, none, f3) == eligible_topic_shapes(reg, none, f2)


def test_dispute_shape_is_capped_for_seed_fidelity_plans(tmp_path, monkeypatch):
    """First paid f3 batch: TS01 on six of nine plans. With a carriable pool of
    three shapes TS01 must be drawn about at its ceiling, not by default."""
    from rc_engine import seed_classify
    info = {"genre": "conceptual_essay", "domain": "philosophy", "one_line": "x",
            "concrete_particulars": [], "bipolar_dispute_available": True,
            "carriable_shapes": ["TS01", "TS05", "TS16"]}
    monkeypatch.setattr(seed_classify, "classify_seed", lambda *a, **k: dict(info))
    assert set(config.SEED_FIDELITY_COHORT_MAX_SHARE[0][0]) == {"TS01"}
    shares = {}
    for label, cohorts in (("capped", config.SEED_FIDELITY_COHORT_MAX_SHARE), ("uncapped", [])):
        monkeypatch.setattr(config, "SEED_FIDELITY_COHORT_MAX_SHARE", cohorts)
        pipe, history, llm = _pipeline(tmp_path / label, monkeypatch)
        pipe.composer.rng = random.Random(5)
        picks = [pipe.composer.classify_and_pick_shape(_seed(), CostLedger(budget_usd=1.0),
                                                       "hard", policy=get_policy(CAT_PYQ_F3))[1]
                 for _ in range(400)]
        shares[label] = picks.count("TS01") / len(picks)
        assert set(picks) <= set(info["carriable_shapes"])
        history.close()
    assert shares["capped"] < 0.28 and shares["uncapped"] > 0.30, shares


def test_fallback_plan_topic_comes_from_the_seed_not_the_publication(tmp_path, monkeypatch):
    for version, expect in ((CAT_PYQ_F3, "compassion with mistaken reasons"), ("", "Psyche")):
        pipe, history, llm = _pipeline(tmp_path / (version or "legacy"), monkeypatch,
                                       policy=version)
        seed = SeedEssay(title="Right acts", text=ESSAY, domain_hint="Psyche")
        bp = pipe.composer.compose("hard", seed, CostLedger(budget_usd=1.0),
                                   seed_info={"genre": "conceptual_essay",
                                              "one_line": "compassion with mistaken reasons"},
                                   topic_shape_id="TS01" if version else "",
                                   policy=get_policy(version))
        fallback = pipe.composer._fallback_refine(bp, ["M1", "M2"])
        assert expect in fallback["topic"]
        history.close()


# ---- elite: legacy engine plus seed fidelity, nothing else ----------------------

def test_legacy_sf1_is_legacy_plus_seed_fidelity_only():
    import dataclasses
    from rc_engine.generation_policy import legacy_base_errors
    from rc_engine.policy_catalog import LEGACY_SF1
    p = get_policy(LEGACY_SF1)
    assert p.legacy_base and p.seed_fidelity and p.reads_legacy and "elite" in p.tiers
    assert legacy_base_errors(p) == []
    sneaky = dataclasses.replace(p, version="sneaky", question_contracts=True)
    assert any("question_contracts" in e for e in legacy_base_errors(sneaky))
    wider = dataclasses.replace(p, version="wider", system_extensions={"compliance": "x"})
    assert any("only refine" in e for e in legacy_base_errors(wider))


def test_elite_takes_legacy_sf1_only_when_named(monkeypatch):
    from rc_engine.generation_policy import LEGACY_POLICY
    from rc_engine.policy_catalog import LEGACY_SF1
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": CAT_PYQ_F3, "hard": CAT_PYQ_F3, "elite": LEGACY_SF1})
    assert policy_for_new_plan("elite").version == LEGACY_SF1
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": CAT_PYQ_F3})
    assert policy_for_new_plan("elite") is LEGACY_POLICY


def test_cli_elite_policy_refuses_anything_but_a_legacy_based_policy(monkeypatch):
    from rc_engine import cli
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    monkeypatch.delenv("RC_ENGINE_ELITE_PLAN_POLICY", raising=False)
    assert cli._apply_elite_policy(CAT_PYQ_F3) == 2
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["elite"] == ""
    assert cli._apply_elite_policy("legacy-sf1") == 0
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["elite"] == "legacy-sf1"
    monkeypatch.delenv("RC_ENGINE_ELITE_PLAN_POLICY", raising=False)


def test_seedless_elite_plan_under_legacy_sf1_is_the_legacy_plan(tmp_path, monkeypatch):
    """With no seed text nothing fidelity-specific can apply, so every draw and
    the refine user prompt must equal legacy's: legacy_base really reads legacy."""
    from rc_engine.policy_catalog import LEGACY_SF1
    plans, prompts = [], []
    for version in ("", LEGACY_SF1):
        pipe, history, llm = _pipeline(tmp_path / (version or "legacy"), monkeypatch)
        pipe.composer.rng = random.Random(21)
        bp = pipe.composer.compose("elite", SeedEssay(), CostLedger(budget_usd=1.0),
                                   seed_info={"genre": "unknown"},
                                   policy=get_policy(version))
        d = json.loads(bp.to_json())
        for k in ("blueprint_id", "generation_policy", "seed"):
            d.pop(k, None)
        plans.append(d)
        prompts.append([c[2] for c in llm.calls if c[0] == "refine"][-1])
        history.close()
    assert plans[0] == plans[1]
    assert prompts[0] == prompts[1]


def test_elite_under_legacy_sf1_runs_the_plan_check(tmp_path, monkeypatch):
    from rc_engine.policy_catalog import LEGACY_SF1
    pipe, history, llm = _pipeline(tmp_path, monkeypatch, verdicts=[DRIFT, DRIFT])
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": LEGACY_SF1})
    res = pipe.generate_one("elite", _seed())
    assert res.status == "rejected_seed_fidelity", res.notes
    classify = [c for c in llm.calls if c[0] == "seed_classify"][0]
    assert "CARRIABLE TOPIC SHAPES" in classify[1]
    refine_system = [c for c in llm.calls if c[0] == "refine"][0][1]
    assert "SOURCE FIDELITY" in refine_system
    history.close()


# ---- resume re-clears topology before paying for questions (2026-09-14) ---------

def _failed_questions(pipe, monkeypatch):
    from rc_engine.question_engine import QuestionEngineError
    real = pipe.qengine.build

    def fail(*args, **kwargs):
        raise QuestionEngineError("forced question interruption")

    monkeypatch.setattr(pipe.qengine, "build", fail)
    res = pipe.generate_one("medium", _seed())
    assert res.status == "failed_questions", res.notes
    monkeypatch.setattr(pipe.qengine, "build", real)
    return res


def test_resume_repicks_a_topology_a_sibling_shipped_meanwhile(tmp_path, monkeypatch):
    from rc_engine.models import Blueprint
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    res = _failed_questions(pipe, monkeypatch)
    stored = Blueprint.from_json(history.conn.execute(
        "SELECT blueprint_json FROM blueprints WHERE blueprint_id=?",
        (res.blueprint_id,)).fetchone()[0])
    taken = stored.topology_id
    monkeypatch.setattr(pipe, "_topology_collisions",
                        lambda tid: [(1.0, "RC-SIBLING")] if tid == taken else [])
    resumed = pipe.resume_questions(res.blueprint_id)
    assert any("re-pick" in n for n in resumed.notes), resumed.notes
    after = Blueprint.from_json(history.conn.execute(
        "SELECT blueprint_json FROM blueprints WHERE blueprint_id=?",
        (res.blueprint_id,)).fetchone()[0])
    assert after.topology_id != taken
    assert resumed.status in config.SHIPPING_STATUSES, resumed.notes
    history.close()


def test_resume_with_no_clear_topology_pays_for_no_questions_when_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TOPOLOGY_GATE_ENFORCE", True)
    pipe, history, llm = _pipeline(tmp_path, monkeypatch)
    res = _failed_questions(pipe, monkeypatch)
    monkeypatch.setattr(pipe, "_topology_collisions", lambda tid: [(1.0, "RC-SIBLING")])
    start = len(llm.calls)
    resumed = pipe.resume_questions(res.blueprint_id)
    assert resumed.status == "rejected_novelty", resumed.notes
    assert "questions" not in [c[0] for c in llm.calls[start:]]
    status = history.conn.execute("SELECT status FROM rendered_passages WHERE blueprint_id=?",
                                  (res.blueprint_id,)).fetchone()[0]
    assert status in ("questions_failed", "awaiting_questions")
    history.close()


def test_run_slot_rotates_the_seed_after_a_fidelity_reject():
    from rc_engine.pipeline import run_slot
    first, second = _seed(), SeedEssay(doc_id="b", title="second", text=ESSAY)
    handed = []

    def provider(tier, exclude_ids=None, avoid_kinds=None):
        seed = first if not handed else second
        handed.append(seed)
        return seed, (lambda rc_id: None)

    seen = []

    class Pipe:
        embed = False

        def generate_one(self, tier, seed, ban_families=None, ban_movements=None):
            seen.append(seed)
            if len(seen) == 1:
                return RCResult(None, "BP1", tier, "rejected_seed_fidelity")
            return RCResult("RC-1", "BP2", tier, "approved")

    results = []
    run_slot(Pipe(), "hard", 1, 1, provider, set(), spent=lambda: 0.0, max_usd=10.0,
             keep=lambda res, *a: results.append(res.status))
    assert results == ["rejected_seed_fidelity", "approved"]
    assert seen == [first, second]
