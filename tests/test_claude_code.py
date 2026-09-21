"""Claude Code as a generation backend (2026-09-18), with the API behind it:

    rc_engine -> claude code -> (error / usage limit) -> API

The invariants worth pinning are the ones that keep a batch moving: which
stages take the subscription lane, that ANY failure degrades to the fallback
rather than stopping, that a usage limit is sticky so the batch does not pay a
timeout per stage rediscovering the same wall, and that a subscription call
books no API money.

The subprocess itself is injected, so none of this shells out.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.claude_code import (ClaudeCodeClient, ClaudeCodeUnavailable,  # noqa: E402
                                   _argv, _extract, probe)
from rc_engine.llm import CostLedger  # noqa: E402


class _Fallback:
    def __init__(self, reply="from the api"):
        self.calls = []
        self._reply = reply

    def call(self, ledger, stage, model, max_tokens, system, user, context=None):
        self.calls.append(stage)
        return self._reply, False

    def probe(self):
        return "probed"


class _BP:
    def __init__(self, tier="hard"):
        self.tier = tier
        self.blueprint_id = "BP_TEST"


class _Result:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _envelope(text, cost=0.0123):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": text, "total_cost_usd": cost})


def _runner(*results):
    """Stub for subprocess.run; each call returns (or raises) the next item."""
    seen = []
    it = iter(results)

    def run(argv, turn, timeout):
        seen.append({"argv": argv, "turn": turn, "timeout": timeout})
        nxt = next(it)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt
    run.seen = seen
    return run


def _cc(fallback=None, *, runner=None, **kw):
    kw.setdefault("system_mode", "inline")
    # No test may pay the real backoff: the retry ladder is seconds long.
    kw.setdefault("sleep", lambda s: _SLEPT.append(s))
    return ClaudeCodeClient(fallback or _Fallback(), runner=runner or _runner(),
                            binary="claude", **kw)


_SLEPT: list = []


def _ledger():
    return CostLedger(budget_usd=10.0)


def _ctx(tier="hard"):
    return {"blueprint": _BP(tier)}


# ---- routing ---------------------------------------------------------------------

@pytest.mark.parametrize("stage,tier,takes_cc", [
    ("render", "hard", True),
    ("questions", "hard", True),
    ("solver", "hard", True),
    ("refine", "hard", True),
    ("refine", "medium", False),        # the one tier-scoped pin -> openai
    ("compliance", "hard", False),
    ("judge", "hard", False),
    ("seed_classify", "hard", False),
    ("answerability", "hard", False),
])
def test_only_anthropic_bound_stages_take_the_subscription_lane(stage, tier, takes_cc):
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_Result(_envelope("from claude code"))))
    text, _ = cc.call(_ledger(), stage, config.OPUS, 100, "s", "u", context=_ctx(tier))
    assert (text == "from claude code") is takes_cc
    assert (fb.calls == []) is takes_cc


def test_explicit_stage_list_overrides_the_pin_table():
    fb = _Fallback()
    cc = _cc(fb, stages={"questions"},
             runner=_runner(_Result(_envelope("qs"))))
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "qs"


def test_attribute_passthrough():
    assert _cc().probe() == "probed"


# ---- the fallback is the point ---------------------------------------------------

@pytest.mark.parametrize("outcome", [
    _Result("", "boom", returncode=1),                  # non-zero exit
    _Result(""),                                        # empty stdout
    _Result(json.dumps({"is_error": True, "result": "model overloaded"})),
    FileNotFoundError("claude"),                        # not installed
    subprocess.TimeoutExpired("claude", 600),           # hung
    RuntimeError("something unforeseen"),               # anything at all
])
def test_every_failure_degrades_to_the_api(outcome, capsys):
    """An unusable subscription lane must never stop a batch — it degrades,
    loudly, exactly as RoutedClient does for an unusable pin."""
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(outcome))
    text, _ = cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert text == "from the api" and fb.calls == ["render"]
    assert "falling back to the API" in capsys.readouterr().out


@pytest.mark.parametrize("blob", [
    "Claude usage limit reached. Your limit resets at 4pm.",
    "429 Too Many Requests",
    "You are out of credits",
    "rate limit exceeded",
])
def test_usage_limits_are_recognised(blob):
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_Result("", blob, returncode=1)))
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"


@pytest.mark.parametrize("passage", [
    "The quota system rewarded exactly the behaviour it was meant to curb.",
    "Each amnesty resets at midnight, which is the whole difficulty.",
    "Critics urged the board to upgrade to a more honest accounting.",
    "The rate limit on borrowing was never the binding constraint.",
])
def test_a_successful_passage_is_never_read_as_a_usage_limit(passage):
    """REGRESSION (2026-09-18). The first cut scanned stdout+stderr for limit
    wording BEFORE checking the exit code — i.e. it searched the model's own
    output. The first real render tripped it, the sticky flag latched, and the
    batch fell through to the API on a set that had generated fine. Only the
    error channel may be scanned."""
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_Result(_envelope(passage))))
    text, _ = cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert text == passage
    assert fb.calls == [] and cc._limited is False


def test_a_real_limit_on_the_error_channel_still_latches():
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_Result("", "Claude usage limit reached", returncode=1)))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc._limited is True


def test_a_usage_limit_is_sticky():
    """Once the subscription is out, later stages go straight to the API
    instead of paying a subprocess timeout each to rediscover the wall."""
    fb = _Fallback()
    # Only ONE runner result: a second invocation would raise StopIteration.
    cc = _cc(fb, runner=_runner(_Result("", "usage limit reached", returncode=1)))
    for stage in ("render", "questions", "solver"):
        assert cc.call(_ledger(), stage, config.OPUS, 100, "s", "u",
                       context=_ctx())[0] == "from the api"
    assert fb.calls == ["render", "questions", "solver"]


def test_sticky_can_be_turned_off():
    fb = _Fallback()
    cc = _cc(fb, prefer_fallback_after_limit=False,
             runner=_runner(_Result("", "usage limit", returncode=1),
                            _Result(_envelope("recovered"))))
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "recovered"


def test_an_ordinary_failure_is_not_sticky():
    """One flaky call must not push the whole batch onto the API."""
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_Result("", "transient blip", returncode=1),
                                _Result(_envelope("fine now"))))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "fine now"



# ---- transient failures ----------------------------------------------------------
#
# 2026-09-21: 1 live call in 4 lost the OAuth token refresh to the Claude Code
# session the engine was being driven from, and the stage fell straight through
# to the paid API. On this lane that is the one outcome that costs money, so a
# blip the CLI calls temporary is retried before the fallback is reached.

_OAUTH_COLLISION = ("Failed to refresh OAuth token: another Claude Code process "
                    "is refreshing it or exited mid-refresh. This is usually "
                    "transient; retry in a minute")


def _err_envelope(detail):
    """What 2.1.276 actually prints for a failed call: rc=1 and is_error."""
    return _Result(json.dumps({"type": "result", "is_error": True,
                               "result": detail}), returncode=1)


def test_an_oauth_collision_is_retried_instead_of_billed_to_the_api():
    """The measured failure. It must never reach the fallback on its own."""
    fb = _Fallback()
    cc = _cc(fb, runner=_runner(_err_envelope(_OAUTH_COLLISION),
                                _Result(_envelope("rendered after the retry"))))
    text, _ = cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                      context=_ctx())
    assert text == "rendered after the retry"
    assert fb.calls == [], "a transient blip must not become a paid API call"


def test_a_transient_failure_gives_up_after_the_configured_retries(monkeypatch):
    """Bounded, not infinite: the API is still the backstop."""
    monkeypatch.setattr(config, "CLAUDE_CODE_TRANSIENT_RETRIES", 2)
    fb = _Fallback("from the api")
    run = _runner(*[_err_envelope(_OAUTH_COLLISION)] * 3)
    cc = _cc(fb, runner=run)
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert len(run.seen) == 3, "1 attempt + 2 retries"
    assert fb.calls == ["render"]


def test_retries_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CODE_TRANSIENT_RETRIES", 0)
    fb = _Fallback("from the api")
    run = _runner(_err_envelope(_OAUTH_COLLISION))
    cc = _cc(fb, runner=run)
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert len(run.seen) == 1


def test_the_backoff_grows_between_retries(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CODE_TRANSIENT_RETRIES", 2)
    monkeypatch.setattr(config, "CLAUDE_CODE_TRANSIENT_BACKOFF_S", 4)
    slept = []
    cc = _cc(_Fallback(), sleep=slept.append,
             runner=_runner(*[_err_envelope(_OAUTH_COLLISION)] * 3))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert slept == [4, 8]


def test_a_usage_limit_is_never_retried():
    """_LIMIT_RE is tested first, so a real wall latches even if its wording
    happens to read as temporary. Retrying it would burn the timeout twice."""
    fb = _Fallback("from the api")
    run = _runner(_err_envelope("usage limit reached; this is usually transient"))
    cc = _cc(fb, runner=run)
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert len(run.seen) == 1
    assert cc._limited is True


@pytest.mark.parametrize("outcome", [
    _Result("", "exit 1: command not found", returncode=1),
    _Result("", "invalid model name", returncode=2),
])
def test_an_ordinary_failure_still_goes_straight_to_the_fallback(outcome):
    """Only conditions that name themselves temporary are worth a second
    subprocess; everything else should fail over immediately, as before."""
    fb = _Fallback("from the api")
    run = _runner(outcome)
    cc = _cc(fb, runner=run)
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert len(run.seen) == 1


def test_a_timeout_is_not_retried():
    """A 600s ceiling retried twice is half an hour of a stalled batch."""
    fb = _Fallback("from the api")
    run = _runner(subprocess.TimeoutExpired("claude", 600))
    cc = _cc(fb, runner=run)
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == "from the api"
    assert len(run.seen) == 1


def test_a_passage_about_a_dropped_connection_is_not_a_transient_failure():
    """_TRANSIENT_RE, like _LIMIT_RE, must never read the MODEL'S OWN OUTPUT."""
    passage = ("The telegraph operators described every connection reset as a "
               "small death; the line was overloaded and usually transient.")
    cc = _cc(_Fallback(), runner=_runner(_Result(_envelope(passage))))
    assert cc.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                   context=_ctx())[0] == passage

