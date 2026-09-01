"""The commitment-curve novelty channel.

On 2026-08-10 the corpus crossed CURVE_CAP_MIN_CORPUS (75) and the curve gate
went live for the first time. It immediately rejected three consecutive paid
hard-tier renders. The channel was scored with Pearson correlation, which is
invariant to location and scale: it asks "do these two curves rise together",
never "are they at the same commitment levels". Because the engine deliberately
builds toward a late thesis, almost every passage produces a monotonically
rising curve — so Pearson flagged the corpus's most common and most desirable
shape. Leave-one-out over the real curves: 29% of renders hit the unconditional
reject and 90% hit the soft cap.

The fix is fingerprints.curve_similarity — mean absolute deviation over a
resampled grid, which keeps the levels. These tests pin both halves: the false
positive stays out, and genuine duplicate arcs are still caught.

Run: python -m pytest tests/test_novelty_curve.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config
from rc_engine.fingerprints import CURVE_GRID, curve_similarity, pearson

CAP = config.NOVELTY_CAPS["curve_similarity"]
EXTREME = config.NOVELTY_SUPPORT_CAPS["curve_similarity_extreme"]

# The exact pair that blocked the 2026-08-10 hard run. One author opens hostile
# (-0.8) and is won over; the other opens mildly warm (0.3) and warms further.
# Opposite passages — Pearson scored them a perfect 1.000.
HOSTILE_TO_CONVINCED = [-0.8, 0.4, 0.7, 1.0]
WARM_TO_WARMER = [0.3, 0.7, 0.8, 0.9]


def test_opposite_arcs_are_not_duplicates():
    """The regression test for the 2026-08-10 hard-tier rejections."""
    assert pearson(HOSTILE_TO_CONVINCED, WARM_TO_WARMER) > 0.99, (
        "precondition: this is the pair Pearson called identical")
    sim = curve_similarity(HOSTILE_TO_CONVINCED, WARM_TO_WARMER)
    assert sim <= CAP, (
        f"opposite commitment arcs scored {sim:.3f} vs cap {CAP} — the level-aware "
        f"metric has regressed toward Pearson's shape-only behaviour")


def test_identical_curve_is_a_duplicate():
    assert curve_similarity(WARM_TO_WARMER, WARM_TO_WARMER) == pytest.approx(1.0)
    assert curve_similarity(WARM_TO_WARMER, WARM_TO_WARMER) >= EXTREME


def test_near_duplicate_still_breaches():
    """A real duplicate arc must still be caught — the gate has to keep working."""
    nudged = [v + d for v, d in zip(WARM_TO_WARMER, (0.05, -0.05, 0.05, 0.0))]
    sim = curve_similarity(WARM_TO_WARMER, nudged)
    assert sim >= EXTREME, f"near-duplicate scored {sim:.3f}, below extreme {EXTREME}"


def test_a_rising_curve_is_not_inherently_suspicious():
    """Every tier builds commitment toward a late thesis, so 'rises monotonically'
    describes most valid passages and must not by itself constitute a match."""
    rising_low = [-0.9, -0.4, 0.0, 0.3]
    rising_high = [0.4, 0.6, 0.8, 0.95]
    assert pearson(rising_low, rising_high) > 0.95, "precondition: both rise"
    assert curve_similarity(rising_low, rising_high) <= CAP


def test_resampling_compares_endings():
    """pearson() truncated to the shorter curve, silently dropping the closing
    paragraph. Curves of different length must still be compared end to end."""
    four = [0.0, 0.3, 0.6, 0.9]
    five_same_start_opposite_end = [0.0, 0.2, 0.4, 0.6, -0.9]
    assert len(curve_similarity.__doc__ or "") > 0
    sim = curve_similarity(four, five_same_start_opposite_end)
    assert sim <= CAP, (
        f"curves that agree early and diverge sharply at the close scored {sim:.3f}; "
        f"the ending is being dropped rather than resampled")


def test_degenerate_curves_do_not_match():
    assert curve_similarity([], [0.1, 0.2, 0.3]) == 0.0
    assert curve_similarity([0.1, 0.2, 0.3], []) == 0.0


def test_grid_resampling_preserves_endpoints():
    from rc_engine.fingerprints import _resample_curve
    for curve in ([0.0, 0.5, 1.0], [-1.0, 0.0, 0.5, 1.0], [0.2] * 5):
        out = _resample_curve(curve)
        assert len(out) == CURVE_GRID
        assert out[0] == pytest.approx(curve[0])
        assert out[-1] == pytest.approx(curve[-1])


def test_caps_are_ordered():
    assert 0.0 < CAP < EXTREME <= 1.0
