"""Pins the rhetorical-move channel and the house-voice findings behind it.

Origin (2026-08-21): two shipped elite passages — RC-ELITE-260712-0028 (an
oboist retuning mid-concert) and RC_E_0706_1 (a grandmaster explaining a knight
sacrifice) — read as near-identical to a human while scoring maximally novel on
every channel the engine had. Different personas, zero movement-token overlap,
near-inverted commitment curves, 5 vs 4 paragraphs.

The signatures below are the real extractions for those two passages, kept as
fixtures so the metric can never silently regress to one that cannot see them.
"""

import sys

from rc_engine import config
from rc_engine.fingerprints import move_signature_similarity, movement_similarity

# real `move-audit` output for the pair that motivated the channel
OBOIST = ["SCENE_PARTICULAR", "TWO_CAMP_SPLIT", "INSTANCE_SURVEY", "STAKES_RAISED",
          "EASY_READING_DEMOLISHED", "LEVEL_RELOCATION", "BOTHSIDES_REFUSED",
          "MECHANISM_EXPLAINED", "CONCESSION_COSTED", "CONCRETE_RETURN"]
GRANDMASTER = ["SCENE_PARTICULAR", "EASY_READING_DEMOLISHED", "AUTHORITY_QUOTED",
               "DISCLAIM_RESTATE", "INSTANCE_SURVEY", "STACCATO_TRIAD",
               "LEVEL_RELOCATION", "CONCESSION_GRANTED", "SYMMETRY_BROKEN",
               "BOTHSIDES_REFUSED", "QUESTION_LEFT_OPEN"]
# a genuinely differently-shaped passage (RC-HARD-260819-0050, Shannon's "signal")
UNRELATED = ["HISTORICAL_ORIGIN", "DEFINITION_STAKED", "GENEALOGY_TRACED",
             "CONCESSION_GRANTED", "INSTANCE_SURVEY", "EASY_READING_DEMOLISHED",
             "DISCLAIM_RESTATE", "MECHANISM_EXPLAINED", "CONCESSION_COSTED",
             "BOUND_CONTINUATION"]


def test_vocabulary_is_closed_and_documented():
    assert len(config.RHETORICAL_MOVES) >= 20
    for label, gloss in config.RHETORICAL_MOVES.items():
        assert label == label.upper()
        assert gloss and gloss[0].islower(), f"{label} gloss should read as a phrase"


def test_every_fixture_label_is_in_the_vocabulary():
    for sig in (OBOIST, GRANDMASTER, UNRELATED):
        for move in sig:
            assert move in config.RHETORICAL_MOVES


def test_shares_more_with_its_twin_than_with_an_unrelated_passage():
    """The ordering that matters. The absolute number is NOT asserted: the pair
    sits at the corpus median (~0.31), which is the finding — half the corpus is
    that similar — not a bug in the metric."""
    twin = move_signature_similarity(OBOIST, GRANDMASTER)
    other = move_signature_similarity(OBOIST, UNRELATED)
    assert twin > other


def test_movement_similarity_is_the_wrong_tool_here():
    """Why the channel does not reuse movement_similarity. Exact-order
    Levenshtein plus adjacent-bigram Jaccard scores this pair at essentially
    zero despite six shared moves, because the two passages interleave the same
    grammar differently. If this ever starts passing, the guard below is stale."""
    lev, jac = movement_similarity("|".join(OBOIST), "|".join(GRANDMASTER))
    assert lev < 0.35 and jac < 0.15
    assert move_signature_similarity(OBOIST, GRANDMASTER) > max(lev, jac)


def test_identical_signature_scores_one():
    assert move_signature_similarity(OBOIST, list(OBOIST)) == 1.0


def test_disjoint_signatures_score_zero():
    a = ["SCENE_PARTICULAR", "TWO_CAMP_SPLIT"]
    b = ["MECHANISM_EXPLAINED", "BOUND_CONTINUATION"]
    assert move_signature_similarity(a, b) == 0.0


def test_empty_signature_is_unknown_not_similar():
    """An unextracted signature must never read as 'structurally identical' —
    same convention as UNKNOWN_MOVEMENT."""
    assert move_signature_similarity([], []) == 0.0
    assert move_signature_similarity(OBOIST, []) == 0.0


def test_rarity_weighting_discounts_a_move_the_whole_corpus_performs():
    """LEVEL_RELOCATION was in 96% of the shipped corpus. Two passages sharing
    only that should score below two sharing only a rare move."""
    n = 100
    freq = {"LEVEL_RELOCATION": 96, "ANALOGY_EXTENDED": 5,
            "SCENE_PARTICULAR": 47, "MECHANISM_EXPLAINED": 73}
    common = move_signature_similarity(
        ["LEVEL_RELOCATION", "SCENE_PARTICULAR"],
        ["LEVEL_RELOCATION", "MECHANISM_EXPLAINED"], freq, n)
    rare = move_signature_similarity(
        ["ANALOGY_EXTENDED", "SCENE_PARTICULAR"],
        ["ANALOGY_EXTENDED", "MECHANISM_EXPLAINED"], freq, n)
    assert rare > common


def test_cap_sits_above_the_measured_p99():
    """Calibrated from move-audit over 85 sets / 3570 pairs: p99 = 0.61.
    A cap at or below the median would reject every render — see the comment on
    MOVE_SIGNATURE_CAPS."""
    cap = config.MOVE_SIGNATURE_CAPS["move_signature_sim"]
    assert 0.61 <= cap < 0.75


def test_saturation_thresholds_are_ordered():
    assert config.MOVE_SATURATION_WARN < config.MOVE_SATURATION_BAN < 1.0
    assert config.MOVE_SATURATION_MAX_BANS >= 1


# ---------------------------------------------------------------------------
# Beat plan (2026-08-22). The ban-list build shipped 2026-08-21 and failed:
# RC-ELITE-260821-0050 performed all three banned moves and closed on a
# forbidden aphorism, after a forced retry. Prohibitions were being ignored
# while the positive paragraph plan in the same prompt was obeyed, so the
# grammar moved to the plan side.
# ---------------------------------------------------------------------------

def _composer():
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.registry import ComponentRegistry
    from rc_engine.llm import MockLLMClient

    class _FakeHistory:
        """Corpus stuck in the state that started this: LEVEL_RELOCATION in
        nearly every set, ANALOGY_EXTENDED in almost none."""
        def fingerprint_window(self, n, include_quarantined=False):
            class _FP:
                def __init__(self, sig): self.move_signature = sig
            hot = "SCENE_PARTICULAR|LEVEL_RELOCATION|EASY_READING_DEMOLISHED|HEDGED_APHORISM"
            return [_FP(hot) for _ in range(29)] + [
                _FP("QUESTION_POSED|ANALOGY_EXTENDED|BOUND_CONTINUATION")]

    reg = ComponentRegistry()
    return BlueprintComposer(reg, _FakeHistory(), CompatibilityRules(reg),
                             MockLLMClient()), reg


def test_move_plan_has_a_coherent_arc():
    comp, _ = _composer()
    for _ in range(25):
        plan = comp._sample_move_plan(None)
        assert config.MOVE_PLAN_LEN[0] <= len(plan) <= config.MOVE_PLAN_LEN[1]
        assert plan[0] in config.MOVE_GROUPS["opening"]
        assert plan[-1] in config.MOVE_GROUPS["closing"]
        assert len(set(plan)) == len(plan), "a plan should not repeat a beat"


