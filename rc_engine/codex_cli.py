"""Codex CLI subscription lane: Opus -> Astra, Sonnet -> Sol (2026-09-20).

Same engine prompts/gates, fresh exec per call. CLI reasoning levels match
the Claude Code lane, not the older OpenAI API cost experiments. The CLI is
still a harness: equivalent effort names do not mean identical sampling.
Failures stop the batch by default; API fallback must be explicitly selected.
"""
from __future__ import annotations

import json
from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import config
from .cli_runtime import run_process, subscription_env
from .llm import APIExhausted


class CodexUnavailable(RuntimeError):
    def __init__(self, message, usage=None):
        super().__init__(message)
        self.usage = usage


def resolve_binary(binary=None):
    path = shutil.which(binary or config.CODEX_CLI_BIN)
    if not path and binary and os.path.isfile(binary):
        path = os.path.abspath(binary)
    if not path or path.lower().endswith((".cmd", ".bat", ".ps1")):
        return None
    return path


def probe(binary=None):
    """Free version/flags/login/catalog checks; no model request."""
    path = resolve_binary(binary)
    info = {"ok": False, "path": path, "version": None, "models": {}, "detail": ""}
    if not path:
        info["detail"] = "native Codex executable not found; set RC_ENGINE_CODEX_BIN"
        return info
    try:
        def run(*args):
            r = subprocess.run([path, *args], capture_output=True, text=True,
                               encoding="utf-8", timeout=30,
                               env=subscription_env(), cwd=tempfile.gettempdir())
            if r.returncode:
                raise CodexUnavailable(f"{' '.join(args)} failed (exit {r.returncode})")
            return r.stdout or r.stderr or ""
        info["version"] = run("--version").strip()
        helptext = run("exec", "--help")
        for flag in ("--json", "--ephemeral", "--ignore-user-config",
                     "--output-last-message", "--skip-git-repo-check", "--sandbox"):
            if flag not in helptext:
                raise CodexUnavailable(f"installed CLI lacks {flag}; update Codex")
        if "logged in using chatgpt" not in run("login", "status").lower():
            raise CodexUnavailable("ChatGPT login required; run codex login")
        catalog = json.loads(run("debug", "models", "--bundled"))
        for m in catalog["models"]:
            if m["slug"] in config.CODEX_CLI_MODEL_MAP.values():
                info["models"][m["slug"]] = [x["effort"] for x in m["supported_reasoning_levels"]]
        for model in config.CODEX_CLI_MODEL_MAP.values():
            if model not in info["models"]:
                raise CodexUnavailable(f"{model} absent from the installed CLI catalog")
        info.update(ok=True, detail="ChatGPT login; model catalog available")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            CodexUnavailable) as e:
        info["detail"] = str(e)
    return info


# Disable unrelated capabilities, leaving managed policy in force. The
# read-only sandbox is an additional boundary, not a claim of zero tools.
_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent",
    "multi_agent_v2", "browser_use", "browser_use_external", "computer_use",
    "image_generation", "view_image", "memories", "skill_search",
    "skill_mcp_dependency_install", "code_mode", "code_mode_host", "goals",
    "sleep_tool", "workspace_dependencies",
    "tool_suggest", "tool_call_mcp_elicitation", "shell_snapshot",
    "default_mode_request_user_input", "send_message_to_user_async",
)


@lru_cache(maxsize=4)
def _bundled_catalog(binary):
    result = subprocess.run([binary, "debug", "models", "--bundled"],
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=30, env=subscription_env(), cwd=tempfile.gettempdir())
    if result.returncode:
        raise CodexUnavailable("cannot load local model catalog for text-only CLI")
    try:
        catalog = json.loads(result.stdout)
        if not isinstance(catalog.get("models"), list):
            raise ValueError()
        return catalog
    except (ValueError, AttributeError):
        raise CodexUnavailable("invalid local model catalog") from None


