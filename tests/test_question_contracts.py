"""cat-pyq-q1 question contracts (plan section 4), 2026-09-13.

What is pinned here:
  - every released contract has a valid fixture with a defensible key, and the
    structural counterexamples of each are rejected by the validator;
  - semantic defects the validator CANNOT see are recorded as such, so nobody
    mistakes the deterministic checks (or solver agreement) for verification;
  - slot resolution: exactly two negatives per medium/hard set, only released
    tasks, pre-existing EXCEPT slots counted, no traps on negative slots,
    deterministic per blueprint, stored and reused on resume;
  - a topology that cannot carry the target is never composed or re-picked;
  - negative stems are never dealt to affirmative contracts, or the reverse;
  - contract markers stay out of trap histograms;
  - an end-to-end mock run: stored slots, QA prompt extensions, fingerprint
    negation counts, resume, and elite untouched in the same run;
  - policy validation, the run-level opt-in and the env override.
Elite equality against the pre-policy engine is tests/test_generation_policy.py.
"""
import collections
import copy
import json
import os
import pathlib
import random
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc_engine import config  # noqa: E402
from rc_engine.generation_policy import (LEGACY_POLICY, GenerationPolicy, _ro,  # noqa: E402
                                         get_policy, temporary_policy, validation_errors)
from rc_engine.policy_catalog import CAT_PYQ_F6, CAT_PYQ_Q1  # noqa: E402
from rc_engine.question_contracts import (CONTRACT_MARKERS, NEGATIVE_CONTRACTS,  # noqa: E402
                                          STAGED_NEGATIVE_STEM_FORMS, TASK_OF_TYPE,
                                          ContractError, bad_paragraph_refs,
                                          keyword_set_problems, missing_quotes,
                                          negation_count, resolve_slots, stem_key,
                                          topology_supports)
from rc_engine.question_engine import QuestionEngine, QuestionEngineError  # noqa: E402
from rc_engine.registry import ComponentRegistry  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "question_contracts.json")
                     .read_text(encoding="utf-8"))
PASSAGE = FIXTURE["passage"]
VALID = {v["name"]: v for v in FIXTURE["valid"]}
POLICY = get_policy(CAT_PYQ_Q1)
SHIPPED = ("approved", "needs_review", "solver_dispute")


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture(scope="module")
def engine(registry):
    return QuestionEngine(registry, llm=None)


def _check(engine, name, mutate=None):
    item = copy.deepcopy(VALID[name])
    if mutate:
        mutate(item["question"], item["slot"])
    engine._validate_contracts([item["question"]], [item["slot"]], PASSAGE)


# ---- fixtures and counterexamples --------------------------------------------------

def test_fixture_covers_every_released_contract_and_new_type():
    contracts = {v["slot"]["contract"] for v in FIXTURE["valid"]}
    released = {f"{t}_negative" for t, c in NEGATIVE_CONTRACTS.items() if c["released"]}
    assert released <= contracts
    types = {(v["slot"]["type"], v["slot"].get("variant")) for v in FIXTURE["valid"]}
    assert {("author_would_endorse", None), ("keyword_set", "keywords"),
            ("keyword_set", "sequence")} <= types
    # 2026-09-22: consistency was released for cat-pyq-f6, so q1 no longer
    # enables every released task. The invariants that still must hold are that
    # no policy enables an UNRELEASED one, and that some registered policy
    # exercises each release — otherwise a contract could rot unused.
    released = {t for t, c in NEGATIVE_CONTRACTS.items() if c["released"]}
    assert set(POLICY.negative_tasks) <= released
    assert set(get_policy(CAT_PYQ_F6).negative_tasks) == released


@pytest.mark.parametrize("name", list(VALID))
def test_valid_fixture_passes_structural_checks(engine, name):
    _check(engine, name)


def _set_mech(i, m):
    return lambda q, s: q["wrong"][i].__setitem__("mechanism", m)