def test_move_plan_suppresses_what_the_corpus_is_saturated_with():
    comp, _ = _composer()
    plans = [comp._sample_move_plan(None) for _ in range(200)]
    hot = sum(1 for p in plans if "LEVEL_RELOCATION" in p) / len(plans)
    cold = sum(1 for p in plans if "ANALOGY_EXTENDED" in p) / len(plans)
    assert hot < 0.10, f"saturated move still planned {hot:.0%} of the time"
    assert cold > hot, "the under-used move should be favoured over the saturated one"


def test_stance_forbidden_beats_are_excluded_from_the_plan():
    """The stance's bans now shape SAMPLING rather than being handed to the
    renderer as prohibitions it ignores."""
    comp, reg = _composer()
    stance = reg.get("render_stance", "RS02")   # forbids LEVEL_RELOCATION
    assert "LEVEL_RELOCATION" in stance["forbidden_beats"]
    for _ in range(40):
        assert "LEVEL_RELOCATION" not in comp._sample_move_plan(stance)


def test_every_group_member_is_in_the_vocabulary():
    seen = set()
    for group in config.MOVE_GROUPS.values():
        for m in group:
            assert m in config.RHETORICAL_MOVES
            assert m not in seen, f"{m} appears in two groups"
            seen.add(m)
    assert seen == set(config.RHETORICAL_MOVES), "every move needs a group"


# ---------------------------------------------------------------------------
# No-thesis Q1 (2026-08-22). Q1 is the thesis slot in all 24 topologies and was
# hardcoded as such in QUESTION_SYSTEM. Four arc-shape families state no
# position by design, so a "central idea" question there has no answer the
# passage supports — only one the solver can argue with.
# ---------------------------------------------------------------------------

def test_thesis_withholding_families_get_a_different_q1():
    from rc_engine.registry import ComponentRegistry
    from rc_engine.question_engine import QuestionEngine
    from rc_engine.models import Blueprint

    reg = ComponentRegistry()
    qe = QuestionEngine(reg, None)
    topo = reg.get("topology", reg.ids("topology")[0])
    assert topo["slots"][0]["type"] == "thesis", "Q1 is expected to be pinned to thesis"

    def q1_for(fid):
        bp = Blueprint(blueprint_id="x", tier="hard",
                       schema_version=config.BLUEPRINT_SCHEMA_VERSION,
                       family_id=fid, persona_id="P01", ending_id="E01",
                       rhythm_id="T01", revelation_id="R01",
                       distractor_profile_id="D01", topology_id=topo["id"],
                       instability=0.5, aperture="x")
        return qe._retarget_thesis(topo["slots"], bp)[0]

    withholding = [f for f in reg.ids("family") if reg.withholds_thesis(f)]
    assert withholding, "at least one family should withhold a thesis"
    for fid in withholding:
        slot = q1_for(fid)
        assert slot["type"] == config.NO_THESIS_Q1_SLOT
        assert slot["target"] == "global", "Q1 must stay an integrating question"

    stating = [f for f in reg.ids("family") if not reg.withholds_thesis(f)][:5]
    for fid in stating:
        assert q1_for(fid)["type"] == "thesis"


def test_retarget_preserves_slot_count_and_difficulty():
    from rc_engine.registry import ComponentRegistry
    from rc_engine.question_engine import QuestionEngine
    from rc_engine.models import Blueprint

    reg = ComponentRegistry()
    qe = QuestionEngine(reg, None)
    topo = reg.get("topology", reg.ids("topology")[0])
    fid = next(f for f in reg.ids("family") if reg.withholds_thesis(f))
    bp = Blueprint(blueprint_id="x", tier="hard",
                   schema_version=config.BLUEPRINT_SCHEMA_VERSION,
                   family_id=fid, persona_id="P01", ending_id="E01",
                   rhythm_id="T01", revelation_id="R01",
                   distractor_profile_id="D01", topology_id=topo["id"],
                   instability=0.5, aperture="x")
    out = qe._retarget_thesis(topo["slots"], bp)
    assert len(out) == len(topo["slots"])
    assert out[0]["difficulty"] == topo["slots"][0]["difficulty"]
    assert topo["slots"][0]["type"] == "thesis", "must not mutate the library"


def test_every_family_declares_whether_it_states_a_thesis():
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    for fid in reg.ids("family"):
        fam = reg.get("family", fid)
        assert isinstance(fam.get("withholds_thesis"), bool), fid


# ---------------------------------------------------------------------------
# Aphorism classifier (2026-08-22). The original test was "terse, quotable,
# standalone", which called every short forceful ending an aphorism. Measured
# against the corpus, at least 60% of the stored flags were wrong — including
# all three finals of the 2026-08-22 batch, each of which had in fact obeyed
# its assigned register. Every aphorism-rate figure quoted before that date is
# inflated by an unknown amount.
# ---------------------------------------------------------------------------

def _passage_ending(last_line):
    nl = chr(10)
    return ("A first paragraph that introduces Form PA 1663 and a building." + nl + nl +
            "A second paragraph that develops the argument at some length." + nl + nl +
            "A third paragraph continuing the case. " + last_line)


def test_bound_endings_are_not_aphorisms():
    from rc_engine.compliance import ComplianceAuditor
    bound = [
        "Start with the countersignature line on Form PA 1663, still blank, still required.",
        "It is what else, in that building, was being held together by gestures nobody named.",
        "It was the reverse.",
    ]
    for line in bound:
        assert ComplianceAuditor._final_line_is_bound(_passage_ending(line)), line


def test_genuine_aphorisms_are_not_flagged_as_bound():
    from rc_engine.compliance import ComplianceAuditor
    real = [
        "A recipe is not yet a meal.",
        "Every measure eventually becomes a target.",
        "The work was always the performance.",
        "Such confidence is rarely earned twice.",
        # cataphoric "it" resolved inside the sentence by the that-clause
        "It is a truth universally acknowledged that institutions outlive their reasons.",
    ]
    for line in real:
        got = ComplianceAuditor._final_line_is_bound(_passage_ending(line))
        assert got is None, "%r wrongly bound by %r" % (line, got)


def test_level_relocation_has_a_milder_neighbour():
    """LEVEL_RELOCATION read 97% of the corpus because it absorbed every
    'X is the symptom, Y is the cause' move. Narrowing it to 'the dispute as
    posed is misconceived' needs somewhere for the mild case to go, or the
    extractor just picks the next-broadest label."""
    assert "UNDERLYING_CAUSE_NAMED" in config.RHETORICAL_MOVES
    strong = config.RHETORICAL_MOVES["LEVEL_RELOCATION"]
    assert "not merely" in strong.lower() or "misconceived" in strong.lower(), (
        "the narrowed gloss must say what it excludes, not just what it includes")
    assert "UNDERLYING_CAUSE_NAMED" in config.MOVE_GROUPS["middle"]


# ---------------------------------------------------------------------------
# Similarity screen (2026-08-22). The last gate, and the only one that reads
# the passages instead of a proxy for them.
# ---------------------------------------------------------------------------

def test_screen_is_pinned_to_its_own_provider():
    """Pinning matters: asking the model that wrote the passage whether the
    passage is repetitive asks the judgement that produced the sameness to
    notice the sameness."""
    cfg = config.SIMILARITY_SCREEN
    assert cfg["provider"] in config.PROVIDERS
    assert cfg["model"] in config.MODEL_RATES, "screen model needs a rate entry"
    assert cfg["compare_n"] >= 5
    assert cfg["max_tokens"] >= 500, "reasoning models spend the ceiling first"


