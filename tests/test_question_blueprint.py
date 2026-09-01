"""The question blueprint: type vocabulary, positional balance, tier difficulty.

The client's report was that "all the RCs have the same 6 questions" and that the
assumption question should go. Both were properties of `components/topologies.json`,
not of any code path: across the 28 shipped sets in rc_pipeline.db, Q1 was `thesis`
19 times, Q3 was structural_function/contextual_inference 23 times and Q6 was
`stance` 18 times, because 14 of 20 topologies opened on thesis and 13 of 20 closed
on stance.

Nothing in the engine could have caught that — the library was data, and data with
no invariants. These tests are the invariants. They fail if a future edit lets one
slot type recapture a position, drops a type out of circulation, reintroduces the
assumption question, or narrows a tier's pool to the point where it starves.

Run: python -m pytest tests/test_question_blueprint.py -q
"""

import collections
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config
from rc_engine.composer import BlueprintComposer
from rc_engine.fingerprints import topology_similarity
from rc_engine.models import Blueprint
from rc_engine.pipeline import RCPipeline
from rc_engine.question_engine import QuestionEngine, QuestionEngineError
from rc_engine.registry import MIN_STEM_FORMS, ComponentRegistry

TIERS = ("medium", "hard", "elite")

# The form CAT does not ask. It was in 13 of the 20 original topologies and held
# slot 5 in 6 of them, which is the "assumption question 5" the client saw.
BANNED_TYPE = "implicit_assumption"
# Added because the real papers are full of them and the library had none.
REQUIRED_NEW_TYPES = ("except_scan", "undermine_thesis", "primary_purpose")
# Every set needs one question about the passage as a whole.
WHOLE_PASSAGE = {"thesis", "primary_purpose", "undermine_thesis"}

# Q1 is pinned to thesis on every topology (client requirement 2026-08-10), so
# the positional cap cannot apply there — the pin IS the invariant, and
# test_q1_is_always_thesis asserts it directly.
PINNED_POSITIONS = {0: "thesis"}

POSITION_CAP = 6          # of 24 topologies, per position (positions 2..8)
# One slot per set by design, so they legitimately fill 24 of 192: thesis is
# pinned at Q1, detail_check is the single "detail" slot the CAT weighting asks
# for. Everything else is capped.
ONE_PER_SET_TYPES = {"thesis", "detail_check"}
TYPE_CAP = 16             # of 192 slots (was 12 of 144 — same 8.3% share)
MIN_TOPOLOGIES_PER_TYPE = 3
# A tier whose pool approaches EXCLUSION_WINDOWS["topology"] can be emptied by
# the window alone, which dead-ends sample_skeleton. Keep real headroom.
POOL_HEADROOM = 6


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture(scope="module")
def topologies(registry):
    return [registry.get("topology", tid) for tid in registry.ids("topology")]


@pytest.fixture(scope="module")
def composer(registry):
    """Only _topology_allowed is exercised, so the LLM, history and rules
    collaborators are deliberately not constructed."""
    c = BlueprintComposer.__new__(BlueprintComposer)
    c.registry = registry
    return c


def _eligible(composer, tier):
    return [t for t in composer.registry.ids("topology")
            if composer._topology_allowed(t, tier)]


# ------------------------------------------------------------ type vocabulary


def test_assumption_question_is_gone(registry, topologies):
    assert BANNED_TYPE not in registry.slot_type_definitions
    offenders = [t["id"] for t in topologies
                 if any(s["type"] == BANNED_TYPE for s in t["slots"])]
    assert not offenders, f"{BANNED_TYPE} still planned by {offenders}"


@pytest.mark.parametrize("stype", REQUIRED_NEW_TYPES)
def test_cat_types_are_defined_and_used(registry, topologies, stype):
    assert stype in registry.slot_type_definitions
    used = sum(1 for t in topologies if any(s["type"] == stype for s in t["slots"]))
    assert used >= MIN_TOPOLOGIES_PER_TYPE, f"{stype} used by only {used} topologies"


def test_every_declared_type_is_actually_reachable(registry, topologies):
    """A type defined but never planned is dead vocabulary — it can never appear
    in a set, so it silently narrows the real repertoire."""
    planned = {s["type"] for t in topologies for s in t["slots"]}
    assert planned == set(registry.slot_type_definitions)


