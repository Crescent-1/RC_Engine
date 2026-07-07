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
        if self.spent_usd + worst > self.budget_usd:
            raise BudgetExceeded(stage, worst, self.spent_usd, self.budget_usd)

    def record(self, stage: str, model: str, in_tok: int, out_tok: int) -> float:
        rate_in, rate_out = config.MODEL_RATES[model]
        cost = (in_tok / 1e6) * rate_in + (out_tok / 1e6) * rate_out
        self.spent_usd += cost
        self.lines.append(CostLine(stage, model, in_tok, out_tok, cost))
        return cost


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
        # thinking tokens count against max_tokens, so every small-ceiling call
        # stops at max_tokens ("truncated"). The budget model assumes no thinking.
        extra = {"thinking": {"type": "disabled"}} if model == config.SONNET else {}
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

    def _questions(self, ctx) -> str:
        bp = ctx["blueprint"]
        mechs = ctx["mechanisms"]
        rng = random.Random(bp.blueprint_id + "q")
        questions = []
        for i, slot in enumerate(ctx["slots"], start=1):
            wrong = []
            for j in range(3):
                wrong.append({
                    "text": f"A plausible but flawed reading of the passage's position on point {i}.{j + 1}, "
                            f"phrased at matching register and length.",
                    "mechanism": mechs[j % 2],
                    "why_wrong": f"{mechs[j % 2]} — distorts the passage's actual bridge at that point.",
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
                for i in range(6)
            ],
        })

    def _judge(self, ctx) -> str:
        dims = ctx["dimensions"]
        return json.dumps({
            "scores": {d: {"score": 8, "note": "mock"} for d in dims},
            "average": 8.0,
            "verdict": "approve",
        })