def test_screen_degrades_to_unchecked_without_a_key(monkeypatch):
    """A screen that cannot run must never cost a set that passed every other
    gate — and must never pass one silently either."""
    from rc_engine import similarity_screen as ss
    monkeypatch.setattr(ss, "_screen_client",
                        lambda: (_ for _ in ()).throw(ss.ScreenUnavailable("no key")))
    out = ss.screen_passage("RC-X", "a passage", [("RC-Y", "another passage")])
    assert out["verdict"] == "unchecked"
    assert "no key" in out["reason"]


def test_screen_with_no_prior_corpus_is_unchecked_not_green():
    from rc_engine import similarity_screen as ss
    out = ss.screen_passage("RC-X", "a passage", [])
    assert out["verdict"] == "unchecked", "an empty window is not evidence of novelty"


def test_only_green_and_red_are_accepted_verdicts(monkeypatch):
    from rc_engine import similarity_screen as ss

    class _Client:
        def __init__(self, payload): self.payload = payload
        def call(self, *a, **k): return self.payload, False

    monkeypatch.setattr(ss, "_screen_client",
                        lambda: _Client('{"verdict": "amber", "nearest": null}'))
    out = ss.screen_passage("RC-X", "p", [("RC-Y", "q")])
    assert out["verdict"] == "unchecked", "an unrecognised verdict must not read as green"

    monkeypatch.setattr(ss, "_screen_client",
                        lambda: _Client('{"verdict": "red", "nearest": "RC-Y", '
                                        '"shared": ["two-camp split"], "reason": "same shape"}'))
    out = ss.screen_passage("RC-X", "p", [("RC-Y", "q")])
    assert out["verdict"] == "red" and out["nearest"] == "RC-Y"


# ---------------------------------------------------------------------------
# Per-stage pinning, the free pre-render check, and the QA second opinions
# (2026-08-22). 150 of 205 blueprints ever composed died at a novelty gate,
# each after paying for refine + render.
# ---------------------------------------------------------------------------

class _RecordingClient:
    def __init__(self):
        self.seen = []

    def call(self, ledger, stage, model, max_tokens, system, user, context=None):
        self.seen.append((stage, model))
        return "{}", False


def test_pin_falls_back_when_provider_unavailable(monkeypatch):
    """The invariant that matters most: a pin is an optimisation and must never
    be able to stop a batch that would otherwise run."""
    from rc_engine import providers
    from rc_engine.llm import CostLedger

    monkeypatch.setattr(providers, "provider_key_present", lambda p: None)
    base = _RecordingClient()
    r = providers.RoutedClient(base, {"judge": ("openai", "gpt-5.6-luna")})
    r.call(CostLedger(budget_usd=1.0), "judge", "claude-haiku-4-5", 100, "s", "u")
    assert base.seen == [("judge", "claude-haiku-4-5")]


def test_pin_is_used_when_provider_is_available(monkeypatch):
    from rc_engine import providers
    from rc_engine.llm import CostLedger

    pinned = _RecordingClient()
    base = _RecordingClient()
    monkeypatch.setattr(providers, "provider_key_present", lambda p: "OPENAI_API_KEY")
    monkeypatch.setattr(providers, "make_client", lambda p: pinned)
    r = providers.RoutedClient(base, {"judge": ("openai", "gpt-5.6-luna")})
    r.call(CostLedger(budget_usd=1.0), "judge", "claude-haiku-4-5", 100, "s", "u")
    r.call(CostLedger(budget_usd=1.0), "render", "claude-opus-5", 100, "s", "u")
    assert pinned.seen == [("judge", "gpt-5.6-luna")], "pinned stage must reroute"
    assert base.seen == [("render", "claude-opus-5")], "unpinned stage must not"


def test_only_cheap_checking_stages_are_pinned():
    """render and questions are where the passage actually comes from; pinning
    them would trade output quality for a few cents and must never happen.

    refine was DELIBERATELY added to the pins on 2026-08-22 (operator decision
    to remove Haiku entirely): the medium tier assigns refine the "small" role,
    which on Anthropic is Haiku. It is the one generative stage pinned here, and
    the exception is recorded rather than silently allowed."""
    for stage in ("render", "questions"):
        assert stage not in config.STAGE_MODEL_PINS, stage
    generative_pins = {s for s in ("refine", "render", "questions")
                       if s in config.STAGE_MODEL_PINS}
    assert generative_pins <= {"refine"}, generative_pins
    # A pin is either (provider, model) or {tier: (provider, model)}.
    for stage, pin in config.STAGE_MODEL_PINS.items():
        entries = list(pin.values()) if isinstance(pin, dict) else [pin]
        for provider, model in entries:
            assert provider in config.PROVIDERS, (stage, provider)
            assert model in config.MODEL_RATES, f"{model} needs a MODEL_RATES entry"


def test_move_plan_precheck_cap_is_below_the_gate():
    """The realized signature is longer and richer than the plan, so a plan at
    the gate's cap will almost certainly breach it once rendered."""
    assert (config.MOVE_PLAN_PRECHECK_CAP
            < config.MOVE_SIGNATURE_CAPS["move_signature_sim"])


def test_precheck_rejects_a_plan_that_clones_the_corpus():
    from rc_engine.composer import BlueprintComposer

    sig = "SCENE_PARTICULAR|TWO_CAMP_SPLIT|LEVEL_RELOCATION|HEDGED_APHORISM"

    class _FP:
        def __init__(self, rc_id, s):
            self.rc_id, self.move_signature = rc_id, s

    class _H:
        def fingerprint_window(self, n, include_quarantined=False):
            return [_FP("RC-%d" % i, sig) for i in range(12)]

    c = BlueprintComposer.__new__(BlueprintComposer)
    c.history = _H()
    assert c._plan_collides(sig.split("|")) is not None, "an exact clone must collide"
    fresh = ["HISTORICAL_ORIGIN", "GENEALOGY_TRACED", "ANALOGY_EXTENDED",
             "SELF_CORRECTION", "CONCRETE_RETURN"]
    assert c._plan_collides(fresh) is None, "an unrelated plan must pass"


def test_qa_checks_degrade_without_blocking():
    """Both QA stages report; neither may withhold a set or change a key."""
    from rc_engine.llm import CostLedger
    from rc_engine import qa_checks

    class _Boom:
        def call(self, *a, **k):
            raise RuntimeError("no client")

    led = CostLedger(budget_usd=1.0)
    assert qa_checks.check_answerability("p", [{"stem": "q"}], _Boom(), led) == []
    out = qa_checks.tiebreak("p", {"stem": "q"}, "A", "B", _Boom(), led)
    assert out["supported"] == "unchecked"


def test_answerability_warnings_name_the_problem():
    from rc_engine import qa_checks
    rows = [
        {"q": 1, "answerable": True, "unique": True, "contenders": [], "note": ""},
        {"q": 2, "answerable": False, "unique": True, "contenders": [], "note": "needs outside fact"},
        {"q": 3, "answerable": True, "unique": False, "contenders": ["B", "D"], "note": ""},
    ]
    w = qa_checks.answerability_warnings(rows)
    assert len(w) == 2
    assert "Q2" in w[0] and "not answerable" in w[0]
    assert "Q3" in w[1] and "B, D" in w[1]


# ---------------------------------------------------------------------------
# Architecture invisibility + fabricated scholarship (2026-08-22).
# Both are ways generated prose fakes the surface of serious writing: the first
# announces scaffolding the reader should feel rather than see, the second
# borrows authority the passage has not earned. The second is worse for a test
# item — a candidate who knows the field is penalised for knowing the cited
# study does not exist.
# ---------------------------------------------------------------------------

