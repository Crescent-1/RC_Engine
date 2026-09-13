"""Generation-policy boundary, 2026-09-13 (plan section 3).

The golden comparisons run a full deterministic mock scenario (in a subprocess
with a pinned hash seed; see tests/policy_harness.py) and require it to match
output captured from the engine BEFORE the policy layer existed (23e3d49):

  generation_policy_legacy_golden.json          the interleaved 14-attempt run
  generation_policy_elite_isolation_golden.json  six mixed attempts, then four
                                                 elite ones with a resume

The remaining tests run in-process against tests/policy_fixtures.py, a
test-only policy that owns one tagged component of every sampled type plus an
extra beat, slot type, stem forms, prompt extensions and a weight boost.
"""
import copy
import functools
import json
import os
import pathlib
import random
import shutil
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import policy_fixtures as pf  # noqa: E402
from policy_harness import SEQUENCE, run_in_subprocess  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "generation_policy_legacy_golden.json"
ELITE_GOLDEN = FIXTURES / "generation_policy_elite_isolation_golden.json"
SHIPPED = ("approved", "needs_review", "solver_dispute")


def first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: present on one side only"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def _golden(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---- golden comparisons (subprocess) ----------------------------------------

def test_legacy_scenario_matches_pre_policy_golden(tmp_path):
    result = run_in_subprocess(str(tmp_path / "scenario.json"), str(tmp_path))
    if os.environ.get("RC_REGEN_POLICY_GOLDEN") == "1":
        FIXTURES.mkdir(exist_ok=True)
        shutil.copyfile(tmp_path / "scenario.json", GOLDEN)
        pytest.skip("golden regenerated")
    diff = first_difference(_golden(GOLDEN), result)
    assert diff is None, f"legacy behaviour changed at {diff}"


def test_registered_but_disabled_policy_with_tagged_libraries_matches_golden(tmp_path):
    """A registered policy and tagged components in every library change
    nothing while no tier composes under the policy: legacy plans never see
    tagged components, including through recency/ban/topology fallbacks."""
    result = run_in_subprocess(str(tmp_path / "scenario.json"), str(tmp_path), {
        "setup": "policy_fixtures:install_disabled",
        "components_dir": str(tmp_path / "components")})
    diff = first_difference(_golden(GOLDEN), result)
    assert diff is None, f"tagged components leaked into legacy plans at {diff}"


def test_elite_matches_pre_policy_golden_while_medium_hard_use_policy(tmp_path):
    """Same history, RNG state and ids at the switch; from then on medium and
    hard compose under the policy (in a side pipeline in the same process,
    between every elite attempt) and elite output — components, prompts,
    effective slots, stem shapes, resume, topology re-pick, exhausted-pool
    probes — still equals the pre-policy engine's."""
    report = tmp_path / "side.json"
    result = run_in_subprocess(str(tmp_path / "scenario.json"), str(tmp_path), {
        "sequence": SEQUENCE[:6] + ["elite"] * 4, "switch_at": 6, "resume_at": 6,
        "probe_tiers": ["elite"],
        "setup": "policy_fixtures:install_disabled",
        "switch": "policy_fixtures:enable_medium_hard",
        "between": "policy_fixtures:run_side_attempt",
        "components_dir": str(tmp_path / "components"),
        "workdir": str(tmp_path), "side_report": str(report)})
    diff = first_difference(_golden(ELITE_GOLDEN), result)
    assert diff is None, f"elite behaviour changed at {diff}"
    assert result["resume"] and result["resume"]["tier"] == "elite"

    side = json.loads(report.read_text(encoding="utf-8"))
    assert len(side) == 4
    assert all(s["generation_policy"] == pf.TEST_VERSION for s in side if s["family"])
    assert any(s["family"] == pf.TAGGED["family"] or s["topology"] == pf.TAGGED["topology"]
               for s in side), side
    assert any(s["question_slots"] == 8 for s in side), side


@pytest.mark.parametrize("version", ["cat-pyq-s1", "cat-pyq-s2"])
def test_elite_matches_pre_policy_golden_while_structure_release_runs(tmp_path, version):
    """Section 5 releases (families, beats, revelations, rhythms, personas,
    permissions, rewritten render rules) run between elite attempts; elite still
    equals the pre-policy engine's output."""
    report = tmp_path / "side.json"
    result = run_in_subprocess(str(tmp_path / "scenario.json"), str(tmp_path), {
        "sequence": SEQUENCE[:6] + ["elite"] * 4, "switch_at": 6, "resume_at": 6,
        "probe_tiers": ["elite"],
        "switch": "policy_fixtures:enable_policy", "policy": version,
        "between": "policy_fixtures:run_side_attempt",
        "workdir": str(tmp_path), "side_report": str(report)})
    diff = first_difference(_golden(ELITE_GOLDEN), result)
    assert diff is None, f"elite behaviour changed at {diff}"
    side = json.loads(report.read_text(encoding="utf-8"))
    assert all(s["generation_policy"] == version for s in side if s["family"])


