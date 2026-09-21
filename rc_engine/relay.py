"""Human relay: run the Anthropic-bound stages through a chat window.

WHY (2026-09-18)
----------------
When the Anthropic API has no credit but a claude.ai seat does, the engine
can still run. Every model call in this codebase goes through one contract —

    call(ledger, stage, model, max_tokens, system, user, context)

— which llm.MockLLMClient and providers.RoutedClient already implement. This
module adds a third implementation: for the stages that WOULD have hit
Anthropic, it writes the exact prompt to disk, puts it on the clipboard, and
waits for the operator to paste the model's reply back. Everything
downstream — novelty channels, compliance, fingerprints, gates, the DB, the
export — is untouched, so a relayed set is audited on exactly the same terms
as an API set.

This is deliberately NOT MANUAL_GENERATION_PROMPT.md. That file is a
hand-written approximation that loses the composed blueprint, the component
draws, the trap map and the generation policy. The relay sends the real
prompt the API would have received.

WHICH STAGES RELAY
------------------
Exactly the calls that would have cost Anthropic money. Most checking stages
are pinned to openai/gpt-5.6-luna in config.STAGE_MODEL_PINS and keep running
normally, so on a hard/elite set the operator pastes four times (refine,
render, questions, solver) and the other eight stages run unattended. The
pin table is the single source of truth here — a stage that is repinned
later changes lanes automatically, with no edit to this file.

WHAT IT CANNOT PRESERVE
-----------------------
Three fidelity gaps, all of them the chat surface's rather than this
module's, and all worth knowing before treating a relayed set as an API set:

  - `system` is a separate API field; a chat has no equivalent. The default
    inlines it above the user turn under a "=== SYSTEM ===" rule. With
    system_mode="project" it is written once per (stage, policy) under
    relay/_system/ instead, to live in a claude.ai Project's instructions,
    and the pasted text is then the user turn alone — which is the higher
    fidelity of the two.
  - llm.py sends thinking={"type": "disabled"} on every Opus/Sonnet call and
    the whole ceiling and budget model assumes it (see config.THINKING_STAGES
    and the 2026-08-11 probe). A chat cannot disable thinking.
  - output_config.effort (config.STAGE_EFFORT) has no chat equivalent.

A relayed set is therefore the same PROMPT, not the same sampling
conditions. That is precisely why it is worth relaying through the pipeline
rather than generating in a bare chat: the gates get to decide whether the
result is shippable, instead of the operator guessing.

CONTROL FLOW
------------
The paste loop reuses the exceptions the pipeline already understands rather
than inventing new ones:
  - "skip"  -> BudgetExceeded, which optional stages (solver, judge,
               answerability) already treat as "note it and carry on", and
               core stages already treat as a clean abort of that RC.
  - "abort" -> APIExhausted, which run_batch already treats as "stop the
               batch with the finished work committed".

COST LEDGER
-----------
A relayed call spends no API money, so it books a zero-cost line exactly as
MockLLMClient does: the audit trail keeps the call, and the tier budget
guard cannot abort a run that is free. The would-be cost is printed per call
so the operator can see what the paste saved.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time

from . import config
from .llm import APIExhausted, BudgetExceeded

# Written verbatim into the paste text. Deliberately bare: any editorializing
# preamble ("follow these carefully…") is a change to the prompt, and the
# whole point of the relay is that the prompt is the one the API would have
# seen. Two rules and nothing else.
_INLINE_FRAME = "=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n"

_SKIP_WORDS = {"skip", "s"}
_ABORT_WORDS = {"abort", "quit", "stop"}


def _ps(command: str, **kw) -> subprocess.CompletedProcess:
    """Run one PowerShell command with the profile suppressed."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", timeout=30, **kw)


def copy_file_to_clipboard(path: str) -> bool:
    """Put a UTF-8 file's contents on the clipboard.

    Goes through the FILE rather than stdin on purpose: piping into
    PowerShell hands the text to the console's codepage, and this project's
    prompts are full of em-dashes and curly quotes that do not survive the
    round trip. -Encoding UTF8 on a file read does."""
    literal = path.replace("'", "''")
    try:
        r = _ps(f"Get-Content -Raw -Encoding UTF8 -LiteralPath '{literal}' "
                f"| Set-Clipboard")
        return r.returncode == 0
    except Exception:                                # no powershell, timeout
        return False