NEGATIVE = "support_negative on detail_check"
COUNTEREXAMPLES = [
    (NEGATIVE, "marker missing on one option", _set_mech(1, "scope_inflation"), "passage_supported"),
    (NEGATIVE, "stem lost its negation",
     lambda q, s: q.__setitem__("stem", "According to the passage, which is true of the notes?"),
     "exactly one negation"),
    (NEGATIVE, "double negation",
     lambda q, s: q.__setitem__("stem", "All of the following, if false, are consistent, EXCEPT:"),
     "exactly one negation"),
    (NEGATIVE, "no failure mode", lambda q, s: q["correct"].pop("failure_mode"), "failure_mode"),
    (NEGATIVE, "'not mentioned' is not a failure mode",
     lambda q, s: q["correct"].__setitem__("failure_mode", "not_mentioned"), "failure_mode"),
    (NEGATIVE, "unexplained supported option",
     lambda q, s: q["wrong"][2].__setitem__("why_wrong", ""), "why_wrong"),
    ("application_negative", "support marker on an application contract",
     _set_mech(0, "passage_supported"), "rule_satisfied"),
    ("author_would_endorse (affirmative)", "affirmative stem negated",
     lambda q, s: q.__setitem__("stem", "The author would NOT support which one of the following?"),
     "must not be negated"),
    ("author_would_endorse (affirmative)", "marker in an affirmative question",
     _set_mech(0, "passage_supported"), "marks wrong options"),
    ("author_would_endorse (affirmative)", "mechanism outside the allowed list",
     _set_mech(0, "vibes"), "outside the allowed list"),
    ("keyword_set keywords", "three keywords",
     lambda q, s: q["correct"].__setitem__("text", "tide tables, pilots' notes, bar soundings"),
     "needs 4-5"),
    ("keyword_set keywords", "keyword too long",
     lambda q, s: q["wrong"][0].__setitem__("text", "tide tables, folklore, dredging, printing the tables every winter"),
     "exceeds 4 words"),
    ("keyword_set keywords", "sequence arrows in a keyword set",
     lambda q, s: q["wrong"][1].__setitem__("text", "pilots' notes → temperament → customs house → masters"),
     "needs 4-5"),
    ("keyword_set sequence", "commas in a sequence",
     lambda q, s: q["wrong"][1].__setitem__("text", "official tables, folklore, dredging costs, winter printing"),
     "needs 4-5"),
    ("keyword_set sequence", "duplicate option",
     lambda q, s: q["wrong"][2].__setitem__("text", q["correct"]["text"]),
     "same items"),
    ("contextual_inference with an exact quote (affirmative)", "quote not in the passage",
     lambda q, s: q.__setitem__("stem", q["stem"].replace("never been", "not been")),
     "not in the passage"),
    (NEGATIVE, "paragraph that does not exist",
     lambda q, s: q.__setitem__("stem", "According to paragraph 7, all of the following are true, EXCEPT:"),
     "paragraph 7"),
]


@pytest.mark.parametrize("name,defect,mutate,match", COUNTEREXAMPLES,
                         ids=[c[1] for c in COUNTEREXAMPLES])
def test_structural_counterexamples_are_rejected(engine, name, defect, mutate, match):
    with pytest.raises(QuestionEngineError, match=match):
        _check(engine, name, mutate)


@pytest.mark.parametrize("case", FIXTURE["semantic_counterexamples"],
                         ids=[c["defect"] for c in FIXTURE["semantic_counterexamples"]])
def test_semantic_defects_are_not_claimed_by_the_validator(engine, case):
    """These are broken questions the structural checks PASS. Recorded so the
    limit is explicit: uniqueness and key quality stay with answerability QA,
    the blind solver and human review."""
    def mutate(q, s):
        if "replace_wrong" in case:
            q["wrong"][case["replace_wrong"]] = case["with"]
        if "replace_correct" in case:
            q["correct"] = case["replace_correct"]
    _check(engine, case["base"], mutate)


