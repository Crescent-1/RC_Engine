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

# The EXCEPT slot type. Its wrong options are statements the passage supports,
# so it takes no planted trap and its options carry a marker rather than a
# distractor mechanism.
TRAPLESS_SLOT = "except_scan"
EXCEPT_MECHANISM = "passage_supported"

_N_Q = config.QUESTIONS_PER_SET
_MAX_LONGEST = config.MAX_CORRECT_LONGEST

# Max word difference between the longest and shortest option in one question.
# Set 8 -> 3 on 2026-08-11 (client: the spread reads too wide).
#
# The old instruction gave the model two rules that contradict each other at
# real option lengths: "spread of 8 words (longest at most 1.25x the shortest)".
# Options run ~15 words, where an 8-word spread IS 1.53x. The model satisfied
# the number that was easy to check — 0 of 80 questions exceeded 8 words — and
# missed the ratio on 16%. A single absolute rule removes the conflict: at any
# option of 12+ words, a 3-word spread already implies <= 1.25x, so the ratio
# does not need stating separately. The generator still chooses how long the
# options are; they just have to match each other.
OPTION_LENGTH_SPREAD_TARGET = 3

QUESTION_SYSTEM = f"""You are a senior CAT VARC question architect. You receive a passage,
its hidden structural blueprint (trap map, tension system, revelation schedule), and a
QUESTION PLAN of {_N_Q} slots. Write exactly one MCQ per slot, to spec.

Q1 is the set's opening integrator: whatever its slot type, it must be answerable
only by holding the passage's full movement — never by matching a single sentence —
and its correct option must not be the longest of the four. Usually the slot is
thesis / main-idea. Some passages state no position at all, by design; those are
given a primary_purpose slot instead, and for them there IS no central claim to
recover — ask what the passage is doing, and never invent a thesis it withheld.

DISTRACTOR RULES:
- Where a slot lists a trap_id, at least one wrong option must be exactly the
  misreading that trap invites — a fast reader who fell into the trap should find
  that option waiting for them.
- Every wrong option carries a named mechanism from the allowed list. Wrong options
  fail narrowly, not theatrically: no "completely", "never", "proves". Extremity must
  be conceptual, not lexical.
- All four options in a question: same register, parallel grammar, and word counts
  within {OPTION_LENGTH_SPREAD_TARGET} WORDS OF EACH OTHER. You choose how long the
  options are for a given question — they simply have to match each other. Count the
  words; do not eyeball it. If one option needs a qualifier the others don't, give the
  others their own substance rather than letting that one run longer.
- In thesis/main-point slots the correct option must NOT be the longest of the four:
  write at least one wrong option with more words than the correct one.

SLOT TYPES THAT INVERT OR NARROW THE RULES ABOVE:
- except_scan — the option contract flips. The three WRONG options must each be
  directly supported by the passage: they are the statements that ARE true. Give
  each of them mechanism "passage_supported" and a why_wrong that cites the
  sentence supporting it. The CORRECT option is the one the passage does NOT
  support, and it must fail for a nameable reason (scope, stance, causality,
  level) — never merely because it is unmentioned, and never because it is
  lexically extreme. The stem must use the CAT form: "...all of the following
  EXCEPT" or "Which one of the following does NOT ...".
- undermine_thesis — the options are candidate NEW facts, not restatements of the
  thesis. The correct one must damage the argument's load-bearing move, not
  contradict a decorative detail. Wrong options should be facts that look
  damaging but leave the actual argument standing.
- primary_purpose — the answer is why the author put the material there
  (authorial purpose), not what the material says (summary) and not the
  structural role it plays. Wrong options should include a correct summary and a
  correct structural description, both of which miss the question.
- ACROSS THE SET: in at least {_N_Q - _MAX_LONGEST} of the {_N_Q} questions the correct option must NOT be
  the strictly longest of its four — pad a wrong option or compress the correct one.
  The correct option may be strictly longest in AT MOST {_MAX_LONGEST} of the {_N_Q} questions.
- Never make "longest option = right" a reliable heuristic anywhere in the set.
- Correct options must not be systematically the most hedged; in at least 2 questions
  phrase the correct option more flatly than its strongest distractor.
- Application slots require a genuinely NEW scenario, not a paraphrase.

LENGTH-BIAS SELF-CHECK (mandatory before you emit JSON):
After drafting all {_N_Q} questions, re-count word lengths for every option (A-D texts
as you wrote them — ignore letters; count the option strings only).
1. Per question: max_words - min_words <= {OPTION_LENGTH_SPREAD_TARGET}. This is the
   binding parity rule — check it on every question before you emit, and fix any
   question that fails by rewriting options, not by trimming one into a fragment.
2. Set-wide: count how many questions have the correct option as the STRICTLY
   longest (unique max). That count must be <= {_MAX_LONGEST}. If it is {_MAX_LONGEST + 1}+, fix before emit —
   prefer lengthening a wrong option with one precise clause; only then shorten
   the correct option.
3. Thesis / main-point / global slots: correct must NOT be strictly longest.
4. COMPREHENSIBILITY LOCK when adjusting length:
   - Never trim into fragments, telegraphic stubs, or options that lose the claim.
   - After any cut, the option must still be a full grammatical proposition a CAT
     test-taker can parse in one read — subject, predicate, and the content that
     makes it right or wrong must remain explicit.
   - Do not delete qualifiers that change meaning (scope, stance, causality).
   - Prefer adding substance to a distractor over gutting the correct answer.
5. Only after this recheck passes, emit the JSON.

OUTPUT DISCIPLINE (this model writes extra visible reasoning when thinking is
off, and that reasoning competes with the JSON for the output budget):
- Emit the JSON object and NOTHING else. No preamble, no "Here is...", no
  commentary before or after, no markdown fences, no notes on your process.
- Do the length-bias recheck silently. Do not narrate it or show your counts.
- The first character of your response must be '{' and the last must be '}'.

Respond ONLY with valid JSON, no markdown fences:
{{
  "questions": [
    {{
      "q": 1,
      "slot_type": "...",
      "stem": "...",
      "correct": {{"text": "...", "why_right": "1-2 sentences naming the structural bridge"}},
      "wrong": [
        {{"text": "...", "mechanism": "...", "why_wrong": "one sentence, max 25 words, naming the error and the passage location it distorts"}},
        {{"text": "...", "mechanism": "...", "why_wrong": "..."}},
        {{"text": "...", "mechanism": "...", "why_wrong": "..."}}
      ]
    }},
    ...exactly {_N_Q}...
  ]
}}"""