# ---- ledger ----------------------------------------------------------------------

def test_a_subscription_call_books_no_api_money():
    led = _ledger()
    cc = _cc(runner=_runner(_Result(_envelope("text", cost=0.44))))
    cc.call(led, "render", config.OPUS, 1600, "s" * 5000, "u" * 5000, context=_ctx())
    assert led.spent_usd == 0.0
    assert [(l.stage, l.model) for l in led.lines] == [("render", config.OPUS)]


def test_the_notional_cost_is_totalled_for_reporting():
    cc = _cc(runner=_runner(_Result(_envelope("a", cost=0.10)),
                            _Result(_envelope("b", cost=0.25))))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.notional_usd == pytest.approx(0.35)


def test_subscription_call_does_not_require_hypothetical_api_headroom():
    led = CostLedger(budget_usd=0.0000001)
    cc = _cc(runner=_runner(_Result(_envelope("x"))))
    assert cc.call(led, "render", config.OPUS, 1600, "s" * 5000, "u" * 5000,
                   context=_ctx())[0] == "x"
    assert led.spent_usd == 0


# ---- invocation ------------------------------------------------------------------

def test_inline_mode_appends_no_system_flag_and_frames_the_turn():
    """The default. Claude Code's own coding-agent system prompt cannot be
    removed by --append-system-prompt, so the stage prompt goes in the turn."""
    argv, turn = _argv("claude", "claude-opus-5", "SYS", "USR", system_mode="inline")
    assert "--append-system-prompt" not in argv and "--system-prompt" not in argv
    assert turn == "=== SYSTEM ===\nSYS\n\n=== USER ===\nUSR\n"


