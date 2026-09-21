"""Claude Code as a generation backend, with the API behind it.

WHY (2026-09-18)
----------------
A claude.ai subscription seat and the Anthropic API bill from different
pockets. When the API pocket is empty the engine can still reach the same
models through Claude Code's headless mode (`claude -p`), which answers one
non-interactive turn and prints the result. That gives the lane the operator
actually wants:

    rc_engine -> claude code -> (error / usage limit) -> API

This module is the first rung. It honours the same contract as every other
client in this codebase —

    call(ledger, stage, model, max_tokens, system, user, context)

— so nothing in the pipeline changes: every gate, novelty channel,
fingerprint and DB write behaves exactly as it does on an API run.

THE FALLBACK IS THE POINT
-------------------------
`fallback` is another client (normally providers.RoutedClient). A Claude Code
call that hits a usage limit, times out, returns nothing usable, or cannot
find the binary at all is retried once on the fallback, and the reason is
printed the first time it happens. Subscription runs require their pinned
checking providers to remain available rather than substituting another model.

`prefer_fallback_after_limit` (default on) makes a usage limit STICKY for the
rest of the process: once the subscription is out, every later stage goes
straight to the API instead of paying a ~10s subprocess timeout each time to
rediscover the same wall.

WHAT IT CANNOT PRESERVE
-----------------------
Claude Code is an agent harness, not a raw model endpoint, so three things
differ from an API call and all three are worth knowing before treating a
Claude-Code set as an API set:

  - HARNESS CONTEXT — mostly SOLVED, see _LEAN_FLAGS (2026-09-19). The first
    cut of this module carried 21-36k tokens of tool schemas and user
    customizations on every call, and one render looped eight times using Bash
    and Write to `wc -w` its own passage: ~1M tokens for a single medium set.
    `--tools "" --safe-mode` takes the same trivial prompt from 42,451 tokens
    to 694. Lean mode is the default; pass lean=False to measure the old
    behaviour. What remains is ordinary prompt and response.
  - SYSTEM PROMPT. --system-prompt SUBSTITUTES Claude Code's own (verified
    2.1.276), which is why "replace" is the default and is as close to the
    API's `system=` field as this surface gets. On a build without that flag,
    or behind a .cmd shim where prompt text cannot go on argv, it degrades to
    "inline": the stage prompt at the top of the stdin turn under a
    "=== SYSTEM ===" rule, the same shape relay.py uses.
  - max_tokens has no CLI equivalent. The stage ceilings still drive the
    API fallback's budget guard, but they do not bound the CLI response.
    Truncation is still detected — the result envelope reports stop_reason —
    and render/questions still validate what comes back regardless.
  - --effort follows CLAUDE_CODE_EFFORT_BY_TIER for questions, with low effort
    elsewhere. These harness levels do not reproduce API thinking=disabled.

COST LEDGER
-----------
Subscription-billed calls spend no API money, so they book a zero-cost line
exactly as MockLLMClient and RelayClient do: the audit trail keeps the call,
and the tier budget guard cannot abort a free run. The notional cost Claude
Code reports is printed and totalled in the run summary. Calls that fall through to the API
book real money through the fallback client, as they should.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

from . import config
from .cli_runtime import subscription_env

# Usage/rate limits, as they arrive from the CLI. Deliberately broad: the cost
# of a false positive is one unnecessary fallback to the API, and the cost of a
# false negative is a stalled batch.
_LIMIT_RE = re.compile(
    r"usage limit|rate limit|limit reached|too many requests|quota|"
    r"resets? at|upgrade to|out of (?:credits|usage)", re.I)


# Failures the CLI itself describes as temporary, which are worth another
# attempt rather than a fallback to the paid API. Deliberately NARROW — the
# mirror image of _LIMIT_RE above. A false positive here costs a wasted
# subprocess and a few seconds; a false positive in _LIMIT_RE costs nothing but
# one fallback, which is why that one is allowed to be broad and this one is
# not. Only conditions that name themselves transient belong here.
_TRANSIENT_RE = re.compile(
    r"refresh oauth token|another claude code process|usually transient|"
    r"overloaded|temporarily unavailable|connection (?:reset|refused|error)|"
    r"socket hang up|ECONNRESET|ETIMEDOUT|EAI_AGAIN|\b5(?:02|03|29)\b", re.I)


class ClaudeCodeUnavailable(RuntimeError):
    """Claude Code could not answer this call; the fallback should.

    `transient` marks a condition the CLI calls temporary — an OAuth refresh
    collision, an overloaded upstream — which _invoke retries before handing
    the stage to the paid API (2026-09-21)."""

    def __init__(self, *args, transient: bool = False):
        super().__init__(*args)
        self.transient = transient


def resolve_binary(binary: str | None = None) -> str | None:
    """Full path to an executable that can be handed an argv array safely.

    Prefers the NATIVE exe over npm's .CMD shim. Measured 2026-09-18: a .cmd
    is executed through cmd.exe, which interprets < > & | ^ % in ARGUMENTS as
    shell syntax, and a system prompt containing an angle bracket died with
    "The system cannot find the file specified" before reaching the model.
    Engine prompts carry those characters routinely, so the shim cannot be
    trusted with prompt content. npm's shim is a two-line wrapper around
    bin/claude.exe, which takes argv verbatim."""
    binary = binary or config.CLAUDE_CODE_BIN
    if os.path.isfile(binary):
        return binary
    path = shutil.which(binary)
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat")):
        native = os.path.join(os.path.dirname(path), "node_modules",
                              "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.isfile(native):
            return native
    return path


def argv_is_shell_safe(path: str) -> bool:
    """False for a .cmd/.bat shim — see resolve_binary."""
    return not path.lower().endswith((".cmd", ".bat"))


# Flags that strip Claude Code back to something close to a raw model call.
# MEASURED 2026-09-19 on 2.1.276, same trivial prompt, twice each:
#
#   no flags                 42,451 tokens   $0.2019
#   --safe-mode only         27,988 tokens   $0.0572   (tool schemas remain)
#   --tools "" only          68,459 tokens   $0.6847   (customizations remain)
#   --tools "" --safe-mode      694 tokens   $0.0071   <- 61x less, reproducible
#
# BOTH are needed and they remove different things:
#   --tools ""    drops the built-in tool schemas (~23k of cached input per
#                 call) AND, more importantly, removes the agent's ability to
#                 loop. Before this, one render ran EIGHT internal turns: the
#                 model used Bash and Write to save its own passage to a temp
#                 file and run `wc -w` on it until it hit the word target. That
#                 is 10x the tokens, unsanctioned disk I/O, and a capability
#                 the API path does not have — so removing it is a fidelity
#                 gain, not just a saving.
#   --safe-mode   stops CLAUDE.md, skills, plugins, hooks, MCP servers and
#                 custom agents being loaded into EVERY call. None of it is
#                 wanted: the engine supplies the entire prompt. Auth, model
#                 selection and permissions are unaffected (unlike --bare).
#
# NOT --bare, ever: it forces "Anthropic auth is strictly ANTHROPIC_API_KEY or
# apiKeyHelper", i.e. it bypasses OAuth — which is the subscription this whole
# lane exists to use. It would silently move the batch onto a dead API key.
#
# NOT --disallowed-tools: measured worse than doing nothing (4 turns and 2.6x
# the tokens) because the model reasons harder when a tool is refused than when
# it was never offered.
_LEAN_FLAGS = ("--tools", "", "--safe-mode")


def _argv(binary: str, model: str, system: str, user: str, *,
          system_mode: str, effort: str | None = None, lean: bool = True,
          extra: tuple = ()) -> tuple[list[str], str]:
    """Build the headless invocation, and the turn piped to it on stdin.

    ONE place on purpose. Claude Code's flag surface moves faster than this
    engine does, so a renamed flag is a one-function edit — and probe() reports
    which spellings the installed build actually accepts.

    Verified against Claude Code 2.1.276 (2026-09-18):
      - --max-turns is NOT in this build; passing it fails the call.
      - --allowed-tools rejects an empty value, so tool definitions cannot be
        stripped this way. They ride along as ~21-36k cached input tokens per
        call; see the module docstring.
      - the user turn goes on STDIN, never argv: argv is capped near 32k chars
        on Windows and a questions prompt carries a whole passage.
    """
    argv = [binary, "-p", "--model", model, "--output-format", "json"]
    if lean:
        argv += list(_LEAN_FLAGS)
    # --effort is Claude Code's equivalent of the API's output_config.effort,
    # and the one fidelity gap this surface CAN close (2.1.276 accepts
    # low|medium|high|xhigh|max).
    if effort:
        argv += ["--effort", effort]
    turn = user
    if system_mode == "append":
        argv += ["--append-system-prompt", system]
    elif system_mode == "replace":
        argv += ["--system-prompt", system]
    else:                                      # "inline"
        turn = f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n"
    argv += list(extra)
    return argv, turn


def _extract(stdout: str) -> str:
    """Pull the answer out of --output-format json.

    The envelope carries the text in `result`. Falls back to the raw stdout so
    a CLI build that prints plain text still works."""
    raw = (stdout or "").strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except ValueError:
        return raw                              # plain-text build
    if isinstance(obj, list):                   # stream-json, last result wins
        obj = next((o for o in reversed(obj)
                    if isinstance(o, dict) and o.get("type") == "result"), {})
    if not isinstance(obj, dict):
        return raw
    if obj.get("is_error"):
        raise ClaudeCodeUnavailable(str(obj.get("result") or obj.get("error")
                                        or "claude code reported an error"))
    for key in ("result", "text", "content", "response"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return raw


def _envelope_of(stdout: str) -> dict:
    """The result envelope as a dict, or {} for a plain-text build."""
    try:
        obj = json.loads((stdout or "").strip())
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _stop_reason(stdout: str) -> str | None:
    """stop_reason from the result envelope, when the build reports one."""
    return _envelope_of(stdout).get("stop_reason")


def probe(binary: str | None = None) -> dict:
    """$0 check: is Claude Code usable, and which flags does this build take?

    Returns {ok, path, version, flags, detail}. `flags` reports the spellings
    _argv depends on, so a rename shows up here rather than as a batch of
    silent fallbacks."""
    binary = binary or config.CLAUDE_CODE_BIN
    path = resolve_binary(binary)
    if not path:
        return {"ok": False, "path": None, "version": None, "flags": {},
                "detail": f"{binary!r} is not on PATH — install it with "
                          f"`npm install -g @anthropic-ai/claude-code`"}
    out = {"ok": True, "path": path, "version": None, "flags": {}, "detail": "ok"}
    try:
        # `path`, never `binary`: on Windows the npm shim is claude.CMD, and
        # CreateProcess cannot exec a bare name that resolves through PATHEXT.
        r = subprocess.run([path, "--version"], capture_output=True, text=True,
                           encoding="utf-8", timeout=30, env=subscription_env())
        if r.returncode:
            raise ClaudeCodeUnavailable(f"version check exited {r.returncode}")
        out["version"] = (r.stdout or r.stderr or "").strip() or None
    except Exception as e:
        out["ok"] = False
        out["detail"] = f"{type(e).__name__}: {e}"
        return out
    try:
        r = subprocess.run([path, "--help"], capture_output=True, text=True,
                           encoding="utf-8", timeout=30, env=subscription_env())
        helptext = (r.stdout or "") + (r.stderr or "")
        for flag in ("--print", "--model", "--output-format",
                     "--append-system-prompt", "--system-prompt"):
            out["flags"][flag] = flag in helptext
        if not out["flags"].get("--system-prompt"):
            out["detail"] = ("ok, but this build has no --system-prompt: set "
                             "RC_ENGINE_CC_SYSTEM_MODE=inline")
    except Exception as e:
        out["detail"] = f"version ok, --help failed ({type(e).__name__}: {e})"
    try:
        r = subprocess.run([path, "auth", "status", "--json"], capture_output=True,
                           text=True, encoding="utf-8", timeout=30, env=subscription_env())
        auth = json.loads(r.stdout)
        if r.returncode or not auth.get("loggedIn") or auth.get("authMethod") != "claude.ai":
            raise ClaudeCodeUnavailable("Claude subscription login required (claude auth login)")
    except Exception:
        out.update(ok=False, detail="Claude subscription login could not be verified; run claude auth login")
    return out


class ClaudeCodeClient:
    """Runs a stage through `claude -p`, with `fallback` behind it."""

    def __init__(self, fallback, *, binary: str | None = None,
                 model_map: dict | None = None, timeout_s: int | None = None,
                 system_mode: str | None = None, runner=None, sleep=None,
                 prefer_fallback_after_limit: bool = True,
                 stages: set[str] | None = None, provider: str | None = None,
                 effort: str | None = None, lean: bool | None = None):
        self._fallback = fallback
        self._binary = resolve_binary(binary) or binary or config.CLAUDE_CODE_BIN
        self._map = model_map if model_map is not None else config.CLAUDE_CODE_MODEL_MAP
        self._timeout = timeout_s or config.CLAUDE_CODE_TIMEOUT_S
        self._system_mode = system_mode or config.CLAUDE_CODE_SYSTEM_MODE
        # A .cmd shim cannot be trusted with prompt content on argv, so the
        # system prompt has to travel inside the stdin turn instead.
        if not argv_is_shell_safe(str(self._binary)) and self._system_mode != "inline":
            print(f"  [cc] {os.path.basename(str(self._binary))} is a shell shim - "
                  f"forcing system_mode=inline so prompt text stays off argv")
            self._system_mode = "inline"
        self._effort = (effort if effort is not None
                        else (config.CLAUDE_CODE_EFFORT
                              or dict(config.CLAUDE_CODE_EFFORT_BY_TIER))) or "auto"
        self._lean = config.CLAUDE_CODE_LEAN if lean is None else lean
        self._run = runner or self._subprocess
        self._sleep = sleep or time.sleep   # injectable: tests never wait
        self._sticky = prefer_fallback_after_limit
        self._stages = stages
        self._provider = provider or config.ACTIVE_PROVIDER
        self._limited = False                   # subscription wall hit this run
        self._announced: set[str] = set()
        self.notional_usd = 0.0                 # what the subscription lane saved
        self.usage = {"calls": 0, "input": 0, "cache_write": 0,
                      "cache_read": 0, "output": 0, "thinking": 0}
        self.by_stage: dict[str, dict] = {}

    # -- routing -------------------------------------------------------------

    @staticmethod
    def _tier_of(context: dict | None) -> str | None:
        ctx = context or {}
        bp = ctx.get("blueprint")
        return ctx.get("tier") or (getattr(bp, "tier", None) if bp is not None else None)

    def _should_run(self, stage: str, context: dict | None) -> bool:
        """Same rule as relay.py: only the calls that would have cost Anthropic
        money. A stage pinned to another provider is cheap and already working;
        routing it through a subprocess would be slower and no cheaper."""
        if self._stages is not None:
            return stage in self._stages
        pin = config.resolve_stage_pin(stage, self._tier_of(context))
        if pin is not None:
            return pin[0] == "claude"
        return self._provider == "claude"

    # -- the contract --------------------------------------------------------

    def call(self, ledger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None):
        if not self._should_run(stage, context) or (self._sticky and self._limited):
            return self._fallback.call(ledger, stage, model, max_tokens, system,
                                       user, context)
        # 2026-09-20: dollar guards belong to the paid fallback. Applying an
        # API-price estimate here can strand a zero-API-cost subscription call.
        try:
            text, truncated = self._invoke(stage, model, system, user, ledger,
                                           max_tokens, context)
        except ClaudeCodeUnavailable as e:
            self._degrade(stage, str(e))
            return self._fallback.call(ledger, stage, model, max_tokens, system,
                                       user, context)
        ledger.record(stage, model, 0, 0)       # subscription-billed: $0 of API
        return text, truncated

    def __getattr__(self, name):
        return getattr(self._fallback, name)

    # -- invocation ----------------------------------------------------------

    def _subprocess(self, argv: list[str], turn: str, timeout: int):
        # The turn goes on STDIN, never argv: Windows caps a command line near
        # 32k chars and a questions prompt carries a whole passage. cwd is
        # deliberately not the project — a text generation call has no business
        # being able to see the repo even in principle.
        return subprocess.run(argv, input=turn, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout,
                              cwd=os.path.expanduser("~"),
                              env=subscription_env())

    def _effort_for(self, stage: str, context: dict | None) -> str | None:
        """Effort for this call.

        Three shapes, in order of precedence:
          - a dict: per-tier, e.g. {"medium": "high", "elite": "max"}. A tier
            missing from the map gets the provider default (no flag sent).
          - "auto": honours the engine's own STAGE_EFFORT table, which pins
            medium render/questions to "low" as a cost trade on the API path.
          - any other string: that level on every stage and tier.
        """
        eff = self._effort
        if eff == "auto":
            from .llm import resolve_effort
            return resolve_effort(stage, context)
        # The per-tier ladder applies to the questions stage alone; everything
        # else sits on the baseline floor. See CLAUDE_CODE_EFFORT_STAGES — this
        # mirrors THINKING_STAGES, which reached the same answer by measurement.
        if stage not in config.CLAUDE_CODE_EFFORT_STAGES:
            # A stage may sit above the floor without joining the tier ladder;
            # render does (2026-09-21). See CLAUDE_CODE_EFFORT_BY_STAGE.
            return (config.CLAUDE_CODE_EFFORT_BY_STAGE.get(stage)
                    or config.CLAUDE_CODE_EFFORT_BASELINE or None)
        if isinstance(eff, dict):
            return eff.get(self._tier_of(context)) or None
        return eff

    def _invoke(self, stage, model, system, user, ledger, max_tokens,
                context=None) -> tuple[str, bool]:
        """One stage, with a bounded retry on transient CLI failures.

        MEASURED 2026-09-21: 1 live call in 4 lost the OAuth token refresh to
        the Claude Code session the operator was driving the engine from, and
        the stage fell straight through to the API — a paid Opus render on a
        lane whose entire purpose is to spend no API money. Retried here first;
        a usage limit still latches and never retries. See
        config.CLAUDE_CODE_TRANSIENT_RETRIES."""
        attempts = max(0, config.CLAUDE_CODE_TRANSIENT_RETRIES) + 1
        for attempt in range(1, attempts + 1):
            try:
                return self._attempt(stage, model, system, user, ledger,
                                     max_tokens, context)
            except ClaudeCodeUnavailable as e:
                if attempt == attempts or not getattr(e, "transient", False):
                    raise
                print(f"  [cc] {stage}: {e} - retry {attempt}/{attempts - 1}")
                self._sleep(config.CLAUDE_CODE_TRANSIENT_BACKOFF_S * attempt)

    def _attempt(self, stage, model, system, user, ledger, max_tokens,
                 context=None) -> tuple[str, bool]:
        cli_model = self._map.get(model, model)
        argv, turn = _argv(self._binary, cli_model, system, user,
                           system_mode=self._system_mode, lean=self._lean,
                           effort=self._effort_for(stage, context))
        try:
            r = self._run(argv, turn, self._timeout)
        except FileNotFoundError:
            raise ClaudeCodeUnavailable(
                f"{self._binary!r} not found — `npm install -g "
                f"@anthropic-ai/claude-code`, or set RC_ENGINE_CLAUDE_CODE_BIN")
        except subprocess.TimeoutExpired:
            raise ClaudeCodeUnavailable(f"timed out after {self._timeout}s")
        except Exception as e:
            raise ClaudeCodeUnavailable(f"{type(e).__name__}: {e}")

        stdout = getattr(r, "stdout", "") or ""
        stderr = getattr(r, "stderr", "") or ""
        rc = getattr(r, "returncode", 0)
        envelope = _envelope_of(stdout)

        if rc != 0 or envelope.get("is_error"):
            # ONLY the error channel is scanned for a usage limit.
            #
            # The first cut scanned stdout+stderr before looking at the exit
            # code, which meant it searched the MODEL'S OWN OUTPUT. Measured
            # 2026-09-18 on the first real render: the generated passage
            # tripped the limit pattern, the sticky flag latched, and every
            # later stage fell through to the API on a set that had been
            # produced perfectly well. A passage about immigration quotas or
            # a deadline that "resets at" midnight must not look like a
            # billing wall.
            detail = (stderr.strip()
                      or str(envelope.get("result") or envelope.get("error") or "")
                      or stdout.strip())
            if _LIMIT_RE.search(detail):
                self._limited = True
                raise ClaudeCodeUnavailable(
                    "subscription usage limit reached"
                    + (" — every later stage goes straight to the API"
                       if self._sticky else ""))
            # Tested AFTER the limit, never before: a real wall must latch even
            # if its wording happens to look temporary.
            raise ClaudeCodeUnavailable(
                f"exit {rc}: {detail[:200]}",
                transient=bool(_TRANSIENT_RE.search(detail)))

        text = _extract(stdout)
        if not text.strip():
            raise ClaudeCodeUnavailable("empty response")
        self._book_notional(stdout, stage, ledger, model, max_tokens)
        # The envelope reports stop_reason, so truncation is detected here the
        # same way llm.LLMClient detects it, rather than always claiming False
        # and leaving it to a downstream validator.
        return text, _stop_reason(r.stdout) == "max_tokens"

    def _book_notional(self, stdout, stage, ledger, model, max_tokens):
        """Record what this call consumed of the SUBSCRIPTION, for reporting.

        Never touches ledger.spent_usd: a subscription call spends no API
        money, and inflating the ledger would let the tier guard abort a free
        run. But "free" is only true of API dollars — the quota is real and
        finite, so the tokens and the notional list price are totalled here and
        printed at the end of the batch. Without this the operator has no way
        to answer "how many sets can I still generate?" (2026-09-18)."""
        env = _envelope_of(stdout)
        try:
            reported = float(env.get("total_cost_usd") or 0.0)
        except (TypeError, ValueError):
            reported = 0.0
        self.notional_usd += reported or ledger.worst_case(0, model, max_tokens)

        # 2026-09-21 controlled Claude/Codex A/B: Claude's top-level `usage`
        # covered only the requested Sonnet/Opus response, while `modelUsage`
        # also reported a Haiku helper on every call. The displayed token total
        # was therefore 30,119 although the subscription actually processed
        # 43,915 tokens across models. Prefer the complete per-model ledger;
        # fall back to `usage` for older/plain envelopes. Never add both.
        models = env.get("modelUsage")
        if isinstance(models, dict) and any(isinstance(v, dict) for v in models.values()):
            values = [v for v in models.values() if isinstance(v, dict)]
            u = {
                "input_tokens": sum(int(v.get("inputTokens") or 0) for v in values),
                "cache_creation_input_tokens": sum(
                    int(v.get("cacheCreationInputTokens") or 0) for v in values),
                "cache_read_input_tokens": sum(
                    int(v.get("cacheReadInputTokens") or 0) for v in values),
                "output_tokens": sum(int(v.get("outputTokens") or 0) for v in values),
                "output_tokens_details": {"thinking_tokens": sum(
                    int(v.get("thinkingTokens") or 0) for v in values)},
            }
        else:
            u = env.get("usage") if isinstance(env.get("usage"), dict) else {}
        agg = self.usage
        agg["calls"] += 1
        for key, field in (("input", "input_tokens"),
                           ("cache_write", "cache_creation_input_tokens"),
                           ("cache_read", "cache_read_input_tokens"),
                           ("output", "output_tokens")):
            try:
                agg[key] += int(u.get(field) or 0)
            except (TypeError, ValueError):
                pass
        try:
            agg["thinking"] += int(
                (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
        except (TypeError, ValueError, AttributeError):
            pass
        per = self.by_stage.setdefault(stage, {"calls": 0, "usd": 0.0})
        per["calls"] += 1
        per["usd"] += reported

        if stage not in self._announced:
            self._announced.add(stage)
            print(f"  [cc] {stage} answered by Claude Code (no API spend)")

    def usage_report(self) -> list[str]:
        """Lines for the batch summary. Empty when the lane never ran."""
        a = self.usage
        if not a["calls"]:
            return []
        billable = a["input"] + a["cache_write"] + a["cache_read"] + a["output"]
        breakdown = ", ".join(f"{stage} x{d['calls']}"
                              for stage, d in sorted(self.by_stage.items()))
        lines = [
            f"--- {getattr(self, 'usage_label', 'Claude Code')} subscription usage (NOT API spend) ---",
            f"  calls                {a['calls']} ({breakdown})",
            f"  tokens               in {a['input']:,} | cache-write "
            f"{a['cache_write']:,} | cache-read {a['cache_read']:,} | out "
            f"{a['output']:,}"
            + (f" (thinking {a['thinking']:,})" if a["thinking"] else ""),
            f"  total tokens         {billable:,}",
            f"  notional list price  ${self.notional_usd:.4f} "
            f"— what these calls WOULD have cost on the API; the subscription "
            f"is metered in usage, not dollars, so treat this as a relative "
            f"meter between runs, not a bill",
        ]
        return lines

    def _degrade(self, stage: str, reason: str):
        key = f"degrade:{stage}"
        if key not in self._announced:
            self._announced.add(key)
            print(f"  [cc] {stage}: {reason} - falling back to the API")