class QuestionEngineError(RuntimeError):
    pass


class QuestionEngine:
    def __init__(self, registry, llm):
        self.registry = registry
        self.llm = llm

    def build(self, bp: Blueprint, passage: str, ledger: CostLedger,
              extra_guidance: str | None = None,
              stage: str = "questions") -> dict:
        """Returns {"questions": [...], "letters": [...], "trap_usage": {...}}
        with letters already assigned per the blueprint's letter plan.
        extra_guidance: optional operator directives (e.g. from a resumed
        retry) appended verbatim to the user prompt.
        stage: which STAGE_CONFIG entry drives model/max_tokens and cost
        labelling (normally 'questions')."""
        model, max_tokens = config.STAGE_CONFIG[stage][bp.tier]
        topo = self.registry.get("topology", bp.topology_id)
        profile = self.registry.get("distractor_profile", bp.distractor_profile_id)
        slots = self._retarget_thesis(topo["slots"], bp)
        slots = self._scale_slots(self._assign_traps(slots, bp), bp.tier)

        user = self._prompt(bp, passage, slots, topo, profile)
        if extra_guidance:
            user += f"\n\nADDITIONAL DIRECTIVES:\n{extra_guidance}"
        last_err = None
        for _ in range(config.MAX_QUESTION_ATTEMPTS):
            text, truncated = self.llm.call(
                ledger, stage, model, max_tokens, QUESTION_SYSTEM, user,
                context={"blueprint": bp, "slots": slots,
                         "mechanisms": [profile["primary"], profile["secondary"]]})
            try:
                data = extract_json(text)
                questions = self._validate(data, truncated, slots)
                return self._letter_assign(questions, bp)
            except (ValueError, QuestionEngineError) as e:
                last_err = e
                user += ("\n\nYOUR PREVIOUS RESPONSE WAS INVALID: "
                         f"{e}. Emit complete, valid JSON exactly per schema.")
        raise QuestionEngineError(f"question generation failed: {last_err}")

    # ------------------------------------------------------------- internals

    def _retarget_thesis(self, slots: list[dict], bp: Blueprint) -> list[dict]:
        """Swap the pinned thesis slot for families that state no position.

        All 24 topologies pin `thesis` at Q1. Four arc-shape families withhold a
        thesis by design, and asking one for its central idea yields a key the
        solver can argue with rather than one the passage supports. The slot
        keeps its difficulty and global target — only what it asks changes."""
        try:
            if not self.registry.withholds_thesis(bp.family_id):
                return slots
        except Exception:
            return slots
        out = [dict(s) for s in slots]
        for s in out:
            if s["type"] == "thesis":
                s["type"] = config.NO_THESIS_Q1_SLOT
                s["target"] = "global"
        return out

    def _assign_traps(self, slots: list[dict], bp: Blueprint) -> list[dict]:
        """Attach blueprint traps to the slots that can naturally harvest them.

        except_scan slots are skipped: a trap is a planted misreading offered as
        a wrong option, and that slot's wrong options are statements the passage
        actually supports.
        """
        slots = [dict(s) for s in slots]
        harvest_pref = {
            "premature_closure": ["thesis", "decoy_escape", "closure_reading"],
            "scope_inflation": ["thesis", "detail_check", "undermine_thesis"],
            "stance_misread": ["stance", "author_vs_reported"],
            "level_confusion": ["author_vs_reported", "stance", "primary_purpose"],
        }
        trappable = [s for s in slots if s["type"] != TRAPLESS_SLOT]
        unassigned = list(bp.trap_map)
        for trap in list(unassigned):
            prefs = harvest_pref.get(trap["mechanism"], [])
            for slot in trappable:
                if slot["type"] in prefs and "trap_id" not in slot:
                    slot["trap_id"] = trap["trap_id"]
                    unassigned.remove(trap)
                    break
        # remaining traps: attach to still-free slots in order
        for trap in unassigned:
            for slot in trappable:
                if "trap_id" not in slot:
                    slot["trap_id"] = trap["trap_id"]
                    break
        return slots

    @staticmethod
    def _scale_slots(slots: list[dict], tier: str) -> list[dict]:
        """Map the plan's hard-tier slot difficulties into the tier's own band.

        The topology library is authored once, at hard calibration; without this
        the same plan asks equally hard questions at medium and elite, and tier
        difficulty would rest entirely on which plans a tier is allowed to draw
        (see config.TIER_TOPOLOGY_BAR for why that lever was abandoned).
        """
        rules = config.TIER_SLOT_SCALING.get(tier)
        if not rules:
            return slots
        out = [dict(s) for s in slots]
        for s in out:
            d = s["difficulty"] * rules["scale"]
            if rules.get("cap") is not None:
                d = min(d, rules["cap"])
            if rules.get("floor") is not None:
                d = max(d, rules["floor"])
            s["difficulty"] = round(d, 2)
        # pull cross-paragraph slots back to local so an easier tier asks fewer
        # questions that can only be answered by holding the whole passage
        for _ in range(rules.get("span_to_local", 0)):
            hit = next((s for s in out if s["target"] == "span"), None)
            if hit is None:
                break
            hit["target"] = "local"
        return out

    def _stem_shapes(self, slots: list[dict], bp: Blueprint) -> list[str]:
        """One authentic CAT stem shape per slot.

        Dealt without replacement within a slot type, so a topology that plans
        the same type twice (detail_check at Q1 and Q3, say) does not ask it in
        identical words — two shipped sets already opened with a verbatim
        identical thesis stem, which is the surface half of the sameness report.

        Seeded from the blueprint, like the letter plan, so a resumed run
        reproduces its shapes instead of re-rolling them.
        """
        rng = random.Random(f"{bp.blueprint_id}:stems")
        stem_forms = self.registry.stem_forms
        pools: dict[str, list[str]] = {}
        shapes = []
        for s in slots:
            stype = s["type"]
            if stype not in stem_forms:
                shapes.append("")
                continue
            if not pools.get(stype):
                pools[stype] = rng.sample(stem_forms[stype], len(stem_forms[stype]))
            shapes.append(pools[stype].pop())
        return shapes

    def _prompt(self, bp: Blueprint, passage: str, slots: list[dict],
                topo: dict, profile: dict) -> str:
        type_defs = self.registry.slot_type_definitions
        shapes = self._stem_shapes(slots, bp)
        slot_lines = []
        for i, s in enumerate(slots, start=1):
            line = (f"  Q{i}: type={s['type']} — {type_defs[s['type']]} | "
                    f"target={s['target']} | difficulty={s['difficulty']}")
            if shapes[i - 1]:
                line += f"\n      stem shape (adapt to this passage): \"{shapes[i - 1]}\""
            if "trap_id" in s:
                trap = next(t for t in bp.trap_map if t["trap_id"] == s["trap_id"])
                line += (f"\n      HARVESTS {s['trap_id']}: one wrong option must be the "
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

TIER: {bp.tier} — {config.TIER_DIFFICULTY_CHARACTER.get(bp.tier, '')}

QUESTION PLAN ({topo['name']}{'; ' + style if style else ''}):
{chr(10).join(slot_lines)}

The stem shapes above are the forms these questions take in the real exam. Adapt each
to this passage's content — keep the shape, replace the placeholders. Do not reuse one
shape for two slots.

Before emitting JSON, recheck option word counts on EVERY question for both rules:
  (a) parity — longest minus shortest <= {OPTION_LENGTH_SPREAD_TARGET} words;
  (b) length bias — the correct option is strictly longest in at most {_MAX_LONGEST}/{_N_Q},
      and never on the thesis/main-point question.
If you adjust for parity, keep every option a complete, comprehensible sentence — no
clipped fragments.
Write the {_N_Q} questions now as JSON."""

    def _validate(self, data: dict, truncated: bool,
                  slots: list[dict] | None = None) -> list[dict]:
        if truncated:
            raise QuestionEngineError("output truncated at max_tokens")
        qs = data.get("questions", [])
        if len(qs) != config.QUESTIONS_PER_SET:
            raise QuestionEngineError(
                f"expected {config.QUESTIONS_PER_SET} questions, got {len(qs)}")
        for q in qs:
            if not q.get("stem") or not q.get("correct", {}).get("text"):
                raise QuestionEngineError(f"Q{q.get('q')} missing stem or correct option")
            if len(q.get("wrong", [])) != 3:
                raise QuestionEngineError(f"Q{q.get('q')} needs exactly 3 wrong options")
            for w in q["wrong"]:
                if not w.get("text") or not w.get("mechanism"):
                    raise QuestionEngineError(f"Q{q.get('q')} wrong option missing text/mechanism")
        # EXCEPT slots invert the option contract: the three wrong options are
        # the passage-supported statements. Enforced against the PLAN, not the
        # model's self-reported slot_type, so it cannot opt out by relabelling.
        for i, slot in enumerate(slots or []):
            if slot["type"] != TRAPLESS_SLOT or i >= len(qs):
                continue
            bad = [w["mechanism"] for w in qs[i]["wrong"]
                   if w["mechanism"] != EXCEPT_MECHANISM]
            if bad:
                raise QuestionEngineError(
                    f"Q{i + 1} is an {TRAPLESS_SLOT} slot: all three wrong options "
                    f"must be passage-supported statements with mechanism "
                    f"'{EXCEPT_MECHANISM}', got {bad}")
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
                # passage_supported is not a distractor mechanism — it marks the
                # true statements in an EXCEPT question. Counting it would put 3
                # phantom traps per except-bearing set into trap_histogram and
                # skew the distractor_jsd novelty channel.
                if w["mechanism"] != EXCEPT_MECHANISM:
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


# Fabricated-scholarship shapes. Deterministic on purpose: the render contract
# already forbids these in prose, and this month has repeatedly shown that a
# prompt rule alone is not enforcement. What is checkable is checked.
#
# These are HEURISTICS and they will occasionally be wrong — a passage may
# legitimately cite a real dated study. They raise a warning for a human, never
# a rejection.
_FABRICATION_PATTERNS = [
    (r"\ba (?:19|20)\d\d (?:study|paper|survey|experiment|trial|report)\b",
     "a dated study"),
    (r"\b(?:study|survey|experiment|paper) (?:by|from) [A-Z][a-z]+",
     "a study attributed to a named person"),
    (r"\b(?:[Rr]esearchers|[Ss]cientists|[Ee]conomists|[Pp]sychologists|[Hh]istorians) at (?:the )?[A-Z][a-z]+",
     "researchers at a named institution"),
    (r"\b\d{1,3}(?:\.\d+)?\s?(?:per ?cent|%)", "a statistic"),
    (r"\b(?:found|showed|demonstrated|concluded) that\b[^.]{0,60}\d{1,3}\s?"
     r"(?:per ?cent|%)", "a quantified finding"),
    (r"\b(?:University|Institute|Laboratory|Foundation|Bureau) of [A-Z][a-z]+",
     "a named institution"),
]

# Signposts that are not fixed phrases (those live in GLOBAL_FORBIDDEN_TICS and
# are audited by compliance); these are shapes the auditor tends to miss.
_SIGNPOST_PATTERNS = [
    (r"\bthe (?:deeper|real|underlying|actual|larger) (?:issue|question|point|"
     r"problem|matter|difficulty)\b", "names its own argumentative level"),
    (r"\bthe (?:first|second|third|next) (?:objection|problem|difficulty|move|step)\b",
     "numbers its own argumentative moves"),
    (r"\bhaving (?:established|shown|argued|granted)\b", "narrates its own progress"),
    (r"\bthe argument (?:so far|thus far|to this point)\b", "summarises itself"),
    (r"\bin (?:this|the) (?:passage|essay|piece)\b", "refers to itself as a text"),
]

def texture_report(passage: str) -> dict:
    """Free scan for architecture signposting and fabricated scholarly texture.

    Both are ways generated prose fakes the surface of serious writing: the
    first announces the scaffolding the reader is supposed to feel rather than
    see, the second borrows authority the passage has not earned. The second is
    worse for a test item specifically — a candidate who actually knows the
    field is penalised for knowing that the cited study does not exist.

    Warnings only. Neither is grounds for rejection, and a real citation will
    sometimes trip the fabrication heuristics.
    """
    import re as _re

    warnings = []
    for pat, label in _SIGNPOST_PATTERNS:
        m = _re.search(pat, passage, _re.I)
        if m:
            warnings.append(f"signposting: {label} - {m.group(0)!r}")
    for pat, label in _FABRICATION_PATTERNS:
        m = _re.search(pat, passage)
        if m:
            warnings.append(
                f"possible fabricated scholarship: {label} - {m.group(0)!r}")
    return {"warnings": warnings,
            "signposts": sum(1 for w in warnings if w.startswith("signposting")),
            "fabrications": sum(1 for w in warnings if w.startswith("possible"))}


def passage_word_report(passage: str) -> dict:
    """Free word-count audit against the one house range (config
    PASSAGE_WORD_MIN..PASSAGE_WORD_MAX). Length is not tier-specific — every
    tier ships a 500-550 word passage.

    `in_band` is a gate, not a warning: the pipeline refuses to auto-approve a
    set whose passage falls outside the range. Both this and `cli vet` read the
    same two constants, so they can no longer disagree about what passes."""
    total = len(passage.split())
    lo, hi = config.PASSAGE_WORD_MIN, config.PASSAGE_WORD_MAX
    in_band = lo <= total <= hi
    return {
        "words": total, "lo": lo, "hi": hi, "in_band": in_band,
        "warnings": ([] if in_band else
                     [f"passage {total} words vs required {lo}-{hi}"]),
    }


def passage_word_check(passage: str, bp: Blueprint | None = None) -> list[str]:
    """Back-compat wrapper returning just the warning strings."""
    return passage_word_report(passage)["warnings"]


def length_bias_report(qdata: dict) -> dict:
    """Structured length-bias audit (free). The single most important number is
    `correct_longest_count`: in how many of the set's questions the correct option
    is the strictly longest. Also flags the thesis question specifically, since a
    'longest = right' tell there is the most exploitable — and thesis is now Q1 of
    every set, so that tell would be visible on the first question a solver reads."""
    warnings = []
    correct_longest_count = 0
    thesis_correct_longest = False
    ranks = []  # rank of the correct option by length; 1 = longest
    for q in qdata["questions"]:
        wc = {l: len(q["options"][l]["text"].split()) for l in "ABCD"}
        spread = max(wc.values()) - min(wc.values())
        if spread > OPTION_LENGTH_SPREAD_MAX:
            warnings.append(f"Q{q['q']}: option word spread {spread} > "
                            f"{OPTION_LENGTH_SPREAD_MAX} ({wc})")
        if min(wc.values()) and max(wc.values()) / min(wc.values()) > OPTION_LENGTH_RATIO_WARN:
            warnings.append(f"Q{q['q']}: option length ratio > {OPTION_LENGTH_RATIO_WARN}")
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
            f"correct option is strictly longest in "
            f"{correct_longest_count}/{config.QUESTIONS_PER_SET} questions "
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


# At most this many correct options may be the strictly longest before the set is
# treated as length-biased (matches the legacy judge's B1 threshold). Derived as
# QUESTIONS_PER_SET // 3, which holds the ceiling at 2 across the 6 -> 8 move —
# proportionally stricter, which is the right direction for the most exploitable
# tell in the set.
CORRECT_LONGEST_MAX = config.MAX_CORRECT_LONGEST

# Option-length parity. The prompt AIMS tighter than the audit ENFORCES, on
# purpose: ordinary phrasing variation should not be flagged.
#
# What the prompt asks for lives at the top of this module
# (OPTION_LENGTH_SPREAD_TARGET) because QUESTION_SYSTEM interpolates it.
#
# What the audit WARNS at — deliberately looser and deliberately unchanged, so
# the prompt change can be measured against a fixed yardstick before anyone
# argues about thresholds.
OPTION_LENGTH_SPREAD_MAX = 8
OPTION_LENGTH_RATIO_TARGET = 1.25
OPTION_LENGTH_RATIO_WARN = 1.35


def option_band_check(qdata: dict) -> list[str]:
    """Back-compat thin wrapper returning just the warning strings."""
    return length_bias_report(qdata)["warnings"]
