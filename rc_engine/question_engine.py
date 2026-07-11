"""Stage 3 — QuestionEngine.

Questions are generated from the blueprint's question plan and trap map, not
reverse-engineered from the finished passage. The model returns options
UNLABELED with the correct one identified; letters are assigned locally from
the blueprint's sampled letter plan, so answer-letter bias is impossible by
construction (and costs zero tokens to enforce).
"""

from __future__ import annotations

import json
import random

from . import config
from .llm import CostLedger, extract_json
from .models import Blueprint

QUESTION_SYSTEM = """You are a senior CAT VARC question architect. You receive a passage,
its hidden structural blueprint (trap map, tension system, revelation schedule), and a
QUESTION PLAN of 6 slots. Write exactly one MCQ per slot, to spec.

DISTRACTOR RULES:
- Where a slot lists a trap_id, at least one wrong option must be exactly the
  misreading that trap invites — a fast reader who fell into the trap should find
  that option waiting for them.
- Every wrong option carries a named mechanism from the allowed list. Wrong options
  fail narrowly, not theatrically: no "completely", "never", "proves". Extremity must
  be conceptual, not lexical.
- All four options in a question: same register, parallel grammar, word counts within
  a spread of 8 words (longest at most 1.25x the shortest).
- In thesis/main-point slots the correct option must NOT be the longest of the four:
  write at least one wrong option with more words than the correct one.
- Correct options must not be systematically the most hedged; in at least 2 questions
  phrase the correct option more flatly than its strongest distractor.
- Application slots require a genuinely NEW scenario, not a paraphrase.

Respond ONLY with valid JSON, no markdown fences:
{
  "questions": [
    {
      "q": 1,
      "slot_type": "...",
      "stem": "...",
      "correct": {"text": "...", "why_right": "1-2 sentences naming the structural bridge"},
      "wrong": [
        {"text": "...", "mechanism": "...", "why_wrong": "one sentence, max 25 words, naming the error and the passage location it distorts"},
        {"text": "...", "mechanism": "...", "why_wrong": "..."},
        {"text": "...", "mechanism": "...", "why_wrong": "..."}
      ]
    },
    ...exactly 6...
  ]
}"""


class QuestionEngineError(RuntimeError):
    pass