def test_detector_catches_fabricated_scholarship():
    from rc_engine.question_engine import texture_report
    for text in [
        "A 2019 Michigan State study found that 62% of claimants missed it.",
        "Researchers at Stanford showed the effect persists.",
        "Historians at the Institute of Advanced Study disagree.",
        "A survey by Kaplan reached the opposite conclusion.",
    ]:
        assert texture_report(text)["fabrications"], text


def test_detector_catches_architecture_signposting():
    from rc_engine.question_engine import texture_report
    for text in [
        "But the deeper issue is not the deadline at all.",
        "Having established that much, we turn to the second objection.",
        "In this passage I will argue the opposite.",
        "The argument so far has assumed good faith.",
    ]:
        assert texture_report(text)["signposts"], text


def test_detector_leaves_legitimate_internal_texture_alone():
    """The distinction that matters: a described case the reader can reason
    about from the text is fine; borrowed real-world authority is not."""
    from rc_engine.question_engine import texture_report
    for text in [
        "A county assistance office with four caseworkers for a workload sized to nine.",
        "In 1948, working out of Bell Labs, Claude Shannon set down what a signal is.",
        "Her packet was date-stamped on receipt and processed after the cutoff.",
        "The oboist sounded the A again, softly, and tuned to it.",
    ]:
        assert texture_report(text)["warnings"] == [], text


def test_signpost_phrases_are_enforced_not_merely_requested():
    """These live in GLOBAL_FORBIDDEN_TICS because that list is audited by
    compliance (caps f1, produces a directive). Prompt-level rules have been
    ignored repeatedly; audited ones have not."""
    tics = [t.lower() for t in config.GLOBAL_FORBIDDEN_TICS]
    for phrase in ("the deeper issue", "this raises the question",
                   "what remains is", "the real point"):
        assert phrase in tics, phrase


def test_authority_quoted_no_longer_invites_fabrication():
    """The move vocabulary and the render rules must not contradict each other:
    a beat that says 'cite a named study' next to a rule that says 'invent no
    studies' puts the renderer in an impossible position."""
    gloss = config.RHETORICAL_MOVES["AUTHORITY_QUOTED"].lower()
    assert "not an invented" in gloss or "never" in gloss or "real and checkable" in gloss


def test_render_contract_carries_both_rules():
    from rc_engine.renderer import RENDER_SYSTEM
    assert "ARCHITECTURE INVISIBILITY" in RENDER_SYSTEM
    assert "NO FABRICATED SCHOLARSHIP" in RENDER_SYSTEM


# ---------------------------------------------------------------------------
# Tier gating of arc shapes (2026-08-22). Before this, hard and elite had
# IDENTICAL family pools (45 vs 46 families, 14 shapes each) — elite was not a
# harder read, only a harder question set. Measured passages bore that out:
# 504 / 516 / 530 words and ~20 word sentences across all three tiers.
# ---------------------------------------------------------------------------

def _reg():
    from rc_engine.registry import ComponentRegistry
    return ComponentRegistry()


def _eligible(reg, tier):
    order = {"medium": 0, "hard": 1, "elite": 2}
    return [f for f in reg.ids("family")
            if order[reg.get("family", f)["tier_floor"]] <= order[tier]]


def test_medium_never_gets_a_thesis_withholding_family():
    """Medium's own difficulty character promises 'the answers live in the
    passage, not behind it'. A family that states no position by design breaks
    that promise — the reader is asked to recover something absent."""
    reg = _reg()
    for fid in _eligible(reg, "medium"):
        assert not reg.withholds_thesis(fid), (
            f"{fid} withholds a thesis but is medium-eligible")


def test_each_tier_unlocks_shapes_the_one_below_cannot_reach():
    reg = _reg()
    shapes = {t: {reg.shape_of(f) for f in _eligible(reg, t)}
              for t in ("medium", "hard", "elite")}
    assert shapes["medium"] < shapes["hard"], "hard must add shapes over medium"
    assert shapes["hard"] < shapes["elite"], (
        "elite must add shapes over hard — before the 2026-08-22 gate these "
        "pools were identical and elite was not a harder read")


def test_medium_keeps_enough_shape_variety():
    """The countervailing constraint: gating must not turn medium into its own
    monoculture, which is the exact problem the arc-shape work was fixing."""
    reg = _reg()
    new = {reg.shape_of(f) for f in _eligible(reg, "medium")} - {"staged_turn_settled"}
    assert len(new) >= 5, f"medium has only {len(new)} non-legacy shapes: {sorted(new)}"


def test_tier_floors_are_monotone_with_reader_effort():
    """Spot-check the ordering the gate encodes, so a future edit that moves a
    family has to move it deliberately."""
    reg = _reg()
    floor = lambda f: reg.get("family", f)["tier_floor"]
    assert floor("F35") == "medium", "thesis stated in paragraph 1 is the easiest read"
    assert floor("F37") == "elite", "two accounts, never reconciled, no synthesis"
    assert floor("F42") == "elite", "six unarbitrated witnesses"
    assert floor("F41") == "elite", "circular return — the change is in the reader"


# ---------------------------------------------------------------------------
# OpenAI / GPT-5.6 alignment (2026-08-22), verified against the official model
# pages rather than pricing aggregators — those had Sol at $5/$30; it is $4/$20.
# ---------------------------------------------------------------------------

def test_gpt56_rates_match_the_official_model_pages():
    assert config.MODEL_RATES["gpt-5.6-sol"] == (4.0, 20.0)
    assert config.MODEL_RATES["gpt-5.6-terra"] == (2.0, 12.0)
    assert config.MODEL_RATES["gpt-5.6-luna"] == (0.20, 1.20)


def test_per_tier_model_routing_for_openai():
    """GPT-5.6 ships three tiers of MODEL, so the tier maps to the model rather
    than to an effort dial on one model. Claude must be unaffected."""
    try:
        config.set_provider("openai")
        for stage in ("render", "questions"):
            row = {t: config.STAGE_CONFIG[stage][t][0]
                   for t in ("medium", "hard", "elite")}
            # Tier maps to MODEL on the GPT-5.6 family; which model sits at
            # elite has changed with the experiments, so pin the invariant
            # (elite is never weaker than hard) rather than a specific id.
            rank = {"gpt-5.6-luna": 0, "gpt-5.6-terra": 1, "gpt-5.6-sol": 2}
            assert rank[row["elite"]] >= rank[row["hard"]] >= rank[row["medium"]], row
            assert row["medium"] == "gpt-5.6-terra", (stage, row)
        # Effort is an operator dial and has ranged none..xhigh across the
        # experiments. What must hold is that the cheap CHECKING stages never
        # run at "none": move_signature there was measured missing a move
        # plainly present in the passage, and those stages cost fractions of a
        # cent, so there is nothing to win by starving them.
        for stage in ("move_signature", "compliance", "judge", "answerability"):
            assert config.OPENAI_STAGE_EFFORT[stage] != "none", stage
        config.set_provider("claude")
        for stage in ("render", "questions"):
            models = {config.STAGE_CONFIG[stage][t][0]
                      for t in ("medium", "hard", "elite")}
            assert len(models) == 1, "claude must still use one big model per stage"
    finally:
        config.set_provider("claude")


def test_every_openai_tier_fits_its_budget():
    """The guard that matters before spending real money on a new provider."""
    from rc_engine.cli import STAGES, _stage_cost
    try:
        config.set_provider("openai")
        for tier in ("medium", "hard", "elite"):
            happy = sum(_stage_cost(st, tier, worst=False) for st in STAGES)
            assert happy <= config.TIER_BUDGET_USD[tier], (tier, happy)
    finally:
        config.set_provider("claude")


