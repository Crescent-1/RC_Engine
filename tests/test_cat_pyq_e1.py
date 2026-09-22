"""cat-pyq-e1 (2026-09-22): the ELITE question release.

Operator decision the same day, amending the 2026-09-14 rule that elite may
only take a legacy-based policy. Elite takes sections A, C and D of the
2026-09-22 review — questions, source facts, seed handling — and NOT section B,
which is everything that changes how a passage reads.

What is pinned here:
  - e1 admits elite and no other tier, and is elite_base;
  - elite_base_errors refuses every section-B field, and the guard is tested
    against a policy that tries to sneak one in — not just against e1 passing;
  - e1's component pools for family, persona, ending, rhythm, revelation and
    topic_shape are IDENTICAL to legacy's, so elite prose is untouched;
  - it adds no system text to render, and rewrites only the compliance
    RESPONSE SCHEMA (source_facts needs a fact_trace key);
  - the hard/elite differentiator: three negative slots at elite against two at
    hard, plus QT31/QT32 reachable by e1 alone and authored above elite's own
    difficulty floor;
  - elite still resolves to legacy unless a run opts in;
  - the CLI accepts e1 for elite and still refuses f6.

Elite equality against the pre-policy engine when medium/hard run a policy is
tests/test_generation_policy.py; that isolation is unaffected because elite
only moves when --elite-policy names a policy.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc_engine import config  # noqa: E402
from rc_engine.generation_policy import (LEGACY_POLICY, GenerationPolicy, _ro,  # noqa: E402
                                         elite_base_errors, get_policy,
                                         policy_for_new_plan, temporary_policy,
                                         validation_errors)
from rc_engine.policy_catalog import CAT_PYQ_E1, CAT_PYQ_F6  # noqa: E402
from rc_engine.question_contracts import resolve_slots  # noqa: E402
from rc_engine.registry import ComponentRegistry  # noqa: E402

ELITE_ONLY_TOPOLOGIES = ("QT31", "QT32")
# The libraries section B widens. e1 must match legacy on every one.
PASSAGE_LIBRARIES = ("family", "persona", "ending", "rhythm", "revelation",
                     "topic_shape")


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture(scope="module")
def e1():
    return get_policy(CAT_PYQ_E1)


@pytest.fixture(scope="module")
def f6():
    return get_policy(CAT_PYQ_F6)


# ---- shape of the policy -----------------------------------------------------

def test_e1_admits_elite_and_nothing_else(e1):
    assert set(e1.tiers) == {"elite"}
    assert e1.elite_base is True
    assert e1.legacy_base is False


def test_e1_passes_its_own_guard_and_registration(e1, registry):
    assert elite_base_errors(e1) == []
    assert validation_errors(registry) == []


def test_e1_takes_sections_a_c_and_d(e1):
    assert e1.question_contracts is True                      # A
    assert {"consistency", "argument_evaluation"} <= set(e1.extra_slot_types)
    assert e1.source_facts is True and e1.strict_source_fact_audit is True   # C
    assert e1.seed_fidelity is True                           # D
    assert e1.coherent_plans is True and e1.render_seed_context is True
    assert e1.underdelivered_beats is True


def test_e1_takes_no_section_b_field(e1):
    """The fields that change how a passage reads must equal legacy's."""
    for name in ("extra_moves", "extra_move_groups", "extra_argument_schemas",
                 "extra_closing_postures", "extra_ending_beats",
                 "extra_exam_derived_shapes", "weight_adjuster",
                 "genre_filtered_personas", "passage_permissions",
                 "family_bound_components", "closing_beat_postures",
                 "revelation_schema_exclusions"):
        assert getattr(e1, name) == getattr(LEGACY_POLICY, name), name


# ---- the guard actually bites ------------------------------------------------

def test_the_guard_refuses_a_policy_that_smuggles_section_b_in():
    bad = GenerationPolicy(
        version="bad-elite", tiers=frozenset({"elite", "hard"}), elite_base=True,
        genre_filtered_personas=True, passage_permissions=True,
        system_extensions=_ro({"render": "be bolder"}),
        system_rewrites=_ro({"render": (("a", "b"),)}),
        prompt_extensions=_ro({"questions": "x"}))
    errors = " | ".join(elite_base_errors(bad))
    assert "changes 'genre_filtered_personas'" in errors
    assert "changes 'passage_permissions'" in errors
    assert "must admit elite and no other tier" in errors
    assert "extends system prompts ['render']" in errors
    assert "rewrites system prompts ['render']" in errors
    assert "extends user prompts ['questions']" in errors


def test_a_registered_elite_policy_is_validated(registry):
    bad = GenerationPolicy(version="bad-elite-2", tiers=frozenset({"elite"}),
                           elite_base=True, genre_filtered_personas=True)
    with temporary_policy(bad):
        errors = " | ".join(validation_errors(registry))
    assert "changes 'genre_filtered_personas'" in errors


def test_a_policy_cannot_be_both_legacy_based_and_elite_based(registry):
    bad = GenerationPolicy(version="bad-elite-3", tiers=frozenset({"elite"}),
                           legacy_base=True, elite_base=True)
    with temporary_policy(bad):
        errors = " | ".join(validation_errors(registry))
    assert "cannot be both legacy-based and elite-based" in errors


# ---- elite prose is untouched ------------------------------------------------

def test_e1_draws_exactly_legacys_passage_components(e1, registry, f6):
    for ct in PASSAGE_LIBRARIES:
        legacy_ids = set(LEGACY_POLICY.eligible_ids(registry, ct))
        assert set(e1.eligible_ids(registry, ct)) == legacy_ids, ct
        # and f6 really would have widened it, so this is a live constraint
        assert set(f6.eligible_ids(registry, ct)) > legacy_ids, ct