def write_text_catalog(binary, work):
    """Override harness capabilities, preserving real model identity/efforts.

    2026-09-20 wire audit: Astra/Sol catalog tool_mode=code_mode_only and
    multi_agent_version=v2 overrode --disable flags, adding ~22K characters.
    No safety/approval metadata is relaxed; the read-only sandbox stays on.
    """
    catalog = json.loads(json.dumps(_bundled_catalog(binary)))
    targets = set(config.CODEX_CLI_MODEL_MAP.values())
    catalog["models"] = [m for m in catalog["models"] if m["slug"] in targets]
    if {m["slug"] for m in catalog["models"]} != targets:
        raise CodexUnavailable("text-only catalog lacks required Astra/Sol models")
    for model in catalog["models"]:
        model.update(tool_mode="direct", multi_agent_version=None,
                     apply_patch_tool_type=None, experimental_supported_tools=[])
    (Path(work) / "text-models.json").write_text(json.dumps(catalog), encoding="utf-8")

# 0.155 emits this startup notice as an item named "error", before the turn
# starts, even when code_mode is disabled and a text answer succeeds. It
# confirms the coding host is unavailable; it is not a model/tool failure.
_CODE_MODE_DISABLED_NOTICE = (
    "Code Mode is unavailable because code-mode host is disabled. "
    "Code mode will fail closed; enable `features.code_mode_host` and install "
    "`codex-code-mode-host`."
)


def build_argv(binary, model, effort, work):
    work = Path(work).resolve()
    argv = [binary, "-a", "never", "exec", "--ignore-user-config", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--json",
            "--color", "never", "-m", model, "-C", str(work),
            "-o", str(work / "answer.txt")]
    overrides = {
        "model_provider": "openai", "forced_login_method": "chatgpt",
        "model_reasoning_effort": effort,
        "model_instructions_file": str(work / "instructions.txt"),
        "model_catalog_json": str(work / "text-models.json"),
        "include_apps_instructions": False,
        "include_collaboration_mode_instructions": False,
        "include_environment_context": False,
        "tools.experimental_request_user_input.enabled": False,
        "tools.update_plan.enabled": False,
        "model_reasoning_summary": "none",
        "model_verbosity": "low",
        "web_search": "disabled", "project_doc_max_bytes": 0,
        "mcp_servers": {},
        # Silence the experimental flag banner, not runtime errors.
        "suppress_unstable_features_warning": True,
    }
    for key, value in overrides.items():
        argv += ["-c", f"{key}={json.dumps(value)}"]
    # skip_host_skill_discovery excludes user/project skills, but not bundled
    # skills. Disable those explicitly (names supported by the installed CLI).
    skills = ("imagegen", "openai-docs", "plugin-creator", "skill-creator", "skill-installer")
    argv += ["-c", "skills.config=[" + ",".join(
        '{name=' + json.dumps(s) + ',enabled=false}' for s in skills) + "]"]
    for feature in _DISABLED_FEATURES:
        argv += ["--disable", feature]
    argv += ["--enable", "skip_host_skill_discovery", "-"]
    return argv


