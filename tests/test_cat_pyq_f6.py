"""cat-pyq-f6 (2026-09-22): the two exam tasks the engine had no slot type for,
the topologies that actually draw them, and CAT's application option design.

What is pinned here:
  - consistency and argument_evaluation exist as slot types, and only for f6;
  - consistency is released as its own negative contract and is NOT support —
    an option the passage never mentions is consistent with it, which is the
    distinction 2026-09-13-cat-pyq-baseline.md section 2 asks for;
  - argument_evaluation is affirmative only (the exam negates 2 of 4 stems,
    n too small to write a contract against);
  - QT27-QT30 are invisible to legacy AND to f5, so no earlier policy's draw
    distribution moves;
  - every f6 topology still resolves exactly two negatives per medium/hard set;
  - the new topologies raise the CAT-shaped share and the inference share, and
    add no second gist slot;
  - the application design note reaches the questions prompt under f6 and not
    under f5;
  - relation_pair is deliberately absent.

Elite equality against the pre-policy engine is tests/test_generation_policy.py.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc_engine.generation_policy import LEGACY_POLICY, get_policy  # noqa: E402
from rc_engine.question_contracts import (NEGATIVE_CONTRACTS, TASK_OF_TYPE,  # noqa: E402
                                          resolve_slots)
from rc_engine.question_mix import EXAM_TASK_SHARES, TASK_OF_SLOT  # noqa: E402
from rc_engine.registry import ComponentRegistry  # noqa: E402

NEW_TOPOLOGIES = ("QT27", "QT28", "QT29", "QT30")
NEW_TYPES = ("consistency", "argument_evaluation")


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture(scope="module")
def f6():
    return get_policy("cat-pyq-f6")


@pytest.fixture(scope="module")
def f5():
    return get_policy("cat-pyq-f5")


# ---- the two missing tasks ---------------------------------------------------

def test_the_two_missing_exam_tasks_now_have_slot_types(f6, f5):
    for t in NEW_TYPES:
        assert t in f6.extra_slot_types
        assert t not in f5.extra_slot_types
        assert t in EXAM_TASK_SHARES, "the mix must be able to score the new type"
        assert TASK_OF_SLOT[t] == t, "otherwise health reports it as engine_only"


def test_f6_keeps_the_q1_types_it_inherits(f6):
    # dataclasses.replace swaps the whole mapping, so a merge that dropped
    # these would silently make QT25/QT26 uncomposable.
    for t in ("author_would_endorse", "keyword_set"):
        assert t in f6.extra_slot_types


def test_consistency_is_released_as_its_own_negative_task(f6):
    assert TASK_OF_TYPE["consistency"] == "consistency"
    assert "consistency" in f6.negative_tasks
    assert NEGATIVE_CONTRACTS["consistency"]["released"] is True
    assert len(f6.keyed_stem_forms["consistency/negative"]) >= 3


def test_consistency_is_not_support(f6):
    """The whole reason the baseline asks for a separate task: support means
    the passage asserts the option, consistency means it does not rule it out.
    A shared 'others' contract would collapse the two."""
    support = NEGATIVE_CONTRACTS["support"]
    cons = NEGATIVE_CONTRACTS["consistency"]
    assert cons["marker"] != support["marker"]
    assert cons["marker"] not in (c["marker"] for k, c in NEGATIVE_CONTRACTS.items()
                                  if k != "consistency")
    assert "NOT" in cons["others"], "must say the options need not be in the passage"


def test_argument_evaluation_is_affirmative_only(f6):
    assert "argument_evaluation" not in TASK_OF_TYPE
    assert not any(k.startswith("argument_evaluation/")
                   for k in f6.keyed_stem_forms)
    for slot in _all_new_slots(ComponentRegistry()):
        if slot["type"] == "argument_evaluation":
            assert slot.get("polarity") != "negative"


def test_relation_pair_is_deliberately_absent(f6):
    """0.3% of the exam, n=1 in 389. One stem is not evidence of a form."""
    assert "relation_pair" not in f6.extra_slot_types
    assert "relation_pair" not in TASK_OF_SLOT


# ---- topology gating ---------------------------------------------------------

def _all_new_slots(registry):
    return [s for tid in NEW_TOPOLOGIES
            for s in registry.get("topology", tid)["slots"]]


def test_the_new_topologies_are_invisible_to_legacy_and_to_f5(registry, f5):
    legacy_ids = set(LEGACY_POLICY.eligible_ids(registry, "topology"))
    f5_ids = set(f5.eligible_ids(registry, "topology", "hard"))
    for tid in NEW_TOPOLOGIES:
        assert tid not in legacy_ids, f"{tid} would change legacy's draw"
        assert tid not in f5_ids, f"{tid} would change a registered policy's draw"


def test_legacy_still_sees_exactly_its_own_topologies(registry):
    # The count that matters: adding four tagged topologies must not widen the
    # pool any untagged plan draws from.
    legacy_ids = LEGACY_POLICY.eligible_ids(registry, "topology")
    assert len(legacy_ids) == 24
    assert not any(registry.get("topology", t).get("policies") for t in legacy_ids)


@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_f6_reaches_every_cat_shaped_topology(registry, f6, tier):
    ids = set(f6.eligible_ids(registry, "topology", tier))
    assert {"QT25", "QT26", *NEW_TOPOLOGIES} <= ids


@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_the_new_topologies_raise_the_cat_shaped_share(registry, f6, f5, tier):
    def share(policy):
        ids = policy.eligible_ids(registry, "topology", tier)
        cat = [i for i in ids if registry.get("topology", i).get("policies")]
        return len(cat) / len(ids)

    assert share(f6) > 2 * share(f5), (share(f5), share(f6))


# ---- slot resolution still holds --------------------------------------------

@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_every_new_topology_resolves_exactly_two_negatives(registry, f6, tier):
    for tid in NEW_TOPOLOGIES:
        topo = registry.get("topology", tid)
        for n in range(15):
            slots = resolve_slots(topo["slots"], f6, tier, f"BP_{tid}_{n}")
            neg = [s for s in slots if s["polarity"] == "negative"]
            assert len(neg) == 2, (tid, [s["type"] for s in neg])
            assert slots[0]["polarity"] == "affirmative", "Q1 is never negated"
            assert all(s["task"] in f6.negative_tasks for s in neg)
            assert all(s["marker"] == NEGATIVE_CONTRACTS[s["task"]]["marker"]
                       for s in neg)
            assert [s["type"] for s in slots] == [s["type"] for s in topo["slots"]]


def test_a_consistency_slot_resolves_to_the_consistency_contract(registry, f6):
    topo = registry.get("topology", "QT27")       # authored-negative consistency
    slots = resolve_slots(topo["slots"], f6, "hard", "BP_fixed")
    cons = [s for s in slots if s["type"] == "consistency"]
    assert len(cons) == 1
    assert cons[0]["polarity"] == "negative"
    assert cons[0]["task"] == "consistency"
    assert cons[0]["marker"] == "passage_consistent"


# ---- what the new topologies do to the mix ----------------------------------

def test_the_new_topologies_lift_inference_toward_the_exam_share(registry):
    slots = _all_new_slots(registry)
    inference = sum(1 for s in slots if TASK_OF_SLOT.get(s["type"]) == "inference")
    share = inference / len(slots)
    # The measured gap on 2026-09-22 was 7.7% engine against 15.9% exam.
    assert share >= EXAM_TASK_SHARES["inference"], share


def test_the_new_topologies_add_no_second_gist_slot(registry):
    """Q1 is pinned to thesis (client requirement 2026-08-10), so gist has a
    hard floor of 12.5% on an 8-question set whatever the exam's 8.2% says.
    A second gist slot is the only reducible part of the over-share."""
    for tid in NEW_TOPOLOGIES:
        types = [s["type"] for s in registry.get("topology", tid)["slots"]]
        assert types[0] == "thesis"
        assert "primary_purpose" not in types
        assert types.count("thesis") == 1


def test_the_new_topologies_carry_the_new_tasks(registry):
    for tid in NEW_TOPOLOGIES:
        types = {s["type"] for s in registry.get("topology", tid)["slots"]}
        assert types & set(NEW_TYPES), tid


def test_the_new_topologies_use_no_engine_only_types(registry):
    """closure_reading, decoy_escape and counterfactual_structure have no exam
    counterpart. They stay (the client asked for the closure stem on
    2026-09-12) but they do not belong in topologies added to close a gap."""
    for s in _all_new_slots(registry):
        assert TASK_OF_SLOT.get(s["type"]) is not None, s["type"]


# ---- the application design note ---------------------------------------------

def test_the_application_design_note_reaches_the_questions_prompt(f6, f5):
    q6 = f6.system_extensions["questions"]
    q5 = f5.system_extensions["questions"]
    assert "application option design" in q6
    assert "application option design" not in q5
    assert q6.startswith(q5), "f6 must extend the q1 contract, not replace it"


def test_the_application_note_asks_for_two_constraints(f6):
    q6 = f6.system_extensions["questions"]
    assert "TWO of the passage's constraints" in q6
    assert "SAME shape" in q6


def test_the_consistency_guidance_says_not_mentioned_counts_in_favour(f6):
    """The opposite of the rule for every other contract, and the single
    easiest way to get a consistency question wrong."""
    q6 = f6.system_extensions["questions"]
    assert "can never be the key" in q6
    assert "counts in the option's favour" in q6