def test_effort_is_not_silently_downgraded_on_gpt56():
    """GPT-5.6 accepts xhigh and max. The old blanket clamp to 'high' capped
    exactly the stages that ask for the most reasoning."""
    assert config.OPENAI_DEFAULT_EFFORT in (
        "none", "low", "medium", "high", "xhigh", "max")
    src = open("rc_engine/providers.py", encoding="utf-8").read()
    assert 'not model.startswith("gpt-5.6")' in src, (
        "the xhigh/max clamp must no longer apply to gpt-5.6")


# ---------------------------------------------------------------------------
# Topic shapes + seed genre (2026-08-22) — the last layer the house voice was
# living in. Of ~60 stored topics, 14 opened "Whether..." and 11 "Why...",
# essentially all two-sided conceptual disputes about a social practice. Two
# causes, both upstream of the renderer: every RSS feed was the same genre, and
# the refine schema REQUIRED a bipolar tension_system.
# ---------------------------------------------------------------------------

def test_not_every_topic_shape_requires_two_poles():
    """The bug in one line: if every shape needs a tension_system, every topic
    is a dispute no matter what else varies."""
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    shapes = [reg.get("topic_shape", t) for t in reg.ids("topic_shape")]
    needs = [s for s in shapes if s["requires_tension"]]
    assert len(needs) < len(shapes) / 2, (
        "most topic shapes must NOT require a bipolar tension")
    for s in shapes:
        if not s["requires_tension"]:
            assert s.get("content_frame"), (
                f"{s['id']} has no tension and no content_frame — refine would "
                f"have nothing to fix the material with")


def test_seed_with_no_dispute_cannot_draw_a_dispute_shape():
    """A technical seed being converted into 'whether X or Y' is the exact
    failure this layer exists to stop."""
    from rc_engine.registry import ComponentRegistry
    from rc_engine.seed_classify import eligible_topic_shapes
    reg = ComponentRegistry()
    info = {"genre": "technical_explainer", "bipolar_dispute_available": False}
    for tid in eligible_topic_shapes(reg, info):
        assert not reg.get("topic_shape", tid)["requires_tension"], tid


def test_eligible_shapes_never_dead_end():
    """An unrecognised genre must fall back to the whole library rather than
    returning nothing and starving the composer."""
    from rc_engine.registry import ComponentRegistry
    from rc_engine.seed_classify import eligible_topic_shapes
    reg = ComponentRegistry()
    weird = {"genre": "sports_recap", "bipolar_dispute_available": True}
    assert eligible_topic_shapes(reg, weird)


def test_classifier_failure_degrades_to_todays_behaviour():
    from rc_engine.seed_classify import classify_seed
    from rc_engine.models import SeedEssay

    class _Boom:
        def call(self, *a, **k):
            raise RuntimeError("no client")

    seed = SeedEssay(doc_id="x", url="u", title="t", text="word " * 300)
    out = classify_seed(seed, _Boom())
    assert out["genre"] == "conceptual_essay"
    assert out["bipolar_dispute_available"] is True


def test_genre_saturation_needs_corpus_mass():
    """A share computed over three sets means nothing; the check must stay
    silent until there is enough history, or the very first sets of a fresh
    corpus would each look like a saturated genre."""
    from rc_engine import seed_classify

    class _Cur:
        def __init__(self, n):
            self.n = n

        def fetchall(self):
            return [("conceptual_essay",)] * self.n

    class _Conn:
        def __init__(self, n):
            self.n = n

        def execute(self, *a):
            return _Cur(self.n)

    class _H:
        def __init__(self, n):
            self.conn = _Conn(n)

    assert seed_classify.genre_is_saturated(_H(3), "conceptual_essay") is None
    hot = seed_classify.genre_is_saturated(_H(20), "conceptual_essay")
    assert hot is not None and hot > config.SEED_GENRE_SATURATION


def test_rag_feeds_span_more_than_one_kind():
    import RAG
    kinds = {v.get("kind", "idea_essay") for v in RAG.FEEDS.values()}
    assert len(kinds) >= 5, f"seed pool still narrow: {sorted(kinds)}"


def test_refine_accepts_a_shape_appropriate_payload():
    """Regression: the validator required tension_system unconditionally while
    the topic-shape layer made it optional, so every refine fell through to the
    deterministic fallback. That produces generic topics, and three elite
    attempts died on topic collisions in the 2026-08-22 batch."""
    import inspect
    from rc_engine.composer import BlueprintComposer

    src = inspect.getsource(BlueprintComposer._refine_with_retry)
    assert 'refined.get("content_frame")' in src, (
        "a shape with no tension must still be able to satisfy the validator")


def test_refine_schema_contains_no_json_comments():
    """`//` is not valid JSON. A commented example invites a commented reply,
    which extract_json then rejects."""
    from rc_engine.composer import REFINE_SYSTEM
    for line in REFINE_SYSTEM.splitlines():
        assert not line.strip().startswith("//"), line


def test_no_stage_runs_on_haiku():
    """Operator decision 2026-08-22: Haiku is replaced by gpt-5.6-luna
    everywhere. Luna is ~5x cheaper on input and ~4x on output, and the one
    accuracy check that mattered (move_signature at effort=none missing a move)
    was an EFFORT problem, not a model one."""
    try:
        for provider in ("claude", "openai"):
            config.set_provider(provider)
            for stage in config._STAGE_PLAN:
                if config.STAGE_MODEL_PINS.get(stage):
                    continue
                for tier in ("medium", "hard", "elite"):
                    model = config.STAGE_CONFIG[stage][tier][0]
                    assert "haiku" not in model, f"{provider}/{stage}/{tier} -> {model}"
    finally:
        config.set_provider("claude")


def test_every_cheap_checking_stage_is_pinned():
    for stage in ("compliance", "judge", "move_signature", "answerability",
                  "solver_tiebreak", "seed_classify"):
        assert stage in config.STAGE_MODEL_PINS, stage
    assert config.SIMILARITY_SCREEN["model"] in config.MODEL_RATES


def test_refine_is_pinned_only_where_it_would_otherwise_be_haiku():
    """Regression: a stage-level pin on refine silently demoted hard and elite
    content planning from Sonnet 5 to Luna. refine takes the 'small' role only
    at medium; hard and elite take 'mid'. Removing Haiku must not touch tiers
    that were never on it."""
    try:
        config.set_provider("claude")
        assert config.resolve_stage_pin("refine", "medium") is not None
        for tier in ("hard", "elite"):
            assert config.resolve_stage_pin("refine", tier) is None, tier
            assert "sonnet" in config.STAGE_CONFIG["refine"][tier][0]
    finally:
        config.set_provider("claude")


def test_per_tier_and_whole_stage_pins_both_resolve():
    assert config.resolve_stage_pin("judge", "elite") is not None, "whole-stage pin"
    assert config.resolve_stage_pin("judge", None) is not None
    assert config.resolve_stage_pin("refine", None) is None, (
        "a tier-scoped pin must not apply when the tier is unknown")
    assert config.resolve_stage_pin("render", "elite") is None


