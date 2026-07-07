"""Stage 2 — PassageRenderer: generates the passage strictly from the
blueprint's structural contract. The prompt is assembled per-blueprint;
nothing structural is hardcoded here."""

from __future__ import annotations

from . import config
from .llm import CostLedger
from .models import Blueprint
from .registry import ComponentRegistry

RENDER_SYSTEM = """You are a writer producing intellectually serious long-form prose
(Aeon / LRB / Boston Review register) that will later be adapted into a CAT VARC
reading-comprehension passage.

You will receive a STRUCTURAL CONTRACT: an authorial persona, a paragraph-by-paragraph
movement plan, a thesis-revelation schedule, reader-trap directives, and an ending
directive. The contract fixes STRUCTURE. You invent all content.

HARD RULES:
1. Output ONLY the passage text: plain paragraphs separated by blank lines. No title,
   no headers, no commentary, no questions.
2. Produce EXACTLY the number of paragraphs specified, in order, each performing its
   assigned function within its word range.
3. The passage must read as a naturally occurring essay, not prose engineered to sound
   difficult. Sentence-by-sentence it stays readable; the difficulty is architectural.
4. Reader traps: each trap paragraph must genuinely INVITE the specified misreading
   from a fast reader while a careful reader can see past it. Never state the
   misreading; make it the path of least resistance.
5. The thesis must first become visible exactly where the revelation schedule says,
   in the manner it says.
6. Stay entirely in the specified persona's voice. Do not use any forbidden phrase.
7. No moralizing, no policy prescriptions, no direct address to the reader."""


class PassageRenderer:
    def __init__(self, registry: ComponentRegistry, llm):
        self.registry = registry
        self.llm = llm

    def render(self, bp: Blueprint, ledger: CostLedger,
               directives: list[str] | None = None) -> str:
        model, max_tokens = config.STAGE_CONFIG["render"][bp.tier]
        user = self._contract(bp, directives or [])
        text, truncated = self.llm.call(
            ledger, "render", model, max_tokens, RENDER_SYSTEM, user,
            context={"blueprint": bp})
        if truncated:
            raise TruncatedRender("render hit max_tokens")
        if not text or not text.strip():
            raise TruncatedRender("render returned an empty response")
        return text.strip()

    @staticmethod
    def _register_instruction(bp: Blueprint) -> str:
        for reg_id, _w, instruction in config.CLOSING_REGISTERS:
            if reg_id == bp.closing_register:
                return instruction
        # legacy blueprints without a register default to the anti-aphorism form
        return config.CLOSING_REGISTERS[0][2]

    def _contract(self, bp: Blueprint, directives: list[str]) -> str:
        persona = self.registry.get("persona", bp.persona_id)
        family = self.registry.get("family", bp.family_id)
        ending = self.registry.get("ending", bp.ending_id)
        rhythm = self.registry.get("rhythm", bp.rhythm_id)
        revelation = self.registry.get("revelation", bp.revelation_id)

        movement_lines = []
        for p in bp.movement:
            fn_human = p.function.replace("_", " ").lower()
            movement_lines.append(
                f"  Paragraph {p.para} ({p.len_words[0]}-{p.len_words[1]} words, "
                f"cadence: {p.cadence.replace('_', ' ')}): role = {fn_human}."
                + (f" Content brief: {p.gist}" if p.gist else ""))

        trap_lines = [
            f"  {t['trap_id']} (paragraph {t['anchor_para']}): invite the misreading that "
            f"\"{t['invited_misreading']}\" [mechanism: {t['mechanism']}]"
            for t in bp.trap_map]

        forbidden = config.GLOBAL_FORBIDDEN_TICS + persona.get("extra_forbidden", [])
        ts = bp.tension_system or {}
        primary = ts.get("primary", {})
        secondary = ts.get("secondary", {})

        return f"""STRUCTURAL CONTRACT

TOPIC: {bp.topic}
ARGUMENT FAMILY: {family['name']} — {family['core']}

PRIMARY TENSION: {primary.get('axis', 'n/a')} (poles: {', '.join(primary.get('poles', []))};
fate by the end: {primary.get('fate', 'n/a')})
SECONDARY TENSION: {secondary.get('axis', 'n/a')} (fate: {secondary.get('fate', 'n/a')})
INTERACTION: {ts.get('interaction', 'n/a')}
INSTABILITY DEGREE: {bp.instability} (0 = neat closure, 1 = fully suspended; this governs
how contested the MIDDLE of the passage feels — the ENDING's stance is governed by the
closing posture directive below, not by this number)

AUTHORIAL PERSONA: {persona['name']}
  Register: {persona['register']}
  Sentence signature: {persona['sentence_profile']}
  Hedging style: {persona['hedge_style']}
  Characteristic moves: {'; '.join(persona['signature_moves'])}
  Pronoun posture: {persona.get('pronoun_posture', 'neutral')}
  Metaphor domains to draw from: {', '.join(persona.get('metaphor_domains', []))}

PARAGRAPH MOVEMENT PLAN ({len(bp.movement)} paragraphs; rhythm: {rhythm['name']} — {rhythm['cadence_note']}):
{chr(10).join(movement_lines)}

THESIS REVELATION: {revelation['name']} — {revelation['mechanism']}
The thesis first becomes visible in paragraph {bp.revelation_detail.get('planned_para')}.
Before that point, the reader must not be able to state the passage's final position.

READER TRAPS (build these into the prose):
{chr(10).join(trap_lines)}

ENDING DIRECTIVE: {ending['name']} — {ending['gesture']}. Aperture: {ending['aperture']}.
CLOSING POSTURE (hard requirement): {self.registry.closing_postures[family['closing_posture']]}
FINAL SENTENCE: {self._register_instruction(bp)}

FORBIDDEN WORDS/PHRASES (never use any of these): {', '.join(forbidden)}
{("REVISION DIRECTIVES from the previous attempt (fix these precisely):" + chr(10) + chr(10).join('  - ' + d for d in directives)) if directives else ''}
Write the passage now."""


class TruncatedRender(RuntimeError):
    pass