@pytest.mark.parametrize("mode,flag", [("append", "--append-system-prompt"),
                                       ("replace", "--system-prompt")])
def test_flag_system_modes_pass_the_prompt_untouched(mode, flag):
    argv, turn = _argv("claude", "claude-opus-5", "SYS", "USR", system_mode=mode)
    assert argv[argv.index(flag) + 1] == "SYS"
    assert turn == "USR"


def test_the_invocation_is_headless_json_and_nothing_else():
    argv, _ = _argv("claude", "claude-opus-5", "s", "u", system_mode="inline")
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--output-format") + 1] == "json"


@pytest.mark.parametrize("flag", ["--max-turns", "--allowed-tools",
                                  "--allowedTools", "--permission-mode"])
def test_flags_this_build_rejects_are_not_sent(flag):
    """Verified against 2.1.276 (2026-09-18): --max-turns is absent from the
    build and --allowed-tools refuses an empty value. Either one fails the
    call outright, which would silently push every stage onto the API."""
    argv, _ = _argv("claude", "claude-opus-5", "s", "u", system_mode="replace")
    assert flag not in argv


def test_the_model_map_can_rewrite_an_id_a_build_refuses():
    run = _runner(_Result(_envelope("ok")))
    cc = _cc(model_map={config.OPUS: "opus"}, runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    argv = run.seen[0]["argv"]
    assert argv[argv.index("--model") + 1] == "opus"


def test_the_prompt_is_the_last_argument():
    run = _runner(_Result(_envelope("ok")))
    cc = _cc(runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "SYS", "USR", context=_ctx())
    assert run.seen[0]["turn"].endswith("=== USER ===\nUSR\n")


# ---- output parsing --------------------------------------------------------------

def test_extract_reads_the_json_envelope():
    assert _extract(_envelope("  the passage  ")) == "the passage"


def test_extract_tolerates_a_plain_text_build():
    assert _extract("just the answer") == "just the answer"


def test_extract_takes_the_last_result_of_a_stream():
    blob = json.dumps([{"type": "assistant", "result": "early"},
                       {"type": "result", "result": "final"}])
    assert _extract(blob) == "final"


def test_extract_raises_on_a_reported_error():
    with pytest.raises(ClaudeCodeUnavailable):
        _extract(json.dumps({"is_error": True, "result": "context too long"}))


def test_questions_json_survives_the_envelope():
    """The questions stage expects JSON back; it must not arrive double-encoded."""
    from rc_engine.llm import extract_json
    payload = '```json\n{"questions": [{"q": 1}]}\n```'
    assert extract_json(_extract(_envelope(payload))) == {"questions": [{"q": 1}]}


# ---- probe -----------------------------------------------------------------------

def test_a_cmd_shim_forces_the_system_prompt_off_argv(tmp_path, capsys):
    """cmd.exe reads < > & | ^ % in ARGUMENTS as shell syntax, and engine
    prompts carry all of them. Measured 2026-09-18: an angle bracket in the
    system prompt killed the call before it reached the model."""
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo off", encoding="utf-8")
    cc = ClaudeCodeClient(_Fallback(), binary=str(shim), system_mode="replace",
                          runner=_runner(_Result(_envelope("ok"))))
    assert cc._system_mode == "inline"
    assert "forcing system_mode=inline" in capsys.readouterr().out


def test_a_native_exe_keeps_the_system_flag(tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_text("", encoding="utf-8")
    cc = ClaudeCodeClient(_Fallback(), binary=str(exe), system_mode="replace",
                          runner=_runner(_Result(_envelope("ok"))))
    assert cc._system_mode == "replace"


def test_resolve_binary_prefers_the_native_exe_behind_an_npm_shim(tmp_path):
    shim = tmp_path / "claude.CMD"
    shim.write_text("@echo off", encoding="utf-8")
    native = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    native.mkdir(parents=True)
    (native / "claude.exe").write_text("", encoding="utf-8")
    import rc_engine.claude_code as ccmod
    old = ccmod.shutil.which
    ccmod.shutil.which = lambda _n: str(shim)
    try:
        assert ccmod.resolve_binary("claude") == str(native / "claude.exe")
    finally:
        ccmod.shutil.which = old


def test_probe_reports_a_missing_binary():
    info = probe("definitely-not-a-real-binary-xyz")
    assert info["ok"] is False
    assert "not on PATH" in info["detail"]
    assert "@anthropic-ai/claude-code" in info["detail"]


@pytest.mark.parametrize("auth,ok", [
    ({"loggedIn": True, "authMethod": "claude.ai"}, True),
    ({"loggedIn": True, "authMethod": "api_key"}, False),
    ({"loggedIn": False}, False),
])
def test_probe_verifies_saved_subscription_without_inherited_api_key(monkeypatch, auth, ok):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    monkeypatch.setattr("rc_engine.claude_code.resolve_binary", lambda _: "claude.exe")
    def run(argv, **kwargs):
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        if argv[1:] == ["auth", "status", "--json"]:
            return _Result(json.dumps(auth))
        return _Result("--print --model --output-format --system-prompt --append-system-prompt")
    monkeypatch.setattr("rc_engine.claude_code.subprocess.run", run)
    assert probe()["ok"] is ok


# ---- CLI wiring ------------------------------------------------------------------

def test_claude_code_flags_parse():
    from rc_engine.cli import build_parser
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code",
         "--claude-code-stages", "render,questions"])
    assert args.claude_code is True
    assert args.claude_code_stages == "render,questions"


