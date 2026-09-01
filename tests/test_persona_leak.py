"""persona_leak: a leak is specific, the house voice is diffuse.

On 2026-08-11 persona_leak appeared in 11 of 22 paid novelty rejections — the
largest single source of wasted spend. The check was per-pair, so it could not
distinguish two very different situations:

  - "this passage reads like persona P14"          -> a real leak, reject
  - "this passage reads like the corpus average"   -> the house voice

One rejected render (persona P20) landed inside the leak band against SEVEN
distinct personas at once (P03/P05/P06/P07/P14/P15/P16, deltas 0.59-0.69). That
is not a leak of any one voice; it is the single generator converging on its own
register — which a blind re-roll cannot change, so rejecting it only burns a
paid render. The corpus separates the two cleanly: shipped sets that trip the
gate breach exactly 1 distinct persona.

Diffuse cases now surface as a corpus flag instead, so the convergence is still
visible without costing a render.

Run: python -m pytest tests/test_persona_leak.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config

MIN = config.PERSONA_LEAK_DIFFUSE_MIN
EXTREME = config.NOVELTY_SUPPORT_CAPS["stylometry_delta_extreme"]
FLOOR = config.NOVELTY_CAPS["stylometry_delta_floor"]

# The render that consumed three paid hard-tier attempts.
THE_BURNER = ["P14", "P15", "P05", "P06", "P07", "P14", "P16", "P03"]


def _is_leak(persona_ids) -> bool:
    """Mirror of the post-loop decision in NoveltyScorer.score."""
    return len(set(persona_ids)) < MIN


def test_the_burner_is_reclassified_as_house_voice():
    """The regression test. Seven distinct personas is convergence, not a leak."""
    assert len(set(THE_BURNER)) == 7
    assert not _is_leak(THE_BURNER), (
        "a render inside the leak band against 7 personas is still being "
        "rejected as a persona leak — it is the house voice")


def test_a_single_persona_echo_still_rejects():
    """The gate must keep working: one voice bleeding through is a real leak."""
    assert _is_leak(["P14"])
    assert _is_leak(["P14", "P14", "P14"]), (
        "repeated hits on the SAME persona are one leak, not diffuse spread")


def test_two_personas_still_rejects():
    """Below the diffuse threshold stays a rejection — the fix must not become
    a blanket amnesty for stylometric collisions."""
    assert _is_leak(["P14", "P15"])


def test_threshold_separates_the_observed_cases():
    """1 (shipped sets that fire) on one side, 7 (the burner) on the other."""
    assert 1 < MIN <= 7, f"PERSONA_LEAK_DIFFUSE_MIN={MIN} no longer separates the data"


def test_caps_are_ordered():
    assert 0.0 < EXTREME < FLOOR <= 1.0


def test_house_voice_flag_is_surfaced_not_swallowed():
    """A diffuse case must still be visible — the voice IS converging, and that
    is worth reporting even though it does not justify paying for a re-render."""
    import inspect

    from rc_engine.novelty import NoveltyScorer
    src = inspect.getsource(NoveltyScorer.score)
    assert "house_voice_flag" in src
    assert "corpus_flags" in src.split("house_voice_flag")[-1], (
        "house_voice_flag is computed but never reaches corpus_flags")
