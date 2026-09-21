"""Section 5 structure and rendering releases: cat-pyq-s1 and cat-pyq-s2 (2026-09-13).

Plan acceptance, as tests:
  - every enabled family and beat is reachable in an appropriate tier and
    unreachable in elite;
  - every supported topic shape composes;
  - new neutral plans acquire no invented thesis or obligatory rebuttal;
  - permissions are identical across renderer, compliance and texture_report,
    and no prompt keeps a ban another prompt lifts;
  - category objectives normalise within a category before applying a share;
  - the R01 audit, revelation/schema exclusions, T21/T22 fit, P21-P23 genre
    and pronoun eligibility, and a full mock run under each version.
Elite equality with these releases running is in test_generation_policy.py.
"""
import collections
import copy
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.composer import BlueprintComposer  # noqa: E402
from rc_engine.constraints import CompatibilityRules  # noqa: E402
from rc_engine.generation_policy import LEGACY_POLICY, get_policy  # noqa: E402
from rc_engine.history import HistoryStore  # noqa: E402
from rc_engine.policy_catalog import (CAT_PYQ_Q1, CAT_PYQ_S1, CAT_PYQ_S2,  # noqa: E402
                                      REFUSAL_OBJECTIVE, _category_objective)
from rc_engine.registry import ComponentRegistry, posture_class  # noqa: E402

S1, S2, Q1 = get_policy(CAT_PYQ_S1), get_policy(CAT_PYQ_S2), get_policy(CAT_PYQ_Q1)
NEW_FAMILIES = {"F59": ("medium", "hard"), "F60": ("medium", "hard"),
                "F61": ("hard",), "F62": ("medium", "hard")}
STAGE1_BEATS = ["ENUMERATED_SET", "HYPOTHETICAL_CASE", "PRESCRIPTION_STATED", "FORECAST",
                "SPLIT_VERDICT"]
STAGE2_BEATS = ["TERM_COINED", "IRONY_NOTED", "OBJECTION_FORESTALLED", "THEN_NOW_CONTRAST",
                "REPORTED_POSITION"]
TAGGED = {"family": ["F59", "F60", "F61", "F62"], "revelation": ["R21", "R22", "R23"],
          "rhythm": ["T21", "T22"], "persona": ["P21", "P22", "P23"],
          "topic_shape": ["TS15", "TS16"], "ending": ["E21"]}


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture
def composer(registry, tmp_path):
    history = HistoryStore(str(tmp_path / "compose.db"))
    c = BlueprintComposer(registry, history, CompatibilityRules(registry), llm=None,
                          rng=random.Random(5))
    yield c
    history.close()


# ---- visibility --------------------------------------------------------------------

def test_tagged_components_are_seen_only_by_their_releases(registry):
    for ctype, ids in TAGGED.items():
        for p, visible in ((LEGACY_POLICY, False), (Q1, False), (S1, True), (S2, True)):
            got = set(p.eligible_ids(registry, ctype))
            assert set(ids) <= got if visible else not set(ids) & got, (p.version, ctype)
    for p in (S1, S2):     # structure releases keep the question release's topologies
        assert {"QT25", "QT26"} <= set(p.eligible_ids(registry, "topology"))
    assert "R21" not in LEGACY_POLICY.eligible_ids(registry, "revelation")


def test_vocabulary_is_recognised_before_it_is_plannable():
    vocab1 = S1.move_vocabulary()
    plannable1 = {m for g in S1.move_groups().values() for m in g}
    plannable2 = {m for g in S2.move_groups().values() for m in g}
    assert set(STAGE1_BEATS + STAGE2_BEATS) <= set(vocab1)
    assert set(STAGE1_BEATS) <= plannable1 and not set(STAGE2_BEATS) & plannable1
    assert set(STAGE1_BEATS + STAGE2_BEATS) <= plannable2
    assert "REPORTED_POSITION" in S2.move_groups()["opening"]
    assert not set(STAGE1_BEATS + STAGE2_BEATS) & set(LEGACY_POLICY.move_vocabulary())
    for beat in STAGE1_BEATS + STAGE2_BEATS:
        assert S1.exam_move_shares()[beat] <= 0.10       # conservative planning weights