def test_quote_and_paragraph_helpers():
    assert missing_quotes("What does 'the notes recorded what the bar did' imply?", PASSAGE) == []
    assert missing_quotes("The author’s phrase “a different question” refers to:", PASSAGE) == []
    assert missing_quotes("In 'The gauge sat in still water … behind the breakwater', the author:",
                          PASSAGE) == []
    assert missing_quotes("The pilots' notes and the survey's 'nine days in ten' show:", PASSAGE) == []
    assert missing_quotes("Why is 'a quiet revolution' mentioned?", PASSAGE) == ["a quiet revolution"]
    assert bad_paragraph_refs("In the fifth paragraph and paragraph 2, the author:", PASSAGE) == []
    assert bad_paragraph_refs("In the sixth paragraph, the author:", PASSAGE) == [6]


def test_negation_count_reads_cat_operators_only():
    assert negation_count("All of the following are true, EXCEPT:") == 1
    assert negation_count("Which one is NOT supported?") == 1
    assert negation_count("The author is least likely to agree with:") == 1
    # lowercase "not" inside an affirmative contract is not a negated stem
    assert negation_count("Which position is described but not endorsed by the author?") == 0
    assert negation_count("All of the following, if false, are consistent, EXCEPT:") == 2


def test_staged_negative_forms_are_single_negations_and_unreleased():
    for stype, forms in STAGED_NEGATIVE_STEM_FORMS.items():
        assert not NEGATIVE_CONTRACTS[TASK_OF_TYPE[stype]]["released"]
        assert all(negation_count(f) == 1 for f in forms), forms
        assert f"{stype}/negative" not in POLICY.keyed_stem_forms


# ---- slot resolution ---------------------------------------------------------------

def _pool(registry, policy, tier):
    from rc_engine.composer import BlueprintComposer
    c = BlueprintComposer.__new__(BlueprintComposer)
    c.registry = registry
    return [t for t in policy.eligible_ids(registry, "topology", tier)
            if c._topology_allowed(t, tier)]


@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_every_policy_topology_resolves_exactly_two_released_negatives(registry, tier):
    for tid in _pool(registry, POLICY, tier):
        topo = registry.get("topology", tid)
        for n in range(15):
            slots = resolve_slots(topo["slots"], POLICY, tier, f"BP_{tid}_{n}")
            neg = [s for s in slots if s["polarity"] == "negative"]
            assert len(neg) == 2, (tid, slots)
            assert slots[0]["polarity"] == "affirmative"
            assert all(s["task"] in POLICY.negative_tasks for s in neg)
            assert all(s["marker"] == NEGATIVE_CONTRACTS[s["task"]]["marker"] for s in neg)
            # pre-existing EXCEPT slots count toward the two and keep their type
            assert all(s["polarity"] == "negative" for s in slots if s["type"] == "except_scan")
            assert [s["type"] for s in slots] == [s["type"] for s in topo["slots"]]
            for s in slots:
                assert ("variant" in s) == (s["type"] == "keyword_set")


def test_resolution_is_deterministic_and_varies_across_plans(registry):
    topo = registry.get("topology", "QT07")      # several negatable slots, no EXCEPT
    a = resolve_slots(topo["slots"], POLICY, "hard", "BP_fixed")
    assert a == resolve_slots(topo["slots"], POLICY, "hard", "BP_fixed")
    patterns = {tuple(s["polarity"] for s in resolve_slots(topo["slots"], POLICY, "hard", f"BP_{n}"))
                for n in range(30)}
    assert len(patterns) > 1


