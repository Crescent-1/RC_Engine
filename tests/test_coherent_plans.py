"""cat-pyq-f4 / legacy-sf2 (2026-09-14): seed context for the writer and
self-consistent plans. Evidence: the prompt review of RC-HARD-260914-0099 and a
count over 135 shipped plans (see GenerationPolicy.coherent_plans)."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.composer import COMMITTED_POSTURE_CLASSES, CONFLICTING_BEATS  # noqa: E402
from rc_engine.generation_policy import get_policy, legacy_base_errors  # noqa: E402
from rc_engine.llm import MockLLMClient  # noqa: E402
from rc_engine.policy_catalog import (CAT_PYQ_F3, CAT_PYQ_F4, LEGACY_SF1,  # noqa: E402
                                      LEGACY_SF2)


def _composer(tmp_path, seed=11):
    from rc_engine.history import HistoryStore
    from rc_engine.pipeline import RCPipeline
    history = HistoryStore(str(tmp_path / "coherent.db"))
    pipe = RCPipeline(history, MockLLMClient(), embed=False, rng=random.Random(seed))
    return pipe, history


def test_f4_and_legacy_sf2_add_only_the_two_flags():
    f3, f4 = get_policy(CAT_PYQ_F3), get_policy(CAT_PYQ_F4)
    s1, s2 = get_policy(LEGACY_SF1), get_policy(LEGACY_SF2)
    for new, old in ((f4, f3), (s2, s1)):
        assert new.coherent_plans and new.render_seed_context
        assert not old.coherent_plans and not old.render_seed_context
        assert new.seed_fidelity and new.system_extensions == old.system_extensions
    assert s2.legacy_base and legacy_base_errors(s2) == [] and "elite" in s2.tiers
    assert "elite" not in f4.tiers


def test_committed_close_never_draws_a_never_stated_thesis(tmp_path):
    pipe, history = _composer(tmp_path)
    comp, reg = pipe.composer, pipe.registry
    seen_committed = 0
    for version, guarded in ((LEGACY_SF2, True), ("", False)):
        clashes = 0
        comp.rng = random.Random(3)
        for _ in range(250):
            ids = comp.sample_skeleton("elite", policy=get_policy(version))
            committed = reg.posture_of(ids["family"]).split("_")[0] in COMMITTED_POSTURE_CLASSES
            seen_committed += committed
            if committed and reg.get("revelation", ids["revelation"])["timing"] == "never_stated":
                clashes += 1
        if guarded:
            assert clashes == 0
        else:
            assert clashes > 0          # the legacy draw really does produce the clash
    assert seen_committed
    history.close()


def test_move_plans_never_hold_both_contradictory_beats(tmp_path):
    pipe, history = _composer(tmp_path)
    comp = pipe.composer
    pair = next(iter(CONFLICTING_BEATS))
    counts = {}
    for version in (CAT_PYQ_F4, CAT_PYQ_F3):
        comp.rng = random.Random(9)
        both = 0
        policy = get_policy(version)
        for _ in range(300):
            plan = comp._sample_move_plan(None, "hard", None, policy=policy)
            both += pair <= set(plan)
        counts[version] = both
    assert counts[CAT_PYQ_F4] == 0
    assert counts[CAT_PYQ_F3] > 0, counts
    history.close()


def _bp(version, seed):
    from rc_engine.models import Blueprint, ParagraphPlan
    bp = Blueprint(blueprint_id="BP_ctx", tier="hard", schema_version="2.0", family_id="F12",
                   persona_id="P01", ending_id="E07", rhythm_id="T01", revelation_id="R02",
                   distractor_profile_id="D01", topology_id="QT01", instability=0.5,
                   aperture="x", generation_policy=version, seed_genre="criticism",
                   seed=seed)
    bp.movement = [ParagraphPlan(1, "SMALL_DISPUTE_STAGED", (100, 120), "mixed", gist="a brief")]
    bp.revelation_detail = {"planned_para": 1}
    bp.topic = "a topic"
    return bp


def test_render_contract_names_the_seed_and_subordinates_the_role_only_under_f4():
    from rc_engine.registry import ComponentRegistry
    from rc_engine.renderer import PassageRenderer
    seed = {"title": "Chills of the Unsaid", "subject": "what a novelist leaves unsaid",
            "seed_domain": "literature", "particulars": ["Gwendoline Riley"]}
    renderer = PassageRenderer(ComponentRegistry(), None)
    f4 = renderer._contract(_bp(CAT_PYQ_F4, seed), [])
    assert "SOURCE ESSAY (the passage stays on its subject):" in f4
    assert "Chills of the Unsaid" in f4 and "Gwendoline Riley" in f4
    assert "subject area: literature" in f4 and "kind of material: criticism" in f4
    assert "arc role = small dispute staged (where the brief or beats differ, they govern)" in f4
    f3 = renderer._contract(_bp(CAT_PYQ_F3, seed), [])
    assert "SOURCE ESSAY" not in f3 and "role = small dispute staged." in f3
    assert "TOPIC: a topic\nSOURCE GENRE: criticism\nTIER:" in f3     # no stray blank line
    seedless = renderer._contract(_bp(CAT_PYQ_F4, {}), [])
    assert "SOURCE ESSAY" not in seedless