# ---- reachability ---------------------------------------------------------------------

def _schemas_with_family(policy, fid):
    return [s for s, f in policy.schema_forms().items() if fid in f["family"]]


@pytest.mark.parametrize("policy", [S1, S2], ids=[CAT_PYQ_S1, CAT_PYQ_S2])
def test_every_new_family_is_reachable_in_its_tiers_and_not_elsewhere(composer, registry, policy):
    all_families = set(registry.ids("family"))
    for fid, tiers in NEW_FAMILIES.items():
        schemas = _schemas_with_family(policy, fid)
        assert schemas, fid
        for tier in ("medium", "hard", "elite"):
            p = policy if tier != "elite" else LEGACY_POLICY
            hits = 0
            for schema in schemas:
                if schema not in p.schema_forms():
                    continue
                for n in range(8):
                    composer.rng = random.Random(f"{fid}{tier}{schema}{n}")
                    try:
                        ids = composer.sample_skeleton(tier, ban_families=all_families - {fid},
                                                       argument_schema_id=schema, policy=p)
                    except Exception:                          # noqa: BLE001
                        continue
                    hits += ids["family"] == fid
            assert (hits > 0) == (tier in tiers), (policy.version, fid, tier, hits)


@pytest.mark.parametrize("policy,beats", [(S1, STAGE1_BEATS), (S2, STAGE1_BEATS + STAGE2_BEATS)],
                         ids=[CAT_PYQ_S1, CAT_PYQ_S2])
def test_every_plannable_new_beat_is_reachable(composer, registry, policy, beats):
    seen = collections.Counter()
    families = policy.eligible_ids(registry, "family")
    endings = policy.eligible_ids(registry, "ending")
    for n in range(1500):
        rng = random.Random(n)
        composer.rng = rng
        schema = rng.choice(sorted(policy.schema_forms()))
        forms = policy.schema_forms()[schema]
        fid = rng.choice(sorted(set(families) & set(forms["family"])))
        eid = rng.choice(endings)
        posture = registry.posture_of(fid)
        if not policy.closing_beats(eid, posture, fid):
            continue
        try:
            plan = composer._sample_move_plan(None, "hard", None, schema_id=schema, ending_id=eid,
                                              posture=posture, family_id=fid, policy=policy)
        except Exception:                                      # noqa: BLE001
            continue
        seen.update(set(plan) & set(beats))
    assert set(beats) <= set(seen), sorted(set(beats) - set(seen))


def test_every_supported_topic_shape_composes(composer, registry):
    for policy in (S1, S2):
        for tier in ("medium", "hard"):
            for ts in policy.eligible_ids(registry, "topic_shape"):
                from rc_engine.voice_plan import schema_ids_for_shape
                ok = False
                for schema in schema_ids_for_shape(ts, policy):
                    composer.rng = random.Random(f"{ts}{tier}{schema}")
                    try:
                        composer.sample_skeleton(tier, argument_schema_id=schema, policy=policy)
                        ok = True
                        break
                    except Exception:                          # noqa: BLE001
                        continue
                assert ok, (policy.version, tier, ts)


# ---- closing semantics -----------------------------------------------------------------

def test_new_families_close_only_on_their_beats_with_their_endings(registry):
    for fid in NEW_FAMILIES:
        fam = registry.get("family", fid)
        allowed = [e for e in S1.eligible_ids(registry, "ending")
                   if e not in fam["incompatible_endings"]]
        assert allowed, fid
        for eid in allowed:
            beats = S1.closing_beats(eid, fam["closing_posture"], fid)
            assert beats and beats <= set(S1.family_closing_beats[fid]), (fid, eid, beats)
    for fid in ("F47", "F12", "F58"):
        assert all("SPLIT_VERDICT" not in S1.closing_beats(e, registry.posture_of(fid), fid)
                   for e in registry.ids("ending"))
    assert "PRESCRIPTION_STATED" not in S1.closing_beats("E09", "refusal_suspended", "F19")


