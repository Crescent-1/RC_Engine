"""The adaptive-thinking experiment hook: thinking and ceilings must pair up.

Thinking bills at output rates AND counts against max_tokens. So a stage with
thinking switched on but its normal ceiling does not "cost a bit more" — it
spends the budget reasoning and then truncates mid-output.

That happened on 2026-08-11. The ceilings were narrowed to `questions` while
llm.py still keyed the thinking flag on the MODEL — and render and questions
both run on OPUS. Render therefore ran adaptive thinking against its 1600-token
ceiling, truncated twice, and returned failed_render for $0.17.

These tests pin the invariant so the flag and the ceilings cannot drift apart
again, and confirm the whole hook stays inert unless explicitly enabled.

Run: python -m pytest tests/test_thinking_experiment.py -q
"""

import contextlib
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config


@contextlib.contextmanager
def reloaded_config(**env):
    """Re-import config under a temporary environment, then restore it.

    Must be a context manager, not a function returning the module: reload()
    mutates the module object in place, so a `return reload(); finally reload()`
    helper hands back an object the finally block has already reset to defaults.
    """
    old = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield importlib.reload(config)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(config)


def test_every_thinking_stage_has_a_raised_ceiling():
    """The regression test. A thinking stage without headroom truncates."""
    assert set(config.THINKING_STAGES) == set(config._THINKING_CEILINGS), (
        "thinking stages and raised ceilings have drifted apart — the stage "
        "without a ceiling will truncate, not merely cost more")


def test_raised_ceilings_actually_exceed_the_normal_ones():
    with reloaded_config(RC_ENGINE_OPUS_THINKING="1") as cfg:
        for stage in cfg.THINKING_STAGES:
            for tier in ("medium", "hard", "elite"):
                _model, raised = cfg.STAGE_CONFIG[stage][tier]
                assert raised == cfg._THINKING_CEILINGS[stage]
                assert raised > 5000, (
                    f"{stage}/{tier} ceiling {raised} leaves no room for a "
                    f"reasoning pass on top of the payload")


def test_non_thinking_stages_keep_their_normal_ceiling():
    """Only the named stages change; render in particular must stay put."""
    base = {s: config.STAGE_CONFIG[s]["hard"][1]
            for s in ("refine", "render", "compliance", "solver", "judge")}
    with reloaded_config(RC_ENGINE_OPUS_THINKING="1") as cfg:
        for stage, ceiling in base.items():
            assert cfg.STAGE_CONFIG[stage]["hard"][1] == ceiling, (
                f"{stage} ceiling moved but it is not a thinking stage")


def test_hook_is_off_by_default():
    """Production must be untouched — this is a probe, not a setting."""
    with reloaded_config(RC_ENGINE_OPUS_THINKING=None,
                         RC_ENGINE_TIER_BUDGET_USD=None) as cfg:
        assert cfg.OPUS_THINKING is False
        assert cfg.STAGE_CONFIG["questions"]["hard"][1] == 5600
        assert cfg.TIER_BUDGET_USD == {"medium": 0.34, "hard": 0.36, "elite": 0.42}


def test_budget_override_applies_to_every_tier():
    with reloaded_config(RC_ENGINE_TIER_BUDGET_USD="2.00") as cfg:
        assert cfg.TIER_BUDGET_USD == {"medium": 2.0, "hard": 2.0, "elite": 2.0}


def test_opus_model_override():
    with reloaded_config(RC_ENGINE_OPUS_MODEL="claude-opus-5") as cfg:
        assert cfg.OPUS == "claude-opus-5"
        assert cfg.OPUS in cfg.MODEL_RATES, "override must keep a priced model"
        assert cfg.STAGE_CONFIG["questions"]["hard"][0] == "claude-opus-5"


def test_default_pin_is_priced():
    assert config.OPUS in config.MODEL_RATES


def test_no_stage_ceiling_exceeds_the_non_streaming_limit():
    """The engine calls messages.create() non-streaming. The SDK raises
    ValueError before sending if max_tokens implies a >10-minute response, so a
    too-high ceiling is not "slower", it is a hard failure that loses the run.
    Checked with the hook ON, since that is where the raised ceilings live."""
    with reloaded_config(RC_ENGINE_OPUS_THINKING="1") as cfg:
        for stage, tiers in cfg.STAGE_CONFIG.items():
            for tier, (_model, ceiling) in tiers.items():
                assert ceiling <= cfg.MAX_NONSTREAMING_TOKENS, (
                    f"{stage}/{tier} ceiling {ceiling} exceeds the "
                    f"non-streaming limit {cfg.MAX_NONSTREAMING_TOKENS} — the "
                    f"SDK will reject this call before sending")


def test_sdk_actually_accepts_our_highest_ceiling():
    """Pin the bound against the installed SDK rather than a remembered number."""
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="dummy")
    with reloaded_config(RC_ENGINE_OPUS_THINKING="1") as cfg:
        highest = max(c for tiers in cfg.STAGE_CONFIG.values()
                      for _m, c in tiers.values())
        client._calculate_nonstreaming_timeout(highest, None)  # raises if too high