def test_reasoning_headroom_follows_the_pinned_model_not_the_batch_provider():
    """Regression, 2026-08-24: headroom was keyed on the batch provider, so on
    a --provider claude run the Luna-pinned check stages kept their bare
    Anthropic ceilings, exhausted them on reasoning, and paid twice via the
    doubling retry — five times in a single batch."""
    try:
        config.set_provider("claude")
        for stage in ("compliance", "judge", "move_signature", "answerability"):
            base = config._STAGE_PLAN[stage]["elite"][1]
            actual = config.STAGE_CONFIG[stage]["elite"][1]
            assert actual > base, (
                f"{stage} is pinned to a reasoning model but got no headroom")
        # an unpinned Anthropic stage must be untouched
        assert (config.STAGE_CONFIG["render"]["elite"][1]
                == config._STAGE_PLAN["render"]["elite"][1])
    finally:
        config.set_provider("claude")


def test_family_exclusion_window_cannot_erase_an_arc_shape():
    """Regression, 2026-08-24. 32 of 46 families carry the legacy arc and had
    not been used in 25 sets, while all 14 new-shape families had been used that
    day. The recency window therefore excluded every new shape and left medium
    with 7 candidates, all legacy — the anti-repetition mechanism enforcing the
    very arc it was meant to move away from. Two of three sets in that batch
    came back flagged as repeats."""
    import collections
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.registry import ComponentRegistry
    from rc_engine.llm import MockLLMClient

    reg = ComponentRegistry()
    order = {"medium": 0, "hard": 1, "elite": 2}

    class _H:
        """Every NEW-shape family used recently; every legacy family stale."""
        def component_positions(self, ctype):
            if ctype != "family":
                return {}
            return {f: (0 if reg.shape_of(f) != "staged_turn_settled" else 10**6)
                    for f in reg.ids("family")}
        def usage_counts_trailing(self, *a, **k): return {}
        def recent_shipped_blueprints(self, n): return []
        def shipped_combo_hashes(self): return set()
        def fingerprint_window(self, n, include_quarantined=False): return []

    comp = BlueprintComposer(reg, _H(), CompatibilityRules(reg), MockLLMClient())
    for tier in ("medium", "hard", "elite"):
        pool = comp._eligible("family", tier)
        shapes = {reg.shape_of(f) for f in pool}
        eligible_shapes = {
            reg.shape_of(f) for f in reg.ids("family")
            if order[reg.get("family", f)["tier_floor"]] <= order[tier]
            # tier_max is a ceiling (2026-08-25): the exam-derived expository
            # families are deliberately unavailable above hard, so they are not
            # expected in the elite pool.
            and order[reg.get("family", f).get("tier_max", "elite")] >= order[tier]}
        assert shapes == eligible_shapes, (
            f"{tier}: window dropped shapes {sorted(eligible_shapes - shapes)}")


def test_elite_never_draws_an_exam_derived_family():
    """Decision 2026-08-25: the exam-derived expository families widen medium
    and hard; elite keeps only the literary forms that produce the hardest
    passages. tier_max enforces it — tier_floor alone could not, being a floor."""
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    order = {"medium": 0, "hard": 1, "elite": 2}
    capped = [f for f in reg.ids("family")
              if reg.get("family", f).get("tier_max", "elite") != "elite"]
    assert capped, "no family carries a tier ceiling"
    for fid in capped:
        fam = reg.get("family", fid)
        assert order[fam["tier_max"]] >= order[fam["tier_floor"]], fid
        assert fam.get("difficulty_source"), (
            f"{fid} must declare what reading skill it tests — a form is not "
            f"easy just because it is expository")


def test_exam_derived_families_declare_a_real_difficulty_source():
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    for fid in ("F47", "F48", "F49", "F50", "F51", "F52"):
        fam = reg.get("family", fid)
        assert fam["tier_max"] == "hard", fid
        assert len(fam["difficulty_source"].split()) >= 12, (
            f"{fid}: difficulty_source is too thin to be a real claim")


def test_exam_form_share_is_capped_per_tier():
    """The exam-derived families are a variety valve, not a template — this
    engine deliberately sets above exam level. Left to the decay weighting they
    took 71% of medium draws and 52% of hard on the day they were added, simply
    because new components carry no usage history."""
    import collections
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.history import HistoryStore
    from rc_engine.registry import ComponentRegistry
    from rc_engine.llm import MockLLMClient

    reg = ComponentRegistry()
    hist = HistoryStore(config.DB_PATH)
    try:
        comp = BlueprintComposer(reg, hist, CompatibilityRules(reg), MockLLMClient())
        for tier, cap in config.EXAM_FORM_MAX_SHARE.items():
            n = 400
            drawn = collections.Counter(
                reg.shape_of(comp.sample_skeleton(tier)["family"]) for _ in range(n))
            share = sum(v for k, v in drawn.items()
                        if k in config.EXAM_DERIVED_SHAPES) / n
            # 3-sigma on the binomial, not a magic constant. Until 2026-08-29
            # the realised share was 0.0% (a posture ban was erasing the whole
            # cohort), so any tolerance passed. Now that the share actually
            # binds at the cap, a fixed +0.05 at n=400 is a ~2-sigma bound and
            # fails roughly one run in fifty.
            tol = 3 * (cap * (1 - cap) / n) ** 0.5
            assert share <= cap + tol, (
                f"{tier}: {share:.1%} exceeds cap {cap:.0%} "
                f"by more than 3 sigma ({tol:.1%})")
    finally:
        hist.close()


def test_exam_form_caps_are_ceilings_not_targets():
    assert config.EXAM_FORM_MAX_SHARE["elite"] == 0.0
    assert (config.EXAM_FORM_MAX_SHARE["hard"]
            < config.EXAM_FORM_MAX_SHARE["medium"] <= 0.5)
    assert config.EXAM_DERIVED_SHAPES, "the cap needs shapes to apply to"


def test_topic_shapes_have_a_recency_window():
    """TS08 was drawn for two of three elite sets on 2026-08-25 and the screen
    correctly flagged the pair — the structure it named was TS08's own
    instruction. Topic shapes need the recency pressure every other component
    already has."""
    assert "topic_shape" in config.EXCLUSION_WINDOWS
    assert 2 <= config.EXCLUSION_WINDOWS["topic_shape"] <= 6


def test_seed_genre_cap_is_a_ceiling_not_a_quota():
    """At 0.45 the cap blocked an entire hard tier: conceptual_essay sat at 55%
    of 11 keyed sets, so every hard seed was rotated. 25 of 34 RAG feeds are
    still idea-essays, so most seeds classify that way regardless."""
    assert 0.5 <= config.SEED_GENRE_SATURATION <= 0.75


def test_weak_elite_families_are_capped_at_hard():
    """F40 scored 6.0 at elite with family_realization 2/10 — its definition is
    that no paragraph states a verdict, and the renderer stated them anyway.
    F44 scored 6.8 and is the only 3-paragraph family, ~180 words per paragraph
    against a typical ~110. Both stay available where they work."""
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    for fid in ("F40", "F44"):
        fam = reg.get("family", fid)
        assert fam.get("tier_max") == "hard", fid
        assert fam.get("tier_max_reason"), f"{fid} must record WHY it was capped"


def test_seed_ancestry_threshold_is_calibrated_not_guessed():
    """Two seeds can share a territory that the finished passages no longer
    visibly share, because refine walked each one somewhere specific:
    RC-ELITE-260822-0062 (New Atlantis on AI builders) became chatbots of the
    dead; RC-HARD-260828-0067 (Noema on AI's gift) became a parish prayer board
    in a livestream. Different family, stance and topic shape — and the screen
    still called them the same essay.

    Measured over 946 seed pairs: median 0.537, p99 0.719, and that pair 0.764.
    A threshold above ~0.78 misses it; below ~0.72 starts rotating ordinary
    same-domain seeds."""
    assert 0.72 <= config.SEED_ANCESTRY_COSINE <= 0.78
    assert config.SEED_ANCESTRY_COSINE > config.SEED_PRESCREEN_COSINE * 0.8
    assert config.SEED_ANCESTRY_WINDOW >= 8