def test_claude_code_defaults_off():
    from rc_engine.cli import build_parser
    args = build_parser().parse_args(["generate", "--hard", "1"])
    assert args.claude_code is False


def test_an_absent_binary_leaves_the_stack_on_the_fallback(capsys, monkeypatch):
    """No Claude Code on this machine must be a printed note, not a failure."""
    from rc_engine.cli import build_parser, _wrap_client
    monkeypatch.setattr(config, "CLAUDE_CODE_BIN", "definitely-not-a-real-binary-xyz")
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code"])
    client = _wrap_client(_Fallback(), args, "claude")
    assert not isinstance(client, ClaudeCodeClient)
    assert "unusable" in capsys.readouterr().out


def test_the_chain_order_puts_relay_behind_the_api(monkeypatch):
    """--claude-code --relay means: Claude Code, then the API, then paste."""
    from rc_engine.cli import build_parser, _wrap_client
    from rc_engine.relay import RelayClient
    monkeypatch.setattr("rc_engine.claude_code.probe",
                        lambda binary=None: {"ok": True, "path": "/x/claude",
                                             "version": "1.0", "flags": {},
                                             "detail": "ok"})
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code", "--relay"])
    client = _wrap_client(_Fallback(), args, "claude")
    assert isinstance(client, ClaudeCodeClient)
    assert isinstance(client._fallback, RelayClient)
    assert client._fallback._api_first is True


# ---- effort ----------------------------------------------------------------------

def test_effort_is_passed_through():
    """--effort is Claude Code's output_config.effort, and the one fidelity
    gap this surface can actually close."""
    argv, _ = _argv("claude", config.OPUS, "s", "u", system_mode="replace",
                    effort="max")
    assert argv[argv.index("--effort") + 1] == "max"


def test_no_effort_flag_when_none_resolves():
    argv, _ = _argv("claude", config.OPUS, "s", "u", system_mode="replace",
                    effort=None)
    assert "--effort" not in argv


def test_an_explicit_level_overrides_every_tier():
    """A bare level ignores the per-tier map, but still reaches only the stages
    in CLAUDE_CODE_EFFORT_STAGES — render stays on the baseline."""
    run = _runner(_Result(_envelope("ok")), _Result(_envelope("ok")))
    cc = _cc(effort="max", runner=run)
    for tier in ("medium", "elite"):
        cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx(tier))
    for seen in run.seen:
        assert seen["argv"][seen["argv"].index("--effort") + 1] == "max"


def test_render_sits_above_the_baseline_without_joining_the_tier_ladder():
    """2026-09-21 operator decision: render runs at medium.

    The distinction that matters is render vs solver. Both are outside
    CLAUDE_CODE_EFFORT_STAGES, so before this they shared one floor; render
    now has its own level and solver must NOT follow it up there."""
    run = _runner(*[_Result(_envelope("ok"))] * 4)
    cc = _cc(runner=run)
    for stage in ("render", "solver", "refine"):
        cc.call(_ledger(), stage, config.OPUS, 100, "s", "u", context=_ctx("hard"))
    render, solver, refine = run.seen
    assert render["argv"][render["argv"].index("--effort") + 1] == "medium"
    assert solver["argv"][solver["argv"].index("--effort") + 1] == "low"
    assert refine["argv"][refine["argv"].index("--effort") + 1] == "low"


