"""Offline Codex lane contracts. No test invokes a model or reads credentials."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from rc_engine import config, cli, codex_cli, pipeline, providers, workers
from rc_engine.cli_runtime import subscription_env
from rc_engine.codex_cli import CodexCLIClient, CodexUnavailable, parse_events
from rc_engine.llm import APIExhausted, BudgetExceeded, CostLedger, MockLLMClient


@pytest.fixture(autouse=True)
def offline_catalog(monkeypatch):
    monkeypatch.setattr(codex_cli, "_bundled_catalog", lambda binary: {"models": [
        {"slug": slug, "tool_mode": "code_mode_only", "multi_agent_version": "v2",
         "supported_reasoning_levels": ["low", "xhigh", "max"],
         "node_repl_auto_review_required": True}
        for slug in set(config.CODEX_CLI_MODEL_MAP.values())]})


def test_text_catalog_removes_model_forced_tools_but_preserves_identity_and_safety(tmp_path):
    codex_cli.write_text_catalog("unused", tmp_path)
    models = json.loads((tmp_path / "text-models.json").read_text())["models"]
    assert {m["slug"] for m in models} == set(config.CODEX_CLI_MODEL_MAP.values())
    for model in models:
        assert model["tool_mode"] == "direct"
        assert model["multi_agent_version"] is None
        assert model["apply_patch_tool_type"] is None
        assert model["experimental_supported_tools"] == []
        assert model["node_repl_auto_review_required"] is True
        assert model["supported_reasoning_levels"] == ["low", "xhigh", "max"]


def test_missing_text_model_fails_before_invocation(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli, "_bundled_catalog", lambda binary: {"models": []})
    runner = Runner()
    with pytest.raises(APIExhausted, match="lacks required"):
        call(client(tmp_path, runner))
    assert not runner.calls


class Base:
    def __init__(self):
        self.calls = []

    def call(self, *args):
        self.calls.append(args)
        return "base answer", False


def stream(*events):
    return "\n".join(json.dumps(x) for x in events)


def completed(**usage):
    return {"type": "turn.completed", "usage": usage}


class Runner:
    def __init__(self, answer="final answer", stdout=None, returncode=0, error=None):
        self.answer = answer
        self.stdout = stdout if stdout is not None else stream(
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "commentary"}},
            completed(input_tokens=100, cached_input_tokens=80, output_tokens=20,
                      reasoning_output_tokens=5))
        self.returncode, self.error, self.calls = returncode, error, []

    def __call__(self, argv, turn, timeout, **kwargs):
        self.calls.append((argv, turn, timeout, kwargs))
        if self.error:
            raise self.error
        if self.answer is not None:
            Path(argv[argv.index("-o") + 1]).write_text(self.answer, encoding="utf-8")
        return SimpleNamespace(stdout=self.stdout, stderr="private error detail", returncode=self.returncode)


def client(tmp_path, runner=None, **kwargs):
    return CodexCLIClient(Base(), binary="codex.exe", runner=runner or Runner(),
                          root=str(tmp_path), version="test", **kwargs)


def call(cc, stage="render", source=None, tier="hard", ledger=None):
    return cc.call(ledger or CostLedger(10), stage, source or config.OPUS, 100,
                   "system instruction", "user prompt", {"tier": tier})


@pytest.mark.parametrize("tier", ["medium", "hard", "elite"])
def test_every_resolved_opus_and_sonnet_stage_is_mapped_without_touching_pins(tmp_path, tier):
    config.set_provider("claude")
    cc = client(tmp_path)
    for stage, tiers in config.STAGE_CONFIG.items():
        source, _ = tiers[tier]
        pin = config.resolve_stage_pin(stage, tier)
        expected = None if pin and pin[0] != "claude" else config.CODEX_CLI_MODEL_MAP.get(pin[1] if pin else source)
        assert cc.mapped_model(stage, source, {"tier": tier}) == expected, stage


@pytest.mark.parametrize("source,target", [
    (config.OPUS, "gpt-6-astra"), (config.SONNET, "gpt-5.6-sol"),
    ("claude-opus-4-8", "gpt-6-astra"), ("claude-sonnet-4-5", "gpt-5.6-sol")])
def test_actual_child_and_ledger_use_mapped_model(tmp_path, source, target):
    runner, ledger = Runner(), CostLedger(.000001)
    cc = client(tmp_path, runner)
    assert call(cc, source=source, ledger=ledger) == ("final answer", False)
    argv = runner.calls[0][0]
    assert argv[argv.index("-m") + 1] == target
    assert ledger.spent_usd == 0
    assert ledger.lines[0].model == target


@pytest.mark.parametrize("tier,effort", [("medium", "high"), ("hard", "xhigh"), ("elite", "max")])
@pytest.mark.parametrize("source", [config.OPUS, config.SONNET])
def test_questions_keep_the_claude_tier_ladder(tmp_path, tier, effort, source):
    cc = client(tmp_path)
    call(cc, "questions", source, tier)
    assert cc.last_call["effort"] == effort


@pytest.mark.parametrize("stage", ["refine", "render", "solver"])
def test_other_stages_use_low_even_with_questions_override(tmp_path, stage):
    cc = client(tmp_path, effort="max")
    call(cc, stage, config.SONNET, "elite")
    assert cc.last_call["effort"] == "low"


def test_luna_pins_and_haiku_calls_delegate(tmp_path):
    runner = Runner()
    cc = client(tmp_path, runner)
    assert call(cc, "refine", config.SONNET, "medium")[0] == "base answer"
    assert call(cc, "judge")[0] == "base answer"
    assert call(cc, "other", config.HAIKU)[0] == "base answer"
    assert not runner.calls


def test_json_answer_is_not_double_encoded_or_replaced_by_commentary(tmp_path):
    answer = '{"questions": [{"q": 1}]}'
    assert call(client(tmp_path, Runner(answer=answer)), "questions")[0] == answer


def test_cli_plan_update_is_not_misclassified_as_external_tool_use(tmp_path):
    cc = client(tmp_path, Runner(stdout=stream(
        {"type": "item.started", "item": {"type": "todo_list", "items": []}},
        {"type": "item.completed", "item": {"type": "todo_list", "items": []}},
        completed(input_tokens=100, output_tokens=20))))
    assert call(cc)[0] == "final answer"
    assert cc.last_call["events"]["item_types"] == {"todo_list": 2}


def test_disabled_coding_host_startup_notice_accepts_successful_text_only(tmp_path):
    notice = {"type": "item.completed", "item": {
        "type": "error", "message": codex_cli._CODE_MODE_DISABLED_NOTICE}}
    cc = client(tmp_path, Runner(stdout=stream(notice, {"type": "turn.started"}, completed())))
    assert call(cc)[0] == "final answer"
    assert cc.last_call["events"]["startup_notices"] == ["code_mode_host_disabled"]
    for events in ([notice], [notice, {"type": "turn.failed"}],
                   [{"type": "turn.started"}, notice, completed()],
                   [notice, {"type": "error"}, completed()],
                   [{"type": "item.completed", "item": {"type": "error", "message": "unknown failure"}}, completed()]):
        with pytest.raises(CodexUnavailable):
            parse_events(stream(*events))


def test_long_unicode_prompts_stay_off_argv_and_keys_stay_out_of_child(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    runner = Runner()
    cc = client(tmp_path, runner)
    user = 'long <&|%> $() ` quoted — λ ' * 3000
    system = 'system "prompt" \n with — Unicode'
    cc.call(CostLedger(1), "render", config.OPUS, 100, system, user, {"tier": "hard"})
    argv, turn, _, kwargs = runner.calls[0]
    assert turn == user and user not in argv and system not in argv
    work = Path(kwargs["cwd"])
    assert (work / "instructions.txt").read_text(encoding="utf-8") == system
    assert "OPENAI_API_KEY" not in kwargs["env"] and "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "forced_login_method=\"chatgpt\"" in argv
    assert "suppress_unstable_features_warning=true" in argv
    for setting in ("include_collaboration_mode_instructions=false",
                    "include_environment_context=false",
                    "tools.experimental_request_user_input.enabled=false",
                    "tools.update_plan.enabled=false",
                    'model_reasoning_summary="none"', 'model_verbosity="low"'):
        assert setting in argv
    assert any(x.startswith("model_catalog_json=") for x in argv)
    assert any(x.startswith("skills.config=[") for x in argv)
    assert "read-only" in argv and "--ignore-user-config" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv


def test_usage_does_not_double_count_cache_or_reasoning(tmp_path):
    cc = client(tmp_path)
    call(cc)
    assert cc.usage == {"calls": 1, "input": 20, "cache_write": 0,
                        "cache_read": 80, "output": 20, "thinking": 5}
    assert cc.notional_usd == pytest.approx(.00128)
    assert "120" in "\n".join(cc.usage_report())
    assert "Codex CLI" in "\n".join(cc.usage_report())


@pytest.mark.parametrize("stdout", [
    "not-json", "[]", stream({"type": "turn.started"}),
    stream(completed(), {"type": "turn.failed"}),
    stream(completed(), {"type": "error", "message": "limit"}),
    stream(completed(), {"type": "turn.started"}),
    stream({"type": "item.completed", "item": {"type": "command_execution"}}, completed()),
    stream(completed(input_tokens=-1)), stream(completed(output_tokens="10")),
])
def test_bad_or_partial_events_stop_without_api_fallback(tmp_path, stdout):
    cc = client(tmp_path, Runner(stdout=stdout))
    with pytest.raises(APIExhausted):
        call(cc)
    assert not cc._fallback.calls


@pytest.mark.parametrize("runner", [Runner(returncode=1), Runner(answer=""), Runner(answer=None),
                                    Runner(error=subprocess.TimeoutExpired("codex", 1)),
                                    Runner(error=FileNotFoundError("missing"))])
def test_child_failures_stop_and_do_not_relaunch(tmp_path, runner):
    cc = client(tmp_path, runner)
    with pytest.raises(APIExhausted):
        call(cc)
    with pytest.raises(APIExhausted):
        call(cc, "questions")
    assert len(runner.calls) == 1
    assert not cc._fallback.calls


def test_explicit_api_fallback_preserves_model_effort_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "provider_key_present", lambda _: "SYNTHETIC_KEY_NAME")
    api = Base()
    monkeypatch.setattr(providers, "OpenAIClient", lambda: api)
    cc = client(tmp_path, Runner(returncode=1), fallback_mode="api")
    assert call(cc, "questions", config.SONNET, "elite")[0] == "base answer"
    args = api.calls[0]
    assert args[2] == "gpt-5.6-sol"
    assert args[3] == 100 + config.REASONING_HEADROOM["max"]
    assert args[-1]["cli_reasoning_effort"] == "max"
    assert not cc._fallback.calls


def test_paid_fallback_can_be_refused_by_its_dollar_guard(tmp_path, monkeypatch):
    class Guarded:
        def call(self, ledger, stage, model, ceiling, system, user, ctx):
            ledger.guard(stage, len(system) + len(user), model, ceiling)
            pytest.fail("an unaffordable API call reached the paid operation")
    monkeypatch.setattr(providers, "provider_key_present", lambda _: "SET")
    monkeypatch.setattr(providers, "OpenAIClient", Guarded)
    with pytest.raises(BudgetExceeded):
        call(client(tmp_path, Runner(returncode=1), fallback_mode="api"),
             "questions", ledger=CostLedger(.001))


@pytest.mark.parametrize("source,model", [(config.OPUS, "gpt-6-astra"),
                                         (config.SONNET, "gpt-5.6-sol")])
def test_paid_fallback_sends_the_cli_effort_to_the_sdk(tmp_path, monkeypatch, source, model):
    import sys
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {})))
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="paid answer"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))
    api = providers.OpenAIClient.__new__(providers.OpenAIClient)
    api._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(providers, "provider_key_present", lambda _: "SET")
    cc = client(tmp_path, Runner(returncode=1), fallback_mode="api")
    cc._api = api
    ledger = CostLedger(2)
    assert call(cc, "questions", source, "elite", ledger)[0] == "paid answer"
    assert sent[0]["model"] == model and sent[0]["reasoning_effort"] == "max"
    assert sent[0]["max_completion_tokens"] == 100 + config.REASONING_HEADROOM["max"]
    assert ledger.spent_usd > 0 and ledger.lines[0].model == model


def test_unsupported_effort_fails_before_child(tmp_path):
    runner = Runner()
    cc = client(tmp_path, runner, models={"gpt-6-astra": ["low"]})
    with pytest.raises(APIExhausted, match="does not support"):
        call(cc, "questions")
    assert not runner.calls


@pytest.mark.parametrize("flag", ["--claude-code", "--codex-cli", "--relay"])
def test_dry_run_never_probes_calls_or_wraps_a_live_lane(monkeypatch, flag):
    def forbidden(*a, **kw):
        pytest.fail("dry-run touched a live boundary")
    monkeypatch.setattr(codex_cli, "probe", forbidden)
    monkeypatch.setattr("rc_engine.claude_code.probe", forbidden)
    monkeypatch.setattr(providers, "provider_key_present", forbidden)
    args = cli.build_parser().parse_args(["generate", "--dry-run", "--hard", "1", flag])
    llm, code = cli._setup_provider(args)
    assert code == 0 and isinstance(llm, MockLLMClient)
    assert cli._lane_spec(args) is None


def fake_probe():
    return {"ok": True, "path": "codex.exe", "version": "test", "detail": "ok",
            "models": {m: list(config.CODEX_CLI_EFFORTS) for m in config.CODEX_CLI_MODEL_MAP.values()}}


def test_setup_needs_no_anthropic_key_and_workers_receive_complete_spec(monkeypatch):
    monkeypatch.setattr(codex_cli, "probe", fake_probe)
    monkeypatch.setattr(providers, "provider_key_present", lambda p: "SET" if p == "openai" else None)
    args = cli.build_parser().parse_args(["generate", "--hard", "1", "--codex-cli"])
    llm, code = cli._setup_provider(args)
    assert code == 0 and isinstance(llm, CodexCLIClient)
    import pickle
    spec = pickle.loads(pickle.dumps(cli._lane_spec(args)))
    child = workers._lane_client(Base(), spec)
    assert isinstance(child, CodexCLIClient)
    assert child._models == llm._models and child._effort == llm._effort
    assert child._binary == llm._binary and child._version == llm._version


def test_failed_claude_subscription_probe_is_also_respected_by_workers(monkeypatch):
    monkeypatch.setattr("rc_engine.claude_code.probe", lambda: {"ok": False, "detail": "API-key login"})
    monkeypatch.setattr(providers, "provider_key_present", lambda p: "SET" if p == "openai" else None)
    args = cli.build_parser().parse_args(["generate", "--hard", "1", "--claude-code"])
    llm, code = cli._setup_provider(args)
    assert code == 0 and isinstance(llm, providers.RoutedClient)
    assert cli._lane_spec(args) is None


@pytest.mark.parametrize("extra", [["--claude-code"], ["--relay"], ["--provider", "openai"],
                                   ["--codex-effort", "auto"], ["--codex-effort", "elite=ultra"]])
def test_invalid_combinations_fail_without_generation(extra):
    args = cli.build_parser().parse_args(["generate", "--dry-run", "--hard", "1", "--codex-cli", *extra])
    assert cli._setup_provider(args) == (None, 1)


def test_resume_exposes_the_same_codex_options():
    args = cli.build_parser().parse_args(["retry-questions", "--blueprint", "BP_TEST", "--codex-cli",
                                          "--codex-effort", "elite=max"])
    assert cli._lane_spec(args)["effort"] == {"elite": "max"}


@pytest.mark.parametrize("available", [False, True])
def test_required_seed_never_allows_seedless_generation(tmp_path, monkeypatch, available):
    args = cli.build_parser().parse_args(["generate", "--hard", "1", "--codex-cli",
        "--require-seed", "--no-export", "--no-screen", "--db", str(tmp_path / "pilot.db")])
    monkeypatch.setattr(cli, "_setup_provider", lambda _: (MockLLMClient(), 0))
    provider = (lambda *a, **kw: (None, None)) if available else None
    monkeypatch.setattr(cli, "_make_seed_provider", lambda *a, **kw: provider)
    batches = []
    def run_batch(pipe, tiers, seed_provider, **kwargs):
        assert seed_provider is not None and seed_provider.restricted is True
        batches.append(1)
        # Existing run_slot refuses to call generate_one when restricted seeds run out.
        def forbidden(*a, **kw):
            pytest.fail("missing required seed reached generation")
        pipe.generate_one = forbidden
        pipeline.run_slot(pipe, "hard", 1, 1, seed_provider, set(),
            spent=lambda: 0, max_usd=1, keep=forbidden)
        return []
    monkeypatch.setattr(cli, "run_batch", run_batch)
    monkeypatch.setattr(cli.HistoryStore, "backup_to", lambda *a: None)
    assert cli.cmd_generate(args) == 1
    assert batches == ([1] if available else [])


def test_required_seed_rejects_explicit_seedless_before_provider_setup(monkeypatch):
    args = cli.build_parser().parse_args(["generate", "--hard", "1", "--require-seed", "--no-seed"])
    monkeypatch.setattr(cli, "_setup_provider", lambda _: pytest.fail("should fail before setup"))
    assert cli.cmd_generate(args) == 1


def test_reused_worker_returns_only_new_usage(tmp_path, monkeypatch):
    cc = client(tmp_path)
    pipe = SimpleNamespace(llm=cc, history=SimpleNamespace(release_inflight=lambda _: None))
    monkeypatch.setattr(workers, "_PIPE", pipe)
    monkeypatch.setattr(pipeline, "run_slot", lambda *a, **kw: call(cc))
    agg = workers._AggregatedUsage()
    for slot in range(3):
        payload = workers._worker_slot("hard", slot + 1, 3, [], [], 1)
        assert payload["cc"]["usage"]["calls"] == 1
        agg.add(payload["cc"])
    assert agg.usage == cc.usage and agg.usage["calls"] == 3
    assert agg.notional_usd == pytest.approx(cc.notional_usd)
    assert "Codex CLI" in "\n".join(agg.usage_report())


def test_child_environment_retains_auth_store_but_removes_billing_overrides(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                 "CLAUDE_CODE_USE_BEDROCK", "OPENAI_BASE_URL"):
        monkeypatch.setenv(name, "synthetic")
    monkeypatch.setenv("CODEX_HOME", "synthetic-auth-location")
    env = subscription_env()
    assert env["CODEX_HOME"] == "synthetic-auth-location"
    assert not any(name in env for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"))


def test_missing_pinned_provider_is_not_silently_replaced(monkeypatch):
    base = Base()
    routed = providers.RoutedClient(base, strict_pins=True)
    monkeypatch.setattr(providers, "provider_key_present", lambda _: None)
    with pytest.raises(APIExhausted):
        routed.call(CostLedger(1), "judge", config.OPUS, 100, "s", "u")
    assert not base.calls


@pytest.mark.parametrize("auth,ok", [("Logged in using ChatGPT", True),
                                     ("Logged in using an API key", False),
                                     ("Not logged in", False)])
def test_probe_requires_subscription_auth_and_sanitizes_every_command(monkeypatch, auth, ok):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(codex_cli, "resolve_binary", lambda _: "codex.exe")
    calls = []
    def run(argv, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"]
        calls.append(argv[1:])
        output = {
            "--version": "test",
            "exec": "--json --ephemeral --ignore-user-config --output-last-message --skip-git-repo-check --sandbox",
            "login": auth,
            "debug": json.dumps({"models": [
                {"slug": m, "supported_reasoning_levels": [{"effort": e} for e in config.CODEX_CLI_EFFORTS]}
                for m in config.CODEX_CLI_MODEL_MAP.values()]}),
        }[argv[1]]
        return SimpleNamespace(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(codex_cli.subprocess, "run", run)
    info = codex_cli.probe()
    assert info["ok"] is ok
    assert ["exec", "--help"] in calls
    assert not any("-p" in args or "-" in args for args in calls)


def test_reported_usage_survives_a_failed_response(tmp_path):
    cc = client(tmp_path, Runner(stdout=stream(completed(input_tokens=90, output_tokens=10),
                                             {"type": "error"})))
    with pytest.raises(APIExhausted):
        call(cc)
    assert cc.usage["input"] == 90 and cc.usage["output"] == 10
    assert cc.last_call["status"] == "failed"
    assert cc.last_call["usage"]["input_tokens"] == 90


def test_rejected_event_reports_its_type_without_logging_prompt_content(tmp_path):
    cc = client(tmp_path, Runner(stdout=stream(
        {"type": "item.completed", "item": {"type": "command_execution", "command": "private content"}},
        completed())))
    with pytest.raises(APIExhausted, match="command_execution") as caught:
        call(cc)
    assert "private content" not in str(caught.value)
    assert cc.last_call["events"]["item_types"] == {"command_execution": 1}
    assert "private content" not in json.dumps(cc.last_call)


def test_refine_does_not_swallow_terminal_cli_failure(monkeypatch):
    from rc_engine import composer
    calls = []
    def fail(*args, **kw):
        calls.append(1)
        raise APIExhausted("subscription exhausted")
    monkeypatch.setattr(composer, "policy_for_blueprint", lambda _: SimpleNamespace(
        source_facts=False, system_prompt=lambda stage, default: default))
    fake = SimpleNamespace(llm=SimpleNamespace(call=fail))
    with pytest.raises(APIExhausted, match="subscription exhausted"):
        composer.BlueprintComposer._refine_with_retry(fake, SimpleNamespace(),
            config.SONNET, 100, "user", [], CostLedger(1))
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("codex", 1), KeyboardInterrupt()])
def test_process_timeout_or_cancel_terminates_its_tree(monkeypatch, failure):
    from rc_engine import cli_runtime
    actions = []
    class Process:
        pid = 12345
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def communicate(self, *args, **kw):
            if kw.get("timeout"):
                raise failure
            actions.append("reaped")
            return "", ""
        def poll(self):
            return None
        def kill(self):
            actions.append("kill")
    monkeypatch.setattr(cli_runtime.subprocess, "Popen", lambda *a, **kw: Process())
    if cli_runtime.os.name == "nt":
        def taskkill(argv, **kwargs):
            assert argv == ["taskkill", "/PID", "12345", "/T", "/F"]
            actions.append("tree")
            raise OSError("cleanup failed")
        monkeypatch.setattr(cli_runtime.subprocess, "run", taskkill)
    else:
        monkeypatch.setattr(cli_runtime.os, "killpg", lambda *a: actions.append("tree"))
    with pytest.raises(type(failure)):
        cli_runtime.run_process(["codex"], "user", 1, cwd=".", env={})
    assert actions == ["tree", "kill", "reaped"]
