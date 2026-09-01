"""Stage 5 — quality gates retained from the legacy pipeline, made
blueprint-aware: the judge rubric is derived from the blueprint instead of
assuming one universal structure."""

from __future__ import annotations

import json

from . import config
from .llm import CostLedger, extract_json
from .models import Blueprint

NL = chr(10)

SOLVER_SYSTEM = f"""You are an expert CAT VARC solver operating at a 99.9 percentile level.
You will receive a Reading Comprehension passage and {config.QUESTIONS_PER_SET} MCQs WITHOUT the answer key.
Solve honestly from the passage alone — reason from the text, do not guess what a
test-setter would want.

Confidence definitions:
- "certain": you would commit to it in a real CAT attempt
- "leaning": best answer after elimination, but one rival option survived scrutiny
- "torn": two options are genuinely defensible — name the rival in your reasoning

Respond ONLY with valid JSON, no markdown fences:
{{"answers": [{{"q": 1, "answer": "A", "confidence": "certain", "reasoning": "max 20 words"}}, ...exactly {config.QUESTIONS_PER_SET}...]}}"""


def blind_solve(llm, ledger: CostLedger, bp: Blueprint, passage: str,
                qdata: dict) -> dict:
    """Returns {"verdict": "ok"|"solver_error", "disputes": [...], ...}."""
    model, max_tokens = config.STAGE_CONFIG["solver"][bp.tier]
    lines = [passage, ""]
    for q in qdata["questions"]:
        lines.append(f"Q{q['q']}. {q['stem']}")
        for letter in "ABCD":
            lines.append(f"({letter}) {q['options'][letter]['text']}")
        lines.append("")
    user = "\n".join(lines)
    try:
        text, _ = llm.call(ledger, "solver", model, max_tokens, SOLVER_SYSTEM, user,
                           context={"letter_plan": qdata["letters"]})
        parsed = extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        return {"verdict": "solver_error", "error": str(e), "disputes": []}

    answers = {int(a["q"]): a for a in parsed.get("answers", [])
               if isinstance(a.get("q"), int) and a.get("answer")}
    disputes = []
    for q in qdata["questions"]:
        sa = answers.get(q["q"], {})
        letter = str(sa.get("answer", "")).strip().upper()
        if letter and letter != q["correct"]:
            disputes.append({"q": q["q"], "solver": letter, "key": q["correct"],
                             "confidence": sa.get("confidence"),
                             "reasoning": sa.get("reasoning", "")})
    return {"verdict": "ok", "answers": parsed.get("answers", []),
            "disputes": disputes,
            "comparable": len(answers) == config.QUESTIONS_PER_SET}


JUDGE_SYSTEM_TEMPLATE = """You are a strict, adversarial CAT VARC quality auditor. Assume the
set is mediocre until proven otherwise with evidence you can quote. You will receive
an RC set AND the hidden structural intent it was built to realize. Judge the set
against ITS OWN intent — do not impose a different structural ideal.

Score these dimensions 0-10 (7+ requires quoting evidence; without evidence max 6):
{dimensions}

Calibration: 0-3 failing; 4-6 needs revision; 7-8 mock-ready; 9-10 flagship.
Most sets deserve 5-7.

TERSENESS MANDATE: response must be COMPLETE valid JSON. Every note capped at 20 words.
Output ONLY valid JSON, no markdown fences:
{{
  "scores": {{{score_fields}}},
  "average": 0.0,
  "verdict": "approve | regenerate"
}}
Verdict "approve" only if every score >= 7 and average >= {threshold}."""


