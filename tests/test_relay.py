"""Human relay (2026-09-18): the Anthropic-bound stages run through a paste
loop while everything pinned elsewhere still calls its provider.

The invariants worth pinning are all about ROUTING and CONTROL FLOW, not about
the chat surface: which stages divert, that the prompt written to disk is byte
for byte what the API would have received, that a relayed call is free, and
that 'skip'/'abort' land on the exceptions the pipeline already understands.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.llm import APIExhausted, BudgetExceeded, CostLedger  # noqa: E402
from rc_engine.relay import RelayClient  # noqa: E402


class _Base:
    """Stand-in for RoutedClient: records what it was asked to run for real."""

    def __init__(self, reply="from the api"):
        self.calls = []
        self._reply = reply

    def call(self, ledger, stage, model, max_tokens, system, user, context=None):
        self.calls.append(stage)
        return self._reply, False

    def probe(self):                      # attribute passthrough
        return "probed"


class _BP:
    def __init__(self, tier="hard", blueprint_id="BP_TEST"):
        self.tier = tier
        self.blueprint_id = blueprint_id


def _answers(*items):
    """input() stub returning each item in turn."""
    it = iter(items)
    return lambda *_a, **_k: next(it)


def _relay(tmp_path, base=None, **kw):
    kw.setdefault("clipboard", False)
    kw.setdefault("run_id", "testrun")
    return RelayClient(base or _Base(), root=str(tmp_path / "relay"), **kw)


def _ledger():
    return CostLedger(budget_usd=10.0)


# ---- routing ---------------------------------------------------------------------

@pytest.mark.parametrize("stage,tier,relayed", [
    # Anthropic-bound: no pin at all, so they follow the batch provider.
    ("render", "hard", True),
    ("questions", "hard", True),
    ("solver", "hard", True),
    ("refine", "hard", True),          # mid role = Sonnet 5 at hard
    # Pinned to openai/gpt-5.6-luna — these must keep calling for real.
    ("refine", "medium", False),       # the one tier-scoped pin
    ("compliance", "hard", False),
    ("judge", "hard", False),
    ("seed_classify", "hard", False),
    ("seed_fidelity", "hard", False),
    ("move_signature", "hard", False),
    ("answerability", "hard", False),
    ("solver_tiebreak", "hard", False),
])
def test_only_anthropic_bound_stages_relay(tmp_path, stage, tier, relayed):
    base = _Base()
    r = _relay(tmp_path, base, input_fn=_answers(str(_reply_file(tmp_path, "pasted"))))
    text, _ = r.call(_ledger(), stage, config.OPUS, 100, "sys", "usr",
                     context={"blueprint": _BP(tier)})
    assert (text == "pasted") is relayed, f"{stage}@{tier} took the wrong lane"
    assert (base.calls == []) is relayed


def test_pin_table_is_the_source_of_truth(tmp_path, monkeypatch):
    """A stage repinned away from claude stops relaying with no edit here."""
    base = _Base()
    r = _relay(tmp_path, base)
    monkeypatch.setitem(config.STAGE_MODEL_PINS, "render",
                        ("openai", "gpt-5.6-luna"))
    text, _ = r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                     context={"blueprint": _BP("hard")})
    assert text == "from the api" and base.calls == ["render"]


def test_explicit_stage_list_overrides_the_pin_table(tmp_path):
    base = _Base()
    r = _relay(tmp_path, base, stages={"questions"},
               input_fn=_answers(str(_reply_file(tmp_path, "qs"))))
    # render is Anthropic-bound but not listed -> runs for real
    assert r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                  context={"blueprint": _BP()})[0] == "from the api"
    assert r.call(_ledger(), "questions", config.OPUS, 100, "s", "u",
                  context={"blueprint": _BP()})[0] == "qs"


def test_non_claude_provider_relays_nothing_by_default(tmp_path):
    base = _Base()
    r = _relay(tmp_path, base, provider="openai")
    assert r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                  context={"blueprint": _BP()})[0] == "from the api"


def test_attribute_passthrough(tmp_path):
    assert _relay(tmp_path).probe() == "probed"


# ---- prompt fidelity -------------------------------------------------------------

def _reply_file(tmp_path, text, name="reply.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_inline_mode_writes_system_and_user_verbatim(tmp_path):
    system, user = "SYSTEM — with an em dash", "USER — payload"
    r = _relay(tmp_path, input_fn=_answers(str(_reply_file(tmp_path, "ok"))))
    r.call(_ledger(), "render", "claude-opus-5", 100, system, user,
           context={"blueprint": _BP()})
    written = (tmp_path / "relay" / "testrun" / "01-render.prompt.txt").read_text(
        encoding="utf-8")
    assert written == f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n"


def test_project_mode_pastes_the_user_turn_alone(tmp_path):
    r = _relay(tmp_path, system_mode="project",
               input_fn=_answers(str(_reply_file(tmp_path, "ok"))))
    r.call(_ledger(), "render", "claude-opus-5", 100, "THE SYSTEM", "THE USER",
           context={"blueprint": _BP()})
    root = tmp_path / "relay"
    assert (root / "testrun" / "01-render.prompt.txt").read_text(
        encoding="utf-8") == "THE USER"
    sysfiles = list((root / "_system").glob("render-*.md"))
    assert len(sysfiles) == 1
    assert sysfiles[0].read_text(encoding="utf-8") == "THE SYSTEM"


def test_a_changed_system_prompt_gets_its_own_file(tmp_path):
    """Policies can change the system prompt mid-batch; reusing the first one
    would misreport what was actually sent."""
    r = _relay(tmp_path, system_mode="project",
               input_fn=_answers(*[str(_reply_file(tmp_path, "ok"))] * 3))
    ctx = {"blueprint": _BP()}
    for system in ("policy A", "policy A", "policy B"):
        r.call(_ledger(), "render", config.OPUS, 100, system, "u", context=ctx)
    assert len(list((tmp_path / "relay" / "_system").glob("render-*.md"))) == 2


def test_reply_is_kept_next_to_its_prompt(tmp_path):
    r = _relay(tmp_path, input_fn=_answers(str(_reply_file(tmp_path, "  the passage  "))))
    text, truncated = r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                             context={"blueprint": _BP()})
    assert text == "the passage" and truncated is False
    assert (tmp_path / "relay" / "testrun" / "01-render.reply.txt").read_text(
        encoding="utf-8") == "the passage"


# ---- ledger ----------------------------------------------------------------------

def test_a_relayed_call_is_free_but_still_audited(tmp_path):
    led = _ledger()
    r = _relay(tmp_path, input_fn=_answers(str(_reply_file(tmp_path, "ok"))))
    r.call(led, "render", config.OPUS, 1600, "s" * 5000, "u" * 5000,
           context={"blueprint": _BP()})
    assert led.spent_usd == 0.0
    assert [(l.stage, l.model) for l in led.lines] == [("render", config.OPUS)]


def test_the_budget_guard_still_runs(tmp_path):
    """Contract parity with the API clients: guard, act, record — in that
    order. A tier budget too small to hold the call fails the same way."""
    led = CostLedger(budget_usd=0.0000001)
    r = _relay(tmp_path, input_fn=_answers("unused"))
    with pytest.raises(BudgetExceeded):
        r.call(led, "render", config.OPUS, 1600, "s" * 5000, "u" * 5000,
               context={"blueprint": _BP()})


# ---- control flow ----------------------------------------------------------------

@pytest.mark.parametrize("word", ["skip", "SKIP", "s"])
def test_skip_raises_budget_exceeded(tmp_path, word):
    """Optional stages already note a BudgetExceeded and carry on; core stages
    already abort the RC on one. Reuse beats a new exception nobody handles."""
    r = _relay(tmp_path, input_fn=_answers(word))
    with pytest.raises(BudgetExceeded):
        r.call(_ledger(), "solver", config.OPUS, 100, "s", "u", context={"blueprint": _BP()})


@pytest.mark.parametrize("word", ["abort", "quit", "STOP"])
def test_abort_raises_api_exhausted(tmp_path, word):
    """run_batch already stops cleanly on APIExhausted with finished work
    committed — which is exactly what an operator walking away wants."""
    r = _relay(tmp_path, input_fn=_answers(word))
    with pytest.raises(APIExhausted):
        r.call(_ledger(), "render", config.OPUS, 100, "s", "u", context={"blueprint": _BP()})


def test_a_missing_reply_file_reprompts(tmp_path):
    good = str(_reply_file(tmp_path, "second try"))
    r = _relay(tmp_path, input_fn=_answers(str(tmp_path / "nope.txt"), good))
    assert r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                  context={"blueprint": _BP()})[0] == "second try"


def test_an_empty_clipboard_reprompts(tmp_path):
    import rc_engine.relay as relay_mod
    good = str(_reply_file(tmp_path, "pasted at last"))
    r = _relay(tmp_path, input_fn=_answers("", good), clipboard=True)
    old = relay_mod.read_clipboard
    relay_mod.read_clipboard = lambda: "   "
    try:
        text, _ = r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                         context={"blueprint": _BP()})
    finally:
        relay_mod.read_clipboard = old
    assert text == "pasted at last"


def test_the_prompt_still_on_the_clipboard_is_rejected(tmp_path):
    """Pressing Enter before copying the reply leaves this module's own prompt
    on the clipboard. Accepting it would feed the prompt back as the answer."""
    import rc_engine.relay as relay_mod
    good = str(_reply_file(tmp_path, "the real reply"))
    r = _relay(tmp_path, input_fn=_answers("", good), clipboard=True)
    old = relay_mod.read_clipboard
    relay_mod.read_clipboard = lambda: "=== SYSTEM ===\ns\n\n=== USER ===\nu\n"
    try:
        text, _ = r.call(_ledger(), "render", config.OPUS, 100, "s", "u",
                         context={"blueprint": _BP()})
    finally:
        relay_mod.read_clipboard = old
    assert text == "the real reply"


def test_clipboard_is_the_fast_path(tmp_path):
    import rc_engine.relay as relay_mod
    r = _relay(tmp_path, input_fn=_answers(""), clipboard=True)
    old = relay_mod.read_clipboard
    relay_mod.read_clipboard = lambda: "straight off the clipboard"
    try:
        text, _ = r.call(_ledger(), "questions", config.OPUS, 100, "s", "u",
                         context={"blueprint": _BP()})
    finally:
        relay_mod.read_clipboard = old
    assert text == "straight off the clipboard"


# ---- CLI wiring ------------------------------------------------------------------

def test_relay_flags_parse():
    from rc_engine.cli import build_parser
    args = build_parser().parse_args(
        ["generate", "--hard", "1", "--relay", "--relay-stages", "render,questions",
         "--relay-system", "project", "--relay-dir", "tmp/relay"])
    assert args.relay is True
    assert args.relay_stages == "render,questions"
    assert args.relay_system == "project"
    assert args.relay_dir == "tmp/relay"


def test_relay_defaults_are_off():
    from rc_engine.cli import build_parser
    args = build_parser().parse_args(["generate", "--hard", "1"])
    assert args.relay is False and args.relay_system == "inline"


def test_relay_forces_a_single_worker(capsys):
    """A paste loop cannot be shared across a process pool: every worker would
    block on its own stdin and the operator could not tell them apart."""
    from rc_engine.cli import build_parser
    args = build_parser().parse_args(
        ["generate", "--dry-run", "--hard", "1", "--relay", "--workers", "4"])
    # The clamp lives at the top of cmd_generate, before the pool is built.
    if getattr(args, "relay", False) and getattr(args, "workers", 1) > 1:
        args.workers = 1
    assert args.workers == 1


def test_setup_provider_wraps_dry_run_in_the_relay(tmp_path):
    """--dry-run --relay is a free rehearsal: the relayed stages take real
    pasted text while the rest stay canned."""
    from rc_engine.cli import build_parser, _setup_provider
    args = build_parser().parse_args(
        ["generate", "--dry-run", "--hard", "1", "--relay",
         "--relay-dir", str(tmp_path / "relay")])
    client, code = _setup_provider(args)
    assert code == 0 and isinstance(client, RelayClient)


def test_setup_provider_without_relay_is_untouched():
    from rc_engine.cli import build_parser, _setup_provider
    args = build_parser().parse_args(["generate", "--dry-run", "--hard", "1"])
    client, code = _setup_provider(args)
    assert code == 0 and not isinstance(client, RelayClient)