def test_render_takes_the_same_level_on_every_tier():
    """It is a floor, not a ladder: the tier map belongs to questions alone."""
    run = _runner(*[_Result(_envelope("ok"))] * 3)
    cc = _cc(runner=run)
    for tier in ("medium", "hard", "elite"):
        cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx(tier))
    for seen in run.seen:
        assert seen["argv"][seen["argv"].index("--effort") + 1] == "medium"


def test_the_per_stage_map_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CODE_EFFORT_BY_STAGE", {"solver": "high"})
    run = _runner(_Result(_envelope("ok")), _Result(_envelope("ok")))
    cc = _cc(runner=run)
    cc.call(_ledger(), "solver", config.OPUS, 100, "s", "u", context=_ctx())
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    solver, render = run.seen
    assert solver["argv"][solver["argv"].index("--effort") + 1] == "high"
    assert render["argv"][render["argv"].index("--effort") + 1] == "low"  # baseline


def test_questions_ignores_the_per_stage_map(monkeypatch):
    """CLAUDE_CODE_EFFORT_STAGES wins: questions keeps its per-tier ladder even
    if someone adds it to the per-stage map by mistake."""
    monkeypatch.setattr(config, "CLAUDE_CODE_EFFORT_BY_STAGE",
                        {"questions": "low", "render": "medium"})
    run = _runner(_Result(_envelope("ok")))
    cc = _cc(runner=run)
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx("elite"))
    seen = run.seen[0]
    assert seen["argv"][seen["argv"].index("--effort") + 1] == "max"


def test_auto_still_bypasses_the_per_stage_map():
    """'auto' hands the whole question to STAGE_EFFORT, as it always did."""
    run = _runner(_Result(_envelope("ok")))
    cc = _cc(effort="auto", runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("medium"))
    seen = run.seen[0]
    assert seen["argv"][seen["argv"].index("--effort") + 1] == "low"


def test_auto_honours_the_engines_own_stage_effort_table():
    """STAGE_EFFORT pins medium render to 'low' as an API cost trade; 'auto'
    is the way back to that behaviour."""
    run = _runner(_Result(_envelope("ok")), _Result(_envelope("ok")))
    cc = _cc(effort="auto", runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("medium"))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("hard"))
    medium, hard = run.seen
    assert medium["argv"][medium["argv"].index("--effort") + 1] == "low"
    assert "--effort" not in hard["argv"]      # hard is None = provider default


def test_effort_flag_parses_and_defaults_to_config():
    from rc_engine.cli import build_parser
    p = build_parser()
    assert p.parse_args(["generate", "--hard", "1"]).claude_code_effort is None
    assert p.parse_args(["generate", "--hard", "1", "--claude-code-effort",
                         "xhigh"]).claude_code_effort == "xhigh"


# ---- subscription usage accounting -----------------------------------------------

def _usage_envelope(text, *, cost=0.25, inp=2, cw=21000, cr=25000, out=3000,
                    thinking=0):
    """A _Result carrying a full usage envelope, as 2.1.276 emits one."""
    return _Result(json.dumps({
        "type": "result", "is_error": False, "result": text,
        "total_cost_usd": cost,
        "usage": {"input_tokens": inp, "cache_creation_input_tokens": cw,
                  "cache_read_input_tokens": cr, "output_tokens": out,
                  "output_tokens_details": {"thinking_tokens": thinking}},
    }))


def test_subscription_tokens_are_totalled():
    """API dollars read $0 on this lane, which is true but not the whole
    story — the quota is finite and the operator needs to see it."""
    cc = _cc(runner=_runner(_usage_envelope("a"), _usage_envelope("b")))
    for stage in ("render", "questions"):
        cc.call(_ledger(), stage, config.OPUS, 100, "s", "u", context=_ctx())
    u = cc.usage
    assert u["calls"] == 2
    assert u["cache_write"] == 42000 and u["cache_read"] == 50000
    assert u["output"] == 6000
    assert cc.notional_usd == pytest.approx(0.50)


def test_thinking_tokens_are_counted_when_reported():
    cc = _cc(runner=_runner(_usage_envelope("a", thinking=8000)))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.usage["thinking"] == 8000


def test_model_usage_includes_helper_models_without_double_counting_primary():
    """Claude 2.1.276's top-level usage omits its internal Haiku helper."""
    payload = {
        "type": "result", "is_error": False, "result": "ok", "total_cost_usd": .2,
        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100,
                  "cache_read_input_tokens": 0, "output_tokens": 20},
        "modelUsage": {
            "claude-opus": {"inputTokens": 2, "cacheCreationInputTokens": 100,
                             "cacheReadInputTokens": 0, "outputTokens": 20,
                             "thinkingTokens": 5},
            "claude-haiku": {"inputTokens": 40, "cacheCreationInputTokens": 0,
                              "cacheReadInputTokens": 0, "outputTokens": 3,
                              "thinkingTokens": 0},
        },
    }
    cc = _cc(runner=_runner(_Result(json.dumps(payload))))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.usage == {"calls": 1, "input": 42, "cache_write": 100,
                        "cache_read": 0, "output": 23, "thinking": 5}


