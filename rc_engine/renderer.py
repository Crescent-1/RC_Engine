"""Stage 2 — PassageRenderer: generates the passage strictly from the
blueprint's structural contract. The prompt is assembled per-blueprint;
nothing structural is hardcoded here."""

from __future__ import annotations

from . import config
from .llm import CostLedger
from .models import Blueprint
from .registry import ComponentRegistry

NL = chr(10)

RENDER_SYSTEM = """You are a writer producing intellectually serious prose that will
later be adapted into a CAT VARC reading-comprehension passage. Use the source
genre and assigned persona to set the register: explanation, history, criticism
and practical description need different sentence behaviour.

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
7. No moralizing, no policy prescriptions, no direct address to the reader.
8. ARCHITECTURE INVISIBILITY. The contract's structure is scaffolding for you, not
   content for the reader. Never use wording whose main job is to announce the
   passage's own argumentative shape — "the deeper issue", "the real point", "this
   raises the question", "the first objection", "what remains is", "it is worth
   pausing", "which brings us to", "the question then becomes" — or any equivalent
   signpost. A movement plan beat is performed, never named. The reader should be
   able to feel the turn without being told a turn is happening. The single
   exception is a genre that genuinely signposts (a formal review, a legal brief),
   and only where the persona already establishes that genre.
9. NO FABRICATED SCHOLARSHIP. Do not invent empirical studies, statistics,
   quotations, named scholars, institutions, dated experiments, or historical
   events and present them as real. This is the most common way generated prose
   fakes authority, and it makes the passage unusable as a test item: a
   well-read candidate who knows the field is penalised for knowing it.
   - Real, checkable references are fine when you are confident they are accurate
     (Shannon at Bell Labs in 1948; Boas on Kwakwaka'wakw texts).
   - Where the argument needs a case the world does not supply, keep it INTERNAL
     and verifiable inside the passage: an unnamed practitioner, a described
     document, a situation set out in enough detail that the reader can reason
     about it from the text alone. "A county assistance office with four
     caseworkers for a workload sized to nine" is legitimate; "a 2019 Michigan
     State study found that 62% of claimants..." is not.
   - When a beat plan asks you to quote an authority, satisfy it with a real
     source, a described-but-unnamed one, or a document the passage itself
     characterises — never with a plausible-sounding invention.
10. SUBJECT REGISTER — write about the thing, not the apparatus around it.
   Measured 2026-09-05 against 124 real CAT/XAT/GMAT passages: they use the
   vocabulary of measurement, procedure, records, categories and classification
   at 3.4 occurrences per 1000 words. This engine's passages use it at 10.0 —
   nearly three times as often — and the seeds it works from sit at 2.2, BELOW
   the exam. The register is being added here, not inherited.
   - When the topic is a phenomenon, explain the phenomenon. Real exam prose
     spends its length on how a thing works, what happened, why it changed.
   - Critiquing how something is known, counted or sorted is a legitimate
     subject when the topic is genuinely about that. It is not the default
     subject, and it is where this engine goes when it is not thinking.
   - Test the finished paragraph on its concrete nouns. If they are mostly the
     machinery around the subject rather than the people, objects, places and
     processes the passage is supposed to be about, rewrite toward the latter.
   No example phrases are quoted here deliberately. "no: more precisely" was
   given as an illustration in rule 11 below until 2026-08-22 and was copied
   verbatim into four passages; naming a pattern in this prompt reproduces it.
   (Numbered 10 because HUMAN TEXTURE below was mis-numbered 8, duplicating the
   ARCHITECTURE INVISIBILITY rule above; corrected to 11 in the same edit.)

11. HUMAN TEXTURE (a touch only — keep the intellect; break factory polish):
   - Use concrete particulars where they advance this argument, rather than adding
     a decorative detail to every passage. A detail added for texture must earn
     its place instead of becoming a system-metaphor.
     It belongs in the BODY: not the opening sentence, not the closing one.
     Measured 2026-08-29: this instruction alone put a concrete particular in
     sentence 1 of six of nine consecutive passages, none of which planned it.
     Barring it from the opening moved it to the close instead — all five of
     the next batch ended on a named physical object, a higher rate than the
     fifteen before. A tell that relocates has not been fixed. Place the
     particular where the ARGUMENT needs it, which is neither of the two
     positions a reader uses to recognise a writer.
   - Allow one sentence that is plainer / more workmanlike than its neighbors — not
     every sentence equally epigrammatic. One midstream re-steer is fine, if it
     arises from the argument rather than from a formula. Do NOT use a fixed
     correction phrase: "no: more precisely" was given here as an illustration
     until 2026-08-22 and was copied verbatim into four separate passages,
     where the similarity screen then flagged it as a shared tell. Re-steer in
     whatever words that sentence needs.
   - Mix sentence subjects; avoid a run of abstract openers ("The doctrine… The
     residue… The mechanism… The ledger…"). Prefer some agents and concrete nouns
     when the persona allows.
   - Do not default to the stock cadence "I grant X. The trouble is Y. What remains
     is Z." unless the movement plan requires that shape; rebuild the paragraph if
     you hear yourself writing it.
   - Soft-ban stock house metaphors (ledger / residue / aperture / altitude as
     default furniture) unless the topic forces them; invent fresher local images.
   - Still forbidden as "humanizing": typos, slang, throat-clearing, fake anecdotes,
     "as someone who…", reader address, moral lectures."""


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

    def _commitment_instruction(self, posture: str) -> str:
        """Say where the passage should END on the commitment scale.

        The scale was measured and weighted but never targeted: across 74 real
        curves the planned posture moved the realised endpoint by a spread of
        just 0.20, and refusal_suspended ended at a median of 0.93. Naming the
        band is the cheap half of the fix; ComplianceAuditor audits it.
        """
        band = config.POSTURE_END_COMMITMENT.get(posture)
        if not band:
            return ""
        lo, hi = band
        if hi <= 0.5:
            where = ("The passage must NOT arrive at a settled answer to the "
                     "question it opened. Argue the refusal as the correct "
                     "verdict, but do not let the closing paragraph read as a "
                     "position on the original question")
        elif hi <= 0.9:
            where = ("Commit firmly, but to the RELOCATED question — the "
                     "original one should still read as unsettled at the end")
        else:
            where = ("The closing paragraph must actually land on a position "
                     "and stay there")
        return (f"COMMITMENT AT THE CLOSE ({lo:+.2f} to {hi:+.2f} on a scale "
                f"where +1 is fully committed to a substantive answer to the "
                f"question the passage opened, and -1 points away from one): "
                f"{where}.")

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
        stance = (self.registry.get("render_stance", bp.render_stance_id)
                  if bp.render_stance_id else None)

        # The rhetorical beats are folded INTO the paragraph plan rather than
        # listed separately. Two parallel plans that never referenced each other
        # left the model to reconcile 8 beats against 5 paragraphs itself, and
        # the beat list was the only instruction in the whole contract with no
        # address. Measured 2026-09-05: every located constraint (word target,
        # role, thesis paragraph, trap anchor, first/last sentence) is obeyed;
        # the one unlocated instruction was obeyed 51% of the time.
        from .composer import BlueprintComposer
        alloc = BlueprintComposer.allocate_beats(bp.move_plan, bp.movement)             if bp.move_plan else [[] for _ in bp.movement]
        movement_lines = []
        for i, p in enumerate(bp.movement):
            fn_human = p.function.replace("_", " ").lower()
            beats = alloc[i] if i < len(alloc) else []
            movement_lines.append(
                f"  Paragraph {p.para} (~{p.words_label} words, "
                f"cadence: {p.cadence.replace('_', ' ')}): role = {fn_human}."
                + (f" Content brief: {p.gist}" if p.gist else ""))
            for m in beats:
                movement_lines.append(
                    f"       BEAT: {m} — {config.RHETORICAL_MOVES.get(m, '')}")

        trap_lines = [
            f"  {t['trap_id']} (paragraph {t['anchor_para']}): invite the misreading that "
            f"\"{t['invited_misreading']}\" [mechanism: {t['mechanism']}]"
            for t in bp.trap_map]

        forbidden = config.GLOBAL_FORBIDDEN_TICS + persona.get("extra_forbidden", [])
        ts = bp.tension_system or {}
        primary = ts.get("primary", {})
        secondary = ts.get("secondary", {})
        if ts.get("content_frame"):
            material_block = (f"CONTENT FRAME:\n{ts['content_frame']}\n"
                              "Use this material to carry the reasoning. No opposing "
                              "positions are required unless the plan names them.")
        else:
            material_block = (
                f"PRIMARY TENSION: {primary.get('axis', 'n/a')} "
                f"(poles: {', '.join(primary.get('poles', []))}; "
                f"fate by the end: {primary.get('fate', 'n/a')})\n"
                f"SECONDARY TENSION: {secondary.get('axis', 'n/a')} "
                f"(fate: {secondary.get('fate', 'n/a')})\n"
                f"INTERACTION: {ts.get('interaction', 'n/a')}")
        # Ask undershooting providers for a higher number than the band that
        # validates — see config.PROVIDER_WORD_TARGET_OFFSET.
        _off = config.PROVIDER_WORD_TARGET_OFFSET.get(config.ACTIVE_PROVIDER, 0)
        band_lo = config.PASSAGE_WORD_MIN + _off
        band_hi = config.PASSAGE_WORD_MAX + _off

        # A PLAN, not a ban list. The 2026-08-21 build put the rhetorical
        # grammar here as prohibitions — stance forbidden_beats plus up to four
        # saturation bans — and the renderer ignored all of them
        # (RC-ELITE-260821-0050 performed every banned move and closed on a
        # forbidden aphorism, twice). The paragraph movement plan below is
        # obeyed reliably in the same prompt, so the grammar is prescribed in
        # the same shape as that plan and audited the same way.
        beat_plan_block = ""
        if bp.move_plan:
            lines = NL.join(
                f"  {i}. {m} — {config.RHETORICAL_MOVES.get(m, '')}"
                for i, m in enumerate(bp.move_plan, start=1))
            first, last = bp.move_plan[0], bp.move_plan[-1]
            # The first and last beat are stated again, on their own, ABOVE the
            # list. Measured 2026-08-29 over the nine sets of 08-24..08-28, the
            # renderer obeyed the planned opening 2/9 and the planned closing
            # 1/9 while satisfying every beat somewhere in the middle — so the
            # list alone reads as an unordered menu however it is labelled.
            # The FINAL sentence gets the same weight as the first, and its
            # own prohibition. Measured 2026-08-29 across the batch that
            # followed the opening fix: openings went 2/9 -> 5/5, closings only
            # 1/9 -> 2/5, and all three misses collapsed to the SAME beat
            # (CONCRETE_RETURN). Reading the five, every one ended on a named
            # physical object — a higher rate than the 15 before the fix. The
            # particular did not disappear when it was barred from sentence
            # one; it relocated to the last sentence, which is the other
            # position a reader hears as voice.
            beat_plan_block = (
                f"FIRST SENTENCE — {first}: "
                f"{config.RHETORICAL_MOVES.get(first, '')}.{NL}"
                f"  Do NOT open on a concrete scene, object, or document "
                f"unless that beat literally says so.{NL}"
                f"FINAL SENTENCE — {last}: "
                f"{config.RHETORICAL_MOVES.get(last, '')}.{NL}"
                f"  The passage ENDS on this move. Do NOT land the last "
                f"sentence on a named physical object, a return to the opening "
                f"image, or a detachable quotable line, unless that beat "
                f"literally calls for one. Ending on a concrete particular is "
                f"this engine's most repeated tell; if you feel the pull "
                f"toward one, the beat above is what the ending owes "
                f"instead.{NL}"
                f"These two positions are not negotiable.{NL}{NL}"
                f"THE BODY BEATS ARE NOT OPTIONAL EITHER. You may run them in "
                f"whatever order the argument wants — that part is yours — but "
                f"every one must actually happen, and you may not substitute. "
                f"Measured across 13 consecutive passages, this renderer kept "
                f"only 43% of its planned middle beats and replaced the rest "
                f"with the same few gestures every time, whatever the plan said: "
                f"conceding an opposing account at length, then demolishing an "
                f"easy reading of it. If you feel that shape arriving and the "
                f"plan below did not ask for it, it is displacing a beat you "
                f"owe.{NL}{NL}"
                f"RHETORICAL BEAT PLAN — {len(bp.move_plan)} beats, and they "
                f"are assigned to specific paragraphs in the PARAGRAPH "
                f"MOVEMENT PLAN below. Perform each one where it is assigned. "
                f"Together they are the whole argument: if you find yourself "
                f"performing an operation that is not on this list, the beat it "
                f"displaced is the one you still owe. The full list, in "
                f"order:{NL}{lines}{NL}{NL}")

        stance_block = ""
        if stance:
            stance_block = (
                f"WRITING STANCE (the way this argument is developed within "
                f"the paragraph plan):{NL}"
                f"  {stance['name']}: {stance['frame']}{NL}"
                f"  Arc constraint: {stance['arc_constraint']}{NL}{NL}")

        # Positive prescription, deliberately. The render prompt already told
        # the model that critiquing how things are known "is not the default
        # subject", and 47% of the last 32 sets did it anyway — against 12.9%
        # of real exam passages. Everything this session actually moved was
        # moved by prescribing a thing, not by forbidding one (the opening beat
        # went 2/9 to 5/5 the moment it was stated positionally).
        schema = config.ARGUMENT_SCHEMAS.get(bp.argument_schema_id or "")
        schema_block = ""
        if schema:
            schema_block = (
                f"WHAT THE ARGUMENT DOES (the shape of the reasoning itself — this "
                f"is not the topic and not the family arc; it is what the passage "
                f"is FOR):{NL}  {schema['directive']}{NL}{NL}")

        return f"""STRUCTURAL CONTRACT

{schema_block}{stance_block}The schema is the primary reasoning purpose. Paragraph roles and beats
develop that argument; keep the content briefs consistent with it.
TOPIC: {bp.topic}
SOURCE GENRE: {bp.seed_genre or 'unspecified'}
TIER: {bp.tier} — {config.TIER_DIFFICULTY_CHARACTER.get(bp.tier, '')}
ARGUMENT FAMILY: {family['name']} — {family['core']}

{material_block}
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
  Texture: let this subject and persona determine the sentence detail. Perform
  self-correction when the plan calls for it, rather than adding a recurring tic.

TOTAL LENGTH (hard requirement): {band_lo}-{band_hi} words. Anything outside that
range is rejected. The per-paragraph targets below are sized to land inside it —
follow them and the total takes care of itself.

{beat_plan_block}PARAGRAPH MOVEMENT PLAN ({len(bp.movement)} paragraphs; rhythm: {rhythm['name']} — {rhythm['cadence_note']}):
{chr(10).join(movement_lines)}

THESIS REVELATION: {revelation['name']} — {revelation['mechanism']}
The thesis first becomes visible in paragraph {bp.revelation_detail.get('planned_para')}.
Before that point, the reader must not be able to state the passage's final position.

READER TRAPS (build these into the prose):
{chr(10).join(trap_lines)}

ENDING DIRECTIVE: {ending['name']} — {ending['gesture']}. Aperture: {ending['aperture']}.
CLOSING POSTURE (hard requirement): {self.registry.closing_postures[family['closing_posture']]}
{self._commitment_instruction(family['closing_posture'])}
FINAL SENTENCE: {self._register_instruction(bp)}

FORBIDDEN WORDS/PHRASES (never use any of these): {', '.join(forbidden)}
{("DIRECTIVES (hard requirements — satisfy every one):" + chr(10) + chr(10).join('  - ' + d for d in directives)) if directives else ''}
BEFORE YOU RESPOND: count the words in the passage you have written. If the
total is not between {band_lo} and {band_hi}, revise it into that range —
expand or compress the argument itself, do not pad with filler or amputate a
paragraph's function. Emit only the corrected passage.

Write the passage now."""


class TruncatedRender(RuntimeError):
    pass