def test_every_type_has_several_stem_forms(registry):
    """One stem form means every set drawing that type words it identically —
    the surface half of the sameness complaint."""
    for stype in registry.slot_type_definitions:
        forms = registry.stem_forms.get(stype, [])
        assert len(forms) >= MIN_STEM_FORMS, f"{stype}: {len(forms)} stem forms"
        assert len(set(forms)) == len(forms), f"{stype} has duplicate stem forms"


# --------------------------------------------------------- positional balance


def test_q1_is_always_thesis(topologies):
    """Client requirement: every set opens on the main-idea question. This is the
    one position a type is SUPPOSED to own, which is why it is exempt from
    POSITION_CAP below rather than silently raising the cap for everyone."""
    for t in topologies:
        assert t["slots"][0]["type"] == "thesis", f"{t['id']} Q1 is not thesis"


def test_q1_thesis_does_not_open_at_peak_difficulty(topologies):
    """Pinning an integrative question first must not make every set open hard.
    The band matches where Q1 sat before the pin (mean 0.58, thesis 0.55-0.75)."""
    for t in topologies:
        d = t["slots"][0]["difficulty"]
        assert 0.50 <= d <= 0.75, f"{t['id']} Q1 difficulty {d} outside 0.50-0.75"


def test_no_type_owns_a_position(topologies):
    """The direct regression test for "all the RCs have the same questions".
    Q1 is excluded: it is pinned by design and covered by test_q1_is_always_thesis."""
    for i in range(config.QUESTIONS_PER_SET):
        if i in PINNED_POSITIONS:
            continue
        counts = collections.Counter(t["slots"][i]["type"] for t in topologies)
        worst, n = counts.most_common(1)[0]
        assert n <= POSITION_CAP, (
            f"Q{i + 1}: {worst} holds {n} of {len(topologies)} topologies "
            f"(cap {POSITION_CAP}) — {counts.most_common(3)}")


def test_no_type_dominates_the_library(topologies):
    counts = collections.Counter(s["type"] for t in topologies for s in t["slots"])
    for stype, n in counts.items():
        if stype in ONE_PER_SET_TYPES:
            assert n == len(topologies), (
                f"{stype} is one-per-set by design but fills {n} of "
                f"{len(topologies)} sets")
            continue
        assert n <= TYPE_CAP, f"{stype} fills {n} slots (cap {TYPE_CAP})"
    for stype, n in counts.items():
        ntop = sum(1 for t in topologies if any(s["type"] == stype for s in t["slots"]))
        assert ntop >= MIN_TOPOLOGIES_PER_TYPE, (
            f"{stype} appears in only {ntop} topologies — effectively unreachable")


def test_every_topology_asks_about_the_whole_passage(topologies):
    for t in topologies:
        assert WHOLE_PASSAGE & {s["type"] for s in t["slots"]}, (
            f"{t['id']} has no whole-passage question")


def test_no_two_topologies_can_collide_at_the_novelty_gate(topologies):
    """Gate C rejects a set whose topology signature is too close to a recent
    one. If two library entries exceed the cap against each other, that rejection
    fires on distinct plans and burns a paid render — which is exactly why the
    cap could not previously be tightened."""
    cap = config.NOVELTY_CAPS["topology_similarity"]
    worst, pair = 0.0, None
    for i, a in enumerate(topologies):
        for b in topologies[i + 1:]:
            sim = topology_similarity(a["slots"], b["slots"])
            if sim > worst:
                worst, pair = sim, (a["id"], b["id"])
    assert worst < cap, f"{pair} similar at {worst:.3f} vs cap {cap}"


# ------------------------------------------------------------- tier behaviour


@pytest.mark.parametrize("tier", TIERS)
def test_tier_pool_cannot_starve(composer, tier):
    """The failure the old hand-picked medium whitelist was already widened once
    to escape: a pool near the exclusion window empties, _eligible returns [] and
    sample_skeleton dead-ends."""
    pool = _eligible(composer, tier)
    floor = config.EXCLUSION_WINDOWS["topology"] + POOL_HEADROOM
    assert len(pool) >= floor, (
        f"{tier} may draw {len(pool)} topologies; needs >= {floor} "
        f"(exclusion window {config.EXCLUSION_WINDOWS['topology']})")


def test_medium_pool_is_wider_than_the_whitelist_it_replaced(composer):
    """Regression guard on the fix itself: medium used to see 11 of 20."""
    assert len(_eligible(composer, "medium")) > 11


