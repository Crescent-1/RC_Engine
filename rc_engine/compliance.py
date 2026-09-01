"""Blueprint Compliance Auditor — verifies the rendered passage realized the
planned structure, extracts the realized structure (which is what gets
fingerprinted), and produces targeted re-render directives on failure."""

from __future__ import annotations

import json

from . import config
from .llm import CostLedger, extract_json
from .models import Blueprint, RealizedStructure

COMPLIANCE_SYSTEM = """You are a structural auditor for generated essay passages.
You receive a passage and the structural plan it was supposed to realize.
For each paragraph, judge whether it performs its PLANNED function (the plan is
given; judge realization, not quality).

Also:
- identify the paragraph where the passage's thesis/final position FIRST becomes
  visible to a careful reader,
- rate, for each paragraph, how far the author has committed to a SUBSTANTIVE
  ANSWER to the question the passage opens, from -1.0 (actively pointing away
  from one) to 1.0 (fully committed to one).
  Measure against the OPENING QUESTION, not against wherever the passage ends.
  A passage that closes by refusing to settle, suspending judgment, or showing
  the question dissolves is NOT at 1.0 — it is LOW at the end, however
  confidently that refusal is argued. Confidence in a refusal is not commitment
  to an answer. Only a paragraph that actually lands on a position scores high.
- check each planned reader-trap: does the paragraph genuinely invite that misreading?
- list any forbidden phrases that appear,
- classify the passage's CLOSING POSTURE: the stance a careful reader takes away from
  the final paragraph, as exactly one of the labels defined in the input,
- judge the FINAL sentence against BOTH parts of the aphorism test. It is an
  aphorism only if BOTH are true:
    (a) GENERALIZES — it states something about how things are in general, not
        about this passage's particular case, people, place, or object.
    (b) SELF-CONTAINED — every referring expression in it is intelligible to
        someone who has not read the passage. If it contains a proper noun, a
        pronoun, a demonstrative ("that", "this", "such"), or a definite noun
        phrase that only the passage introduces, it is NOT self-contained.
  Report the specific expression that ties it to the passage, if any.
  Terse and quotable are NOT sufficient: "Start with the countersignature line
  on Form PA 1663, still blank, still required." is short and forceful but
  names a passage-specific object, so it fails (b) and is not an aphorism.

Respond ONLY with valid JSON, no markdown fences:
{
  "paragraphs": [{"para": 1, "function_guess": "<the planned function token, or OTHER>", "matches_plan": true, "word_count": 0}, ...],
  "thesis_first_visible_para": 1,
  "commitment_curve": [0.0, ...one per paragraph...],
  "traps_present": ["TR1", ...],
  "forbidden_tics_found": [],
  "closing_posture_guess": "<one label from CLOSING POSTURE LABELS>",
  "final_line_is_aphorism": false,
  "aphorism_test": {"generalizes": false, "self_contained": false, "back_reference": null},
  "notes": "max 30 words"
}"""


MOVE_SIGNATURE_SYSTEM = """You read a finished essay passage and report the sequence of
RHETORICAL MOVES it performs, in the order they occur.

A rhetorical move is an OPERATION the prose performs on its argument — how it opens,
how it turns, how it closes. It is not the topic, and it is not the paragraph count.

Rules:
- Use ONLY labels from the vocabulary given. Never invent one.
- Report moves in the order they appear. A passage typically performs 5-9 of them.
- One move per distinct operation, not one per paragraph. A paragraph may perform two;
  two paragraphs may jointly perform one.
- Do not report a move you cannot point to specific sentences for.
- Some labels are deliberately narrow and have a milder neighbour. Do not reach
  for the strong label when the mild one fits: LEVEL_RELOCATION requires that
  the dispute AS POSED is wrong and gets reframed, not merely that a deeper
  cause is named — that is UNDERLYING_CAUSE_NAMED. When a passage says "X is
  the symptom, Y is the real cause", that is UNDERLYING_CAUSE_NAMED. Reserve
  LEVEL_RELOCATION for "these people are not actually arguing about X at all".
- Judge only what is on the page. You are not being shown any plan, and there is no
  intended answer to recover — report what the prose does.

Respond ONLY with valid JSON, no markdown fences:
{"moves": ["LABEL", "LABEL", ...]}"""