def parse_events(stdout, diagnostics=None):
    """Do not treat commentary or a partial answer as a completed response."""
    usage = {"input_tokens": 0, "cached_input_tokens": 0,
             "output_tokens": 0, "reasoning_output_tokens": 0}
    terminal = None
    failure = None
    turn_started = False
    diagnostics = diagnostics if diagnostics is not None else {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise CodexUnavailable("malformed JSON event stream", usage) from None
        if not isinstance(event, dict):
            raise CodexUnavailable("invalid JSON event", usage)
        kind = event.get("type")
        counts = diagnostics.setdefault("event_types", {})
        counts[str(kind)] = counts.get(str(kind), 0) + 1
        if kind == "turn.started":
            terminal = None
            turn_started = True
        elif kind == "turn.completed":
            terminal = kind
            u = event.get("usage") or {}
            if not isinstance(u, dict):
                raise CodexUnavailable("invalid usage object", usage)
            for key in usage:
                value = u.get(key, 0)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise CodexUnavailable("invalid usage counter", usage)
                usage[key] += value
        elif kind in ("turn.failed", "error"):
            failure = "Codex reported a failed turn or error"
        elif kind in ("item.started", "item.completed"):
            item = event.get("item") or {}
            if not isinstance(item, dict):
                raise CodexUnavailable("invalid item event", usage)
            item_type = item.get("type")
            counts = diagnostics.setdefault("item_types", {})
            counts[str(item_type)] = counts.get(str(item_type), 0) + 1
            if (item_type == "error" and not turn_started
                    and item.get("message") == _CODE_MODE_DISABLED_NOTICE):
                diagnostics.setdefault("startup_notices", []).append("code_mode_host_disabled")
                continue
            # exec names planning updates todo_list (0.155); these carry no
            # external execution. Keep rejecting command/file/MCP/tool items.
            if item_type not in ("agent_message", "reasoning", "plan", "todo_list", None):
                failure = f"unexpected item type {str(item_type)[:80]!r} in a text-generation call"
    if failure:
        raise CodexUnavailable(failure, usage)
    if terminal != "turn.completed":
        raise CodexUnavailable("no successful terminal event", usage)
    return usage


class CodexCLIClient:
    usage_label = "Codex CLI"

    def __init__(self, fallback, *, binary=None, effort=None, fallback_mode="stop",
                 models=None, version=None, runner=None, root=None, timeout_s=None):
        self._fallback = fallback
        self._binary = binary or resolve_binary() or config.CODEX_CLI_BIN
        self._effort = effort or dict(config.CODEX_CLI_EFFORT_BY_TIER)
        self._fallback_mode = fallback_mode
        if fallback_mode not in ("stop", "api"):
            raise ValueError("Codex fallback must be stop or api")
        self._models = models or {m: list(config.CODEX_CLI_EFFORTS)
                                  for m in config.CODEX_CLI_MODEL_MAP.values()}
        self._version = version
        self._run = runner or run_process
        self._root = root
        self._timeout = timeout_s or config.CODEX_CLI_TIMEOUT_S
        self._unavailable = False
        self._api = None
        self.usage = {"calls": 0, "input": 0, "cache_write": 0,
                      "cache_read": 0, "output": 0, "thinking": 0}
        self.by_stage = {}
        self.notional_usd = 0.0
        self.last_call = None

    @staticmethod
    def _tier(context):
        ctx = context or {}
        return ctx.get("tier") or getattr(ctx.get("blueprint"), "tier", None)

    def mapped_model(self, stage, model, context=None):
        pin = config.resolve_stage_pin(stage, self._tier(context))
        if pin:
            if pin[0] != "claude":
                return None
            model = pin[1]
        # Match configured IDs and older persisted Opus/Sonnet IDs.
        if model in config.CODEX_CLI_MODEL_MAP:
            return config.CODEX_CLI_MODEL_MAP[model]
        if model.startswith("claude-opus-"):
            return "gpt-6-astra"
        if model.startswith("claude-sonnet-"):
            return "gpt-5.6-sol"
        return None

    def effort_for(self, stage, context=None):
        if stage not in config.CODEX_CLI_EFFORT_STAGES:
            return config.CODEX_CLI_EFFORT_BASELINE
        if isinstance(self._effort, dict):
            return self._effort.get(self._tier(context), config.CODEX_CLI_EFFORT_BASELINE)
        return self._effort

    def call(self, ledger, stage, model, max_tokens, system, user, context=None):
        target = self.mapped_model(stage, model, context)
        if target is None:
            return self._fallback.call(ledger, stage, model, max_tokens, system, user, context)
        effort = self.effort_for(stage, context)
        if effort not in self._models.get(target, []):
            raise APIExhausted(f"Codex CLI {target} does not support effort {effort!r}")
        try:
            if self._unavailable:
                raise CodexUnavailable("CLI unavailable earlier in this run")
            return self._invoke(ledger, stage, target, effort, system, user, context)
        except (CodexUnavailable, OSError, subprocess.SubprocessError) as e:
            self._unavailable = True
            # Do not echo arbitrary stderr: it may contain prompt text or auth data.
            reason = str(e) if isinstance(e, CodexUnavailable) else type(e).__name__
            if self._fallback_mode == "stop":
                raise APIExhausted(f"Codex CLI stopped at {stage}: {reason}") from e
            print(f"  [codex] {stage}: {reason}; explicit API fallback -> {target}/{effort}")
            from .providers import OpenAIClient, provider_key_present
            if not provider_key_present("openai"):
                raise APIExhausted("OpenAI API key missing for the selected fallback") from e
            if self._api is None:
                self._api = OpenAIClient()
            # The old model's non-thinking ceiling is insufficient on a paid
            # reasoning endpoint. Its guard must price the full new ceiling.
            ceiling = max_tokens + config.REASONING_HEADROOM[effort]
            ctx = dict(context or {}, cli_reasoning_effort=effort)
            return self._api.call(ledger, stage, target, ceiling, system, user, ctx)

    def _invoke(self, ledger, stage, model, effort, system, user, context):
        # Retain artifacts: project rules forbid automatic deletion. Only the
        # stage instructions and final answer are files; the user prompt is stdin.
        work = Path(tempfile.mkdtemp(prefix="rc-codex-", dir=self._root))
        (work / "instructions.txt").write_text(system, encoding="utf-8", newline="\n")
        meta = {"stage": stage, "model": model, "effort": effort,
                "transport": "codex-cli", "cli_version": self._version,
                "tier": self._tier(context),
                "blueprint_id": getattr((context or {}).get("blueprint"), "blueprint_id", None),
                "status": "started"}
        def save():
            (work / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        save()
        self.last_call = meta
        usage = {"input_tokens": 0, "cached_input_tokens": 0,
                 "output_tokens": 0, "reasoning_output_tokens": 0}
        try:
            write_text_catalog(self._binary, work)
            result = self._run(build_argv(self._binary, model, effort, work), user,
                               self._timeout, cwd=str(work), env=subscription_env())
            usage = parse_events(result.stdout or "", meta.setdefault("events", {}))
            if result.returncode:
                raise CodexUnavailable(f"process exited {result.returncode}")
            # -o contains ONLY the final response, unlike agent_message events
            # which may contain commentary on some CLI versions.
            answer = (work / "answer.txt").read_text(encoding="utf-8").strip()
            if not answer:
                raise CodexUnavailable("empty final answer")
            ledger.record(stage, model, 0, 0)
            meta.update(status="completed", api_cost_usd=0)
            return answer, False
        except BaseException as e:
            usage = getattr(e, "usage", None) or usage
            meta.update(status="failed", error_type=type(e).__name__)
            raise
        finally:
            self._book(stage, model, usage)
            meta["usage"] = usage
            save()

    def _book(self, stage, model, usage):
        # Codex cached_input_tokens is INCLUDED in input_tokens. Normalize to
        # the existing summary's exclusive input/cache-read buckets.
        inp, out = usage["input_tokens"], usage["output_tokens"]
        cached = min(inp, usage["cached_input_tokens"])
        self.usage["calls"] += 1
        self.usage["input"] += inp - cached
        self.usage["cache_read"] += cached
        self.usage["output"] += out
        self.usage["thinking"] += usage["reasoning_output_tokens"]
        rate_in, rate_out = config.MODEL_RATES[model]
        cost = ((inp - cached) * rate_in + cached * config.MODEL_RATES_CACHED_IN.get(model, rate_in)
                + out * rate_out) / 1e6
        self.notional_usd += cost
        d = self.by_stage.setdefault(stage, {"calls": 0, "usd": 0.0})
        d["calls"] += 1
        d["usd"] += cost
        print(f"  [codex] {stage} -> {model} (CLI usage recorded; no API spend)")

    def usage_report(self):
        from .claude_code import ClaudeCodeClient
        return ClaudeCodeClient.usage_report(self)

    def __getattr__(self, name):
        return getattr(self._fallback, name)