def test_seed_ancestry_degrades_when_the_store_is_unavailable():
    """A $0 local check must never be able to stop a batch."""
    from rc_engine import pipeline as pm

    class _H:
        class conn:
            @staticmethod
            def execute(*a):
                raise RuntimeError("no db")
    class _P:
        history = _H()
    assert pm._seed_ancestry_collision(_P(), object(), [0.1, 0.2]) is None


# ---------------------------------------------------------------------------
# Beat POSITION obedience (2026-08-29)
#
# Membership in the move plan was the only check until now. Measured over the
# nine sets shipped 08-24..08-28: SCENE_PARTICULAR was planned as the opening
# beat 0 times and realised as it 6 times; CONCRETE_RETURN was planned to close
# once and closed 5 times. Openings obeyed 2/9, closings 1/9 — and every one of
# those scored a PERFECT beat_score, because the displaced beat still turned up
# somewhere in the middle. These tests pin the gap, not the wording.
# ---------------------------------------------------------------------------

def _mock_blueprint():
    from rc_engine.models import Blueprint, ParagraphPlan
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    topo = reg.get("topology", reg.ids("topology")[0])
    return Blueprint(
        blueprint_id="x", tier="hard",
        schema_version=config.BLUEPRINT_SCHEMA_VERSION,
        family_id=reg.ids("family")[0], persona_id="P01", ending_id="E01",
        rhythm_id="T01", revelation_id="R01", distractor_profile_id="D01",
        topology_id=topo["id"], render_stance_id=reg.ids("render_stance")[0],
        instability=0.5, aperture="x", closing_register="bound_continuation",
        topic="a topic",
        movement=[ParagraphPlan(para=i, function="F%d" % i,
                                len_words=(140, 140), cadence="plain")
                  for i in range(1, 4)],
        revelation_detail={"planned_para": 2},
        trap_map=[{"trap_id": "TR1", "anchor_para": 1,
                   "invited_misreading": "x", "mechanism": "half_truth"}])


def _audit_with_moves(planned, realised):
    """Score a blueprint whose move_plan is `planned` against prose that the
    blind reader saw as `realised`. Returns the RealizedStructure."""
    from rc_engine.compliance import ComplianceAuditor
    from rc_engine.llm import CostLedger, MockLLMClient
    from rc_engine.registry import ComponentRegistry
    import rc_engine.compliance as C

    reg = ComponentRegistry()
    auditor = ComplianceAuditor(MockLLMClient(), reg)
    bp = _mock_blueprint()
    bp.move_plan = list(planned)
    # drive the LLM-scored half to a fixed, passing shape so the only thing
    # varying between cases is the beat positions
    passage = "\n\n".join("Paragraph %d body text here." % i
                          for i in range(1, len(bp.movement) + 1))
    return auditor.audit(passage, bp, CostLedger(budget_usd=1.0), list(realised))


def test_opening_beat_out_of_position_is_caught():
    """The exact failure from RC-HARD-260828-0067: ABSTRACT_CLAIM_OPEN planned,
    SCENE_PARTICULAR delivered, and the planned beat still present later."""
    planned = ["ABSTRACT_CLAIM_OPEN", "CONCESSION_GRANTED", "BOUND_CONTINUATION"]
    realised = ["SCENE_PARTICULAR", "ABSTRACT_CLAIM_OPEN",
                "CONCESSION_GRANTED", "BOUND_CONTINUATION"]
    r = _audit_with_moves(planned, realised)
    assert r.opening_beat_ok is False, (
        "opened on SCENE_PARTICULAR against a plan that said ABSTRACT_CLAIM_OPEN")
    assert any("FIRST SENTENCE" in d for d in r.directives), r.directives


def test_every_planned_beat_present_but_misordered_still_fails():
    """The reason this went unnoticed: set-membership scoring gives this a
    perfect beat_score. Position must be judged separately."""
    planned = ["QUESTION_POSED", "MECHANISM_EXPLAINED", "CONCESSION_COSTED"]
    realised = ["SCENE_PARTICULAR", "MECHANISM_EXPLAINED",
                "CONCESSION_COSTED", "QUESTION_POSED", "CONCRETE_RETURN"]
    r = _audit_with_moves(planned, realised)
    assert set(planned) <= set(realised), "premise: no beat is missing"
    assert r.opening_beat_ok is False and r.closing_beat_ok is False


def test_obedient_passage_is_not_penalised():
    planned = ["QUESTION_POSED", "MECHANISM_EXPLAINED", "CONCESSION_COSTED"]
    realised = ["QUESTION_POSED", "MECHANISM_EXPLAINED",
                "INSTANCE_SURVEY", "CONCESSION_COSTED"]
    r = _audit_with_moves(planned, realised)
    assert r.opening_beat_ok is True and r.closing_beat_ok is True
    assert not any("FIRST SENTENCE" in d or "FINAL SENTENCE" in d
                   for d in r.directives)


def test_directives_prescribe_rather_than_forbid():
    """The 2026-08-22 finding on the closing register: negative constraints are
    what the renderer ignores. The directive must name the beat it owes."""
    planned = ["HISTORICAL_ORIGIN", "MECHANISM_EXPLAINED", "BOUND_CONTINUATION"]
    r = _audit_with_moves(planned, ["SCENE_PARTICULAR", "MECHANISM_EXPLAINED",
                                    "HISTORICAL_ORIGIN", "BOUND_CONTINUATION"])
    d = next(x for x in r.directives if "FIRST SENTENCE" in x)
    assert "HISTORICAL_ORIGIN" in d and "must perform" in d


def test_render_contract_states_the_positional_beats_before_the_list():
    """A list labelled 'in order' was already being read as an unordered menu.
    The two positional beats have to appear above it, on their own."""
    from rc_engine.registry import ComponentRegistry
    from rc_engine.renderer import PassageRenderer
    bp = _mock_blueprint()
    bp.move_plan = ["HISTORICAL_ORIGIN", "MECHANISM_EXPLAINED", "CONCESSION_COSTED"]
    contract = PassageRenderer(ComponentRegistry(), None)._contract(bp, [])
    assert "FIRST SENTENCE — HISTORICAL_ORIGIN" in contract
    assert "FINAL SENTENCE — CONCESSION_COSTED" in contract
    assert contract.index("FIRST SENTENCE") < contract.index("RHETORICAL BEAT PLAN")


def test_concrete_particular_is_barred_from_sentence_one():
    """renderer.py's HUMAN TEXTURE rule put a concrete particular in sentence 1
    of 6 of 9 consecutive passages, none of which planned one."""
    from rc_engine.registry import ComponentRegistry
    from rc_engine.renderer import PassageRenderer, RENDER_SYSTEM
    assert "NOT be the opening sentence" in RENDER_SYSTEM
    bp = _mock_blueprint()
    bp.move_plan = ["ABSTRACT_CLAIM_OPEN", "MECHANISM_EXPLAINED", "BOUND_CONTINUATION"]
    contract = PassageRenderer(ComponentRegistry(), None)._contract(bp, [])
    assert "Do not open on a concrete scene" in contract