def build_judge_dimensions(bp: Blueprint, registry) -> dict[str, str]:
    family = registry.get("family", bp.family_id)
    ending = registry.get("ending", bp.ending_id)
    persona = registry.get("persona", bp.persona_id)
    return {
        "family_realization":
            f"does the passage genuinely execute '{family['name']}' — {family['core']} "
            f"— with difficulty arising from: {family['difficulty_source']}?",
        "ending_behavior":
            f"does the ending perform '{ending['name']}' ({ending['gesture']}) with "
            f"aperture '{bp.aperture}', rather than a generic conclusion? The intended "
            f"closing stance: {family['closing_posture'].replace('_', ' ')}.",
        "voice_consistency":
            f"does the prose stay in the '{persona['name']}' voice ({persona['register']}) "
            f"without generic AI-essay register, and does it show a touch of human texture "
            f"(one stubborn concrete particular; uneven polish; not every sentence "
            f"epigrammatic; not a run of abstract-noun openers)?",
        # Rewritten 2026-09-01. The old wording — "does every question have at
        # least one trap" — was a bar almost any set clears, and the scores
        # showed it: across 76 judged sets this dimension was 8 in 84% of them,
        # never scored below 7, and only ever took three values. A fifth of the
        # judge average could not express a failure, which inflated every score
        # toward 8 and compressed the range the 7.0 threshold works in.
        #
        # It is now COUNTABLE and pointed at the defect the corpus actually has:
        # the per-set correct-longest count is 1.74x overdispersed against
        # chance, and 10% of sets sit where "pick the longest" beats the set.
        # The length count is MEASURED and handed in (see `length_facts`), not
        # asked for. The first version of this rubric asked the judge to count
        # word lengths across 32 options; on the first batch it reported 7/8 and
        # 3 where the deterministic checker measured 2 and 2, and both errors
        # downgraded the set. That was the same mistake as the "silent tally"
        # this session removed from the question prompt: arithmetic an LLM
        # cannot do reliably, used as if it were evidence. The judge now scores
        # against a true number instead of producing one.
        "distractor_efficiency":
            "In how many of the questions is there at least one distractor a "
            "strong reader could genuinely choose? Count them and give the count "
            "in your note. Lexical extremity ('always', 'never') is a wasted "
            "distractor, not a trap. Name the trap type for the weakest question "
            "you found. Score bands, applied strictly, combining your count with "
            "the MEASURED length-bias figure given above: 9-10 = every question "
            "has a real trap AND correct-longest is 0-1; 7-8 = all but one AND "
            "correct-longest at most 2; 5-6 = two or more questions lack a real "
            "trap, OR correct-longest is 3; AT MOST 4 if correct-longest is 4 or "
            "more, because a length heuristic then beats the set however good "
            "the traps are.",
        "explanation_quality":
            "do wrong-option explanations name specific mechanisms tied to passage "
            "locations, never 'not mentioned' or 'too extreme'?",
    }


def judge_rc(llm, ledger: CostLedger, bp: Blueprint, rc_text: str,
             registry, length_facts: dict | None = None) -> dict:
    """length_facts: the deterministic length_bias_report for this set. Handed
    to the judge as fact so it scores against a measured number rather than one
    it estimated by eye — see the note in build_judge_dimensions."""
    dims = build_judge_dimensions(bp, registry)
    model, max_tokens = config.STAGE_CONFIG["judge"][bp.tier]
    dim_lines = "\n".join(f"- {k}: {v}" for k, v in dims.items())
    score_fields = ", ".join(f'"{k}": {{"score": 0, "note": "..."}}' for k in dims)
    system = JUDGE_SYSTEM_TEMPLATE.format(
        dimensions=dim_lines, score_fields=score_fields,
        threshold=config.JUDGE_SCORE_THRESHOLD)

    if length_facts and isinstance(length_facts.get("correct_longest_count"), int):
        n_q = config.QUESTIONS_PER_SET
        system += (
            f"{NL}{NL}MEASURED FACT (computed deterministically, not your "
            f"estimate — use it as given and do not recount): the correct option "
            f"is the strictly longest of its four in "
            f"{length_facts['correct_longest_count']} of the {n_q} questions"
            + (", including the thesis question"
               if length_facts.get("thesis_correct_longest") else "") + ".")

    user = rc_text
    for attempt in range(config.MAX_JUDGE_ATTEMPTS):
        try:
            text, truncated = llm.call(ledger, "judge", model, max_tokens, system,
                                       user, context={"dimensions": list(dims)})
            if truncated:
                # Retrying the identical prompt at the identical ceiling would
                # truncate identically — a guaranteed wasted call. Ask for a
                # shorter body before spending the second attempt.
                user = (rc_text + "\n\nYOUR PREVIOUS REPLY WAS CUT OFF. Emit the "
                        "same JSON with every note at most 8 words.")
                continue
            parsed = extract_json(text)
            if "average" in parsed and "verdict" in parsed:
                return parsed
        except (ValueError, json.JSONDecodeError):
            continue
    return {"scores": {}, "average": 0.0, "verdict": "judge_error"}
