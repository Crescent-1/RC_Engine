# Claude CLI review and Codex/Astra implementation plan

Implementation update, 2026-09-20: the user subsequently approved adding Codex
CLI and requested **all Opus roles -> Astra, all Sonnet roles -> Sol**, with
the Claude CLI thinking ladder. The opt-in `--codex-cli` implementation now
supersedes the narrower writer proposal below, and the six findings below
have fixes and regression coverage. See `RC_ENGINE_README.md` for the shipped
flags and `codex.md` for validation. The following review and proposal are
preserved as the original pre-implementation record.

Reviewed 2026-09-20, Asia/Calcutta. Scope: commit
`32acdaa6a192b7592d84021ef42a96dc8df7bc45` and its current engine integration
at HEAD `a2c0acf`. This is a review and implementation plan; no engine fixes
or Codex adapter have been implemented.

The existing `call(ledger, stage, model, max_tokens, system, user, context)`
boundary is suitable for Codex CLI. It preserves the blueprint, prompts,
generation policies, validators, novelty gates, persistence and export flow.
Fix the following problems before copying the Claude wrapper.

## Review findings

### 1. P1 — API credentials reach the supposedly subscription-only subprocess

`rc_engine/claude_code.py:350-352` starts the child without an explicit `env`.
`config._load_dotenv()` has already placed the project's API key in the
parent environment, and `_setup_provider()` even requires that key to exist.
The child therefore inherits it. Claude's current documentation says that
non-interactive `-p` uses `ANTHROPIC_API_KEY` whenever present, ahead of
subscription OAuth. A valid key can incur API charges while this wrapper
records zero dollars; an invalid key can prevent use of a working subscription.
This establishes a billing risk, not what historical runs actually billed.
[Claude authentication precedence](https://code.claude.com/docs/en/authentication#authentication-precedence)

Reproduction: injected a synthetic key and captured `subprocess.run`; the
effective child environment retained the key. No real credential was printed
or sent. Fix: isolate the child environment from API/cloud-provider overrides,
verify subscription authentication, and retain API credentials only in the
parent fallback client. Do not change the user's global environment.

### 2. P1 — Dry-run can invoke real generation

`rc_engine/cli.py:455-459` now wraps `MockLLMClient` with the real Claude
client. With `--dry-run --claude-code`, selected stages invoke `claude -p`;
only fallback/unselected stages use the mock. `_lane_spec()` also carries
the live lane into dry-run workers (`workers.py:139-144`). This contradicts
the project's guarantee that dry-run is offline and uses only the mock.

Reproduction: parsed those flags, mocked the free probe and intercepted
`_subprocess`; one render reached that subprocess boundary. No CLI model
request ran. Fix both sequential and worker setup so dry-run cannot select
a live adapter. Give any deliberate interactive rehearsal a distinct flag.

### 3. P2 — Reused workers overcount subscription usage

`rc_engine/workers.py:197-199` returns the worker client's lifetime totals
after each slot; line 342 adds each snapshot to the batch aggregate.
Process-pool workers survive across slots, so earlier calls are counted again.

Reproduction: two synthetic one-call slots in the same worker produced two
actual calls but three reported calls. Tokens, per-stage counts and notional
price have the same defect. Return per-slot deltas, or replace each worker's
previous snapshot by worker identity. Test more slots than workers.

### 4. P2 — The documented API-before-relay fallback does not happen

`rc_engine/cli.py:568-580` constructs
`ClaudeCodeClient(RelayClient(RoutedClient(base)))`. For selected stages,
`RelayClient.call()` immediately opens the paste loop (`relay.py:170-177`);
it never tries the base API first. Therefore a Claude CLI failure goes
straight to manual paste even when the API could answer.

Reproduction: failed the fake CLI with relay enabled; the paste handler ran
once and the API handler zero times. Implement a separate fallback-on-error
wrapper for the documented CLI -> API -> relay chain. Preserve direct
`--relay` behavior if that remains an intentional manual mode.

### 5. P2 — A subscription run cannot start without an Anthropic API key

`rc_engine/cli.py:463-467` aborts for a missing key before evaluating the
subscription lane. The later exception for a rejected key only handles a
present-but-invalid key. A valid Claude subscription plus the OpenAI key
needed for pinned checks is consequently insufficient.

Reproduction: mocked `provider_key_present()` to return None with
`--claude-code`; startup returned exit 1 and no client. Construct and verify
the selected lane first, and require credentials only for stages/fallbacks
that will actually use them. Keep checks explicit when a required pin lacks
its own credential; do not silently skip quality checks.

### 6. P2 — API budget estimates can reject a subscription call

`rc_engine/claude_code.py:329` and `rc_engine/relay.py:176` run the API-price
guard before the zero-API-cost operation. The guard estimates the full
hypothetical paid call, even though successful CLI/relay calls record zero.

Reproduction: a medium ledger with $0.30 already spent of $0.34 rejected a
synthetic 6,000-token questions call before the fake CLI ran. This can strand
a passage after earlier paid stages/fallbacks. Apply dollar guards at paid
API boundaries, including every fallback; give subscription work separate
time/call/quota controls. Keep all actual API spending limits intact.

## Codex CLI feasibility

Read-only checks on this machine:

- Installed native binary: `codex-cli 0.155.0-alpha.9.2`.
- `codex login status` outside the restricted review shell reports
  `Logged in using ChatGPT`. The restricted shell had reported `Not logged in`;
  that was an environment/access difference, not proof the user needed login.
- `codex debug models` lists `gpt-6-astra`. The CLI catalog advertises low,
  medium, high, xhigh, max and ultra. This is CLI capability information,
  not a successful generation or a guarantee of available quota.

Official documentation explicitly lists Astra for Codex CLI. Access varies
with account and client; keep the exact model ID and stop clearly if it is
unavailable. Do not silently substitute Sol or Terra.
[Codex models](https://learn.chatgpt.com/docs/models)

## Proposed implementation

### Phase 1 — Repair and test the shared behavior

Address all six findings above with focused regression tests. Extract only
the small shared pieces needed by both lanes: selection, subprocess launch,
fallback policy, invocation metadata and usage accumulation. Keep the two
providers' output parsers and authentication checks separate.

### Phase 2 — Add a default-off Codex adapter

Add `rc_engine/codex_cli.py` implementing the existing call contract. Start
with `render,questions` on `gpt-6-astra`. Leave refinement, the blind solver
and the pinned quality checks on their existing routes. This preserves a
separate solver and limits the first comparison to the writer. Those other
stages still need their configured API credentials and can incur API cost.
An optional explicit stage list can extend the lane later, including refine.

Start Astra render/questions at `medium`: the repository already has that
Astra-specific choice in `config.OPENAI_MODEL_STAGE_EFFORT`. Treat it as a
pilot baseline, not a proven optimum. Do not copy Claude's questions-only
high/xhigh/max ladder. Read supported efforts from the installed CLI catalog;
the older API capability table is not authoritative for this surface.

Proposed user-facing command (not implemented yet):

```powershell
python -m rc_engine.cli generate --hard 2 --codex-cli --codex-model gpt-6-astra --codex-stages render,questions --codex-effort medium --codex-fallback stop --workers 1
```

Provide the same lane options on `retry-questions` so a saved passage can
resume under the chosen writer. Reject conflicting Claude/Codex selections
and misspelled stages/efforts before starting a batch. Existing commands keep
their behavior when the new flag is absent. GUI integration is a later option.

The native child invocation should use `codex exec`, stdin for the user
prompt, `--json`, `--ephemeral`, `--skip-git-repo-check` and a dedicated working
directory. Consume final assistant output only after a successful terminal
event; reject failed, interrupted, empty or incomplete runs. Parse reported
usage from events. Add `--output-schema` for structured stages only when its
schema matches the engine's existing contract; passages remain text.
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)

Use `model_instructions_file` for the stage system prompt and
`model_reasoning_effort` for the requested effort. Require ChatGPT auth via
`forced_login_method="chatgpt"`. Use a sanitized child environment without
API-key overrides, retaining the user's existing CLI authentication store.
[Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

Use `--ignore-user-config` where supported to avoid unrelated user settings
while retaining authentication. Probe required flags before generation.
[CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)

The adapter needs a verified minimal tool/context configuration: read-only
sandbox, no approval prompts, web search disabled, shell execution disabled,
and no unrelated MCP, plugins, hooks, skills or repository instructions.
Changing cwd or choosing read-only alone does not remove tools or stop reads.
Confirm the effective prompt/tool inventory with local diagnostics and a
later authorized smoke call. Do not claim raw-API equivalence or a fully
tool-free harness until measured. Do not bypass organizational controls.

Use unique invocation paths for instruction/output files so retries and
workers cannot read stale answers. Honor the project's no-delete rule for
any retained run artifacts. Terminate the whole child process tree on timeout
or cancellation. CLI `max_tokens` parity is unverified: bound wall time and
retries, and retain the engine's passage/question validators.

### Phase 3 — Fallback, accounting and parallel support

- Default Codex failures to a clean stop with completed work preserved.
  Permit a paid fallback only through explicit `--codex-fallback api`.
  Resolve that fallback to the same Astra model and chosen effort using the
  OpenAI client; never pass the caller's old Claude model ID by accident.
  Reconcile API effort support and budget estimates before enabling it.
- Record actual model, transport, effort, CLI version, fallback reason,
  token usage and known/unknown authentication mode per call. Persist these
  separately from the dollar ledger so later quality comparisons are possible.
  An API-equivalent estimate is not a subscription bill or quota percentage.
- Distinguish tokens from API dollars. Cached input is a subset of input in
  Codex's usage format; do not add it a second time as the Claude format does.
  Check whether any reasoning counter is already included in output before
  summing it. Failed calls can consume usage too; retain reported counters.
- Serialize one complete lane specification into workers, including the
  resolved model/effort and fallback policy. Return per-slot usage deltas.
  After quota exhaustion, stop new dispatches or use only the authorized
  fallback; already-running calls may finish. Start the pilot with one worker.

### Phase 4 — Verification and rollout

Add `tests/test_codex_cli.py` with injected subprocess results covering
successful text/JSON, commentary vs final output, malformed events, terminal
failure after partial output, empty output, timeouts, cancellation, auth
failure, unsupported model/effort, quota exhaustion and fallback guards.

Test dry-run with subprocess/network methods that raise if called; test a
missing fallback key, non-ASCII and long prompts, Windows paths/metacharacters,
all tiers, pinned checks, resume behavior, and multiple slots per worker.
Run selftest, the focused suites, the complete engine suite and existing
policy goldens after implementation. Do not alter novelty thresholds or
registered policies to improve the writer's pass rate.

Only after a separately requested real generation run: verify a small Astra
pilot against comparable Claude outputs using passage length, question
validity, option balance, blind solver agreement, compliance, factual support,
seed fidelity, novelty, retry rate, latency and usage. Keep pilot outputs
separate from client delivery. Medium -> high/xhigh is an experiment, not
an automatic default change. Expand stage coverage and worker count after
the pilot provides evidence.

## Validation performed for this review

- 171 existing focused tests passed: `test_claude_code.py`, `test_relay.py`,
  `test_parallel_workers.py`, `test_review_fixes.py`.
- Six synthetic, in-memory reproduction checks confirmed the findings.
  Child calls, API calls and relay interaction were intercepted.
- Neither available Python initially had pytest. Installed pytest only in
  a temporary review directory. An initial stdin-based test launcher caused
  two Windows spawn failures; rerunning with `python -c` passed all 171.
- Read-only Codex version/help/login/model-catalog checks and official
  documentation checks completed. No live model smoke call or set generation
  ran. No production database, client export, engine source or existing test
  was edited. Full-suite testing and prose-quality comparison were not run.

Changes in this task are documentation only and uncommitted.