def test_medium_bars_only_the_structurally_hard_plans(composer, registry):
    bar = config.TIER_TOPOLOGY_BAR["medium"]
    for tid in registry.ids("topology"):
        slots = registry.get("topology", tid)["slots"]
        allowed = composer._topology_allowed(tid, "medium")
        expected = not (set(bar["forbid_types"]) & {s["type"] for s in slots}
                        or sum(1 for s in slots if s["target"] == "span") > bar["max_span"])
        assert allowed is expected, tid


@pytest.mark.parametrize("tier", TIERS)
def test_pipeline_repick_respects_the_same_bar_as_the_composer(registry, composer, tier):
    """The free pre-render topology clearance re-picks a plan AFTER the composer
    chose one. When the two disagree, the re-pick silently hands a tier a plan
    the composer refused it — which is what happened when the tier gate moved out
    of TIER_PARAMS and pipeline kept reading the old key."""
    pipeline = RCPipeline.__new__(RCPipeline)
    pipeline.registry = registry
    pipeline.composer = composer
    expected = [t for t in registry.ids("topology")
                if composer._topology_allowed(t, tier)]
    assert pipeline._tier_topologies(tier) == expected


def test_medium_pool_is_not_itself_locked(composer, registry):
    """Medium can satisfy the library-wide positional caps and still be locked,
    because it sees a subset. Check the caps inside the subset it actually draws."""
    pool = [registry.get("topology", t) for t in _eligible(composer, "medium")]
    for i in range(config.QUESTIONS_PER_SET):
        if i in PINNED_POSITIONS:
            continue
        counts = collections.Counter(t["slots"][i]["type"] for t in pool)
        worst, n = counts.most_common(1)[0]
        assert n <= POSITION_CAP, (
            f"medium Q{i + 1}: {worst} holds {n} of {len(pool)} — {counts.most_common(3)}")


# ------------------------------------------------- tier difficulty transform


def _scaled(topo, tier):
    return QuestionEngine._scale_slots(topo["slots"], tier)


@pytest.mark.parametrize("tier", TIERS)
def test_scaling_preserves_the_plan(topologies, tier):
    for topo in topologies:
        before = copy.deepcopy(topo["slots"])
        out = _scaled(topo, tier)
        assert [s["type"] for s in out] == [s["type"] for s in before]
        assert len(out) == config.QUESTIONS_PER_SET
        assert all(0.0 < s["difficulty"] <= 1.0 for s in out)
        # the registry hands out the live library dict; scaling must not edit it
        assert topo["slots"] == before, f"{topo['id']}: _scale_slots mutated the library"


def test_medium_is_easier_than_elite_on_every_plan(topologies):
    """The whole point of moving difficulty off the pool and onto the plan: the
    same topology must ask easier questions at medium than at elite."""
    for topo in topologies:
        means = {t: sum(s["difficulty"] for s in _scaled(topo, t))
                 / config.QUESTIONS_PER_SET for t in TIERS}
        assert means["medium"] < means["hard"] <= means["elite"], (
            f"{topo['id']}: {means}")


def test_medium_caps_difficulty_and_cross_paragraph_load(topologies):
    cap = config.TIER_SLOT_SCALING["medium"]["cap"]
    for topo in topologies:
        out = _scaled(topo, "medium")
        assert max(s["difficulty"] for s in out) <= cap, topo["id"]
        spans = sum(1 for s in out if s["target"] == "span")
        raw_spans = sum(1 for s in topo["slots"] if s["target"] == "span")
        assert spans <= max(0, raw_spans - 1), (
            f"{topo['id']}: medium kept {spans} span slots from {raw_spans}")


def test_unknown_tier_passes_through_unchanged(topologies):
    topo = topologies[0]
    assert QuestionEngine._scale_slots(topo["slots"], "nonexistent") == topo["slots"]


# ------------------------------------------------------------- stem rotation


def _blueprint(registry, topology_id, blueprint_id):
    return Blueprint(
        blueprint_id=blueprint_id, tier="hard",
        schema_version=config.BLUEPRINT_SCHEMA_VERSION,
        family_id=next(iter(registry.ids("family"))),
        persona_id=next(iter(registry.ids("persona"))),
        ending_id=next(iter(registry.ids("ending"))),
        rhythm_id=next(iter(registry.ids("rhythm"))),
        revelation_id=next(iter(registry.ids("revelation"))),
        distractor_profile_id=next(iter(registry.ids("distractor_profile"))),
        topology_id=topology_id, instability=0.5, aperture="x")