def test_usage_is_broken_down_per_stage():
    cc = _cc(runner=_runner(_usage_envelope("a"), _usage_envelope("b"),
                            _usage_envelope("c")))
    for stage in ("render", "questions", "questions"):
        cc.call(_ledger(), stage, config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.by_stage["questions"]["calls"] == 2
    assert cc.by_stage["render"]["calls"] == 1


def test_usage_report_is_empty_when_the_lane_never_ran():
    assert _cc().usage_report() == []


def test_usage_report_names_the_totals():
    cc = _cc(runner=_runner(_usage_envelope("a")))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    text = "\n".join(cc.usage_report())
    assert "subscription usage" in text and "NOT API spend" in text
    assert "render x1" in text
    assert "49,002" in text          # 2 + 21000 + 25000 + 3000


def test_a_call_with_no_usage_block_still_counts():
    """A plain-text or older build reports no usage; the call must still be
    counted rather than silently vanishing from the meter."""
    cc = _cc(runner=_runner(_Result(_envelope("a", cost=0.3))))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert cc.usage["calls"] == 1 and cc.notional_usd == pytest.approx(0.3)


def test_the_batch_summary_prints_subscription_usage(capsys):
    """summarize_batch takes the client so the lane's usage lands in the same
    place as the cost telemetry."""
    from rc_engine.models import RCResult
    from rc_engine.pipeline import summarize_batch
    cc = _cc(runner=_runner(_usage_envelope("a")))
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    shipped = RCResult("RC-TEST-0001", "BP", "medium", "needs_review", cost_usd=0.01)
    summarize_batch([shipped], "batch-test", cc)
    out = capsys.readouterr().out
    assert "subscription usage" in out
    assert "per shipped set" in out


def test_the_batch_summary_is_unchanged_without_the_lane(capsys):
    from rc_engine.models import RCResult
    from rc_engine.pipeline import summarize_batch
    summarize_batch([RCResult(None, "BP", "medium", "needs_review", cost_usd=0.01)],
                    "batch-test", None)
    assert "subscription usage" not in capsys.readouterr().out


# ---- lean mode -------------------------------------------------------------------

def test_lean_mode_strips_tools_and_local_customizations():
    """MEASURED 2026-09-19: these two flags took a trivial prompt from 42,451
    tokens to 694. --tools "" removes the schemas AND the agent's ability to
    loop; --safe-mode stops CLAUDE.md/skills/plugins loading per call."""
    argv, _ = _argv("claude", config.OPUS, "s", "u", system_mode="replace",
                    lean=True)
    assert argv[argv.index("--tools") + 1] == ""
    assert "--safe-mode" in argv


def test_lean_mode_is_the_default_on_the_client():
    run = _runner(_usage_envelope("ok"))
    cc = _cc(runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx())
    assert "--safe-mode" in run.seen[0]["argv"]


def test_lean_can_be_turned_off_for_comparison():
    argv, _ = _argv("claude", config.OPUS, "s", "u", system_mode="replace",
                    lean=False)
    assert "--tools" not in argv and "--safe-mode" not in argv


@pytest.mark.parametrize("flag", ["--bare", "--disallowed-tools",
                                  "--disallowedTools", "--allowed-tools"])
def test_the_wrong_answers_are_never_sent(flag):
    """--bare forces ANTHROPIC_API_KEY auth and bypasses OAuth, which would
    silently move the batch onto the dead API key this lane exists to avoid.
    --disallowed-tools measured WORSE than doing nothing (4 turns, 2.6x the
    tokens). --allowed-tools rejects an empty value outright."""
    argv, _ = _argv("claude", config.OPUS, "s", "u", system_mode="replace",
                    lean=True)
    assert flag not in argv


def test_full_context_flag_disables_lean(capsys):
    from rc_engine.cli import build_parser, _wrap_client
    import rc_engine.claude_code as ccmod
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code",
         "--claude-code-full-context"])
    old = ccmod.probe
    ccmod.probe = lambda binary=None: {"ok": True, "path": "/x/claude",
                                       "version": "1", "flags": {}, "detail": "ok"}
    try:
        client = _wrap_client(_Fallback(), args, "claude")
    finally:
        ccmod.probe = old
    assert client._lean is False
    assert "lean mode OFF" in capsys.readouterr().out


# ---- parallel workers ------------------------------------------------------------

def test_lane_spec_is_none_without_the_flag():
    from rc_engine.cli import build_parser, _lane_spec
    args = build_parser().parse_args(["generate", "--hard", "1"])
    assert _lane_spec(args) is None


