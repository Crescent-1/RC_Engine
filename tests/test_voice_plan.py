"""Voice planning and review regressions. All clients and databases are local mocks."""

import json
import random

import pytest

from rc_engine import config
from rc_engine.composer import BlueprintComposer, CompositionExhausted
from rc_engine.constraints import CompatibilityRules
from rc_engine.history import HistoryStore
from rc_engine.llm import CostLedger, MockLLMClient
from rc_engine.models import Blueprint, RealizedStructure, SeedEssay
from rc_engine.registry import ComponentRegistry
from rc_engine.renderer import PassageRenderer
from rc_engine.similarity_screen import select_references, screen_batch
from rc_engine.voice_plan import SCHEMA_FORMS, plan_violations, review_reasons


@pytest.fixture
def setup(tmp_path):
    registry = ComponentRegistry()
    history = HistoryStore(str(tmp_path / "voice.db"))
    composer = BlueprintComposer(registry, history, CompatibilityRules(registry),
                                 MockLLMClient())
    composer.rng = random.Random(104)
    yield registry, history, composer
    history.close()


def compose(composer, tier="hard", shape="TS09"):
    return composer.compose(tier, SeedEssay(domain_hint="history of craft"),
                            CostLedger(10), topic_shape_id=shape)


@pytest.mark.parametrize("tier", ["medium", "hard", "elite"])
def test_every_source_shape_has_a_compatible_plan(setup, tier):
    registry, history, composer = setup
    for shape in registry.ids("topic_shape"):
        bp = compose(composer, tier, shape)
        assert bp.voice_plan_version
        assert plan_violations(bp, registry) == []
        assert "STACCATO_TRIAD" not in bp.move_plan
        assert set(SCHEMA_FORMS[bp.argument_schema_id]["required_middle"]) <= set(bp.move_plan[1:-1])
        assert sum(p.len_words[0] for p in bp.movement) == round(
            (config.PASSAGE_WORD_MIN + config.PASSAGE_WORD_MAX) / 2)


def test_contracts_share_schema_operations_and_content(setup):
    registry, history, composer = setup
    bp = compose(composer)
    prompt = composer._refine_user_prompt(
        bp, registry.get("family", bp.family_id),
        registry.get("revelation", bp.revelation_id),
        registry.get("ending", bp.ending_id),
        registry.get("distractor_profile", bp.distractor_profile_id), SeedEssay())
    directive = config.ARGUMENT_SCHEMAS[bp.argument_schema_id]["directive"]
    assert directive in prompt
    assert all(move in prompt for move in bp.move_plan)
    bp.tension_system = {"content_frame": "The successive repairs of a water clock."}
    rendered = PassageRenderer(registry, MockLLMClient())._contract(bp, [])
    assert directive in rendered
    assert bp.tension_system["content_frame"] in rendered
    assert "PRIMARY TENSION:" not in rendered
    assert all(move in rendered for move in bp.move_plan)


def test_incompatible_plan_is_rejected_before_refinement(setup, monkeypatch):
    registry, history, composer = setup
    monkeypatch.setattr(composer, "_sample_move_plan_checked",
                        lambda *a, **kw: ["ABSTRACT_CLAIM", "STACCATO_TRIAD", "CONCRETE_RETURN"])
    calls = []
    monkeypatch.setattr(composer, "_refine_with_retry", lambda *a: calls.append(a))
    with pytest.raises(CompositionExhausted, match="incompatible voice plan"):
        compose(composer)
    assert not calls


def test_old_blueprint_remains_loadable(setup):
    _, _, composer = setup
    raw = json.loads(compose(composer).to_json())
    raw.pop("voice_plan_version")
    assert Blueprint.from_json(json.dumps(raw)).voice_plan_version == ""


def test_schema_and_body_review_are_independent_of_high_f1(setup):
    _, _, composer = setup
    bp = compose(composer)
    read = RealizedStructure(f1=1.0, rhetorical_moves=bp.move_plan,
                             argument_schema="S8_REMEDIES_WEIGHED", middle_beats_ok=False,
                             middle_retention=0.4, gratuitous_moves=["EASY_READING_DEMOLISHED"])
    reasons = review_reasons(bp, read)
    assert any("schema planned" in r for r in reasons)
    assert any("body plan retention" in r for r in reasons)
    read.argument_schema_secondary = bp.argument_schema_id
    read.middle_beats_ok = True
    assert review_reasons(bp, read) == []
    assert any("not measured" in r for r in review_reasons(bp, RealizedStructure(f1=1)))


def insert_set(history, rc_id, bp, realized, status="approved"):
    history.record_blueprint(bp, "composed")
    history.record_rendered_passage(bp.blueprint_id, bp.tier, "Passage text.",
        realized.to_json(), realized.f1, None, None, None, 0)
    history.insert_rc_set(rc_id, bp.tier, "Passage:\nPassage text.\n\nQ1. Question?",
        status, {}, None, 5, bp.blueprint_id, realized.f1, 0, 0,
        None, None, None, None, 1)
    history.mark_shipped(bp, rc_id)


