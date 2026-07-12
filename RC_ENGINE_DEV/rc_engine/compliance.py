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
- rate the author's apparent commitment to their final position in each paragraph,
  from -1.0 (actively pointing away from it) to 1.0 (fully committed),
- check each planned reader-trap: does the paragraph genuinely invite that misreading?
- list any forbidden phrases that appear,
- classify the passage's CLOSING POSTURE: the stance a careful reader takes away from
  the final paragraph, as exactly one of the labels defined in the input,
- judge whether the FINAL sentence is a detachable aphorism: terse, quotable,
  standalone — it would survive out of context as an epigram.

Respond ONLY with valid JSON, no markdown fences:
{
  "paragraphs": [{"para": 1, "function_guess": "<the planned function token, or OTHER>", "matches_plan": true, "word_count": 0}, ...],
  "thesis_first_visible_para": 1,
  "commitment_curve": [0.0, ...one per paragraph...],
  "traps_present": ["TR1", ...],
  "forbidden_tics_found": [],
  "closing_posture_guess": "<one label from CLOSING POSTURE LABELS>",
  "final_line_is_aphorism": false,
  "notes": "max 30 words"
}"""


class ComplianceAuditor:
    def __init__(self, llm, registry):
        self.llm = llm
        self.registry = registry

    def audit(self, passage: str, bp: Blueprint, ledger: CostLedger) -> RealizedStructure:
        model, max_tokens = config.STAGE_CONFIG["compliance"][bp.tier]
        plan_lines = "\n".join(
            f"  para {p.para}: function={p.function}, words {p.len_words[0]}-{p.len_words[1]}"
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
        return self._score(data, passage, bp)

    def _score(self, data: dict, passage: str, bp: Blueprint) -> RealizedStructure:
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

        # weighted structural score
        fn_score = sum(matches) / n if n else 0.0
        thesis_ok = (isinstance(realized_thesis, int)
                     and abs(realized_thesis - planned_thesis) <= 1)
        trap_score = len(traps_present) / max(1, len(bp.trap_map))
        para_count_ok = len(real_paras) == n
        f1 = 0.55 * fn_score + 0.15 * (1.0 if thesis_ok else 0.0) + \
             0.20 * trap_score + 0.10 * (1.0 if para_count_ok else 0.0)
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

        posture_guess = str(data.get("closing_posture_guess", "")).strip()
        if posture_guess not in self.registry.closing_postures:
            posture_guess = ""   # junk -> unusable; downstream checks skip
        aph = data.get("final_line_is_aphorism")
        aph = aph if isinstance(aph, bool) else None

        return RealizedStructure(
            paragraph_functions=functions, matches=matches,
            thesis_first_visible_para=realized_thesis if isinstance(realized_thesis, int) else None,
            commitment_curve=curve, traps_present=traps_present,
            forbidden_tics_found=list(map(str, tics)),
            word_counts=[len(p.split()) for p in real_paras],
            f1=round(f1, 3), directives=directives,
            closing_posture_guess=posture_guess,
            final_line_is_aphorism=aph)