def test_scope_ending_joins_only_the_framed_inquiry(composer, registry):
    endings = collections.Counter()
    for n in range(400):
        composer.rng = random.Random(n)
        for tier in ("medium", "hard"):
            try:
                ids = composer.sample_skeleton(tier, policy=S1)
            except Exception:                                  # noqa: BLE001
                continue
            if ids["ending"] == "E21":
                endings[ids["family"]] += 1
    assert set(endings) <= {"F61"}, endings


def test_neutral_exposition_plans_carry_no_thesis_rebuttal_or_open_close(composer, registry):
    fam = registry.get("family", "F60")
    assert fam["closing_posture"] == "exposition_neutral"
    assert posture_class(fam["closing_posture"]) == "exposition"
    forbidden = {"EASY_READING_DEMOLISHED", "TWO_CAMP_SPLIT", "LEVEL_RELOCATION",
                 "BOTHSIDES_REFUSED", "CONCESSION_COSTED"}
    endings = [e for e in S1.eligible_ids(registry, "ending") if e not in fam["incompatible_endings"]]
    for n in range(200):
        composer.rng = random.Random(n)
        eid = endings[n % len(endings)]
        plan = composer._sample_move_plan(None, "medium", None, schema_id="S9_TYPOLOGY_DRAWN",
                                          ending_id=eid, posture="exposition_neutral",
                                          family_id="F60", policy=S1)
        assert not forbidden & set(plan), plan
        assert plan[-1] in {"BOUND_CONTINUATION", "CONCRETE_RETURN"}
        assert "ENUMERATED_SET" in plan[1:-1]
    assert "exposition_neutral" in S1.closing_postures(registry)
    assert "exposition_neutral" not in LEGACY_POLICY.closing_postures(registry)
    assert S1.posture_end_commitment()["exposition_neutral"] == (0.40, 0.90)


# ---- category objectives -----------------------------------------------------------------

def test_category_objective_normalises_within_category_first():
    cats = {"a": "refusal", "b": "refusal", "c": "refusal", "d": "committed", "e": "neutral"}
    for refusals in (["a"], ["a", "b", "c"]):
        ids = refusals + ["d", "e"]
        w = _category_objective(ids, [1.0] * len(ids), cats.get, {"refusal": 0.14})
        total = sum(w)
        share = sum(x for i, x in zip(ids, w) if cats[i] == "refusal") / total
        assert share == pytest.approx(0.14)       # independent of how many refusal families
    # absent category: untouched
    assert _category_objective(["d", "e"], [2.0, 1.0], cats.get, {"refusal": 0.14}) == [2.0, 1.0]
    # untargeted categories keep their relative weight
    w = _category_objective(["a", "d", "e"], [5.0, 3.0, 1.0], cats.get, {"refusal": 0.14})
    assert w[1] / w[2] == pytest.approx(3.0)


def test_refusal_share_of_the_family_draw_is_the_objective(composer, registry):
    for tier in ("medium", "hard"):
        pool = composer._eligible("family", tier, policy=S1)
        weights = [1.0 + (i % 3) for i in range(len(pool))]
        adjusted = S1.adjust_weights("family", pool, weights, registry)
        ref = sum(w for f, w in zip(pool, adjusted)
                  if posture_class(registry.posture_of(f)) == "refusal")
        assert ref / sum(adjusted) == pytest.approx(REFUSAL_OBJECTIVE)


# ---- revelations -------------------------------------------------------------------------