def test_topology_without_capacity_is_refused_not_inverted(registry):
    for tid in ("QT05", "QT19"):
        topo = registry.get("topology", tid)
        assert not topology_supports(topo, POLICY, "hard")
        with pytest.raises(ContractError):
            resolve_slots(topo["slots"], POLICY, "hard", "BP_x")
        assert tid not in POLICY.eligible_ids(registry, "topology", "hard")
        assert tid in LEGACY_POLICY.eligible_ids(registry, "topology", "hard")
    for tid in ("QT25", "QT26"):
        assert tid not in LEGACY_POLICY.eligible_ids(registry, "topology", "hard")
        assert tid in POLICY.eligible_ids(registry, "topology", "medium")


def _bp(registry, topology_id, blueprint_id, tier="hard", policy=CAT_PYQ_Q1, traps=True):
    from rc_engine.models import Blueprint
    bp = Blueprint(
        blueprint_id=blueprint_id, tier=tier, schema_version=config.BLUEPRINT_SCHEMA_VERSION,
        family_id="F01", persona_id="P01", ending_id="E01", rhythm_id="T01",
        revelation_id="R01", distractor_profile_id="D01", topology_id=topology_id,
        instability=0.5, aperture="x", generation_policy=policy)
    bp.letter_plan = ["ABCD"[i % 4] for i in range(config.QUESTIONS_PER_SET)]
    if traps:
        bp.trap_map = [{"trap_id": f"TR{i}", "anchor_para": 1, "invited_misreading": "m",
                        "mechanism": m} for i, m in
                       enumerate(["scope_inflation", "premature_closure", "stance_misread"], 1)]
    return bp


def test_negative_slots_carry_no_trap_and_traps_still_land(registry, engine):
    for tid in POLICY.eligible_ids(registry, "topology", "hard"):
        for n in range(5):
            slots = engine.effective_slots(_bp(registry, tid, f"BP_{tid}_{n}"))
            assert not [s for s in slots if s["polarity"] == "negative" and "trap_id" in s]
            assert len({s["trap_id"] for s in slots if "trap_id" in s}) == 3


def test_legacy_plans_get_no_contract_fields(registry, engine):
    slots = engine.effective_slots(_bp(registry, "QT01", "BP_legacy", policy=""))
    assert not any({"polarity", "contract", "task", "marker"} & set(s) for s in slots)


# ---- stems -------------------------------------------------------------------------

def test_negative_stems_never_meet_affirmative_contracts(registry, engine):
    seen = collections.Counter()
    for tid in POLICY.eligible_ids(registry, "topology", "hard"):
        for n in range(20):
            bp = _bp(registry, tid, f"BP_stems_{tid}_{n}")
            slots = engine.effective_slots(bp)
            shapes = engine._stem_shapes(slots, bp, POLICY)
            for slot, shape in zip(slots, shapes):
                assert shape, (tid, slot)
                expected = 1 if slot["polarity"] == "negative" else 0
                assert negation_count(shape) == expected, (tid, slot, shape)
                if slot["type"] == "keyword_set":
                    assert shape in POLICY.keyed_stem_forms[stem_key(slot)]
                seen[stem_key(slot)] += 1
    assert {"detail_check/negative", "application/negative", "contextual_inference/negative",
            "keyword_set/keywords", "keyword_set/sequence", "author_would_endorse"} <= set(seen)


def test_shared_stem_pool_is_untouched(registry):
    before = copy.deepcopy(registry.stem_forms)
    POLICY.stem_pool(registry)["thesis"].append("mutated")
    assert registry.stem_forms == before
    assert "author_would_endorse" not in registry.stem_forms


# ---- trap histogram --------------------------------------------------------------

def test_contract_markers_stay_out_of_the_trap_histogram(registry, engine):
    bp = _bp(registry, "QT26", "BP_hist")
    slots = engine.effective_slots(bp)
    questions = []
    for s in slots:
        mech = s.get("marker") or "scope_inflation"
        questions.append({"stem": "s", "slot_type": "whatever the model said",
                          "correct": {"text": "c", "why_right": "r"},
                          "wrong": [{"text": f"w{j}", "mechanism": mech, "why_wrong": "x"}
                                    for j in range(3)]})
    out = engine._letter_assign(questions, bp, slots)
    assert not CONTRACT_MARKERS & set(out["trap_usage"])
    assert out["trap_usage"]["scope_inflation"] == 3 * (config.QUESTIONS_PER_SET - 2)
    assert [q["slot_type"] for q in out["questions"]] == [s["type"] for s in slots]
    assert sum(q["polarity"] == "negative" for q in out["questions"]) == 2