def test_elite_matches_pre_policy_golden_while_cat_pyq_q1_runs(tmp_path):
    """The same isolation check with the PRODUCTION question release: its
    contract slots, stem pools, QA extensions and QT25/QT26 run in the same
    process between elite attempts, and elite still equals the pre-policy
    engine's output."""
    report = tmp_path / "side.json"
    result = run_in_subprocess(str(tmp_path / "scenario.json"), str(tmp_path), {
        "sequence": SEQUENCE[:6] + ["elite"] * 4, "switch_at": 6, "resume_at": 6,
        "probe_tiers": ["elite"],
        "switch": "policy_fixtures:enable_cat_pyq_q1",
        "between": "policy_fixtures:run_side_attempt",
        "workdir": str(tmp_path), "side_report": str(report)})
    diff = first_difference(_golden(ELITE_GOLDEN), result)
    assert diff is None, f"elite behaviour changed at {diff}"
    side = json.loads(report.read_text(encoding="utf-8"))
    assert len(side) == 4
    assert all(s["generation_policy"] == "cat-pyq-q1" for s in side if s["family"])
    shipped = [s for s in side if s["question_slots"]]
    assert shipped and all(s["question_slots"] == 8 and s["negatives"] == 2
                           for s in shipped), side


# ---- in-process fixtures -----------------------------------------------------

def _text_llm():
    """MockLLMClient that keeps full prompt text and context."""
    from rc_engine.llm import MockLLMClient

    class TextLLM(MockLLMClient):
        def __init__(self):
            self.calls = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append({"stage": stage, "system": system, "user": user,
                               "context": dict(context or {})})
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    return TextLLM()


def _seed(n):
    from rc_engine.models import SeedEssay
    return SeedEssay(url=f"https://example.org/policy-{n}", title=f"Policy source {n}",
                     text="Harbour pilots kept private tide notes that the port's official "
                          "tables never absorbed, and the notes were right more often.")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from rc_engine import config, generation_policy as gp, pipeline as pl, registry as rg
    from rc_engine.history import HistoryStore
    d = pf.build_components(str(tmp_path / "components"))
    monkeypatch.setattr(pl, "ComponentRegistry", functools.partial(rg.ComponentRegistry, d))
    with gp.temporary_policy(pf.make_policy()) as policy:
        monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                            {"medium": pf.TEST_VERSION, "hard": pf.TEST_VERSION, "elite": ""})
        history = HistoryStore(str(tmp_path / "history.db"))
        llm = _text_llm()
        pipe = pl.RCPipeline(history, llm, embed=False, rng=random.Random(20260913))
        try:
            yield SimpleNamespace(pipe=pipe, llm=llm, history=history, policy=policy,
                                  config=config, gp=gp, components=d)
        finally:
            history.close()


def _stored(env, bp_id):
    from rc_engine.models import Blueprint
    row = env.history.conn.execute(
        "SELECT blueprint_json, status, created_at FROM blueprints WHERE blueprint_id = ?",
        (bp_id,)).fetchone()
    return Blueprint.from_json(row[0]), row[1], row[2]


def _tagged_ids(bp):
    ids = set(bp.component_ids.values()) | {bp.topic_shape_id}
    return ids & set(pf.TAGGED.values())


# ---- new plans ---------------------------------------------------------------