def read_clipboard() -> str:
    """Current clipboard text, or "" if it cannot be read."""
    try:
        r = _ps("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                "Get-Clipboard -Raw")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


class RelayClient:
    """Wraps a client and diverts the Anthropic-bound stages to a paste loop.

    Wrap OUTERMOST — RelayClient(RoutedClient(base)) — so a stage the relay
    declines is still routed to its pinned provider as usual.
    """

    def __init__(self, base, root: str = "relay", *, system_mode: str = "inline",
                 stages: set[str] | None = None, provider: str | None = None,
                 input_fn=input, clipboard: bool = True, run_id: str | None = None,
                 api_first: bool = False):
        self._base = base
        self._root = root
        self._system_mode = system_mode
        self._stages = stages                    # None = auto (see _should_relay)
        self._provider = provider or config.ACTIVE_PROVIDER
        self._input = input_fn
        self._clipboard = clipboard
        self._run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self._n = 0
        self._systems_written: set[str] = set()
        self._api_first = api_first

    # -- routing -------------------------------------------------------------

    @staticmethod
    def _tier_of(context: dict | None) -> str | None:
        ctx = context or {}
        bp = ctx.get("blueprint")
        return ctx.get("tier") or (getattr(bp, "tier", None) if bp is not None else None)

    def _should_relay(self, stage: str, context: dict | None) -> bool:
        """True when this call would have spent Anthropic credit.

        An explicit stage set wins. Otherwise the pin table decides: a stage
        pinned to another provider runs there for real, and everything else
        follows the batch's provider."""
        if self._stages is not None:
            return stage in self._stages
        pin = config.resolve_stage_pin(stage, self._tier_of(context))
        if pin is not None:
            return pin[0] == "claude"
        return self._provider == "claude"

    # -- the contract --------------------------------------------------------

    def call(self, ledger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None):
        if not self._should_relay(stage, context):
            return self._base.call(ledger, stage, model, max_tokens, system,
                                   user, context)
        if self._api_first:
            try:
                return self._base.call(ledger, stage, model, max_tokens, system,
                                       user, context)
            except Exception as e:
                print(f"  [relay] API unavailable ({type(e).__name__}); manual fallback")
        # A manual response has no API cost. Paid base clients guard themselves.
        reply = self._relay(ledger, stage, model, max_tokens, system, user, context)
        ledger.record(stage, model, 0, 0)        # zero-cost line keeps the trail
        return reply, False

    def __getattr__(self, name):
        return getattr(self._base, name)

    # -- the paste loop ------------------------------------------------------

    def _run_dir(self) -> str:
        d = os.path.join(self._root, self._run_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _write_system(self, stage: str, system: str) -> str:
        """System prompt for one (stage, policy), written once per run.

        Keyed by content hash, not by stage: the generation policy can change
        the system prompt mid-batch (policy_catalog versions), and silently
        reusing the first one would be a lie about what was sent."""
        digest = hashlib.sha256(system.encode("utf-8")).hexdigest()[:8]
        d = os.path.join(self._root, "_system")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{stage}-{digest}.md")
        if digest not in self._systems_written:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(system)
            self._systems_written.add(digest)
        return path

    def _relay(self, ledger, stage, model, max_tokens, system, user, context):
        self._n += 1
        tier = self._tier_of(context) or "?"
        bp = (context or {}).get("blueprint")
        bp_id = getattr(bp, "blueprint_id", None)

        if self._system_mode == "project":
            paste = user
            sys_path = self._write_system(stage, system)
        else:
            paste = _INLINE_FRAME.format(system=system, user=user)
            sys_path = None

        d = self._run_dir()
        base = f"{self._n:02d}-{stage}"
        prompt_path = os.path.join(d, f"{base}.prompt.txt")
        with open(prompt_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(paste)

        would_cost = ledger.worst_case(len(system) + len(user), model, max_tokens)
        print(f"\n  [relay] {stage} | {model} | tier={tier}"
              + (f" | {bp_id}" if bp_id else ""))
        print(f"  [relay] {len(paste):,} chars -> {prompt_path}")
        print(f"  [relay] this call would have cost up to ${would_cost:.4f} on the API")
        if sys_path:
            print(f"  [relay] system prompt for the Project: {sys_path}")
        copied = self._clipboard and copy_file_to_clipboard(prompt_path)
        print("  [relay] prompt copied to clipboard." if copied
              else "  [relay] clipboard unavailable - open the file above and copy it.")

        return self._await_reply(stage, prompt_path, paste, d, base)

    def _await_reply(self, stage: str, prompt_path: str, paste: str,
                     d: str, base: str) -> str:
        """Block until the operator supplies a non-empty reply.

        Enter takes the clipboard, which is the fast path: copy the reply in
        the browser, press Enter, done. A path is accepted for a reply too
        long or too awkward to copy cleanly."""
        reply_path = os.path.join(d, f"{base}.reply.txt")
        while True:
            print(f"  -> paste into claude.ai, copy the reply, then press Enter."
                  f"\n     (or a file path holding the reply, 'skip', 'abort'): ", end="")
            answer = (self._input() or "").strip()
            low = answer.lower()
            if low in _ABORT_WORDS:
                raise APIExhausted(f"relay aborted by operator at stage '{stage}'")
            if low in _SKIP_WORDS:
                # Optional stages note this and carry on; core stages abort the
                # RC cleanly. Both behaviours already exist for budget skips.
                raise BudgetExceeded(stage, 0.0, 0.0, 0.0)

            if answer:
                candidate = answer.strip('"').strip("'")
                if not os.path.isfile(candidate):
                    print(f"  [relay] no file at {candidate!r} - try again.")
                    continue
                with open(candidate, "r", encoding="utf-8") as fh:
                    text = fh.read()
            else:
                text = read_clipboard()

            text = (text or "").strip()
            if not text:
                print("  [relay] empty reply - copy the model's answer first.")
                continue
            if text == paste.strip():
                # Enter pressed before copying the reply: the prompt this
                # module put there is still on the clipboard.
                print("  [relay] that is still the PROMPT on the clipboard - "
                      "copy the model's reply, then press Enter.")
                continue
            with open(reply_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print(f"  [relay] {len(text):,} chars accepted -> {reply_path}")
            return text