# ---- end to end on the mock --------------------------------------------------------

@pytest.fixture
def run(tmp_path, monkeypatch):
    from rc_engine.history import HistoryStore
    from rc_engine.llm import MockLLMClient
    from rc_engine.pipeline import RCPipeline

    class TextLLM(MockLLMClient):
        def __init__(self):
            self.calls = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append({"stage": stage, "system": system, "user": user,
                               "context": dict(context or {})})
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": CAT_PYQ_Q1, "hard": CAT_PYQ_Q1, "elite": ""})
    history = HistoryStore(str(tmp_path / "h.db"))
    llm = TextLLM()
    pipe = RCPipeline(history, llm, embed=False, rng=random.Random(913))
    yield SimpleNamespace(pipe=pipe, llm=llm, history=history)
    history.close()


def _seed(n):
    from rc_engine.models import SeedEssay
    return SeedEssay(url=f"https://example.org/q-{n}", title=f"Q source {n}",
                     text="A county archive kept two registers of the same river crossings.")


def _stored(run, bp_id):
    from rc_engine.models import Blueprint
    row = run.history.conn.execute("SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?",
                                   (bp_id,)).fetchone()
    return Blueprint.from_json(row[0])


def test_mock_run_ships_contract_sets_and_leaves_elite_legacy(run):
    for n, tier in enumerate(("hard", "medium", "elite")):
        start = len(run.llm.calls)
        res = run.pipe.generate_one(tier, _seed(n))
        assert res.status in SHIPPED, res.notes
        bp = _stored(run, res.blueprint_id)
        calls = run.llm.calls[start:]
        by = collections.defaultdict(list)
        for c in calls:
            by[c["stage"]].append(c)
        fp = run.history.conn.execute(
            "SELECT stylometry FROM fingerprints WHERE blueprint_id = ?",
            (res.blueprint_id,)).fetchone()
        stylo = json.loads(fp[0]) if fp else {}
        if tier == "elite":
            assert bp.generation_policy == "" and bp.question_slots == []
            assert "polarity:" not in by["questions"][0]["user"]
            assert all("NEGATED STEMS" not in c["system"] and "QUESTION CONTRACTS" not in c["system"]
                       for c in calls)
            assert "_negated_slots" not in stylo
            continue
        assert bp.generation_policy == CAT_PYQ_Q1
        assert sum(s["polarity"] == "negative" for s in bp.question_slots) == 2
        q = by["questions"][0]
        assert q["context"]["slots"] == bp.question_slots
        assert "QUESTION CONTRACTS" in q["system"] and "polarity: NEGATIVE" in q["user"]
        assert "NEGATED STEMS" in by["answerability"][0]["system"]
        assert "negated" in by["solver"][0]["system"]
        assert "contract marker" in by["judge"][0]["system"]
        assert stylo.get("_negated_slots") == 2


def test_resume_reuses_contract_slots_and_policy(run, monkeypatch):
    from rc_engine.question_engine import QuestionEngineError as QEE
    real = run.pipe.qengine.build
    fired = {"n": 0}

    def build(*a, **kw):
        if not fired["n"]:
            fired["n"] += 1
            raise QEE("forced")
        return real(*a, **kw)
    monkeypatch.setattr(run.pipe.qengine, "build", build)
    res = run.pipe.generate_one("hard", _seed(7))
    assert res.status == "failed_questions"
    stored = _stored(run, res.blueprint_id).question_slots
    assert sum(s["polarity"] == "negative" for s in stored) == 2
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    start = len(run.llm.calls)
    again = run.pipe.resume_questions(res.blueprint_id)
    assert again.status in SHIPPED, again.notes
    q = [c for c in run.llm.calls[start:] if c["stage"] == "questions"][0]
    assert q["context"]["slots"] == stored
    assert "QUESTION CONTRACTS" in q["system"]