class QuestionEngine:
    def __init__(self, registry, llm):
        self.registry = registry
        self.llm = llm

    def build(self, bp: Blueprint, passage: str, ledger: CostLedger,
              extra_guidance: str | None = None) -> dict:
        """Returns {"questions": [...], "letters": [...], "trap_usage": {...}}
        with letters already assigned per the blueprint's letter plan.
        extra_guidance: optional operator directives (e.g. from a resumed
        retry) appended verbatim to the user prompt."""
        model, max_tokens = config.STAGE_CONFIG["questions"][bp.tier]
        topo = self.registry.get("topology", bp.topology_id)
        profile = self.registry.get("distractor_profile", bp.distractor_profile_id)
        slots = self._assign_traps(topo["slots"], bp)

        user = self._prompt(bp, passage, slots, topo, profile)
        if extra_guidance:
            user += f"\n\nADDITIONAL DIRECTIVES:\n{extra_guidance}"
        last_err = None
        for _ in range(config.MAX_QUESTION_ATTEMPTS):
            text, truncated = self.llm.call(
                ledger, "questions", model, max_tokens, QUESTION_SYSTEM, user,
                context={"blueprint": bp, "slots": slots,
                         "mechanisms": [profile["primary"], profile["secondary"]]})
            try:
                data = extract_json(text)
                questions = self._validate(data, truncated)
                return self._letter_assign(questions, bp)
            except (ValueError, QuestionEngineError) as e:
                last_err = e
                user += ("\n\nYOUR PREVIOUS RESPONSE WAS INVALID: "
                         f"{e}. Emit complete, valid JSON exactly per schema.")
        raise QuestionEngineError(f"question generation failed: {last_err}")

    # ------------------------------------------------------------- internals

    def _assign_traps(self, slots: list[dict], bp: Blueprint) -> list[dict]:
        """Attach blueprint traps to the slots that can naturally harvest them."""
        slots = [dict(s) for s in slots]
        harvest_pref = {
            "premature_closure": ["thesis", "decoy_escape", "closure_reading"],
            "scope_inflation": ["thesis", "detail_check", "implicit_assumption"],
            "stance_misread": ["stance", "author_vs_reported"],
            "level_confusion": ["author_vs_reported", "stance", "implicit_assumption"],
        }
        unassigned = list(bp.trap_map)
        for trap in list(unassigned):
            prefs = harvest_pref.get(trap["mechanism"], [])
            for i, slot in enumerate(slots):
                if slot["type"] in prefs and "trap_id" not in slot:
                    slot["trap_id"] = trap["trap_id"]
                    unassigned.remove(trap)
                    break
        # remaining traps: attach to still-free slots in order
        for trap in unassigned:
            for slot in slots:
                if "trap_id" not in slot:
                    slot["trap_id"] = trap["trap_id"]
                    break
        return slots

    def _prompt(self, bp: Blueprint, passage: str, slots: list[dict],
                topo: dict, profile: dict) -> str:
        type_defs = self.registry.slot_type_definitions
        slot_lines = []
        for i, s in enumerate(slots, start=1):
            line = (f"  Q{i}: type={s['type']} — {type_defs[s['type']]} | "
                    f"target={s['target']} | difficulty={s['difficulty']}")
            if "trap_id" in s:
                trap = next(t for t in bp.trap_map if t["trap_id"] == s["trap_id"])
                line += (f" | HARVESTS {s['trap_id']}: one wrong option must be the "
                         f"misreading \"{trap['invited_misreading']}\" "
                         f"(mechanism: {trap['mechanism']})")
            slot_lines.append(line)
        style = topo.get("style_note", "")
        ts = bp.tension_system or {}
        return f"""PASSAGE:
{passage}

HIDDEN BLUEPRINT CONTEXT (never reveal to students):
- Primary tension: {ts.get('primary', {}).get('axis', 'n/a')} (fate: {ts.get('primary', {}).get('fate', 'n/a')})
- Thesis first visible: paragraph {bp.revelation_detail.get('planned_para')}
- Ending aperture: {bp.aperture}
- Allowed distractor mechanisms: {profile['primary']} (primary, use in ~2 questions),
  {profile['secondary']} (secondary), plus at most 2 other mechanisms from:
  {', '.join(self.registry.mechanisms)}

QUESTION PLAN ({topo['name']}{'; ' + style if style else ''}):
{chr(10).join(slot_lines)}

Write the 6 questions now as JSON."""

    def _validate(self, data: dict, truncated: bool) -> list[dict]:
        if truncated:
            raise QuestionEngineError("output truncated at max_tokens")
        qs = data.get("questions", [])
        if len(qs) != 6:
            raise QuestionEngineError(f"expected 6 questions, got {len(qs)}")
        for q in qs:
            if not q.get("stem") or not q.get("correct", {}).get("text"):
                raise QuestionEngineError(f"Q{q.get('q')} missing stem or correct option")
            if len(q.get("wrong", [])) != 3:
                raise QuestionEngineError(f"Q{q.get('q')} needs exactly 3 wrong options")
            for w in q["wrong"]:
                if not w.get("text") or not w.get("mechanism"):
                    raise QuestionEngineError(f"Q{q.get('q')} wrong option missing text/mechanism")
        return qs

    def _letter_assign(self, questions: list[dict], bp: Blueprint) -> dict:
        """Deterministic letter placement from the blueprint's letter plan."""
        rng = random.Random(bp.blueprint_id)
        out_questions = []
        trap_usage: dict[str, int] = {}
        for i, q in enumerate(questions):
            correct_letter = bp.letter_plan[i]
            letters = ["A", "B", "C", "D"]
            wrong_letters = [l for l in letters if l != correct_letter]
            wrongs = list(q["wrong"])
            rng.shuffle(wrongs)
            options = {correct_letter: {"text": q["correct"]["text"], "is_correct": True,
                                        "why": q["correct"].get("why_right", "")}}
            for letter, w in zip(wrong_letters, wrongs):
                options[letter] = {"text": w["text"], "is_correct": False,
                                   "mechanism": w["mechanism"],
                                   "why": w.get("why_wrong", "")}
                trap_usage[w["mechanism"]] = trap_usage.get(w["mechanism"], 0) + 1
            out_questions.append({
                "q": i + 1, "slot_type": q.get("slot_type", ""),
                "stem": q["stem"], "options": options, "correct": correct_letter})
        return {"questions": out_questions, "letters": list(bp.letter_plan),
                "trap_usage": trap_usage}