def test_r01_audit_and_early_revelation_compatibility(registry):
    audited = {"F01": {"R23"}, "F04": {"R23"}, "F13": {"R22", "R23"}, "F33": {"R22"}}
    for fid in registry.ids("family"):
        fam = registry.get("family", fid)
        inc = set(fam.get("incompatible_revelations", []))
        if fid in NEW_FAMILIES:
            continue
        if fam.get("withholds_thesis"):
            assert {"R21", "R22", "R23"} <= inc, fid
        elif "R01" in inc:
            assert {"R21", "R22", "R23"} - inc == audited.get(fid, set()), fid


def test_schema_directives_exclude_contradicting_revelations(composer):
    for schema, excluded in S1.revelation_schema_exclusions.items():
        for n in range(40):
            composer.rng = random.Random(n)
            try:
                ids = composer.sample_skeleton("hard", argument_schema_id=schema, policy=S1)
            except Exception:                                  # noqa: BLE001
                continue
            assert ids["revelation"] not in excluded, (schema, ids["revelation"])


# ---- rhythms and personas ----------------------------------------------------------------

def test_new_rhythms_fit_the_word_target_without_concession_padding(composer, registry):
    fam = registry.get("family", "F60")
    for rid in ("T21", "T22"):
        rhythm = registry.get("rhythm", rid)
        for n in range(100):
            composer.rng = random.Random(n)
            plans = composer._scale_lengths(composer._build_movement(fam, rhythm), "hard")
            assert len(plans) == len(rhythm["shape"])
            assert sum(p.len_words[0] for p in plans) == round(
                (config.PASSAGE_WORD_MIN + config.PASSAGE_WORD_MAX) / 2)
            assert min(p.len_words[0] for p in plans) >= 35
            assert "CONCESSION_TRAP" not in [p.function for p in plans]
            assert len(plans) // 1 <= 7


def test_new_personas_declare_genres_and_pronouns(composer, registry):
    pronouns = {"P21": "impersonal", "P22": "first_singular", "P23": "first_singular"}
    for pid, pron in pronouns.items():
        p = registry.get("persona", pid)
        assert p["pronoun_person"] == pron and p["compatible_genres"]
        assert "credential" not in json.dumps(p).lower() or "never for credentials" in p["pronoun_posture"]
    seen = collections.Counter()
    for n in range(300):
        composer.rng = random.Random(n)
        try:
            ids = composer.sample_skeleton("hard", policy=S1, seed_genre="criticism")
        except Exception:                                      # noqa: BLE001
            continue
        seen[ids["persona"]] += 1
    assert seen["P21"] == 0 and seen["P23"] == 0     # neither lists criticism


# ---- permissions ---------------------------------------------------------------------------

def _bp(registry, **kw):
    from rc_engine.models import Blueprint
    base = dict(blueprint_id="BP_perm", tier="hard", schema_version="2.0", family_id="F12",
                persona_id="P01", ending_id="E07", rhythm_id="T01", revelation_id="R02",
                distractor_profile_id="D01", topology_id="QT01", instability=0.5, aperture="x",
                generation_policy=CAT_PYQ_S1, move_plan=["ABSTRACT_CLAIM_OPEN",
                                                         "MECHANISM_EXPLAINED",
                                                         "BOUND_CONTINUATION"])
    base.update(kw)
    return Blueprint(**base)


def test_grants_come_from_the_plan_and_family(registry):
    from rc_engine.passage_permissions import grants_for
    assert grants_for(_bp(registry), registry) == []
    assert grants_for(_bp(registry, move_plan=["ABSTRACT_CLAIM_OPEN", "HYPOTHETICAL_CASE",
                                              "PRESCRIPTION_STATED"]), registry) == [
        "bounded_prescription", "hypothetical_case"]
    assert grants_for(_bp(registry, family_id="F60"), registry) == ["content_enumeration"]
    assert grants_for(_bp(registry, family_id="F61"), registry) == ["scope_setting"]
    assert grants_for(_bp(registry, family_id="F58"), registry) == ["bounded_prescription"]