def test_lane_spec_describes_the_whole_lane():
    """Workers never see `args`. Anything the parent wrapped has to survive as
    picklable data or it silently does not happen in parallel mode."""
    from rc_engine.cli import build_parser, _lane_spec
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code",
         "--claude-code-stages", "render,questions",
         "--claude-code-effort", "xhigh"])
    spec = _lane_spec(args)
    assert spec["claude_code"] is True
    assert spec["stages"] == {"render", "questions"}
    assert spec["effort"] == "xhigh" and spec["lean"] is True
    import pickle
    assert pickle.loads(pickle.dumps(spec)) == spec     # crosses a process


def test_lane_spec_carries_full_context_opt_out():
    from rc_engine.cli import build_parser, _lane_spec
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--claude-code", "--claude-code-full-context"])
    assert _lane_spec(args)["lean"] is False


def test_workers_rebuild_the_claude_code_lane():
    """REGRESSION (2026-09-19): `--workers N --claude-code` used to ignore the
    lane entirely. Every worker built a bare RoutedClient and called the
    Anthropic API directly while the parent printed a banner promising the
    subscription lane — a batch of 401s on a dead key, or a surprise bill on a
    live one."""
    from rc_engine.workers import _lane_client
    base = _Fallback()
    client = _lane_client(base, {"claude_code": True, "stages": {"render"},
                                 "provider": "claude", "effort": "max",
                                 "lean": True})
    assert isinstance(client, ClaudeCodeClient)
    assert client._fallback is base
    assert client._stages == {"render"} and client._effort == "max"


@pytest.mark.parametrize("lane", [None, {}, {"claude_code": False}])
def test_workers_are_untouched_without_the_lane(lane):
    from rc_engine.workers import _lane_client
    base = _Fallback()
    assert _lane_client(base, lane) is base


def test_worker_init_accepts_the_initargs_tuple():
    """The pool passes initargs positionally; a signature/arity mismatch only
    shows up at runtime, inside a worker, as a failed batch."""
    import inspect
    from rc_engine.workers import _worker_init
    sig = inspect.signature(_worker_init)
    # (db, provider, dry_run, embed, client_id, lane)
    sig.bind("db.sqlite", "claude", False, True, "AA", {"claude_code": True})


def test_worker_usage_is_aggregated_across_processes():
    """Counters live on each worker's own client in its own process. Without
    shipping them home the parent's meter reads zero on every parallel run."""
    from rc_engine.workers import _AggregatedUsage
    agg = _AggregatedUsage()
    for _ in range(2):
        agg.add({"usage": {"calls": 2, "input": 5, "cache_write": 1000,
                           "cache_read": 300, "output": 4000, "thinking": 900},
                 "by_stage": {"render": {"calls": 1, "usd": 0.5},
                              "questions": {"calls": 1, "usd": 0.7}},
                 "notional_usd": 1.2})
    assert agg.usage["calls"] == 4 and agg.usage["output"] == 8000
    assert agg.by_stage["render"]["calls"] == 2
    assert agg.notional_usd == pytest.approx(2.4)


def test_aggregated_usage_reports_like_the_client():
    from rc_engine.workers import _AggregatedUsage
    agg = _AggregatedUsage()
    agg.add({"usage": {"calls": 1, "input": 2, "cache_write": 10,
                       "cache_read": 20, "output": 30, "thinking": 0},
             "by_stage": {"render": {"calls": 1, "usd": 0.1}},
             "notional_usd": 0.1})
    text = "\n".join(agg.usage_report())
    assert "subscription usage" in text and "render x1" in text


def test_aggregated_usage_is_silent_when_the_lane_never_ran():
    from rc_engine.workers import _AggregatedUsage
    assert _AggregatedUsage().usage_report() == []


# ---- per-tier effort -------------------------------------------------------------

def test_the_default_is_the_per_tier_map():
    """2026-09-19 operator decision: elite=max, hard=xhigh, medium=high. The
    API path's medium="low" is a tier-budget trade that does not apply on a
    subscription-billed lane."""
    assert config.CLAUDE_CODE_EFFORT_BY_TIER == {
        "medium": "high", "hard": "xhigh", "elite": "max"}


def test_a_tier_absent_from_the_map_sends_no_flag():
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort={"elite": "max"}, runner=run)
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx("medium"))
    assert "--effort" not in run.seen[0]["argv"]


def test_the_client_defaults_to_the_map_when_nothing_is_passed():
    run = _runner(_usage_envelope("ok"))
    cc = ClaudeCodeClient(_Fallback(), binary="claude", runner=run,
                          system_mode="inline")
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx("elite"))
    argv = run.seen[0]["argv"]
    assert argv[argv.index("--effort") + 1] == "max"


@pytest.mark.parametrize("raw,expect", [
    (None, None),
    ("", None),
    ("max", "max"),
    ("auto", "auto"),
    ("medium=high,hard=xhigh,elite=max",
     {"medium": "high", "hard": "xhigh", "elite": "max"}),
    ("elite=max", {"elite": "max"}),
    (" medium = high , elite = max ", {"medium": "high", "elite": "max"}),
])
def test_effort_parsing(raw, expect):
    from rc_engine.cli import parse_cc_effort
    assert parse_cc_effort(raw) == expect


