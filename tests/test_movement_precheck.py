"""The movement precheck: what a collision costs, and how far back it looks.

On 2026-08-10 every hard-tier attempt died at the movement precheck while 30 of
31 hard-eligible families still had unused movement strings. Two causes, both
fixed here:

1. A collision on one (family, rhythm) pair banned the ENTIRE family. Rhythm
   only pads a family's function sequence, so a family yields 3-5 distinct
   movement strings; banning it over one collision discarded the rest. Every
   family that run barred still had 3-4 free.

2. The precheck scored candidates against the whole corpus forever, while the
   composer deliberately recycles a family after EXCLUSION_WINDOWS["family"]
   sets. A recycled family necessarily reproduces one of its movement strings,
   so the precheck made the composer's own policy unreachable — 31 shipped sets
   had blocked ~87% of the library's movement space.

Run: python -m pytest tests/test_movement_precheck.py -q
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config
from rc_engine.composer import BlueprintComposer
from rc_engine.constraints import CompatibilityRules
from rc_engine.registry import ComponentRegistry


@pytest.fixture(scope="module")
def composer():
    reg = ComponentRegistry()
    c = BlueprintComposer.__new__(BlueprintComposer)
    c.registry = reg
    c.rules = CompatibilityRules(reg)
    c.rng = random.Random(0)
    return c


@pytest.fixture(scope="module")
def families(composer):
    return list(composer.registry.ids("family"))


def _reaches_multiple(composer, fid):
    opts, padded = composer.family_movement_options(fid)
    return len(opts) > 1 or padded


def test_four_paragraph_families_yield_several_movement_strings(composer, families):
    """The premise of fix 1: if a family had exactly one movement string,
    banning the family on a collision would cost nothing.

    Scoped to 4-paragraph families as of 2026-08-22. Rhythm pads a family's
    function sequence to reach the rhythm's own length, so a 4-beat family
    reaches 3-5 movement strings — but the arc-shape families added that day
    are 5 and 6 beats and are already at or past every rhythm's length, so they
    have exactly one string each and nothing to pad. That is deliberate: their
    whole purpose is one fixed distinctive arc (six witnesses, three-paragraph
    proof), which is precisely what rhythm padding would dissolve."""
    four = [f for f in families
            if len(composer.registry.get("family", f)["movement"]) == 4]
    multi = [f for f in four if _reaches_multiple(composer, f)]
    assert len(multi) >= len(four) - 2, (
        "nearly every 4-paragraph family should reach multiple movement "
        "strings; if that stops being true, the family-vs-movement ban "
        "distinction is moot")


def test_single_string_families_are_banned_only_when_exhausted(composer, families):
    """A family with exactly one movement string IS exhausted the moment that
    string is banned — the escalation must fire immediately for it, and must
    not fire for a family that still has alternatives."""
    single = [f for f in families if not _reaches_multiple(composer, f)]
    if single:
        fid = single[0]
        only = composer.family_movement_options(fid)[0]
        assert composer.family_movement_exhausted(fid, set(only))
    multi = [f for f in families if _reaches_multiple(composer, f)]
    fid = multi[0]
    one = set(list(composer.family_movement_options(fid)[0])[:1])
    assert not composer.family_movement_exhausted(fid, one)


def test_options_are_deterministic(composer, families):
    """_build_movement pads with RANDOM fillers, so an enumeration that walked
    every rhythm returned a different set each call and made the exhaustion
    check unreliable. Only the non-padded rhythms may be enumerated."""
    for fid in families[:8]:
        a = composer.family_movement_options(fid)
        b = composer.family_movement_options(fid)
        assert a == b, f"{fid}: movement options are not reproducible"


def test_one_collision_does_not_exhaust_a_family(composer, families):
    """The regression test for fix 1. Banning a single movement string must not
    mark the family exhausted while alternatives remain."""
    for fid in families:
        fixed, can_randomize = composer.family_movement_options(fid)
        if len(fixed) < 2 and not can_randomize:
            continue
        one_banned = {next(iter(fixed))} if fixed else set()
        assert not composer.family_movement_exhausted(fid, one_banned), (
            f"{fid} reported exhausted after banning 1 of {len(fixed)} fixed "
            f"movement strings — a collision is again costing a whole family")


def test_family_is_exhausted_only_when_all_movements_are_banned(composer, families):
    """The gate still has to close: a family with no randomisation escape hatch
    and every fixed string banned genuinely is unusable and must be barred."""
    closed = [f for f in families if not composer.family_movement_options(f)[1]]
    if not closed:
        pytest.skip("every family can pad with random fillers")
    fid = closed[0]
    fixed, _ = composer.family_movement_options(fid)
    assert composer.family_movement_exhausted(fid, fixed)


def test_a_padding_family_is_never_exhausted(composer, families):
    """Random filler padding is an open-ended supply of movement strings, so
    banning every currently-known one must not bar the family."""
    padders = [f for f in families if composer.family_movement_options(f)[1]]
    if not padders:
        pytest.skip("no family pads with fillers")
    fid = padders[0]
    fixed, _ = composer.family_movement_options(fid)
    assert not composer.family_movement_exhausted(fid, fixed | {"ANY|OTHER|STRING"})


def test_empty_ban_set_never_exhausts(composer, families):
    for fid in families[:5]:
        assert not composer.family_movement_exhausted(fid, set())
        assert not composer.family_movement_exhausted(fid, None)


def test_precheck_window_tracks_the_family_exclusion_window():
    """The regression test for fix 2. The composer may reuse a family after
    EXCLUSION_WINDOWS["family"] sets; if the precheck looks back further than
    that it vetoes the composer's own recycling policy."""
    assert config.MOVEMENT_RECENCY_WINDOW == config.EXCLUSION_WINDOWS["family"], (
        "movement precheck window has drifted from the family exclusion window — "
        "a legitimately recycled family will collide by construction")


def test_precheck_window_is_narrower_than_the_fingerprint_window():
    assert config.MOVEMENT_RECENCY_WINDOW < config.FINGERPRINT_WINDOW