class ComplianceAuditor:
    def __init__(self, llm, registry):
        self.llm = llm
        self.registry = registry

    def audit(self, passage: str, bp: Blueprint, ledger: CostLedger,
              realized_moves: list[str] | None = None) -> RealizedStructure:
        model, max_tokens = config.STAGE_CONFIG["compliance"][bp.tier]
        plan_lines = "\n".join(
            f"  para {p.para}: function={p.function}, words {p.words_label}"
            for p in bp.movement)
        trap_lines = "\n".join(
            f"  {t['trap_id']} @ para {t['anchor_para']}: {t['invited_misreading']}"
            for t in bp.trap_map)
        forbidden = ", ".join(config.GLOBAL_FORBIDDEN_TICS)
        # posture labels only — the PLANNED posture is deliberately withheld so
        # the classification stays blind and can detect renderer disobedience
        posture_lines = "\n".join(
            f"  {name}: {desc}"
            for name, desc in self.registry.closing_postures.items())
        user = (f"PLAN:\n{plan_lines}\n\nPLANNED THESIS VISIBILITY: paragraph "
                f"{bp.revelation_detail.get('planned_para')}\n\nPLANNED TRAPS:\n{trap_lines}\n\n"
                f"FORBIDDEN PHRASES: {forbidden}\n\n"
                f"CLOSING POSTURE LABELS:\n{posture_lines}\n\nPASSAGE:\n{passage}")
        text, _ = self.llm.call(ledger, "compliance", model, max_tokens,
                                COMPLIANCE_SYSTEM, user,
                                context={"blueprint": bp, "passage": passage,
                                         "planned_posture": self.registry.posture_of(bp.family_id)})
        data = extract_json(text)
        return self._score(data, passage, bp, realized_moves or [])

    @staticmethod
    def _final_line_is_bound(passage: str) -> str | None:
        """Cheap structural check for a back-reference in the final sentence.

        Runs regardless of what the classifier said: a final line that reuses a
        capitalised name or a distinctive content word first introduced earlier
        in the passage cannot be read out of context, whatever it sounds like.
        Returns the tying expression, or None."""
        import re as _re
        nl = chr(10)
        paras = [x for x in passage.split(nl + nl) if x.strip()]
        if not paras:
            return None
        sentences = _re.split(r"(?<=[.!?])" + chr(32), paras[-1].strip())
        final = sentences[-1] if sentences else ""
        earlier = " ".join(paras[:-1]) + " " + " ".join(sentences[:-1])
        if not final or not earlier.strip():
            return None
        earlier_l = earlier.lower()

        # (a) demonstrative pointing outside the sentence: "that building",
        #     "this refusal", "such cases". These resolve only in the passage.
        #     Only counts after a preposition or a comma: "in that building"
        #     points outward, but the "that" in "acknowledged that institutions
        #     outlive their reasons" is a complementizer and that sentence is
        #     perfectly self-contained. A demonstrative in subject position
        #     ("Such confidence is rarely earned twice") generalizes rather than
        #     refers, so it is not evidence of binding either.
        dem = _re.search(
            r"(?:[,;]\s+|\b(?:in|on|at|of|for|with|from|by|about|under|behind|"
            r"inside|against|across)\s+)(that|this|these|those|such)\s+"
            r"([a-z][a-z-]{2,})\b", final.lower())
        if dem and dem.group(2) not in ("is", "was", "are", "were", "much", "far"):
            return dem.group(1) + " " + dem.group(2)

        # (b) a pronoun subject with nothing in the sentence to resolve it.
        #     Cataphoric "It is a truth universally acknowledged that ..." is
        #     fine — the that-clause supplies the referent inside the sentence —
        #     so only flag when no such clause follows.
        pro = _re.match(r"\s*(It|This|That|They|These|Those|He|She)\b", final)
        if pro and not _re.search(r"\b(that|which|who|to|when|if)\b", final[len(pro.group(0)):]):
            return pro.group(1)

        # proper nouns / numbered forms mid-sentence
        for tok in _re.findall(r"\b[A-Z][A-Za-z0-9'-]{2,}\b", final[1:]):
            if tok.lower() in earlier_l:
                return tok
        # a rare-ish content word carried over verbatim
        for tok in _re.findall(r"\b[a-z]{7,}\b", final.lower()):
            if earlier_l.count(tok) >= 2:
                return tok
        return None

    @staticmethod
    def _register_instruction(register_id: str) -> str:
        for reg_id, _w, instruction in config.CLOSING_REGISTERS:
            if reg_id == register_id:
                return instruction
        return config.CLOSING_REGISTERS[0][2]

    def move_signature(self, passage: str, ledger: CostLedger,
                       tier: str = "hard") -> list[str]:
        """Blind rhetorical-move read of the passage. Sees the prose and nothing
        else — no blueprint, no persona, no plan. That blindness is the whole
        point: `movement_string` became a near-duplicate of blueprint similarity
        precisely because its auditor was handed the plan first.

        Returns [] on any failure; a missing signature is treated downstream as
        'unknown structure', never as 'similar structure'."""
        model, max_tokens = config.STAGE_CONFIG["move_signature"][tier]
        nl = chr(10)
        vocab = nl.join(f"  {k}: {v}" for k, v in config.RHETORICAL_MOVES.items())
        user = f"VOCABULARY:{nl}{vocab}{nl}{nl}PASSAGE:{nl}{passage}"
        try:
            text, _ = self.llm.call(ledger, "move_signature", model, max_tokens,
                                    MOVE_SIGNATURE_SYSTEM, user,
                                    context={"passage": passage})
            data = extract_json(text)
        except Exception as e:
            # Never abort an RC over a sub-cent stage — but never fail quietly
            # either. An empty signature disables the channel that does most of
            # the novelty work now, and a silent one looks exactly like a
            # passage that simply scored well.
            print(f"  [move-signature] extraction failed ({type(e).__name__}: {e}) "
                  f"- this passage will not be scored on rhetorical grammar")
            return []
        moves = data.get("moves", [])
        if not isinstance(moves, list):
            return []
        # drop anything outside the closed vocabulary — an invented label would
        # never match another passage's and would silently inflate novelty
        return [m for m in (str(x).strip().upper() for x in moves)
                if m in config.RHETORICAL_MOVES]

    def _score(self, data: dict, passage: str, bp: Blueprint,
               realized_moves: list[str] | None = None) -> RealizedStructure:
        n = len(bp.movement)
        paras_report = data.get("paragraphs", [])[:n]
        real_paras = [p for p in passage.split("\n\n") if p.strip()]

        functions, matches = [], []
        for i, p in enumerate(bp.movement):
            rep = paras_report[i] if i < len(paras_report) else {}
            guess = rep.get("function_guess", "OTHER")
            match = bool(rep.get("matches_plan", False))
            functions.append(guess if guess else "OTHER")
            matches.append(match)

        curve = [float(x) for x in data.get("commitment_curve", [])][:n]
        while len(curve) < n:
            curve.append(0.0)

        planned_thesis = bp.revelation_detail.get("planned_para", n)
        realized_thesis = data.get("thesis_first_visible_para")
        traps_present = [t for t in data.get("traps_present", [])
                         if t in {x["trap_id"] for x in bp.trap_map}]
        tics = data.get("forbidden_tics_found", [])

        # ---- beat-plan compliance (2026-08-22) -----------------------------
        # Scored from the BLIND extraction, so this measures the prose and not a
        # restatement of the plan. Missing beats become directives exactly the
        # way missing paragraph functions do — the loop the renderer responds to.
        realized_moves = list(realized_moves or [])
        beat_score = 1.0
        missing_beats: list[str] = []
        if bp.move_plan and realized_moves:
            got = set(realized_moves)
            missing_beats = [m for m in bp.move_plan if m not in got]
            beat_score = 1.0 - len(missing_beats) / len(bp.move_plan)

        # ---- POSITION of the first and last beat (2026-08-29) --------------
        # Membership alone was the whole check until now, and membership is not
        # what a reader hears. Measured over the nine sets shipped 08-24..08-28:
        # the composer planned SCENE_PARTICULAR as the opening beat 0 times and
        # the prose opened on it 6 times; CONCRETE_RETURN was planned to close
        # once and closed five. Every one of those scored a PERFECT beat_score,
        # because the displaced beat still appeared somewhere in the middle.
        # Openings obeyed 2/9, closings 1/9 — against a contract that already
        # calls the plan a "hard requirement".
        #
        # Only the first and last beat are position-checked. Interior order is
        # genuinely the writer's business, but the opening gambit and the final
        # cadence are exactly the two beats a reader recognises as house voice.
        opening_ok = closing_ok = True
        middle_retention = 1.0
        middle_missing: list[str] = []
        gratuitous: list[str] = []
        if bp.move_plan and realized_moves:
            opening_ok = realized_moves[0] == bp.move_plan[0]
            closing_ok = realized_moves[-1] == bp.move_plan[-1]

            # ---- the MIDDLE (2026-09-01) -------------------------------------
            # Order inside the middle is genuinely the writer's business, so this
            # checks RETENTION (did the planned middle beats happen at all) and
            # RESTRAINT (what did it perform instead), never sequence.
            #
            # Measured over 13 sets: planned middle beats retained 43% of the
            # time, with the same substitutes recurring across unrelated
            # families — EASY_READING_DEMOLISHED unplanned in 10 of 13.
            planned_mid = set(bp.move_plan[1:-1])
            real_mid = set(realized_moves[1:-1])
            if planned_mid:
                middle_retention = len(planned_mid & real_mid) / len(planned_mid)
                middle_missing = [m for m in bp.move_plan[1:-1]
                                  if m not in real_mid]
            # An unplanned move is only worth a directive when it is DISTINCTIVE:
            # adding a MECHANISM_EXPLAINED is what 91% of real exam passages do.
            floor = config.UNPLANNED_MOVE_EXAM_FLOOR
            gratuitous = sorted(
                m for m in (real_mid - planned_mid)
                if config.EXAM_MOVE_SHARES.get(m, 0.0) < floor)

        # weighted structural score
        fn_score = sum(matches) / n if n else 0.0
        thesis_ok = (isinstance(realized_thesis, int)
                     and abs(realized_thesis - planned_thesis) <= 1)
        trap_score = len(traps_present) / max(1, len(bp.trap_map))
        para_count_ok = len(real_paras) == n
        # beat_score takes its weight from paragraph functions and traps: the
        # rhetorical grammar is the axis the corpus actually collapsed on, so it
        # earns a share comparable to the trap map.
        f1 = 0.45 * fn_score + 0.12 * (1.0 if thesis_ok else 0.0) + \
             0.18 * trap_score + 0.10 * (1.0 if para_count_ok else 0.0) + \
             0.15 * beat_score
        if tics:
            f1 = min(f1, 0.5)

        directives = []
        if not para_count_ok:
            directives.append(f"produce exactly {n} paragraphs (got {len(real_paras)})")
        for i, m in enumerate(matches):
            if not m:
                p = bp.movement[i]
                directives.append(
                    f"paragraph {p.para} must perform: {p.function.replace('_', ' ').lower()}"
                    + (f" — {p.gist}" if p.gist else ""))
        if not thesis_ok:
            directives.append(
                f"the thesis must first become visible in paragraph {planned_thesis}, "
                f"not paragraph {realized_thesis}")
        missing_traps = [t["trap_id"] for t in bp.trap_map
                         if t["trap_id"] not in traps_present]
        for tid in missing_traps:
            t = next(x for x in bp.trap_map if x["trap_id"] == tid)
            directives.append(
                f"paragraph {t['anchor_para']} must invite the misreading: "
                f"{t['invited_misreading']}")
        if tics:
            directives.append(f"remove forbidden phrases: {', '.join(map(str, tics))}")
        if missing_beats and beat_score < config.MOVE_PLAN_MIN_REALIZED:
            named = "; ".join(
                f"{m} ({config.RHETORICAL_MOVES.get(m, '')})" for m in missing_beats)
            directives.append(
                f"the passage must perform these planned rhetorical moves, which "
                f"a blind reading of it could not find: {named}")

        posture_guess = str(data.get("closing_posture_guess", "")).strip()
        if posture_guess not in self.registry.closing_postures:
            posture_guess = ""   # junk -> unusable; downstream checks skip
        # An aphorism needs BOTH legs of the test. Before 2026-08-22 this was a
        # single "is it terse and quotable" judgement, and it over-fired badly:
        # on the 2026-08-22 batch it called all three finals aphorisms when each
        # had in fact obeyed its assigned register — including
        # "Start with the countersignature line on Form PA 1663, still blank,
        # still required.", which names an object introduced earlier in the
        # passage. Every aphorism-rate figure produced before that date is
        # inflated by an unknown amount.
        aph = data.get("final_line_is_aphorism")
        aph = aph if isinstance(aph, bool) else None
        test = data.get("aphorism_test")
        if isinstance(test, dict):
            generalizes = test.get("generalizes")
            contained = test.get("self_contained")
            if isinstance(generalizes, bool) and isinstance(contained, bool):
                aph = generalizes and contained
            # an explicit back-reference settles it regardless of the verdict
            if str(test.get("back_reference") or "").strip():
                aph = False

        bound_by = self._final_line_is_bound(passage)
        if aph and bound_by:
            aph = False   # structurally tied to the passage; cannot stand alone

        # ---- closing-register / posture obedience (2026-08-21) --------------
        # Both fields were already being classified and then ignored: the
        # register was assigned by the composer, instructed by the renderer,
        # and never checked against what the renderer actually produced. The
        # corpus result was 24/34 aphorism endings against a 12.5% design
        # weight — the single most recognisable beat of the house voice. These
        # are compliance failures, not novelty failures, so they ride the
        # existing directive/retry loop and only cost a render when they fire.
        register_ok = True
        if aph and bp.closing_register and bp.closing_register != "aphoristic":
            register_ok = False
            directives.append(
                "the final sentence broke its assigned closing register — "
                + self._register_instruction(bp.closing_register))
        planned_posture = self.registry.posture_of(bp.family_id)
        posture_ok = True
        if posture_guess and planned_posture and posture_guess != planned_posture:
            posture_ok = False
            directives.append(
                f"the closing posture must be {planned_posture} "
                f"({self.registry.closing_postures.get(planned_posture, '')}), "
                f"not {posture_guess}")
        # NOT capped below the threshold, deliberately — reverted 2026-08-22.
        # Capping forced a dedicated re-render whenever the register was broken,
        # which on Opus 5 is most passages. Measured over three batches the
        # retry cost ~$0.05-0.08 each (render + compliance + move_signature) and
        # produced another aphorism anyway: RC-ELITE-260821-0048 and
        # RC-ELITE-260821-0050 both shipped with _aphorism_ending=1 AFTER a
        # forced retry. Paying for a retry that does not change the outcome is
        # strictly worse than shipping the flag.
        #
        # The directives above still ride any re-render triggered for another
        # reason, and the violation still surfaces on the set. The durable fix
        # is to PRESCRIBE the ending positively rather than forbid the aphorism
        # — negative constraints are what the renderer is ignoring.
        # Positively PRESCRIBED, not forbidden. The 2026-08-22 note below records
        # why: negative constraints are what the renderer ignores. So name the
        # beat it owes and what that beat is, rather than banning what it wrote.
        if not opening_ok:
            want = bp.move_plan[0]
            directives.append(
                f"the FIRST SENTENCE must perform {want} — "
                f"{config.RHETORICAL_MOVES.get(want, '')}. "
                f"The passage opened on {realized_moves[0]} instead")
        if not closing_ok:
            want = bp.move_plan[-1]
            directives.append(
                f"the FINAL SENTENCE must perform {want} — "
                f"{config.RHETORICAL_MOVES.get(want, '')}. "
                f"The passage closed on {realized_moves[-1]} instead")

        middle_ok = True
        if middle_missing and middle_retention < config.MOVE_PLAN_MIN_MIDDLE_RETAINED:
            middle_ok = False
            named = "; ".join(f"{m} ({config.RHETORICAL_MOVES.get(m, '')})"
                              for m in middle_missing)
            directives.append(
                f"the BODY paragraphs dropped {len(middle_missing)} of "
                f"{len(set(bp.move_plan[1:-1]))} planned middle beats. Perform "
                f"these, in whatever order the argument wants: {named}")
        if gratuitous:
            middle_ok = False
            named = ", ".join(gratuitous)
            directives.append(
                f"the body performed rhetorical moves the plan did not ask for: "
                f"{named}. These are not neutral connective tissue — they are the "
                f"gestures this engine reaches for by habit, and each one displaced "
                f"a beat you were given. Drop them and perform the plan instead")

        # ---- commitment at the close (2026-09-01) ---------------------------
        # The curve was measured, weighted at 0.14 in the novelty composite --
        # the largest single channel -- and never targeted by any stage. The
        # posture moved the realised endpoint by a spread of only 0.20 across
        # 74 curves; refusal_suspended, which must end unresolved, ended at a
        # median of 0.93. Audited the same way the beats and the register are:
        # a directive that rides an existing retry, never a forced re-render.
        commitment_ok = True
        band = config.POSTURE_END_COMMITMENT.get(planned_posture or "")
        if band and curve:
            lo, hi = band
            tol = config.POSTURE_END_TOLERANCE
            end = curve[-1]
            if not (lo - tol) <= end <= (hi + tol):
                commitment_ok = False
                directives.append(
                    f"the passage ended at commitment {end:+.2f}; the "
                    f"{planned_posture} posture requires it to close between "
                    f"{lo:+.2f} and {hi:+.2f} on a scale where +1 is fully "
                    f"committed to a substantive answer to the question the "
                    f"passage opened. "
                    + ("Do not let the final paragraph settle the original "
                       "question." if hi <= 0.5 else
                       "The final paragraph must actually land on a position."))

        f1 = round(f1 - (0.0 if (register_ok and posture_ok) else 0.05)
                   - (0.0 if opening_ok else 0.04)
                   - (0.0 if closing_ok else 0.04)
                   - (0.0 if commitment_ok else 0.04)
                   - (0.0 if middle_ok else 0.06), 3)

        return RealizedStructure(
            paragraph_functions=functions, matches=matches,
            thesis_first_visible_para=realized_thesis if isinstance(realized_thesis, int) else None,
            commitment_curve=curve, traps_present=traps_present,
            forbidden_tics_found=list(map(str, tics)),
            word_counts=[len(p.split()) for p in real_paras],
            f1=round(f1, 3), directives=directives,
            closing_posture_guess=posture_guess,
            final_line_is_aphorism=aph,
            rhetorical_moves=realized_moves,
            opening_beat_ok=opening_ok, closing_beat_ok=closing_ok,
            commitment_in_band=commitment_ok,
            middle_beats_ok=middle_ok,
            middle_retention=round(middle_retention, 3),
            gratuitous_moves=gratuitous)