def test_renderer_compliance_and_texture_share_one_permission_set(registry):
    from rc_engine.compliance import COMPLIANCE_SYSTEM, ComplianceAuditor
    from rc_engine.llm import CostLedger, MockLLMClient
    from rc_engine.models import ParagraphPlan
    from rc_engine.passage_permissions import grants_for, permissions_block
    from rc_engine.renderer import RENDER_SYSTEM, PassageRenderer
    bp = _bp(registry, family_id="F61", move_plan=["ABSTRACT_CLAIM_OPEN", "HYPOTHETICAL_CASE",
                                                   "FORECAST"])
    bp.movement = [ParagraphPlan(i, f"FN{i}", (100, 100), "mixed") for i in range(1, 6)]
    bp.revelation_detail = {"planned_para": 2, "timing": "mid"}
    grants = grants_for(bp, registry)
    block = permissions_block(grants)
    contract = PassageRenderer(registry, None)._contract(bp, [])
    assert block in contract
    system = S1.system_prompt("render", RENDER_SYSTEM)
    assert "No moralizing, no policy prescriptions" not in system
    assert "EXCEPT exactly what the PERMISSIONS block" in system
    assert "reader address (beyond what the PERMISSIONS block grants)" in system
    assert LEGACY_POLICY.system_prompt("render", RENDER_SYSTEM) is RENDER_SYSTEM

    class Spy(MockLLMClient):
        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.seen = (system, user, dict(context or {}))
            return super().call(ledger, stage, model, max_tokens, system, user, context)
    llm = Spy()
    ComplianceAuditor(llm, registry).audit("Para one.\n\nPara two.", bp, CostLedger(5.0))
    sys_prompt, user, ctx = llm.seen
    assert ctx["permissions"] == grants and block in user
    assert '"unpermitted_devices": []' in sys_prompt and "self_signposting" in sys_prompt
    assert '"unpermitted_devices"' not in COMPLIANCE_SYSTEM


def test_auditor_reports_only_devices_the_plan_did_not_grant(registry):
    from rc_engine.compliance import ComplianceAuditor
    from rc_engine.models import ParagraphPlan
    bp = _bp(registry, move_plan=["ABSTRACT_CLAIM_OPEN", "HYPOTHETICAL_CASE",
                                  "BOUND_CONTINUATION"])
    bp.movement = [ParagraphPlan(1, "A", (100, 100), "mixed"), ParagraphPlan(2, "B", (100, 100), "mixed")]
    bp.revelation_detail = {"planned_para": 1}
    auditor = ComplianceAuditor(None, registry)
    data = {"paragraphs": [], "unpermitted_devices": ["hypothetical", "prescription",
                                                     "self_signposting", "made_up"]}
    realized = auditor._score(data, "a\n\nb", bp, [], grants=["hypothetical_case"])
    assert realized.unpermitted_devices == ["prescription", "self_signposting"]
    assert any(d.startswith("remove the prescription") for d in realized.directives)
    legacy = auditor._score(data, "a\n\nb", _bp(registry, generation_policy=""), [])
    assert legacy.unpermitted_devices == []


def test_texture_report_applies_the_same_grants():
    from rc_engine.question_engine import texture_report
    passage = ("Suppose a town kept two ledgers. Imagine a second town too.\n\n"
               "There are three kinds of ledger in this essay.\n\n"
               "Councils should publish both.")
    legacy = texture_report(passage)
    assert legacy == texture_report(passage, None)
    # the legacy scan is the pre-2026-09-13 one: signposts and fabrication only
    assert not any("unpermitted" in w for w in legacy["warnings"]), legacy
    assert legacy["warnings"] == ["signposting: refers to itself as a text - 'in this essay'"]
    none = texture_report(passage, [])["warnings"]
    assert any("hypothetical" in w for w in none) and any("prescription" in w for w in none)
    assert any("enumeration" in w for w in none) and any("text" in w or "scope" in w for w in none)
    granted = texture_report(passage, ["hypothetical_case", "bounded_prescription",
                                       "content_enumeration", "scope_setting"])["warnings"]
    assert sum("hypothetical" in w for w in granted) == 1      # only ONE hypothetical is granted
    assert not any("prescription" in w for w in granted)       # it sits in the final paragraph
    assert not any("enumeration" in w for w in granted)
    early = texture_report("Councils should publish both.\n\nThat is all.",
                           ["bounded_prescription"])["warnings"]
    assert any("before the final paragraph" in w for w in early)