# ---------------------------------------------------------------------------
# First-person share (2026-08-29). Never a sampling bug: the library is 6/20 =
# 30% singular-I and the sampler sat exactly on that rate corpus-wide (22/74).
# The library composition itself was out of calibration — an authorial "I"
# appears in 6% of 129 real CAT/XAT/GMAT passages and 6 of our last 9.
# ---------------------------------------------------------------------------

def test_every_persona_declares_its_grammatical_person():
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    ok = {"first_singular", "first_plural", "impersonal"}
    for pid in reg.ids("persona"):
        got = reg.get("persona", pid).get("pronoun_person")
        assert got in ok, f"{pid}: {got!r}"


def test_first_person_share_is_capped_below_the_library_rate():
    """A cap that sits at or above the 30% library rate would be inert."""
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    lib = sum(1 for p in reg.ids("persona")
              if reg.get("persona", p).get("pronoun_person") == "first_singular")
    share = lib / len(reg.ids("persona"))
    assert config.FIRST_PERSON_MAX_SHARE < share, (
        f"cap {config.FIRST_PERSON_MAX_SHARE} does not bind against a "
        f"{share:.0%} library rate")
    assert config.FIRST_PERSON_MAX_SHARE > 0.0, (
        "the first-person essayist is a legitimate register, not one to ban")


# ---------------------------------------------------------------------------
# Share ceilings actually bind (2026-08-29).
#
# Both bugs were found while VERIFYING the first-person cap, not by reading:
#   1. A permit-only flip multiplies two probabilities. A 20% first-person
#      ceiling realised 4-5% (0.20 flip x 0.30 library rate).
#   2. All six exam-derived families close on resolution_qualified, and
#      POSTURE_RUN_MAX is 2, so a two-set resolution run banned the whole
#      cohort. Realised exam-form share was 0.0% against 50%/35% ceilings.
# ---------------------------------------------------------------------------

def _fresh_composer():
    from rc_engine.composer import BlueprintComposer
    from rc_engine.constraints import CompatibilityRules
    from rc_engine.history import HistoryStore
    from rc_engine.llm import MockLLMClient
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    hist = HistoryStore(config.DB_PATH)
    return reg, hist, BlueprintComposer(reg, hist, CompatibilityRules(reg),
                                        MockLLMClient())


def test_posture_ban_cannot_erase_an_arc_shape():
    """A ban on a closing cadence was silently acting as a ban on an entire
    arc-shape cohort."""
    reg, hist, comp = _fresh_composer()
    try:
        exam = [f for f in reg.ids("family")
                if reg.shape_of(f) in config.EXAM_DERIVED_SHAPES]
        assert exam, "premise: exam-derived families exist"
        kept = comp._posture_filter(reg.ids("family"))
        shapes_in = {reg.shape_of(i) for i in reg.ids("family")}
        shapes_out = {reg.shape_of(i) for i in kept}
        assert shapes_in == shapes_out, (
            f"posture ban erased arc shapes: {sorted(shapes_in - shapes_out)}")
    finally:
        hist.close()


def test_share_flip_steers_both_ways():
    """Permitting a cohort and then letting it compete against the whole pool
    multiplies the two probabilities; it does not realise the ceiling."""
    from rc_engine.composer import BlueprintComposer as B
    pool = ["a1", "a2", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8"]
    inc = lambda i: i.startswith("a")
    assert B._steer_share(pool, True, inc) == ["a1", "a2"]
    assert all(not inc(i) for i in B._steer_share(pool, False, inc))
    # never dead-ends a slot when the cohort is absent
    assert B._steer_share(["b1", "b2"], True, inc) == ["b1", "b2"]


def test_exam_form_share_realises_at_its_ceiling():
    """The ceiling the user set on 2026-08-26 was 50% medium / 35% hard and the
    engine was shipping 0%."""
    reg, hist, comp = _fresh_composer()
    try:
        for tier in ("medium", "hard"):
            cap = config.EXAM_FORM_MAX_SHARE[tier]
            n = hits = 0
            for _ in range(250):
                try:
                    fid = comp.sample_skeleton(tier)["family"]
                    n += 1
                    if reg.shape_of(fid) in config.EXAM_DERIVED_SHAPES:
                        hits += 1
                except Exception:
                    continue
            share = hits / max(1, n)
            tol = 3 * (cap * (1 - cap) / max(1, n)) ** 0.5
            assert share <= cap + tol, f"{tier}: {share:.1%} over cap {cap:.0%}"
            assert share >= cap * 0.5, (
                f"{tier}: {share:.1%} far under its {cap:.0%} ceiling — "
                f"the cohort is being filtered out upstream")
    finally:
        hist.close()


def test_first_person_share_realises_at_its_ceiling():
    reg, hist, comp = _fresh_composer()
    try:
        n = hits = 0
        for _ in range(250):
            try:
                pid = comp.sample_skeleton("hard")["persona"]
                n += 1
                if reg.get("persona", pid).get("pronoun_person") == "first_singular":
                    hits += 1
            except Exception:
                continue
        share = hits / max(1, n)
        cap = config.FIRST_PERSON_MAX_SHARE
        tol = 3 * (cap * (1 - cap) / max(1, n)) ** 0.5
        assert cap * 0.5 <= share <= cap + tol, (
            f"realised {share:.1%} against a {cap:.0%} ceiling")
    finally:
        hist.close()


# ---------------------------------------------------------------------------
# Seed-ancestry pre-screen against a REAL store return shape (2026-08-29).
#
# The channel was added and "verified" via a direct script, which passed lists
# around. Chroma actually returns embeddings as a numpy array, so the first
# real batch to reach this code died on `got.get("embeddings") or []` with
# "truth value of an array with more than one element is ambiguous" — at $0,
# but it took the whole batch with it. Mocks that hand back lists cannot catch
# this; the fake below returns arrays the way Chroma does.
# ---------------------------------------------------------------------------

def test_seed_ancestry_handles_numpy_embeddings(monkeypatch):
    import numpy as np
    from rc_engine import pipeline as P
    from rc_engine.models import SeedEssay

    class _Store:
        def get(self, ids, include=None):
            return {"ids": list(ids),
                    "embeddings": np.array([[1.0, 0.0, 0.0]] * len(ids))}

    class _RAG:
        @staticmethod
        def get_db(): return _Store()

    class _Hist:
        class conn:
            @staticmethod
            def execute(*a, **k):
                class R:
                    @staticmethod
                    def fetchall(): return [("RC-X", "doc-1")]
                return R
    class _Pipe:
        history = _Hist()

    monkeypatch.setitem(sys.modules, "RAG", _RAG)
    seed = SeedEssay(doc_id="doc-other", url="u", title="t", text="x")
    hit = P._seed_ancestry_collision(_Pipe(), seed, [1.0, 0.0, 0.0])
    assert hit is not None and "RC-X" in hit, (
        "an identical seed vector must be caught, not crash")


def test_seed_ancestry_never_raises_out_of_a_batch(monkeypatch):
    """Every failure mode here must degrade to None. This runs inside the free
    pre-screen; an exception aborts the entire batch."""
    from rc_engine import pipeline as P
    from rc_engine.models import SeedEssay

    class _Boom:
        @staticmethod
        def get_db(): raise RuntimeError("store gone")

    class _Hist:
        class conn:
            @staticmethod
            def execute(*a, **k):
                class R:
                    @staticmethod
                    def fetchall(): return [("RC-X", "doc-1")]
                return R
    class _Pipe:
        history = _Hist()

    monkeypatch.setitem(sys.modules, "RAG", _Boom)
    assert P._seed_ancestry_collision(_Pipe(), SeedEssay(doc_id="d"), [1.0]) is None