@pytest.mark.parametrize("raw", ["ultra", "medium=ultra", "tier9=max",
                                 "medium=", "=max"])
def test_a_typo_fails_loudly_rather_than_sending_no_flag(raw):
    """A silently-dropped effort flag is a whole batch generated at the wrong
    level, which nothing downstream would flag."""
    from rc_engine.cli import parse_cc_effort
    with pytest.raises(ValueError):
        parse_cc_effort(raw)


def test_the_lane_spec_carries_a_per_tier_map_to_workers():
    import pickle
    from rc_engine.cli import build_parser, _lane_spec
    args = build_parser().parse_args(
        ["generate", "--medium", "1", "--claude-code",
         "--claude-code-effort", "medium=high,elite=max"])
    spec = _lane_spec(args)
    assert spec["effort"] == {"medium": "high", "elite": "max"}
    assert pickle.loads(pickle.dumps(spec)) == spec


def test_the_lane_spec_defaults_to_the_configured_map():
    from rc_engine.cli import build_parser, _lane_spec
    args = build_parser().parse_args(
        ["generate", "--medium", "1", "--claude-code"])
    assert _lane_spec(args)["effort"] == config.CLAUDE_CODE_EFFORT_BY_TIER


# ---- effort applies to the questions stage only -----------------------------------

@pytest.mark.parametrize("stage", ["solver", "refine", "render"])
def test_the_tier_ladder_never_reaches_a_non_questions_stage(stage):
    """REGRESSION (2026-09-19). The first per-tier map applied the tier's level
    to EVERY Anthropic-bound stage. On the aborted 3-worker run one Sonnet
    solver call spent 50,092 thinking tokens answering six MCQs (a gate capped
    at 1,600 output tokens on the API path), and one render at "max" spent
    85,300.

    render is still here after it moved to its own "medium" level on
    2026-09-21: what this guards is that the ELITE tier's "max" never lands on
    it, which is the expensive half of that regression."""
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort=dict(config.CLAUDE_CODE_EFFORT_BY_TIER), runner=run)
    cc.call(_ledger(), stage, config.OPUS, 100, "s", "u", context=_ctx("elite"))
    argv = run.seen[0]["argv"]
    expected = (config.CLAUDE_CODE_EFFORT_BY_STAGE.get(stage)
                or config.CLAUDE_CODE_EFFORT_BASELINE)
    assert argv[argv.index("--effort") + 1] == expected
    assert argv[argv.index("--effort") + 1] != "max"


@pytest.mark.parametrize("tier,level", [("medium", "high"), ("hard", "xhigh"),
                                        ("elite", "max")])
def test_questions_keeps_the_per_tier_ladder(tier, level):
    """The one stage where reasoning was measured to pay: the length-bias
    self-check is a counting task over 32 options."""
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort=dict(config.CLAUDE_CODE_EFFORT_BY_TIER), runner=run)
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx(tier))
    argv = run.seen[0]["argv"]
    assert argv[argv.index("--effort") + 1] == level


def test_a_bare_level_also_respects_the_stage_split():
    run = _runner(_usage_envelope("ok"), _usage_envelope("ok"))
    cc = _cc(effort="max", runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("hard"))
    cc.call(_ledger(), "questions", config.OPUS, 100, "s", "u", context=_ctx("hard"))
    render, questions = run.seen
    assert render["argv"][render["argv"].index("--effort") + 1] == "medium"
    assert questions["argv"][questions["argv"].index("--effort") + 1] == "max"


def test_auto_is_unaffected_by_the_stage_split():
    """'auto' defers to STAGE_EFFORT, which already carries per-stage values."""
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort="auto", runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("medium"))
    argv = run.seen[0]["argv"]
    assert argv[argv.index("--effort") + 1] == "low"


def test_the_effort_stages_agree_with_thinking_stages():
    """Two levers, one finding (2026-08-11 / 2026-09-19). If a measurement ever
    moves one, it should move the other or say why."""
    assert set(config.CLAUDE_CODE_EFFORT_STAGES) == set(config.THINKING_STAGES)


def test_a_none_baseline_sends_no_flag(monkeypatch):
    """solver, not render: render carries its own level and so would still
    send a flag with the baseline cleared (2026-09-21)."""
    monkeypatch.setattr(config, "CLAUDE_CODE_EFFORT_BASELINE", None)
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort=dict(config.CLAUDE_CODE_EFFORT_BY_TIER), runner=run)
    cc.call(_ledger(), "solver", config.OPUS, 100, "s", "u", context=_ctx("elite"))
    assert "--effort" not in run.seen[0]["argv"]


def test_a_none_baseline_does_not_silence_a_per_stage_level(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CODE_EFFORT_BASELINE", None)
    run = _runner(_usage_envelope("ok"))
    cc = _cc(effort=dict(config.CLAUDE_CODE_EFFORT_BY_TIER), runner=run)
    cc.call(_ledger(), "render", config.OPUS, 100, "s", "u", context=_ctx("elite"))
    argv = run.seen[0]["argv"]
    assert argv[argv.index("--effort") + 1] == "medium"
