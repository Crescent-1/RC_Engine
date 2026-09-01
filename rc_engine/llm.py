"""LLM access layer: cost ledger with a hard pre-call budget guard, exhaustion
detection, and a deterministic mock client for $0 end-to-end testing.

THE COST INVARIANT
------------------
CostLedger.guard(stage, prompt_chars, model, max_tokens) computes the WORST
CASE cost of the next call:

    worst = est_input_tokens * rate_in + max_tokens * rate_out

where est_input_tokens deliberately overestimates (chars // 3). If
spent + worst > budget, BudgetExceeded is raised BEFORE any tokens are
bought. The pipeline treats this as: skip (solver/judge) or abort the RC
(core stages). An RC therefore cannot exceed its tier budget — not
approximately, structurally.

Amendment (budget slack): a few stages listed in config.BUDGET_GUARD_SLACK
carry a small per-stage tolerance so the deliberately-conservative estimate
does not strand a fully-paid, novelty-clean passage on a worst case that
rarely materializes. For those stages the bound is spend <= budget * (1 +
slack) — e.g. the questions stage on the hard tier may overshoot by at most
~$0.033. Every other stage keeps the strict budget ceiling.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field

from . import config
from .models import CostLine


class BudgetExceeded(RuntimeError):
    def __init__(self, stage: str, worst: float, spent: float, budget: float):
        super().__init__(
            f"stage '{stage}' worst-case ${worst:.4f} would push spend "
            f"${spent:.4f} past budget ${budget:.4f}")
        self.stage = stage


class APIExhausted(RuntimeError):
    """Rate limit / credits / overload — stop the batch cleanly."""


@dataclass
class CostLedger:
    budget_usd: float
    spent_usd: float = 0.0
    lines: list[CostLine] = field(default_factory=list)

    def estimate_input_tokens(self, text: str) -> int:
        return max(1, len(text) // config.CHARS_PER_TOKEN_ESTIMATE)

    def worst_case(self, prompt_chars: int, model: str, max_tokens: int) -> float:
        rate_in, rate_out = config.MODEL_RATES[model]
        est_in = max(1, prompt_chars // config.CHARS_PER_TOKEN_ESTIMATE)
        return (est_in / 1e6) * rate_in + (max_tokens / 1e6) * rate_out

    def guard(self, stage: str, prompt_chars: int, model: str, max_tokens: int):
        worst = self.worst_case(prompt_chars, model, max_tokens)
        # The worst-case estimate is deliberately ~25-30% conservative (chars//3 +
        # the full max_tokens ceiling), so it aborts on false positives. A few
        # stages carry a small slack so a fully-paid, novelty-clean passage is
        # never stranded for a worst case that almost never materializes. The
        # tier invariant becomes: spend <= budget * (1 + slack) on that one stage.
        slack = config.BUDGET_GUARD_SLACK.get(stage, 0.0)
        if self.spent_usd + worst > self.budget_usd * (1.0 + slack):
            raise BudgetExceeded(stage, worst, self.spent_usd, self.budget_usd)

    def record(self, stage: str, model: str, in_tok: int, out_tok: int) -> float:
        rate_in, rate_out = config.MODEL_RATES[model]
        cost = (in_tok / 1e6) * rate_in + (out_tok / 1e6) * rate_out
        self.spent_usd += cost
        self.lines.append(CostLine(stage, model, in_tok, out_tok, cost))
        return cost


def resolve_effort(stage: str, context: dict | None) -> str | None:
    """Look up STAGE_EFFORT[stage][tier] when configured. Shared by every
    provider client; each interprets the value in its own API's terms."""
    table = getattr(config, "STAGE_EFFORT", None) or {}
    by_tier = table.get(stage) or {}
    if not by_tier:
        return None
    ctx = context or {}
    tier = ctx.get("tier")
    if not tier:
        bp = ctx.get("blueprint")
        tier = getattr(bp, "tier", None) if bp is not None else None
    if not tier:
        return None
    return by_tier.get(tier)