def test_e1_never_touches_the_render_prompt(e1):
    assert "render" not in e1.system_extensions
    assert "render" not in e1.system_rewrites
    assert set(e1.system_rewrites) == {"compliance"}


def test_the_compliance_rewrite_only_adds_fact_trace(e1):
    (anchor, replacement), = e1.system_rewrites["compliance"]
    from rc_engine.compliance import COMPLIANCE_SYSTEM
    assert anchor in COMPLIANCE_SYSTEM, "anchor must exist or the rewrite is a no-op"
    assert "fact_trace" in replacement
    # f6 also injects unpermitted_devices here; that belongs to
    # passage_permissions, a section B field elite does not take.
    assert "unpermitted_devices" not in replacement


def test_the_refine_prompt_names_no_beat_elite_cannot_plan(e1):
    """f6's version prefers facts that carry the four fact beats. Elite plans
    legacy moves and can never carry them, so naming them would be dead text."""
    refine = e1.prompt_extensions["refine"]
    assert "source_facts" in refine
    for beat in ("NEWS_DATA_HOOK", "STUDY_WALKTHROUGH", "EXPERT_AS_SPINE",
                 "QUOTE_CLOSE"):
        assert beat not in refine


# ---- the differentiator ------------------------------------------------------

def test_elite_carries_more_negation_than_hard(e1, f6):
    assert e1.negative_slots_per_set["elite"] == 3
    assert f6.negative_slots_per_set["hard"] == 2
    # CAT 2020-24 runs 41.5% negated; elite at 37.5% sits closer than hard's 25%.
    assert 3 / config.QUESTIONS_PER_SET > 2 / config.QUESTIONS_PER_SET


def test_every_elite_topology_resolves_exactly_three_negatives(e1, registry):
    pool = e1.eligible_ids(registry, "topology", "elite")
    assert pool, "elite pool must not be empty"
    for tid in pool:
        topo = registry.get("topology", tid)
        for n in range(10):
            slots = resolve_slots(topo["slots"], e1, "elite", f"BP_{tid}_{n}")
            neg = [s for s in slots if s["polarity"] == "negative"]
            assert len(neg) == 3, (tid, [s["type"] for s in neg])
            assert slots[0]["polarity"] == "affirmative"


def test_the_elite_pool_clears_the_exclusion_window(e1, registry):
    """config.py records that a pool near EXCLUSION_WINDOWS['topology'] both
    repeats itself and can dead-end sample_skeleton."""
    pool = e1.eligible_ids(registry, "topology", "elite")
    assert len(pool) > config.EXCLUSION_WINDOWS["topology"], len(pool)


def test_the_elite_topologies_belong_to_e1_alone(registry, e1, f6):
    assert set(ELITE_ONLY_TOPOLOGIES) <= set(e1.eligible_ids(registry, "topology", "elite"))
    for name, policy in (("legacy", LEGACY_POLICY), ("f5", get_policy("cat-pyq-f5")),
                         ("f6", f6)):
        try:
            ids = set(policy.eligible_ids(registry, "topology", "hard"))
        except Exception:                                      # noqa: BLE001
            ids = set(policy.eligible_ids(registry, "topology"))
        assert not (ids & set(ELITE_ONLY_TOPOLOGIES)), name


def test_the_elite_topologies_are_authored_above_elites_difficulty_floor(registry):
    """TIER_SLOT_SCALING['elite'] raises anything under 0.60. Authoring below it
    would mean the stored plan and the prompt disagree."""
    floor = config.TIER_SLOT_SCALING["elite"]["floor"]
    cap = config.TIER_SLOT_SCALING["elite"]["cap"]
    for tid in ELITE_ONLY_TOPOLOGIES:
        ds = [s["difficulty"] for s in registry.get("topology", tid)["slots"]]
        assert min(ds) >= floor, (tid, min(ds))
        assert max(ds) <= cap, (tid, max(ds))
        assert sum(ds) / len(ds) > 0.70, (tid, sum(ds) / len(ds))


# ---- rollout -----------------------------------------------------------------

def test_elite_stays_legacy_until_a_run_opts_in(monkeypatch):
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    assert policy_for_new_plan("elite").is_legacy


def test_naming_e1_for_elite_resolves_to_it(monkeypatch):
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": CAT_PYQ_E1})
    assert policy_for_new_plan("elite").version == CAT_PYQ_E1


def test_naming_a_question_policy_for_elite_still_falls_back(monkeypatch):
    """f6 is neither legacy-based nor elite-based; elite must not silently take
    it, and must not silently take half of it either."""
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": CAT_PYQ_F6})
    assert policy_for_new_plan("elite").is_legacy


def test_cli_accepts_e1_for_elite_and_still_refuses_f6(monkeypatch):
    from rc_engine import cli
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    monkeypatch.setenv("RC_ENGINE_ELITE_PLAN_POLICY", "")
    assert cli._apply_elite_policy(CAT_PYQ_E1) == 0
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["elite"] == CAT_PYQ_E1
    assert cli._apply_elite_policy(CAT_PYQ_F6) == 2
    assert cli._apply_elite_policy("legacy-sf2") == 0


def test_the_elite_opt_in_leaves_medium_and_hard_alone(monkeypatch):
    from rc_engine import cli
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": CAT_PYQ_F6, "hard": CAT_PYQ_F6, "elite": ""})
    monkeypatch.setenv("RC_ENGINE_ELITE_PLAN_POLICY", "")
    assert cli._apply_elite_policy(CAT_PYQ_E1) == 0
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["medium"] == CAT_PYQ_F6
    assert config.GENERATION_POLICY_FOR_NEW_PLANS["hard"] == CAT_PYQ_F6