def test_exhausted_topic_shape_falls_back_only_for_policy_plans(registry, tmp_path, monkeypatch):
    """TS15 leads only to S9 and F60; when that skeleton is exhausted a section-5
    plan tries another shape the seed can carry, and a legacy plan still fails."""
    from rc_engine.composer import CompositionExhausted
    from rc_engine.llm import CostLedger, MockLLMClient
    from rc_engine.models import SeedEssay
    history = HistoryStore(str(tmp_path / "fb.db"))
    comp = BlueprintComposer(registry, history, CompatibilityRules(registry), MockLLMClient(),
                             rng=random.Random(3))
    real = comp.sample_skeleton

    def exhaust_s9(tier, **kw):
        if kw.get("argument_schema_id") == "S9_TYPOLOGY_DRAWN":
            raise CompositionExhausted("forced")
        return real(tier, **kw)
    monkeypatch.setattr(comp, "sample_skeleton", exhaust_s9)
    info = {"genre": "analysis", "bipolar_dispute_available": False}
    bp = comp.compose("medium", SeedEssay(), CostLedger(5.0), seed_info=info,
                      topic_shape_id="TS15", policy=S1)
    assert bp.topic_shape_id != "TS15" and bp.argument_schema_id != "S9_TYPOLOGY_DRAWN"

    def exhaust_s8(tier, **kw):     # TS13 leads only to S8 in every policy
        if kw.get("argument_schema_id") == "S8_REMEDIES_WEIGHED":
            raise CompositionExhausted("forced")
        return real(tier, **kw)
    monkeypatch.setattr(comp, "sample_skeleton", exhaust_s8)
    with pytest.raises(CompositionExhausted):
        comp.compose("medium", SeedEssay(), CostLedger(5.0), seed_info=info,
                     topic_shape_id="TS13", policy=LEGACY_POLICY)
    assert comp.compose("medium", SeedEssay(), CostLedger(5.0), seed_info=info,
                        topic_shape_id="TS13", policy=S1).topic_shape_id != "TS13"
    history.close()


# ---- end to end ------------------------------------------------------------------------------

@pytest.mark.parametrize("version", [CAT_PYQ_S1, CAT_PYQ_S2])
def test_mock_batch_under_structure_release(tmp_path, monkeypatch, version):
    from rc_engine.llm import MockLLMClient
    from rc_engine.pipeline import RCPipeline, run_batch
    monkeypatch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                        {"medium": version, "hard": version, "elite": ""})
    history = HistoryStore(str(tmp_path / "s.db"))
    pipe = RCPipeline(history, MockLLMClient(), embed=False, rng=random.Random(21))
    results = run_batch(pipe, {"medium": 4, "hard": 4, "elite": 1}, None, max_usd=10.0)
    shipped = [r for r in results if r.rc_id and r.status in config.SHIPPING_STATUSES]
    assert len(shipped) == 9, [(r.tier, r.status, r.notes[-1:]) for r in results]
    rows = history.conn.execute(
        "SELECT tier, blueprint_json FROM blueprints WHERE status = 'shipped'").fetchall()
    for tier, raw in rows:
        bp = json.loads(raw)
        assert bp["generation_policy"] == ("" if tier == "elite" else version)
        if tier == "elite":
            assert not {bp["family_id"], bp["revelation_id"], bp["rhythm_id"],
                        bp["persona_id"], bp["ending_id"]} & {i for v in TAGGED.values() for i in v}
    history.close()