def extract_json(text: str) -> dict:
    """Tolerant JSON extraction: strips fences and trailing prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = cleaned.rstrip("`").rstrip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in response: {cleaned[:300]!r}")
    obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    return obj


class LLMClient:
    """Real Anthropic client wrapper. call() enforces the ledger guard,
    records actuals, and normalizes exhaustion errors."""

    def __init__(self):
        from anthropic import Anthropic
        self._client = Anthropic()

    def call(self, ledger: CostLedger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None) -> tuple[str, bool]:
        """Returns (text, truncated). Raises BudgetExceeded / APIExhausted."""
        from anthropic import APIConnectionError, APIStatusError, RateLimitError

        ledger.guard(stage, len(system) + len(user), model, max_tokens)
        # Sonnet 5 runs adaptive thinking by default when `thinking` is omitted;
        # Opus 4.8 (the pinned OPUS) does not, but Opus 5 does — so this stays
        # explicit rather than relying on the omission default, and survives
        # repinning OPUS either way. Thinking tokens count against max_tokens,
        # so every
        # small-ceiling call would stop at max_tokens ("truncated") and bill
        # the thinking at output rates. The whole budget model — the stage
        # ceilings, TIER_BUDGET_USD, and the worst-case guard above — assumes
        # no thinking, so turn it off explicitly rather than by omission.
        #
        # `disabled` is only accepted at effort <= high; STAGE_EFFORT uses
        # "low" or the API default (high), so this stays valid. Turning
        # thinking ON is a deliberate quality/cost decision: it needs bigger
        # max_tokens and bigger tier budgets, not just this flag.
        extra: dict = {}
        if model in (config.SONNET, config.OPUS):
            if (model == config.OPUS
                    and getattr(config, "OPUS_THINKING", False)
                    and stage in getattr(config, "THINKING_STAGES", ())):
                # Experiment path only (RC_ENGINE_OPUS_THINKING). "adaptive" is
                # the sole on-mode on Opus 4.8/5 — budget_tokens is removed and
                # returns 400.
                #
                # Gated on STAGE, not just model. Both render and questions run
                # on OPUS, so keying this on the model alone turned thinking on
                # for render too — while only questions got the raised ceiling —
                # and render truncated. Every stage named here has a matching
                # ceiling in config._THINKING_CEILINGS.
                extra["thinking"] = {"type": "adaptive"}
            else:
                extra["thinking"] = {"type": "disabled"}
        # Optional effort (output_config) — e.g. medium-tier Opus at "low".
        # Resolved from context["tier"] when present, else from blueprint.tier.
        effort = self._resolve_effort(stage, context)
        if effort:
            extra["output_config"] = {"effort": effort}
        try:
            resp = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                **extra,
            )
        except (RateLimitError, APIConnectionError) as e:
            raise APIExhausted(str(e)) from e
        except APIStatusError as e:
            status = getattr(e, "status_code", None)
            msg = str(e).lower()
            if status in (429, 402, 529) or "credit balance" in msg or "quota" in msg:
                raise APIExhausted(str(e)) from e
            raise
        text = "".join(b.text for b in resp.content if b.type == "text")
        ledger.record(stage, model, resp.usage.input_tokens, resp.usage.output_tokens)
        return text, resp.stop_reason == "max_tokens"

    @staticmethod
    def _resolve_effort(stage: str, context: dict | None) -> str | None:
        return resolve_effort(stage, context)


# ---------------------------------------------------------------------------
# Mock client — deterministic canned outputs for $0 end-to-end testing.
# The pipeline passes a `context` dict per call; the mock uses it to produce
# structurally valid outputs that satisfy every downstream check.
# ---------------------------------------------------------------------------

_FILLER = [
    "The claim under examination resists the customary reading in ways that repay attention.",
    "What looks like a settled matter turns out to depend on a distinction rarely made explicit.",
    "The evidence, considered without the usual framing, points in a less comfortable direction.",
    "A second look at the founding assumption shows how much weight it has been carrying.",
    "Nothing in the record requires the conclusion so often drawn from it.",
    "The alternative account explains the same facts while asking for considerably less.",
    "Here the argument turns, though the turn is easy to miss on a first reading.",
    "The cost of this concession becomes visible only when the ledger is totalled.",
]


class MockLLMClient:
    """Deterministic stand-in. Still exercises the ledger guard so budget
    logic is tested; records zero-cost lines."""

    def call(self, ledger: CostLedger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None) -> tuple[str, bool]:
        ledger.guard(stage, len(system) + len(user), model, max_tokens)
        ledger.record(stage, model, 0, 0)  # zero-cost line keeps the audit trail
        ctx = context or {}
        fn = getattr(self, f"_{stage}", None)
        if fn is None:
            raise ValueError(f"MockLLMClient has no handler for stage {stage!r}")
        return fn(ctx), False

    # -- stage handlers ------------------------------------------------------

    def _refine(self, ctx) -> str:
        bp = ctx["blueprint"]
        mechs = ctx["mechanisms"]
        briefs = [{"para": p.para, "gist": f"mock gist for {p.function.lower().replace('_', ' ')}"}
                  for p in bp.movement]
        n = len(bp.movement)
        traps = [
            {"trap_id": "TR1", "anchor_para": 1,
             "invited_misreading": "the opening framing is the author's settled view",
             "mechanism": mechs[0]},
            {"trap_id": "TR2", "anchor_para": max(2, n - 2),
             "invited_misreading": "the steelmanned rival position is endorsed",
             "mechanism": mechs[1]},
            {"trap_id": "TR3", "anchor_para": n,
             "invited_misreading": "the ending resolves more than it does",
             "mechanism": mechs[0]},
        ]
        return json.dumps({
            "topic": "the credibility of institutional expertise (mock topic)",
            "tension_system": {
                "primary": {"axis": "expertise versus lived experience", "poles": ["expert", "practitioner"], "fate": "left_open"},
                "secondary": {"axis": "measurement versus meaning", "poles": ["quantifier", "interpreter"], "fate": "displaced"},
                "interaction": "the secondary tension surfaces inside the primary's strongest example",
            },
            "paragraph_briefs": briefs,
            "trap_map": traps,
            "title_hint": "Mock Essay on Expertise",
        })

    def _render(self, ctx) -> str:
        bp = ctx["blueprint"]
        rng = random.Random(bp.blueprint_id)
        paras = []
        for p in bp.movement:
            target = (p.len_words[0] + p.len_words[1]) // 2
            words, sentences = 0, []
            while words < target:
                s = rng.choice(_FILLER)
                sentences.append(s)
                words += len(s.split())
            paras.append(" ".join(sentences))
        return "\n\n".join(paras)

    def _compliance(self, ctx) -> str:
        bp = ctx["blueprint"]
        passage = ctx["passage"]
        counts = [len(p.split()) for p in passage.split("\n\n") if p.strip()]
        rng = random.Random(bp.blueprint_id + "curve")
        curve = [round(rng.uniform(-0.5, 0.9), 2) for _ in bp.movement]
        return json.dumps({
            "paragraphs": [
                {"para": p.para, "function_guess": p.function, "matches_plan": True,
                 "word_count": counts[i] if i < len(counts) else 0}
                for i, p in enumerate(bp.movement)
            ],
            "thesis_first_visible_para": bp.revelation_detail.get("planned_para", len(bp.movement) - 1),
            "commitment_curve": curve,
            "traps_present": [t["trap_id"] for t in bp.trap_map],
            "forbidden_tics_found": [],
            # mock renderer is "obedient": realized posture == planned posture
            "closing_posture_guess": ctx.get("planned_posture", "resolution_qualified"),
            "final_line_is_aphorism": False,
            "notes": "mock compliance pass",
        })

    def _seed_classify(self, ctx) -> str:
        # Vary the genre across mock seeds so a dry run exercises the topic
        # shape filter rather than always taking the same branch.
        from . import config
        genres = sorted(g for g in config.SEED_GENRES if g != "unknown")
        rng = random.Random(str(ctx.get("seed", ""))[:200])
        g = rng.choice(genres)
        return json.dumps({
            "genre": g, "domain": rng.choice(["science", "history", "social"]),
            "concrete_particulars": ["a mock particular"],
            "bipolar_dispute_available": rng.random() < 0.5,
            "one_line": "mock seed classification"})

    def _move_signature(self, ctx) -> str:
        # Deterministic per passage, but genuinely varied across passages —
        # a mock that returned one fixed signature would make every selftest
        # set breach the move_signature gate against its siblings.
        from . import config
        vocab = list(config.RHETORICAL_MOVES)
        rng = random.Random(ctx.get("passage", "")[:400])
        k = rng.randint(5, 8)
        return json.dumps({"moves": rng.sample(vocab, k)})

    def _answerability(self, ctx) -> str:
        # The mock's questions are canned filler, so there is nothing real to
        # judge: report clean rather than inventing warnings that would make
        # every selftest set look defective.
        n = len(ctx.get("questions") or []) or 8
        return json.dumps({"questions": [
            {"q": i, "answerable": True, "unique": True,
             "contenders": [], "note": "mock"} for i in range(1, n + 1)]})

    def _solver_tiebreak(self, ctx) -> str:
        return json.dumps({"supported": "ambiguous", "evidence": "",
                           "reason": "mock tiebreak"})

    def _questions(self, ctx) -> str:
        bp = ctx["blueprint"]
        mechs = ctx["mechanisms"]
        rng = random.Random(bp.blueprint_id + "q")
        questions = []
        for i, slot in enumerate(ctx["slots"], start=1):
            # EXCEPT slots invert the contract: the wrong options are the
            # statements the passage supports (see question_engine._validate).
            is_except = slot["type"] == "except_scan"
            wrong = []
            for j in range(3):
                mech = "passage_supported" if is_except else mechs[j % 2]
                wrong.append({
                    "text": f"A plausible but flawed reading of the passage's position on point {i}.{j + 1}, "
                            f"phrased at matching register and length.",
                    "mechanism": mech,
                    "why_wrong": (f"{mech} — the passage states this directly at that point."
                                  if is_except else
                                  f"{mech} — distorts the passage's actual bridge at that point."),
                })
            questions.append({
                "q": i, "slot_type": slot["type"],
                "stem": f"Mock {slot['type'].replace('_', ' ')} question probing the passage's "
                        f"{slot['target']} movement (difficulty {slot['difficulty']}).",
                "correct": {
                    "text": f"The reading that tracks the passage's actual {slot['type'].replace('_', ' ')} "
                            f"without over- or under-claiming, item {i}.",
                    "why_right": "matches the structural bridge the blueprint designed for this slot.",
                },
                "wrong": wrong,
            })
            rng.random()
        return json.dumps({"questions": questions})

    def _solver(self, ctx) -> str:
        key = ctx["letter_plan"]
        return json.dumps({
            "domain": "sociology_institutions_modernity",
            "answers": [
                {"q": i + 1, "answer": key[i], "confidence": "certain", "reasoning": "mock agreement"}
                for i in range(config.QUESTIONS_PER_SET)
            ],
        })

    def _judge(self, ctx) -> str:
        dims = ctx["dimensions"]
        return json.dumps({
            "scores": {d: {"score": 8, "note": "mock"} for d in dims},
            "average": 8.0,
            "verdict": "approve",
        })
