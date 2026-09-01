"""The 500-550 word house standard: plan arithmetic and the accept band.

Passage length is no longer a tier parameter — every tier is gated on the
range config.PASSAGE_WORD_MIN..PASSAGE_WORD_MAX (500-550). Two things have to
hold for that to be enforceable:

  1. the per-paragraph plan the renderer is handed sums to EXACTLY the midpoint
     of that range (it used to truncate every band downward, so the plan never
     added up to the total stated in the same prompt);
  2. the accept band is closed at both ends and shared by the engine and
     `cli vet` (they used to disagree: +/-60 vs +/-40).

Run: python -m pytest tests/test_passage_length.py -q
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config
from rc_engine.composer import BlueprintComposer
from rc_engine.question_engine import passage_word_check, passage_word_report
from rc_engine.registry import ComponentRegistry

TIERS = ("medium", "hard", "elite")


@pytest.fixture(scope="module")
def registry():
    return ComponentRegistry()


@pytest.fixture(scope="module")
def composer(registry):
    """Only the two pure structure methods are exercised, so the LLM, history
    and rules collaborators are deliberately not constructed."""
    c = BlueprintComposer.__new__(BlueprintComposer)
    c.registry = registry
    c.rng = random.Random(0)
    return c


def _words(n: int) -> str:
    return " ".join(["word"] * n)


# --------------------------------------------------------------- plan sums


def test_every_tier_targets_the_same_length():
    for tier in TIERS:
        assert config.TIER_PARAMS[tier]["passage_words"] == (
            config.PASSAGE_WORD_MIN, config.PASSAGE_WORD_MAX)


def test_range_is_sane():
    assert config.PASSAGE_WORD_MIN < config.PASSAGE_WORD_MAX


def test_scaled_plan_sums_to_exactly_the_target(composer, registry):
    """Across every rhythm x family x tier the composer can produce. The plan
    aims at the midpoint of the accepted range, not either edge."""
    target = round((config.PASSAGE_WORD_MIN + config.PASSAGE_WORD_MAX) / 2)
    checked = 0
    for rid in registry.ids("rhythm"):
        rhythm = registry.get("rhythm", rid)
        for fid in registry.ids("family"):
            family = registry.get("family", fid)
            for tier in TIERS:
                plans = composer._scale_lengths(
                    composer._build_movement(family, rhythm), tier)
                total = sum(p.len_words[0] for p in plans)
                assert total == target, (
                    f"{rid}/{fid}/{tier}: plan sums to {total}, not {target}")
                assert all(p.len_words[0] == p.len_words[1] for p in plans), (
                    f"{rid}/{fid}/{tier}: expected a single target per paragraph")
                assert all(p.len_words[0] > 0 for p in plans), (
                    f"{rid}/{fid}/{tier}: non-positive paragraph target")
                checked += 1
    assert checked > 100, "component libraries look empty — test proved nothing"


def test_single_target_renders_as_one_number(composer, registry):
    """words_label is what the render and compliance prompts print."""
    family = registry.get("family", next(iter(registry.ids("family"))))
    rhythm = registry.get("rhythm", next(iter(registry.ids("rhythm"))))
    plans = composer._scale_lengths(composer._build_movement(family, rhythm), "hard")
    for p in plans:
        assert "-" not in p.words_label, "a degenerate band must print one number"
        assert p.words_label == str(p.len_words[0])


# --------------------------------------------------------------- accept band


@pytest.mark.parametrize("n, expected", [
    (config.PASSAGE_WORD_MIN - 1, False),
    (config.PASSAGE_WORD_MIN, True),
    (round((config.PASSAGE_WORD_MIN + config.PASSAGE_WORD_MAX) / 2), True),
    (config.PASSAGE_WORD_MAX, True),
    (config.PASSAGE_WORD_MAX + 1, False),
])
def test_accept_band_is_closed_at_both_ends(n, expected):
    report = passage_word_report(_words(n))
    assert report["words"] == n
    assert report["in_band"] is expected
    assert bool(report["warnings"]) is (not expected)


def test_band_is_tier_independent():
    """The same passage must pass or fail identically whatever tier asked for
    it — that is the whole point of one house standard."""
    edge = _words(config.PASSAGE_WORD_MAX + 1)
    reports = {t: passage_word_report(edge) for t in TIERS}
    assert {r["in_band"] for r in reports.values()} == {False}


def test_check_wrapper_matches_report():
    for n in (400, 499, 500, 525, 550, 551, 700):
        assert passage_word_check(_words(n)) == passage_word_report(_words(n))["warnings"]