@pytest.fixture(scope="module")
def engine(registry):
    return QuestionEngine(registry, llm=None)


def test_a_repeated_type_never_repeats_its_stem(registry, engine, topologies):
    """Two shipped sets opened with a verbatim identical thesis stem. A topology
    planning one type twice must still ask it two different ways."""
    for topo in topologies:
        for n in range(25):
            bp = _blueprint(registry, topo["id"], f"BP_{topo['id']}_{n:04d}")
            shapes = engine._stem_shapes(topo["slots"], bp)
            assert len(shapes) == config.QUESTIONS_PER_SET
            by_type = collections.defaultdict(list)
            for slot, shape in zip(topo["slots"], shapes):
                by_type[slot["type"]].append(shape)
            for stype, forms in by_type.items():
                assert len(set(forms)) == len(forms), (
                    f"{topo['id']} blueprint {n}: {stype} reused a stem shape")


def test_stem_shapes_are_deterministic(registry, engine, topologies):
    """Resuming a run must not re-roll the stems it already committed to."""
    topo = topologies[0]
    bp = _blueprint(registry, topo["id"], "BP_fixed_0001")
    assert engine._stem_shapes(topo["slots"], bp) == engine._stem_shapes(topo["slots"], bp)


def test_stem_shapes_vary_across_blueprints(registry, engine, topologies):
    """...but two different sets on the same plan must not read identically."""
    topo = topologies[0]
    seen = {tuple(engine._stem_shapes(topo["slots"], _blueprint(
        registry, topo["id"], f"BP_vary_{n:04d}"))) for n in range(20)}
    assert len(seen) > 1, f"{topo['id']} produces one fixed stem set"


# ------------------------------------------------------- the EXCEPT contract


def _payload(mechanisms_per_q):
    return {"questions": [
        {"q": i + 1, "slot_type": "x", "stem": f"stem {i + 1}",
         "correct": {"text": "correct", "why_right": "because"},
         "wrong": [{"text": f"w{j}", "mechanism": m, "why_wrong": "no"}
                   for j, m in enumerate(mechs)]}
        for i, mechs in enumerate(mechanisms_per_q)]}


def test_except_slot_requires_passage_supported_options(engine):
    """The EXCEPT question's wrong options are the TRUE statements. A model that
    hands back ordinary distractor mechanisms has written a normal question with
    an EXCEPT stem, which is a broken question — catch it before it ships."""
    n_tail = config.QUESTIONS_PER_SET - 4
    slots = ([{"type": "thesis"}] * 3 + [{"type": "except_scan"}]
             + [{"type": "stance"}] * n_tail)
    good = _payload([["scope_inflation"] * 3] * 3
                    + [["passage_supported"] * 3]
                    + [["half_truth"] * 3] * n_tail)
    assert len(engine._validate(good, False, slots)) == config.QUESTIONS_PER_SET

    bad = _payload([["scope_inflation"] * 3] * 3
                   + [["passage_supported", "scope_inflation", "passage_supported"]]
                   + [["half_truth"] * 3] * n_tail)
    with pytest.raises(QuestionEngineError, match="except_scan"):
        engine._validate(bad, False, slots)


def test_non_except_slots_are_not_forced_into_the_marker(engine):
    n = config.QUESTIONS_PER_SET
    slots = [{"type": "thesis"}] * n
    data = _payload([["scope_inflation"] * 3] * n)
    assert len(engine._validate(data, False, slots)) == n


def test_passage_supported_stays_out_of_the_trap_histogram(registry, engine, topologies):
    """trap_histogram feeds the distractor_jsd novelty channel; three phantom
    traps per except-bearing set would skew it."""
    topo = next(t for t in topologies
                if any(s["type"] == "except_scan" for s in t["slots"]))
    bp = _blueprint(registry, topo["id"], "BP_hist_0001")
    bp.letter_plan = [("ABCD"[i % 4]) for i in range(config.QUESTIONS_PER_SET)]
    mechs = [["passage_supported"] * 3 if s["type"] == "except_scan"
             else ["scope_inflation"] * 3 for s in topo["slots"]]
    out = engine._letter_assign(_payload(mechs)["questions"], bp)
    assert "passage_supported" not in out["trap_usage"]
    assert out["trap_usage"]["scope_inflation"] > 0