def test_bad_generation_is_retried_then_failed(run, monkeypatch):
    """A model that ignores the contract gets one corrective retry and then a
    resumable failed_questions — never a shipped inverted question."""
    from rc_engine.llm import MockLLMClient
    real = MockLLMClient._contract_question

    def sloppy(i, slot, bp, mechs):
        q = real(i, slot, bp, mechs)
        if slot["polarity"] == "negative":
            q["wrong"][0]["mechanism"] = mechs[0]
        return q
    monkeypatch.setattr(MockLLMClient, "_contract_question", staticmethod(sloppy))
    start = len(run.llm.calls)
    res = run.pipe.generate_one("medium", _seed(8))
    assert res.status == "failed_questions"
    qcalls = [c for c in run.llm.calls[start:] if c["stage"] == "questions"]
    assert len(qcalls) == config.MAX_QUESTION_ATTEMPTS
    assert "YOUR PREVIOUS RESPONSE WAS INVALID" in qcalls[-1]["user"]


# ---- validation and rollout switches ---------------------------------------------

def test_production_policy_validates(registry):
    assert validation_errors(registry) == []


def test_contract_policy_validation_names_each_problem(registry):
    bad = GenerationPolicy(
        version="bad-contracts", tiers=frozenset({"medium", "hard"}),
        question_contracts=True,
        negative_tasks=frozenset({"support", "application", "weaken"}),
        negative_slots_per_set=_ro({"medium": 2, "elite": 2}),
        keyed_stem_forms=_ro({"detail_check/negative": ["Which is true of {X}?", "a EXCEPT", "b EXCEPT"],
                              "application/negative": ["x NOT", "y NOT"]}),
        extra_stem_forms=_ro({"stance": ["Which view does the author NOT hold?"]}))
    with temporary_policy(bad):
        errors = " | ".join(validation_errors(registry))
    assert "unreleased negative task 'weaken'" in errors
    assert "sets a negative target for 'elite'" in errors
    assert "needs exactly one negation: 'Which is true of {X}?'" in errors
    assert "can negate 'application' but has fewer than" in errors
    assert "affirmative stem 'stance' is negated" in errors


def test_cli_opt_in_sets_config_and_worker_environment(monkeypatch):
    from rc_engine import cli
    monkeypatch.setenv("RC_ENGINE_NEW_PLAN_POLICY", "")
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        dict(config.GENERATION_POLICY_FOR_NEW_PLANS))
    assert cli._apply_generation_policy("no-such-policy") == 2
    assert cli._apply_generation_policy(CAT_PYQ_Q1) == 0
    assert os.environ["RC_ENGINE_NEW_PLAN_POLICY"] == CAT_PYQ_Q1
    assert config.GENERATION_POLICY_FOR_NEW_PLANS == {
        "medium": CAT_PYQ_Q1, "hard": CAT_PYQ_Q1, "elite": ""}
    assert cli._apply_generation_policy("") == 0
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["hard"] == ""


def test_default_config_is_legacy_and_env_override_skips_elite():
    code = ("from rc_engine import config; import json; "
            "print(json.dumps(config.GENERATION_POLICY_FOR_NEW_PLANS))")
    env = dict(os.environ, RC_ENGINE_NEW_PLAN_POLICY="")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == {"medium": "", "hard": "", "elite": ""}
    env["RC_ENGINE_NEW_PLAN_POLICY"] = CAT_PYQ_Q1
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == {"medium": CAT_PYQ_Q1, "hard": CAT_PYQ_Q1, "elite": ""}
