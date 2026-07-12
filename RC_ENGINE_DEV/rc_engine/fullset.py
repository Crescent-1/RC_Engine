"""Cheap-mode single-call generator: passage + 6 MCQs + key material in ONE
LLM call, conditioned on the blueprint contract.

Letters are still assigned locally from the blueprint letter plan (zero-cost
anti-bias), reusing QuestionEngine._letter_assign / _validate / _assign_traps.
"""

from __future__ import annotations

from . import config
from .llm import CostLedger, extract_json
from .models import Blueprint
from .question_engine import QuestionEngine, QuestionEngineError
from .renderer import PassageRenderer


FULLSET_SYSTEM = """You are a CAT VARC content writer and question architect.

You receive a STRUCTURAL CONTRACT (persona, paragraph plan, traps, ending) and
a QUESTION PLAN (6 slots). Produce BOTH in one response:

1) The passage — plain paragraphs separated by blank lines. No title.
2) Exactly 6 MCQs as JSON, matching the question schema.

HARD RULES — PASSAGE:
- Exactly the number of paragraphs specified, each performing its role/word band.
- Stay in the persona voice. No forbidden phrases.
- Plant reader traps as invited misreadings; do not state them.
- Thesis appears first only where the revelation schedule says.
- Output passage ONLY under the [PASSAGE] header (no commentary).

HARD RULES — QUESTIONS (LENGTH / PARITY — commercial fail if broken):
- One MCQ per slot, to type/target/difficulty.
- Where a slot HARVESTS a trap, one wrong option must be that trap's misreading.
- Four options: parallel grammar; word counts within a spread of **at most 8**.
- In **at least 4 of 6** questions, the correct option must NOT be the strictly
  longest of the four — pad a wrong option or compress the correct one.
- Thesis / main-point / global slots: correct option must NEVER be strictly longest.
- Wrong options: named mechanism + max-25-word why_wrong.
- Never make "longest option = right" a reliable heuristic.

OUTPUT FORMAT (strict):
[PASSAGE]
<paragraphs separated by blank lines>

[QUESTIONS_JSON]
{ ... valid JSON object with key "questions" array of exactly 6 items ... }

JSON schema for each question:
{
  "q": 1,
  "slot_type": "...",
  "stem": "...",
  "correct": {"text": "...", "why_right": "..."},
  "wrong": [
    {"text": "...", "mechanism": "...", "why_wrong": "..."},
    {"text": "...", "mechanism": "...", "why_wrong": "..."},
    {"text": "...", "mechanism": "...", "why_wrong": "..."}
  ]
}

No markdown fences. No text after the JSON object.
"""


class FullsetError(RuntimeError):
    pass


class FullsetGenerator:
    """One paid call → passage + questions dict ready for assemble_rc_text."""

    def __init__(self, registry, llm):
        self.registry = registry
        self.llm = llm
        self._renderer = PassageRenderer(registry, llm)
        self._qengine = QuestionEngine(registry, llm)

    def generate(self, bp: Blueprint, ledger: CostLedger,
                 directives: list[str] | None = None) -> tuple[str, dict]:
        model, max_tokens = config.STAGE_CONFIG["fullset"][bp.tier]
        topo = self.registry.get("topology", bp.topology_id)
        profile = self.registry.get("distractor_profile", bp.distractor_profile_id)
        slots = self._qengine._assign_traps(topo["slots"], bp)
        user = self._build_user(bp, slots, topo, profile, directives or [])

        last_err = None
        for attempt in range(1, config.MAX_FULLSET_ATTEMPTS + 1):
            text, truncated = self.llm.call(
                ledger, "fullset", model, max_tokens, FULLSET_SYSTEM, user,
                context={"blueprint": bp, "slots": slots,
                         "mechanisms": [profile["primary"], profile["secondary"]],
                         "planned_posture": self.registry.posture_of(bp.family_id)})
            try:
                if truncated:
                    raise FullsetError("output truncated at max_tokens")
                passage, raw_qs = self._parse(text)
                questions = self._qengine._validate({"questions": raw_qs}, False)
                qdata = self._qengine._letter_assign(questions, bp)
                return passage.strip(), qdata
            except (FullsetError, QuestionEngineError, ValueError, KeyError) as e:
                last_err = e
                user += (f"\n\nYOUR PREVIOUS RESPONSE WAS INVALID ({e}). "
                         "Re-emit full [PASSAGE] then [QUESTIONS_JSON] correctly.")
        raise FullsetError(f"fullset generation failed after "
                           f"{config.MAX_FULLSET_ATTEMPTS} attempt(s): {last_err}")

    def _build_user(self, bp: Blueprint, slots: list[dict], topo: dict,
                    profile: dict, directives: list[str]) -> str:
        # Reuse renderer contract for passage structure
        contract = self._renderer._contract(bp, directives)
        type_defs = self.registry.slot_type_definitions
        slot_lines = []
        for i, s in enumerate(slots, start=1):
            line = (f"  Q{i}: type={s['type']} — {type_defs[s['type']]} | "
                    f"target={s['target']} | difficulty={s['difficulty']}")
            if "trap_id" in s:
                trap = next(t for t in bp.trap_map if t["trap_id"] == s["trap_id"])
                line += (f" | HARVESTS {s['trap_id']}: wrong option = "
                         f"\"{trap['invited_misreading']}\" "
                         f"(mechanism: {trap['mechanism']})")
            slot_lines.append(line)
        lo, hi = config.TIER_PARAMS[bp.tier]["passage_words"]
        return f"""{contract}

--- ALSO PRODUCE QUESTIONS ---
Passage length target: {lo}-{hi} words total.

QUESTION PLAN ({topo['name']}):
{chr(10).join(slot_lines)}

Allowed distractor mechanisms: primary={profile['primary']},
secondary={profile['secondary']}; others sparingly from the library.

LENGTH / PARITY (mandatory): within each question option word-count spread ≤ 8;
correct is strictly longest in at most 2 of 6 questions; NEVER on thesis/main-point.
After the passage, emit [QUESTIONS_JSON] with exactly 6 questions.
"""

    @staticmethod
    def _parse(text: str) -> tuple[str, list]:
        t = text.strip()
        if "[PASSAGE]" in t:
            t = t.split("[PASSAGE]", 1)[1]
        if "[QUESTIONS_JSON]" not in t:
            # fallback: try [QUESTIONS] then JSON
            if "[QUESTIONS]" in t and "{" in t:
                pass_part, rest = t.split("[QUESTIONS]", 1)
                passage = pass_part.strip()
                data = extract_json(rest)
                return passage, data.get("questions", [])
            raise FullsetError("missing [QUESTIONS_JSON] section")
        pass_part, json_part = t.split("[QUESTIONS_JSON]", 1)
        passage = pass_part.strip()
        if not passage or len(passage.split()) < 80:
            raise FullsetError("passage too short or empty")
        data = extract_json(json_part)
        qs = data.get("questions", [])
        if not qs:
            raise FullsetError("questions array empty")
        return passage, qs