def test_new_medium_hard_plans_store_policy_and_use_its_additions(env):
    stems_before = copy.deepcopy(env.pipe.registry.stem_forms)
    types_before = copy.deepcopy(env.pipe.registry.slot_type_definitions)
    moves_before = dict(env.config.RHETORICAL_MOVES)
    for n, tier in enumerate(("hard", "medium")):
        start = len(env.llm.calls)
        res = env.pipe.generate_one(tier, _seed(n))
        assert res.status in SHIPPED, res.notes
        bp, _, _ = _stored(env, res.blueprint_id)
        assert bp.generation_policy == pf.TEST_VERSION
        assert _tagged_ids(bp), "the boosted tagged components were never drawn"
        # Slots were fixed before the questions call and stored on the plan.
        assert len(bp.question_slots) == 8
        calls = env.llm.calls[start:]
        by_stage = {}
        for c in calls:
            by_stage.setdefault(c["stage"], []).append(c)
        for stage in ("refine", "render", "compliance", "questions"):
            assert f"{pf.EXTENSION} [{stage}]" in by_stage[stage][0]["user"], stage
            assert f"{pf.SYSTEM_EXTENSION} [{stage}]" in by_stage[stage][0]["system"], stage
        assert by_stage["questions"][0]["context"]["slots"] == bp.question_slots
        # The blind beat read offers the policy's closed vocabulary.
        sig = by_stage["move_signature"][0]
        assert pf.EXTRA_MOVE in sig["user"]
        assert pf.EXTRA_MOVE in sig["context"]["vocabulary"]
        if bp.topology_id == pf.TAGGED["topology"]:
            q = by_stage["questions"][0]["user"]
            assert pf.EXTRA_SLOT in q and "(test " in q
    # Nothing shared was widened in place.
    assert env.pipe.registry.stem_forms == stems_before
    assert env.pipe.registry.slot_type_definitions == types_before
    assert dict(env.config.RHETORICAL_MOVES) == moves_before
    assert pf.EXTRA_MOVE not in env.config.MOVE_GROUPS["middle"]


def test_elite_plans_stay_legacy_even_when_config_names_the_policy(env, monkeypatch):
    monkeypatch.setattr(env.config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": pf.TEST_VERSION, "hard": pf.TEST_VERSION,
                         "elite": pf.TEST_VERSION})
    assert env.gp.policy_for_new_plan("elite") is env.gp.LEGACY_POLICY
    start = len(env.llm.calls)
    res = env.pipe.generate_one("elite", _seed(9))
    bp, _, _ = _stored(env, res.blueprint_id)
    assert bp.generation_policy == "" and bp.question_slots == []
    assert not _tagged_ids(bp)
    for c in env.llm.calls[start:]:
        assert pf.EXTENSION not in c["user"] and pf.SYSTEM_EXTENSION not in c["system"]
        assert pf.EXTRA_MOVE not in c["user"]
        assert "vocabulary" not in c["context"]
    # ...and registry validation names the misconfiguration.
    assert "elite must stay on the legacy generation policy" in \
        env.gp.validation_errors(env.pipe.registry)