def test_feedback_counts_realized_schemas_and_respects_client_scope(setup):
    _, history, composer = setup
    bp = compose(composer)
    measured = "S1_INSTRUMENT_BLIND"
    assert bp.argument_schema_id != measured
    insert_set(history, "one", bp, RealizedStructure(argument_schema=measured))
    assert history.argument_schema_counts(12) == {measured: 1}
    bp2 = compose(composer)
    insert_set(history, "two", bp2, RealizedStructure())
    assert history.argument_schema_counts(1) == {}
    assert history.argument_schema_counts(12) == {measured: 1}
    history.add_client("BB")
    history.client_id = "BB"
    assert history.argument_schema_counts(12) == {}
    assert history.argument_schema_counts(12, scope="others") == {measured: 1}
    assert history.voice_reference_pool() == []


@pytest.mark.parametrize("status,expected", [("approved", "needs_review"),
                                             ("solver_dispute", "solver_dispute")])
def test_persisted_voice_review_routes_without_overriding_disputes(setup, status, expected):
    _, history, composer = setup
    bp = compose(composer)
    insert_set(history, "one", bp, RealizedStructure(f1=1), status)
    reasons = ["schema was not measured"]
    history.record_voice_review("one", reasons)
    row = history.conn.execute("SELECT status, voice_review_status, voice_review_json FROM rc_sets").fetchone()
    assert row[:2] == (expected, "review")
    assert json.loads(row[2]) == reasons
    history.add_client("BB")
    history.client_id = "BB"
    history.record_voice_review("one", [])
    assert history.conn.execute("SELECT voice_review_status FROM rc_sets").fetchone()[0] == "review"


def test_reference_selection_reaches_old_neighbours_and_batch_siblings():
    def row(rc_id, moves):
        return dict(rc_id=rc_id, passage=rc_id, moves=moves, schema="")
    candidate = row("new", ["ABSTRACT_CLAIM", "MECHANISM_EXPLAINED", "CONCRETE_RETURN"])
    sibling = row("sibling", [])
    pool = [candidate, sibling] + [row(f"recent{i}", []) for i in range(20)]
    pool.append(row("old-match", candidate["moves"]))
    refs = select_references(candidate, pool, {"new", "sibling"}, 10)
    ids = [r[0] for r in refs]
    assert {"sibling", "old-match", "recent0"} <= set(ids)
    assert "new" not in ids
    assert len(ids) == len(set(ids)) == 10
    assert refs == select_references(candidate, pool, {"sibling", "new"}, 10)


def test_first_batch_screens_siblings_from_a_fixed_snapshot(setup, monkeypatch):
    _, history, composer = setup
    insert_set(history, "one", compose(composer), RealizedStructure())
    insert_set(history, "two", compose(composer), RealizedStructure())
    seen = {}
    def screen(rc_id, passage, refs, ledger):
        seen[rc_id] = [r[0] for r in refs]
        return dict(verdict="green", nearest=None, shared=[], reason="distinct")
    monkeypatch.setattr("rc_engine.similarity_screen.screen_passage", screen)
    results, spent = screen_batch(history, ["two", "one"])
    assert seen == {"two": ["one"], "one": ["two"]}
    assert results["one"]["references"] == ["two"]
    assert spent == 0


def test_health_separates_new_plans_and_missing_measurements(setup):
    _, history, composer = setup
    bp = compose(composer)
    read = RealizedStructure(argument_schema=bp.argument_schema_id,
                             rhetorical_moves=bp.move_plan, middle_beats_ok=False)
    insert_set(history, "new", bp, read)
    legacy = compose(composer)
    legacy.voice_plan_version = ""
    insert_set(history, "old", legacy, RealizedStructure())
    health = history.voice_health(10)
    assert health[bp.voice_plan_version]['primary_matches'] == 1
    assert health[bp.voice_plan_version]['middle_matches'] == 0
    assert health['legacy']['schema_planned'] == 1
    assert health['legacy']['schema_measured'] == 0
    history.add_client('BB')
    history.client_id = 'BB'
    assert history.voice_health(10) == {}


@pytest.mark.parametrize("deviation", [False, True])
def test_shipping_cannot_hide_voice_failure_behind_passing_scores(setup, monkeypatch, deviation):
    from rc_engine.models import NoveltyReport
    from rc_engine.pipeline import RCPipeline
    registry, history, composer = setup
    bp = compose(composer)
    history.record_blueprint(bp, 'composed')
    read = RealizedStructure(f1=1, argument_schema=bp.argument_schema_id,
                             rhetorical_moves=bp.move_plan, middle_beats_ok=not deviation)
    pipe = RCPipeline(history, MockLLMClient(), embed=False)
    monkeypatch.setattr(pipe.novelty, 'score', lambda *a, **kw: NoveltyReport('pass'))
    monkeypatch.setattr('rc_engine.pipeline.blind_solve', lambda *a: {'disputes': []})
    monkeypatch.setattr('rc_engine.pipeline.judge_rc', lambda *a, **kw:
                        {'average': 10, 'verdict': 'approve', 'scores': {}})
    monkeypatch.setattr('rc_engine.pipeline.length_bias_report', lambda *a:
        dict(biased=False, warnings=[], correct_longest_count=0,
             has_thesis_question=False, thesis_correct_longest=False))
    result = pipe._questions_and_ship(bp, ' '.join(['word'] * 525), read,
        CostLedger(10), [], SeedEssay(), {}, 'test-ship')
    assert result.status == ('needs_review' if deviation else 'approved')
    assert history.conn.execute('SELECT voice_review_status FROM rc_sets').fetchone()[0] == (
        'review' if deviation else 'clear')
    assert any('voice review:' in n for n in result.notes) == deviation