# ---------------------------------------------------------------------------
# Assembly: build the exportable RC text (same shape the legacy exports expect)
# ---------------------------------------------------------------------------

def assemble_rc_text(bp: Blueprint, passage: str, qdata: dict) -> str:
    lines = ["[PASSAGE]", "", passage, "", "[QUESTIONS]", ""]
    for q in qdata["questions"]:
        lines.append(f"Q{q['q']}. {q['stem']}")
        for letter in "ABCD":
            lines.append(f"({letter}) {q['options'][letter]['text']}")
        lines.append("")
    lines += ["[ANSWER KEY & ELIMINATION LOGIC]", ""]
    for q in qdata["questions"]:
        lines.append(f"Q{q['q']} — Correct answer: ({q['correct']})")
        lines.append(f"  ({q['correct']}) CORRECT — {q['options'][q['correct']]['why']}")
        for letter in "ABCD":
            opt = q["options"][letter]
            if not opt["is_correct"]:
                lines.append(f"  ({letter}) {opt.get('mechanism', 'error')} — {opt['why']}")
        lines.append("")
    src = bp.seed.get("title") or bp.topic or "original"
    lines.append(f"[Inspired by: \"{src}\", "
                 f"{bp.seed.get('url') or 'engine-composed'}]")
    return "\n".join(lines)


def passage_word_check(passage: str, bp: Blueprint) -> list[str]:
    """Free structural checks on the passage vs the tier band."""
    warnings = []
    total = len(passage.split())
    lo, hi = config.TIER_PARAMS[bp.tier]["passage_words"]
    if not (lo - 60) <= total <= (hi + 60):
        warnings.append(f"passage {total} words vs tier band {lo}-{hi}")
    return warnings


def length_bias_report(qdata: dict) -> dict:
    """Structured length-bias audit (free). The single most important number is
    `correct_longest_count`: in how many of the 6 questions the correct option is
    the strictly longest. Also flags the thesis question specifically, since a
    'longest = right' tell there is the most exploitable."""
    warnings = []
    correct_longest_count = 0
    thesis_correct_longest = False
    ranks = []  # rank of the correct option by length; 1 = longest
    for q in qdata["questions"]:
        wc = {l: len(q["options"][l]["text"].split()) for l in "ABCD"}
        spread = max(wc.values()) - min(wc.values())
        if spread > 8:
            warnings.append(f"Q{q['q']}: option word spread {spread} > 8 ({wc})")
        if min(wc.values()) and max(wc.values()) / min(wc.values()) > 1.35:
            warnings.append(f"Q{q['q']}: option length ratio > 1.35")
        mx = max(wc.values())
        is_strict_longest = wc[q["correct"]] == mx and list(wc.values()).count(mx) == 1
        if is_strict_longest:
            correct_longest_count += 1
            if q.get("slot_type") == "thesis":
                thesis_correct_longest = True
        ordered = sorted(wc.values(), reverse=True)
        ranks.append(ordered.index(wc[q["correct"]]) + 1)
    if correct_longest_count > CORRECT_LONGEST_MAX:
        warnings.append(
            f"correct option is strictly longest in {correct_longest_count}/6 questions "
            f"(max clean: {CORRECT_LONGEST_MAX})")
    if thesis_correct_longest:
        warnings.append("thesis question's correct option is the strictly longest")
    return {
        "warnings": warnings,
        "correct_longest_count": correct_longest_count,
        "thesis_correct_longest": thesis_correct_longest,
        "has_thesis_question": any(q.get("slot_type") == "thesis"
                                   for q in qdata["questions"]),
        "correct_length_ranks": ranks,
        # systematic within-set bias that should block auto-approval
        "biased": correct_longest_count > CORRECT_LONGEST_MAX or thesis_correct_longest,
    }


# At most this many of 6 correct options may be the strictly longest before the
# set is treated as length-biased (matches the legacy judge's B1 threshold).
CORRECT_LONGEST_MAX = 2


def option_band_check(qdata: dict) -> list[str]:
    """Back-compat thin wrapper returning just the warning strings."""
    return length_bias_report(qdata)["warnings"]