def test_policy_can_be_disabled_for_future_plans(env, monkeypatch):
    monkeypatch.setattr(env.config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    res = env.pipe.generate_one("hard", _seed(3))
    bp, _, _ = _stored(env, res.blueprint_id)
    assert bp.generation_policy == "" and not _tagged_ids(bp)
    assert json.loads(bp.to_json())["question_slots"] == []


# ---- legacy never sees tagged components ---------------------------------------

def test_legacy_pools_and_fallbacks_never_admit_tagged_components(env):
    comp, reg, P = env.pipe.composer, env.pipe.registry, env.policy
    L = env.gp.LEGACY_POLICY
    for ctype, tagged in pf.TAGGED.items():
        assert tagged in reg.ids(ctype)                  # reports stay unfiltered
        assert tagged not in L.eligible_ids(reg, ctype)
        assert tagged in P.eligible_ids(reg, ctype)
        if ctype != "topic_shape":
            for tier in ("medium", "hard", "elite"):
                assert tagged not in comp._eligible(ctype, tier)
            assert tagged in comp._eligible(ctype, "hard", policy=P)

    # Ban every untagged family: the never-empty-pool fallback must return to
    # the legacy pool, not to the one family that is left.
    untagged = {f for f in reg.ids("family") if f != pf.TAGGED["family"]}
    for tier in ("medium", "hard", "elite"):
        assert pf.TAGGED["family"] not in comp._eligible("family", tier, ban_families=untagged)
        ids = comp.sample_skeleton(tier, ban_families=set(untagged))
        assert not set(ids.values()) & set(pf.TAGGED.values())

    # Topic shapes: the "never dead-end" fallback is the policy's own library.
    from rc_engine.seed_classify import eligible_topic_shapes
    for tid in reg.ids("topic_shape"):
        if tid != pf.TAGGED["topic_shape"]:
            reg.libraries["topic_shape"][tid]["compatible_genres"] = ["no-such-genre"]
    info = {"genre": "conceptual_essay", "bipolar_dispute_available": True}
    legacy = eligible_topic_shapes(reg, info)
    untagged = [t for t in reg.ids("topic_shape")
                if not reg.get("topic_shape", t).get("policies")]
    assert pf.TAGGED["topic_shape"] not in legacy and legacy == untagged
    assert eligible_topic_shapes(reg, info, P) == [pf.TAGGED["topic_shape"]]


def test_topology_repick_respects_the_blueprints_policy(env, monkeypatch):
    pipe = env.pipe
    tagged = pf.TAGGED["topology"]
    assert tagged not in pipe._tier_topologies("hard")
    assert tagged in pipe._tier_topologies("hard", env.policy)
    # Everything collides except the tagged topology.
    monkeypatch.setattr(pipe, "_topology_collisions",
                        lambda tid: [] if tid == tagged else [(0.99, "RC-X")])
    legacy_bp = SimpleNamespace(tier="hard", topology_id="QT01", generation_policy="",
                                blueprint_id="BP_L")
    policy_bp = SimpleNamespace(tier="hard", topology_id="QT01",
                                generation_policy=pf.TEST_VERSION, blueprint_id="BP_P")
    assert pipe._pick_clear_topology(legacy_bp) is None
    assert pipe._pick_clear_topology(policy_bp) == tagged

    # Least-colliding fallback, on real stored plans.
    res = pipe.generate_one("elite", _seed(4))
    bp, _, _ = _stored(env, res.blueprint_id)
    monkeypatch.setattr(pipe, "_topology_collisions",
                        lambda tid: [(0.10, "RC-X")] if tid == tagged else [(0.99, "RC-X")])
    bp.topology_id = next(t for t in pipe._tier_topologies("elite"))
    bp2, _notes, _ok = pipe._resolve_topology(bp)
    assert bp2.topology_id != tagged


# ---- resume, stored slots, unknown versions ------------------------------------

def _fail_questions_once(env, monkeypatch):
    from rc_engine.question_engine import QuestionEngineError
    real = env.pipe.qengine.build
    state = {"fired": False}

    def build(*a, **kw):
        if not state["fired"]:
            state["fired"] = True
            raise QuestionEngineError("forced")
        return real(*a, **kw)
    monkeypatch.setattr(env.pipe.qengine, "build", build)


def test_resume_uses_stored_policy_and_stored_slots(env, monkeypatch):
    _fail_questions_once(env, monkeypatch)
    res = env.pipe.generate_one("hard", _seed(5))
    assert res.status == "failed_questions", res.notes
    bp, status, created = _stored(env, res.blueprint_id)
    assert bp.generation_policy == pf.TEST_VERSION and len(bp.question_slots) == 8
    stored_slots = copy.deepcopy(bp.question_slots)

    # Persisting the slots rewrote only the JSON.
    env.history.update_blueprint_json(bp)
    _, status2, created2 = _stored(env, res.blueprint_id)
    assert (status2, created2) == (status, created)

    # The policy is switched off for NEW plans and the library is edited; the
    # stored plan still resumes under its own policy and asks the same slots.
    monkeypatch.setattr(env.config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    topo = env.pipe.registry.libraries["topology"][bp.topology_id]
    topo["slots"][1] = dict(topo["slots"][1], difficulty=0.01)
    assert env.pipe.qengine.effective_slots(bp) == stored_slots

    start = len(env.llm.calls)
    again = env.pipe.resume_questions(res.blueprint_id)
    assert again.status in SHIPPED, again.notes
    q = [c for c in env.llm.calls[start:] if c["stage"] == "questions"][0]
    assert q["context"]["slots"] == stored_slots
    assert f"{pf.EXTENSION} [questions]" in q["user"]


def test_unknown_policy_version_refuses_resume(env, monkeypatch):
    _fail_questions_once(env, monkeypatch)
    res = env.pipe.generate_one("medium", _seed(6))
    assert res.status == "failed_questions", res.notes
    bp, _, _ = _stored(env, res.blueprint_id)
    bp.generation_policy = "retired-or-never-registered"
    env.history.update_blueprint_json(bp)
    again = env.pipe.resume_questions(res.blueprint_id)
    assert again.status == "failed_resume"
    assert "unknown generation policy" in " ".join(again.notes)


def test_policy_version_must_admit_the_blueprints_tier(env):
    from rc_engine.generation_policy import PolicyError, policy_for_blueprint
    with pytest.raises(PolicyError):
        policy_for_blueprint(SimpleNamespace(tier="elite", generation_policy=pf.TEST_VERSION,
                                             blueprint_id="BP_E"))


# ---- plumbing invariants -------------------------------------------------------

def test_missing_version_is_legacy_and_hashes_ignore_policy_fields(env):
    from rc_engine.generation_policy import LEGACY_POLICY, policy_for_blueprint
    from rc_engine.models import Blueprint
    res = env.pipe.generate_one("elite", _seed(7))
    bp, _, _ = _stored(env, res.blueprint_id)
    raw = json.loads(bp.to_json())
    raw.pop("generation_policy")
    raw.pop("question_slots")
    old = Blueprint.from_json(json.dumps(raw))
    assert policy_for_blueprint(old) is LEGACY_POLICY
    assert "generation_policy" not in old.component_ids
    assert "question_slots" not in old.component_ids
    before = (old.combo_hash, old.pair_hashes)
    old.generation_policy, old.question_slots = pf.TEST_VERSION, [{"type": "thesis"}]
    assert (old.combo_hash, old.pair_hashes) == before


def test_legacy_accessors_return_the_shared_objects_themselves():
    from rc_engine import config, voice_plan
    from rc_engine.generation_policy import LEGACY_POLICY as L
    from rc_engine.registry import ComponentRegistry
    reg = ComponentRegistry()
    assert L.move_vocabulary() is config.RHETORICAL_MOVES
    assert L.move_groups() is config.MOVE_GROUPS
    assert L.exam_move_shares() is config.EXAM_MOVE_SHARES
    assert L.argument_schemas() is config.ARGUMENT_SCHEMAS
    assert L.exam_derived_shapes() is config.EXAM_DERIVED_SHAPES
    assert L.schema_forms() is voice_plan.SCHEMA_FORMS
    assert L.closing_registers_by_beat() is voice_plan.CLOSING_REGISTERS_BY_BEAT
    assert L.stem_forms(reg) is reg.stem_forms
    assert L.slot_type_definitions(reg) is reg.slot_type_definitions
    w = [1.0, 2.0]
    assert L.adjust_weights("family", ["F01", "F02"], w, reg) is w
    assert L.user_prompt("render", "x") == "x" and L.system_prompt("render", "y") == "y"
    for ctype in reg.libraries:
        # 2026-09-13: production topologies now include QT25/QT26, tagged for
        # cat-pyq-q1; legacy sees the untagged library in its original order.
        untagged = [i for i in reg.ids(ctype) if not reg.get(ctype, i).get("policies")]
        assert L.eligible_ids(reg, ctype) == untagged
        assert L.eligible_ids(reg, ctype, "hard") == untagged
        if not reg.has_policy_tags(ctype):
            assert L.eligible_ids(reg, ctype) is not None and untagged == reg.ids(ctype)


def test_validation_names_policy_misconfiguration(tmp_path, monkeypatch):
    from rc_engine import config
    from rc_engine.generation_policy import (GenerationPolicy, _ro, known_argument_schema_ids,
                                             temporary_policy, validation_errors)
    from rc_engine.registry import ComponentRegistry, RegistryError
    reg = ComponentRegistry()

    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "never-registered", "hard": "", "elite": ""})
    assert any("unknown policy 'never-registered'" in e for e in validation_errors(reg))
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": "", "hard": "", "elite": ""})
    assert validation_errors(reg) == []

    bad = GenerationPolicy(
        version="bad-test", tiers=frozenset({"medium", "hard", "elite"}),
        extra_slot_types=_ro({"thin_type": "one stem form only"}),
        extra_stem_forms=_ro({"thin_type": ["only one"], "no_such_type": ["a", "b", "c"]}),
        extra_move_groups=_ro({"middle": ["UNGLOSSED_BEAT"]}),
        extra_argument_schemas=_ro({"S9_TEST": {"description": "test"}}))
    with temporary_policy(bad):
        errors = " | ".join(validation_errors(reg))
        assert "must not admit elite" in errors
        assert "'thin_type' needs >=" in errors
        assert "unknown slot type 'no_such_type'" in errors
        assert "'UNGLOSSED_BEAT' with no gloss" in errors
        assert "S9_TEST" in known_argument_schema_ids()
    assert "S9_TEST" not in known_argument_schema_ids()

    # Tagged components need their policy registered before the libraries load.
    d = pf.build_components(str(tmp_path / "components"))
    with pytest.raises(RegistryError, match="tagged for unknown policy"):
        ComponentRegistry(d)
    # A tagged topology's extra slot type is only valid for the policy adding it.
    from rc_engine.generation_policy import temporary_policy as tp
    with tp(pf.make_policy()):
        ComponentRegistry(d)
