"""
RC Set Generation Pipeline — Tiered Difficulty
------------------------------------------------
Three difficulty tiers, each with its own generation prompt, judge rubric,
model assignment, and token budget:

  medium  -> Sonnet 5   -> one pivot/counterpoint, moderate distractors
  hard    -> Opus 4.8   -> two tensions, real traps, partial resolution
  elite   -> Opus 4.8   -> your flagship 99%ile spec, unresolved tension,
                           exhaustive 24-option elimination logic

Judge model is Haiku 4.5 for all tiers (cheap, consistent) — only the
RUBRIC changes per tier, since "dialectical density" is a flaw at lower
tiers and a requirement at Elite level.

Seed essays now come directly from the RAG vector store (RAG.py) instead
of a hardcoded string. Only Aeon-sourced essays are used as seeds for now,
and each essay is pulled only if it hasn't already been used as a source
(tracked via the "used" metadata flag in the vector store).

Two ways to run it (CLI flags, see the __main__ block at the bottom):

  1. Batch mode — choose the tier(s) and how many of each you want, each RC
     pulling a DIFFERENT unused Aeon essay as its seed:
         python rc_pipeline.py --hard 8 --elite 8   # 16 RCs, 16 distinct sources
         python rc_pipeline.py --medium 5

  2. Compare mode — generate_from_rag(conn) pulls ONE unused Aeon essay and
     runs ALL tiers against that SAME essay, so you can see exactly how
     difficulty scales on identical source material:
         python rc_pipeline.py --compare

Every essay pulled from the RAG vector store (RAG.py) is marked "used"
immediately after its RC is generated, so it's never picked as a seed again.

If the Anthropic API runs out of rate limit / credits mid-batch, the run
stops cleanly instead of burning through every remaining essay retrying a
call that will keep failing — whatever was successfully generated before
that point is already committed to the DB and gets exported. Simply re-run
the same command later; already-used essays are skipped automatically, so
you pick up where you left off.

Every run (batch or --compare) exports everything in the DB to .txt and a
combined .pdf when it finishes — whether it completed in full or stopped
early.

Requires: pip install anthropic --break-system-packages
Set ANTHROPIC_API_KEY as an environment variable before running.
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone
from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
)

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

SCRIPT_VERSION = "v10-seed-trim-capped-keys"


class APIExhaustedError(RuntimeError):
    """Raised when the Anthropic API signals it can't serve more requests
    right now (rate limit, insufficient credits/quota, or repeated
    connection failure) — as opposed to a one-off bad response that's
    fine to retry or skip. Batch runs catch this and stop cleanly rather
    than hammering every remaining essay with a call that will keep
    failing the same way."""
    pass


def _is_exhaustion_error(e: Exception) -> bool:
    """True for errors that mean 'stop sending requests for now'."""
    if isinstance(e, RateLimitError):
        return True
    if isinstance(e, APIConnectionError):
        return True
    if isinstance(e, APIStatusError):
        status = getattr(e, "status_code", None)
        if status in (429, 402, 529):  # rate limit, payment required, overloaded
            return True
        msg = str(e).lower()
        if "credit balance" in msg or "insufficient_quota" in msg or "quota" in msg:
            return True
    return False

JUDGE_MODEL = "claude-haiku-4-5-20251001"  # same judge model across all tiers

# $ per million tokens (in, out) — used to compute real cost per call.
# Sonnet 5 intro pricing runs through Aug 31 2026, then moves to $3/$15.
MODEL_RATES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}

MAX_REGENERATIONS = 2  # shared budget for truncation retries + low-score regenerations
DB_PATH = "rc_pipeline.db"

# Short letter used in generated RC IDs, e.g. RC_M_0507_1
TIER_LETTERS = {
    "medium": "M",
    "hard": "H",
    "elite": "E",
}

# For now, seeds are pulled only from this genre in the RAG vector store.
SEED_GENRE = "Aeon"

# ---------------------------------------------------------------------------
# MEDIUM — Sonnet 5
# ---------------------------------------------------------------------------

MEDIUM_GENERATION_PROMPT = """You are a CAT VARC content writer creating a MEDIUM-difficulty Reading Comprehension passage for aspirants who have mastered fundamentals and are building toward higher percentiles.

I. PASSAGE REQUIREMENTS
- Length: 400-450 words.
- Domain: opinion/analysis pieces from serious publications (op-eds, explainer essays, popular science or social commentary).
- Structure: ONE central claim, plus ONE significant complication or counterpoint the author addresses before returning to a qualified version of the original claim. Mostly linear, with exactly one clear pivot — not zero pivots (too easy) and not several (that's Hard tier).
- Vocabulary: some domain-specific terms, but supported by context — a careful reader should follow without outside knowledge.
- Tone: mostly clear, but allow ONE moment of qualification or hedging (e.g. "though not without exception", "largely, but not entirely").

II. QUESTIONS (6 questions)
Q1 - Main idea / central argument (must account for the pivot, not just the opening claim)
Q2 - Detail
Q3 - Inference (two logical steps)
Q4 - Function of the counterpoint/pivot (why the author introduces it)
Q5 - Vocabulary or phrase-in-context
Q6 - Author's tone (moderate nuance — e.g. "cautiously supportive", not simple positive/negative)

Each question has 4 options. Distractors: at least one genuinely tempting distractor per question
(a half-truth, or a claim true of the counterpoint but not the main thesis) — the rest clearly wrong.

II-A. OPTION SURFACE PARITY (HARD CONSTRAINTS — these override stylistic preferences)
1. WORD BAND: within each question, the longest option may contain no more than 1.25x the words of
   the shortest option, with an absolute spread of at most 8 words. If an option cannot fit the band,
   compress the idea, not the grammar.
2. LENGTH-CORRECTNESS DECOUPLING: across the 6 questions, the correct option may be the strictly
   longest option in AT MOST 1 question, and must be the shortest or second-shortest in at least 2.
   For Q1 (main idea) specifically, the correct option must NOT be the longest — let a distractor
   (e.g. an over-detailed half-truth) carry the longest, most elaborate phrasing, while the correct
   answer states the qualified claim compactly.
3. ANSWER-LETTER DISTRIBUTION: no letter may be correct more than twice across the set, and the same
   letter must not be correct in three consecutive questions. Do not favor B/C.
4. SYNTACTIC PARALLELISM: all four options in a question share grammatical scaffolding (all begin
   with a verb phrase, or all with "The author...", etc.), so no option is structurally conspicuous.
Before emitting the final output, silently count option words and tally answer letters; rewrite any
options that violate these rules. Do not print this audit.

III. ANSWER KEY
Correct answers get a 2-3 sentence explanation citing the structural or logical bridge. Wrong
answers get a SPECIFIC reason (half-truth, scope too narrow/broad, or unsupported) — not just
"incorrect".

IV. SOURCE ATTRIBUTION
End with: [Inspired by: "Essay/Article Title", Publication or Author]"""

MEDIUM_JUDGE_PROMPT = """You are a CAT VARC content quality auditor reviewing a MEDIUM-tier RC set.
At this tier, exactly ONE meaningful pivot/counterpoint is correct — zero pivots is too easy for
this tier, and multiple unresolved tensions belong to Hard tier instead. Score 5 dimensions,
0-10 each, with a one-line justification:

1. Clarity - is the passage followable despite the added complexity of the pivot?
2. Balanced Complexity - is there exactly one clear pivot, handled with appropriate nuance
   (not zero, not several)?
3. Option Design - are all 4 options well-formed, similar length, grammatically parallel?
4. Distractor Plausibility - is at least one distractor per question a genuine half-truth trap?
5. Explanation Quality - do wrong-answer explanations name a specific reason, not "incorrect"?

Output ONLY valid JSON, no markdown fences:
{
  "scores": {
    "clarity": {"score": 0, "note": "..."},
    "balanced_complexity": {"score": 0, "note": "..."},
    "option_design": {"score": 0, "note": "..."},
    "distractor_plausibility": {"score": 0, "note": "..."},
    "explanation_quality": {"score": 0, "note": "..."}
  },
  "average": 0.0,
  "verdict": "approve | regenerate"
}"""

# ---------------------------------------------------------------------------
# HARD — Opus 4.8 (one tier below flagship)
# ---------------------------------------------------------------------------

HARD_GENERATION_PROMPT = """You are a senior VARC content writer creating a HARD-difficulty Reading Comprehension passage for aspirants targeting the 90th-98th percentile — one tier below flagship 99%ile difficulty.

I. PASSAGE REQUIREMENTS
- Length: 450-500 words.
- Domain: serious long-form essays (Aeon-style philosophy, sociology, or political-economy commentary).
- Structure: at least TWO distinct tensions or competing frameworks. The passage may complicate
  its own opening claim, but should still arrive at a reasonably identifiable (if qualified)
  position by the end — unlike flagship level, full unresolved suspension is NOT required.
- Vocabulary: domain-specific, moderately dense.
- Sentence-level texture: some variation in cadence; avoid a completely uniform rhythm, but
  polish is acceptable here (unlike flagship level's deliberate roughness).

II. QUESTIONS (6 questions) — same 6 types as flagship, moderately calibrated:
Central Thesis, Logical Function/Structural Role, Contextual Inference, Critical Reasoning
Application (new scenario), Implicit Assumption, Authorial Stance/Tone.

II-A. OPTION SURFACE PARITY (HARD CONSTRAINTS — these override stylistic preferences)
1. WORD BAND: within each question, count the words of all four options. The longest option must
   contain no more than 1.25x the words of the shortest option, and the absolute spread must not
   exceed 8 words. If an option cannot express the idea within the band, compress the idea, not
   the grammar.
2. LENGTH-CORRECTNESS DECOUPLING: across the 6 questions, the correct option may be the strictly
   longest option in AT MOST 1 question, and must be the shortest or second-shortest option in at
   least 2 questions. For the Central Thesis question specifically, the correct option must NOT be
   the longest option.
3. COMPRESSION TECHNIQUE for the thesis answer: a correct thesis option does not need to enumerate
   every stage of the argument. It should name the governing tension and the passage's final
   (qualified) position in one compact clause, while at least one distractor spends MORE words
   elaborating a subtly wrong synthesis. Let a distractor carry the enumerative burden.
4. HEDGING PARITY: qualification markers ("while", "although", "partly", "may", "tends to",
   "rather than") must be distributed so that distractors collectively contain at least as many
   hedges as correct answers. The correct option must not be identifiable as "the most
   moderate-sounding one." In at least 2 questions, phrase the correct option more flatly than its
   strongest distractor.
5. ANSWER-LETTER DISTRIBUTION: no letter may be correct more than twice across the set, and the
   same letter must not be correct in three consecutive questions. Do not favor B/C.
6. SYNTACTIC PARALLELISM: all four options in a question share grammatical scaffolding, so no
   option is structurally conspicuous.
Before emitting the final output, silently verify: option word counts per question, which option
is longest vs which is correct, the answer-letter tally, and hedge distribution. Rewrite any
offending options, then emit. Do not print this audit.

III. DISTRACTOR ENGINEERING
Each question needs AT LEAST ONE real trap distractor (half-truth, scope distortion, or causal
reversal) — not all four options need to be traps, unlike flagship level. Distractors must match
correct answers in register and sophistication; extremity should be conceptual, not lexical
("completely", "never", "proves" are wasted distractors).

IV. ANSWER KEY & ELIMINATION LOGIC
For each wrong option, name the error type (half-truth, scope distortion, causal reversal,
imported framework, etc.) in 1-2 sentences. Correct options get the structural bridge explained.
No option may be skipped.

V. SOURCE ATTRIBUTION
End with: [Inspired by: "Actual Essay/Paper Title", Publication or Author] — the source must be
real and conceptually relevant."""

HARD_JUDGE_PROMPT = """You are a strict, adversarial CAT VARC content quality auditor reviewing a HARD-tier RC set — one tier below flagship 99%ile. Your default posture is skepticism: assume the set is mediocre until it proves otherwise with evidence you can quote. Evaluate in three stages; Stage 0 failures terminate evaluation.

STAGE 0 — COMPLETENESS GATES (binary; ALL must pass)
G1. Passage present and 400-550 words (count them; state the count).
G2. Exactly 6 questions, each with exactly 4 options labeled A-D, none truncated mid-sentence.
G3. Answer key states a correct letter for all 6 questions, gives elimination logic for ALL 18 wrong options and a validation for ALL 6 correct options — count the entries.
G4. Source attribution line present.
G5. No mid-sentence or mid-section truncation anywhere in the artifact.
If ANY gate fails: set every score to 0, "average" to 0.0, verdict to "regenerate", list the failed gate IDs in the gates note, and STOP. Do not score quality dimensions for an incomplete artifact — completeness is a precondition, not a dimension.

STAGE 1 — MECHANICAL BIAS AUDIT (perform the counts; report the numbers)
B1. LENGTH BIAS: for each question, count words per option. If the correct option is the strictly longest in 3 or more questions, or the Central Thesis question's correct answer is the longest option, add flag "length_bias" and cap Option Design at 4.
B2. LETTER CLUSTERING: tally the answer letters. If any letter is correct 4+ times, or one letter is correct in 3 consecutive questions, add flag "letter_bias" and cap Option Design at 5.
B3. HEDGE BIAS: if correct options are systematically the most hedged/moderate-sounding choice in 4 or more questions, add flag "hedge_bias" and cap Distractor Efficiency at 5.

STAGE 2 — DIMENSION SCORING (0-10 each)
Calibration anchors (apply strictly): 0-3 failing; 4-6 usable only after revision; 7-8 mock-ready for a 90-98 percentiler; 9-10 flagship-adjacent. A score of 7+ on any dimension REQUIRES quoting at least one specific line, option, or key entry as evidence; without evidence the maximum is 6. Most generated sets deserve 5-7 — do not award 8+ out of politeness.

1. Structural Complexity - at least 2 distinct tensions, with a reasonably identifiable (if qualified) position by the end — not fully unresolved like flagship, but not simplistically resolved either.
2. Distractor Efficiency - does every question have at least one real trap distractor (half-truth, scope distortion, causal reversal)? Name the trap type; if you cannot name it, the distractor is weak. Penalize lexical extremity used as a crutch. (Respect Stage 1 caps.)
3. Option Design - options well-constructed, word-band compliant, grammatically parallel, no structurally conspicuous option. (Respect Stage 1 caps.)
4. Pedagogical Explanations - elimination logic names specific error mechanisms tied to passage locations, not superficial labels like "not mentioned" or "too extreme".
5. Authorial Nuance - the author's stance is identifiable but not a simplistic binary.

Output ONLY valid JSON, no markdown fences:
{
  "gates": {"passed": true, "failed": [], "word_count": 0, "note": "..."},
  "bias": {"correct_is_longest_count": 0, "thesis_correct_is_longest": false, "letter_tally": {"A": 0, "B": 0, "C": 0, "D": 0}, "flags": []},
  "scores": {
    "structural_complexity": {"score": 0, "evidence": "", "note": "..."},
    "distractor_efficiency": {"score": 0, "evidence": "", "note": "..."},
    "option_design": {"score": 0, "evidence": "", "note": "..."},
    "pedagogical_explanations": {"score": 0, "evidence": "", "note": "..."},
    "authorial_nuance": {"score": 0, "evidence": "", "note": "..."}
  },
  "average": 0.0,
  "verdict": "approve | regenerate"
}
Verdict rules: "approve" ONLY if all gates pass, zero bias flags, every score >= 7, and average >= 7.0. Otherwise "regenerate"."""

# ---------------------------------------------------------------------------
# ELITE — Opus 4.8 (your original flagship 99%ile spec, unchanged)
# ---------------------------------------------------------------------------

ELITE_GENERATION_PROMPT = """You are a senior VARC content architect for a top-tier Indian CAT institute responsible for designing flagship mock RCs intended for 99+ percentile aspirants.
Your task is to generate a single exceptionally difficult Reading Comprehension passage and accompanying CAT-style question set whose difficulty emerges from argumentative instability, conceptual layering, and structural misdirection — not from obscure vocabulary or artificial opacity.
The prose should resemble intellectually serious long-form public scholarship (Aeon, LRB, n+1, Boston Review, Harper's, New Left Review, public-facing philosophy/sociology essays), while remaining readable on a sentence-by-sentence basis.
The passage must feel like a naturally occurring intellectual artifact later adapted into an RC — not like prose consciously engineered to "sound difficult."

I. PASSAGE REQUIREMENTS
1. Length: 500-550 words.
2. Domain (choose ONE): Philosophy of science / epistemology; Political economy / moral philosophy; Sociology of institutions / modernity; Cognitive science / philosophy of language.
The passage must revolve around a live conceptual tension rather than a descriptive topic.
3. Argumentative Architecture: the argument must move through at least three distinct intellectual positions, where an early framing is partially destabilized, a later corrective is itself qualified, and the ending reopens rather than resolves the central tension.
The passage must NOT arrive at a neat synthesis, endorse a single framework unambiguously, or conclude with moral clarity or policy prescription. The final movement should produce structural discomfort rather than closure.
4. Structural Shape: avoid visibly balanced construction. Vary paragraph size aggressively — include at least one dense analytical block and at least one short pivot paragraph, avoid evenly sized paragraphing. Avoid predictable "claim -> example -> conclusion" sequencing. Permit reversals, recursive qualifications, and temporary argumentative dead-ends.
5. Sentence-Level Texture: vary cadence sharply — alternate long periodic reasoning with compressed declarative interruptions. Allow occasional asymmetry, tonal friction, or syntactic roughness; avoid consistently polished rhetorical symmetry. Avoid stock intellectual transitions ("Furthermore", "Consequently", "Moreover", "In conclusion", "It is a testament to", "Paradigm", "Tapestry", "Delve"). Transitions should emerge through conceptual pressure rather than explicit signalling.
6. Intellectual Density: contain at least two competing explanatory frameworks, distinguish between local claims and global implications, and include at least one conceptual reversal that invalidates a naive reading of an earlier paragraph. At least one paragraph should reward rereading because its argumentative role only becomes clear retrospectively.

II. QUESTION SET (6 QUESTIONS)
Generate exactly 6 CAT-style MCQs, each with exactly 4 options (A-D).

II-A. OPTION SURFACE PARITY (HARD CONSTRAINTS — these override stylistic preferences)
1. WORD BAND: within each question, count the words of all four options. The longest option must contain no more than 1.25x the words of the shortest option, and the absolute spread must not exceed 8 words. If an option cannot express the idea within the band, compress the idea, not the grammar.
2. LENGTH-CORRECTNESS DECOUPLING: across the full set of 6 questions, the correct option may be the strictly longest option in AT MOST 1 question, and must be the shortest or second-shortest option in AT LEAST 2 questions. For the Central Thesis question specifically, the correct option must NOT be the longest option.
3. COMPRESSION TECHNIQUE for the thesis answer: a correct thesis option does not need to enumerate every dialectical stage. It should name the governing tension and the passage's final posture toward it in one compact clause (e.g., "treats X and Y as mutually destabilizing rather than reconcilable"), while at least one distractor spends MORE words elaborating a subtly wrong synthesis. Let a distractor carry the enumerative burden.
4. HEDGING PARITY: qualification markers ("while", "although", "partly", "may", "tends to", "without fully", "rather than") must be distributed so that distractors collectively contain at least as many hedges as correct answers. The correct option must not be identifiable as "the most moderate-sounding one." In at least 2 questions, the correct option should be phrased more flatly/assertively than its strongest distractor.
5. ANSWER-LETTER DISTRIBUTION: across the 6 questions, no letter may be correct more than twice, and the same letter must not be correct in three consecutive questions. Do not place correct answers preferentially at B/C.
6. SYNTACTIC PARALLELISM: all four options in a question should share grammatical scaffolding (all begin with a verb phrase, or all with "The author...", etc.) so that no option is structurally conspicuous.

III. QUESTION TYPES
Q1 - Central Thesis: requires integrating the full dialectical movement of the passage. Wrong options correspond to premature closure, anchoring on opening paragraphs, or anchoring on late-stage reversals. Remember II-A.2 and II-A.3: the correct option here must be compact; at least one distractor must be longer and more elaborate than it.
Q2 - Logical Function / Structural Role: why a particular analogy, concession, example, or tonal shift was introduced; correct answer identifies structural function, not local meaning.
Q3 - Contextual Inference: interpret a dense phrase, metaphor, or compressed conceptual claim, dependent on local argumentative context (not vocabulary testing).
Q4 - Critical Reasoning Application: a new real-world scenario (not a paraphrase of the passage); student identifies which mechanism from the passage best explains it.
Q5 - Implicit Assumption: an unstated premise necessary for a major argumentative move. Wrong options include externally imported theories, plausible-but-unnecessary assumptions, and claims the passage actively complicates.
Q6 - Authorial Stance / Tone: precise capture of the author's intellectual posture, avoiding simplistic binaries (positive/negative/optimistic/pessimistic) in favor of controlled ambivalence, analytical restraint, recursive qualification, or dialectical suspension.

IV. DISTRACTOR ENGINEERING
Every question must contain at least two highly attractive distractors, using traps such as: half-truths (accurate for one section but false globally), scope distortion, reversal of causal direction, imported frameworks not endorsed by the passage, over-resolution of intentionally unresolved tensions, misidentification of structural role. Wrong options should fail narrowly, not theatrically.
Distractors must match correct answers in register and sophistication. A distractor that is dumber-sounding, cruder, or visibly extreme ("completely", "entirely", "proves", "never") is a wasted distractor; extremity should be conceptual, not lexical.

V. ANALYTICAL SECTION
After the questions, include a section titled "Why this RC is difficult" with headers. Hard length caps apply — this section must be diagnostic, not essayistic:
- Hidden Structural Shifts: map the passage's argumentative trajectory and where readers likely freeze prematurely. MAXIMUM 3 sentences.
- Core Distractor Traps: name ONLY the 4-5 most dangerous distractors across the whole set, one line each (question + option letter + trap mechanism). Do NOT re-explain distractors here — the answer key already diagnoses every option; repeating that analysis is forbidden.
- Tonal Ambiguity: how the author's stance shifts, retracts, or suspends itself. MAXIMUM 3 sentences.
- Paragraph Function Matrix: exactly one line per paragraph (paragraph number -> argumentative function). No commentary beyond the one line.

VI. ANSWER KEY & ELIMINATION LOGIC
For every wrong option (all 18 of them): ONE sentence, MAXIMUM 25 words, naming the exact error mechanism (causal distortion, scope inversion, temporal misreading, structural freezing, false synthesis, framework importation, local/global confusion — never superficial labels like "not mentioned" or "too extreme") and the passage location it distorts. Model: "Scope inversion — elevates para 2's local claim about institutions into the passage's global thesis." For every correct option (all 6): MAXIMUM 2 sentences stating the structural or inferential bridge validating it. Do not restate option text, do not summarize the passage, do not pad — a precise 20-word diagnosis outranks an 80-word explanation. No option may be skipped.

VII. SELF-AUDIT (perform internally BEFORE producing final output; do not print the audit)
1. Count words in every option. Verify II-A.1 (word band) for all 6 questions.
2. Identify, per question, whether the correct option is the longest. Verify II-A.2 (at most 1 such question; thesis answer not longest; correct is shortest/second-shortest in >= 2 questions).
3. Tally the answer letters. Verify II-A.5.
4. Count hedge markers in correct answers vs distractors. Verify II-A.4.
5. Verify all 24 options have entries in the answer key.
If any check fails, silently rewrite the offending options/keys and re-run the audit. Only then emit the final output.

VIII. OUTPUT CONTRACT
Emit sections strictly in this order, fully, with no truncation and no meta-commentary:
[PASSAGE] -> [QUESTIONS 1-6] -> [WHY THIS RC IS DIFFICULT] -> [ANSWER KEY & ELIMINATION LOGIC] -> [SOURCE ATTRIBUTION]
Source attribution format: [Inspired by: "Actual Essay/Paper Title", Publication or Author] — the source must be real and conceptually relevant to the generated RC."""

ELITE_JUDGE_PROMPT = """You are a strict, adversarial CAT VARC content quality auditor. Your default posture is skepticism: assume the RC set is mediocre until it proves otherwise with evidence you can quote. You are the last gate before commercial sale; a false approve costs money and reputation. Evaluate in three stages. Do not skip stages. Stage 0 failures terminate evaluation.

STAGE 0 — COMPLETENESS GATES (binary; ALL must pass)
G1. Passage present and 450-600 words (count them; state the count).
G2. Exactly 6 questions, each with exactly 4 options labeled A-D, each ending in a complete sentence (no truncated options).
G3. Question types match the spec: Q1 thesis, Q2 structural role, Q3 contextual inference, Q4 application to a new scenario, Q5 implicit assumption, Q6 tone/stance. A question of the wrong type fails this gate.
G4. Analytical section present with ALL FOUR headers: Hidden Structural Shifts, Core Distractor Traps, Tonal Ambiguity, Paragraph Function Matrix (the matrix must actually be a table/structured list covering every paragraph).
G5. Answer key present with a stated correct letter for all 6 questions, elimination logic for ALL 18 wrong options, and a validation for ALL 6 correct options. Count the entries. Any missing entry fails this gate.
G6. Source attribution line present in the required format.
G7. No mid-sentence or mid-section truncation anywhere in the artifact.
If ANY gate fails: set every score to 0, "average" to 0.0, verdict to "regenerate", list the failed gate IDs, and STOP. Do not score quality dimensions for an incomplete artifact — completeness is a precondition, not a dimension.

STAGE 1 — MECHANICAL BIAS AUDIT (perform the counts; report the numbers)
B1. LENGTH BIAS: for each question, count words per option. Report in how many questions the correct option is the strictly longest. If 3 or more, or if the Q1 (thesis) correct answer is the longest option, add flag "length_bias" and cap Option Design at 4.
B2. LETTER CLUSTERING: report the answer-letter tally. If any letter is correct 4+ times, or one letter is correct in 3 consecutive questions, add flag "letter_bias" and cap Option Design at 5.
B3. HEDGE BIAS: count hedging markers ("while", "although", "partly", "may", "tends to", "rather than", "without") in correct options vs distractors. If correct options are systematically the most hedged/moderate choice in 4 or more questions, add flag "hedge_bias" and cap Distractor Efficiency at 5.
B4. ANSWERABILITY SPOT-CHECK: attempt Q1 and Q4 yourself using ONLY the passage, before reading the answer key. If your independently reasoned answer disagrees with the key and the key's justification does not convincingly defeat your reasoning, add flag "key_dispute" and cap Pedagogical Explanations at 4.

STAGE 2 — DIMENSION SCORING (0-10 each)
Calibration anchors (apply strictly): 0-3 failing, structural defects; 4-6 usable only after revision, competent but generic; 7-8 mock-ready, would survive scrutiny by a 99+ percentiler; 9-10 flagship, indistinguishable from the best commercially sold CAT material. A score of 7+ on any dimension REQUIRES quoting at least one specific line, option, or key entry as evidence. If you cannot quote evidence, the score is at most 6. Do not award 8+ out of politeness; most generated sets deserve 5-7.

1. Structural Asymmetry - does the passage preserve non-linear/dialectical structure (destabilized opening, qualified corrective, reopened ending) rather than flattening into thesis-antithesis-synthesis? Penalize neat closure.
2. Dialectical Density - competing frameworks genuinely in tension per paragraph, at least one retrospective-reread paragraph. Penalize decorative "on the other hand" pseudo-tension.
3. Option Design - parallel syntax, word-band compliance, no structurally conspicuous option. (Respect caps from Stage 1.)
4. Distractor Efficiency - per question, are there at least 2 distractors a strong reader could genuinely choose? Name the specific trap type each exploits; if you cannot name the trap, the distractor is weak. Penalize lexical extremity ("completely", "never") used as a crutch. (Respect caps from Stage 1.)
5. Pedagogical Explanations - does elimination logic diagnose named error mechanisms (scope inversion, structural freezing, false synthesis, framework importation, causal distortion, local/global confusion) tied to specific passage locations, rather than "not mentioned"/"too extreme"? (Respect caps from Stage 1.)

Output ONLY valid JSON, no markdown fences:
{
  "gates": {"passed": true, "failed": [], "word_count": 0, "note": "..."},
  "bias": {
    "correct_is_longest_count": 0,
    "q1_correct_is_longest": false,
    "letter_tally": {"A": 0, "B": 0, "C": 0, "D": 0},
    "key_dispute": {"flag": false, "detail": ""},
    "flags": []
  },
  "scores": {
    "structural_asymmetry": {"score": 0, "evidence": "", "note": "..."},
    "dialectical_density": {"score": 0, "evidence": "", "note": "..."},
    "option_design": {"score": 0, "evidence": "", "note": "..."},
    "distractor_efficiency": {"score": 0, "evidence": "", "note": "..."},
    "pedagogical_explanations": {"score": 0, "evidence": "", "note": "..."}
  },
  "average": 0.0,
  "verdict": "approve | regenerate",
  "revision_directives": ["specific, actionable fix", "..."]
}
Verdict rules: "approve" ONLY if all gates pass, zero Stage 1 flags, every score >= 7, and average >= 7.5. Otherwise "regenerate". revision_directives must be concrete enough to feed back into a regeneration prompt (e.g., "Q1 correct option is 41 words vs distractor max 28 — compress to <= 30 words and shift enumerative detail into option C")."""

# ---------------------------------------------------------------------------
# Tier registry — everything a tier needs, in one place
# ---------------------------------------------------------------------------

TIER_CONFIGS = {
    "medium": {
        "gen_model": "claude-sonnet-5",
        "gen_prompt": MEDIUM_GENERATION_PROMPT,
        "judge_prompt": MEDIUM_JUDGE_PROMPT,
        "gen_max_tokens": 20000,
        "judge_max_tokens": 800,    # judge unchanged — small flat JSON
        "score_threshold": 7.0,
    },
    "hard": {
        "gen_model": "claude-opus-4-8",
        "gen_prompt": HARD_GENERATION_PROMPT,
        "judge_prompt": HARD_JUDGE_PROMPT,
        "gen_max_tokens": 20000,
        "judge_max_tokens": 2000,   # gated judge: gate notes + bias tallies + evidence
        "score_threshold": 7.0,
    },
    "elite": {
        "gen_model": "claude-opus-4-8",
        "gen_prompt": ELITE_GENERATION_PROMPT,
        "judge_prompt": ELITE_JUDGE_PROMPT,
        "gen_max_tokens": 20000,
        "judge_max_tokens": 2500,   # gated judge + blind spot-check + revision directives
        "score_threshold": 7.0,
    },
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rc_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rc_id TEXT UNIQUE,
            tier TEXT,
            rc_text TEXT,
            judge_json TEXT,
            average_score REAL,
            status TEXT,
            essay_doc_id TEXT,
            essay_url TEXT,
            gen_input_tokens INTEGER,
            gen_output_tokens INTEGER,
            judge_input_tokens INTEGER,
            judge_output_tokens INTEGER,
            gen_cost_usd REAL,
            judge_cost_usd REAL,
            total_cost_usd REAL,
            attempts INTEGER,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tier TEXT,
            call_type TEXT,
            raw_text TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    return conn


def _save_raw_response(conn, tier: str, call_type: str, raw_text: str, in_tok: int, out_tok: int):
    conn.execute(
        """INSERT INTO raw_responses (tier, call_type, raw_text, input_tokens, output_tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tier, call_type, raw_text, in_tok, out_tok, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _extract_json(text: str) -> dict:
    """Strip accidental markdown fences and parse JSON safely, ignoring
    any trailing text the model appended after the JSON object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response:\n{cleaned[:500]}")
    cleaned = cleaned[start:]

    try:
        obj, _end_index = json.JSONDecoder().raw_decode(cleaned)
        return obj
    except json.JSONDecodeError as e:
        print("---- RAW JUDGE OUTPUT (for debugging) ----")
        print(text[:1000])
        print("-------------------------------------------")
        raise


def generate_rc_id(conn, tier: str) -> str:
    """Builds an ID like RC_M_0705_1 — tier letter, MMDD, and a same-day
    sequence number for that tier (checked against what's already in the DB)."""
    letter = TIER_LETTERS[tier]
    date_str = datetime.now(timezone.utc).strftime("%m%d")
    prefix = f"RC_{letter}_{date_str}_"
    existing = conn.execute(
        "SELECT COUNT(*) FROM rc_sets WHERE rc_id LIKE ?", (prefix + "%",)
    ).fetchone()
    seq = (existing[0] if existing else 0) + 1
    return f"{prefix}{seq}"


SEED_HEAD_WORDS = 700   # opening movements carry the framing and tension
SEED_TAIL_WORDS = 200   # closing words preserve the essay's late-stage turn


def _trim_seed_essay(essay: str) -> str:
    """Full Aeon essays run 2,500-6,000 words (~3-8k input tokens) but the
    generation prompt only asks the model to echo the essay's domain and
    tension — the whole text is mostly wasted input spend. Keep the first
    ~700 words plus the last ~200 (so the essay's concluding turn survives)."""
    words = essay.split()
    if len(words) <= SEED_HEAD_WORDS + SEED_TAIL_WORDS:
        return essay
    head = " ".join(words[:SEED_HEAD_WORDS])
    tail = " ".join(words[-SEED_TAIL_WORDS:])
    return f"{head}\n\n[... middle of essay omitted ...]\n\n{tail}"


def generate_rc_set(tier: str, seed_essay: str | None = None) -> tuple[str, int, int, bool]:
    """Returns (raw_text, input_tokens, output_tokens, truncated) for the given tier."""
    cfg = TIER_CONFIGS[tier]
    if seed_essay:
        seed_essay = _trim_seed_essay(seed_essay)
    user_content = (
        f"Optional inspiration essay (adapt/echo its domain and tension, do not copy it):\n\n{seed_essay}"
        if seed_essay else
        "Generate one RC set now, choosing the domain yourself per the spec."
    )
    response = client.messages.create(
        model=cfg["gen_model"],
        max_tokens=cfg["gen_max_tokens"],
        system=cfg["gen_prompt"],
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    truncated = response.stop_reason == "max_tokens"
    return text, response.usage.input_tokens, response.usage.output_tokens, truncated


def judge_rc_set(conn, tier: str, rc_text: str) -> tuple[dict, int, int]:
    cfg = TIER_CONFIGS[tier]
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=cfg.get("judge_max_tokens", 800),
        system=cfg["judge_prompt"],
        messages=[{"role": "user", "content": rc_text}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    in_tok, out_tok = response.usage.input_tokens, response.usage.output_tokens
    _save_raw_response(conn, tier, "judge", text, in_tok, out_tok)

    try:
        verdict = _extract_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [WARN] Judge JSON parse failed ({e}). Raw output saved. Treating as needs_review.")
        verdict = {"scores": {}, "average": 0.0, "verdict": "parse_error"}

    return verdict, in_tok, out_tok


def process_one(
    tier: str,
    conn,
    seed_essay: str | None = None,
    essay_doc_id: str | None = None,
    essay_url: str | None = None,
):
    """Generates + judges one RC set for a tier, inserts it into the DB with
    a freshly-minted rc_id, and returns (rc_id, rc_text, judge, status, cost)."""
    cfg = TIER_CONFIGS[tier]
    gen_rate_in, gen_rate_out = MODEL_RATES[cfg["gen_model"]]
    judge_rate_in, judge_rate_out = MODEL_RATES[JUDGE_MODEL]

    gen_in_total, gen_out_total = 0, 0
    judge_in_total, judge_out_total = 0, 0
    attempt = 0
    best_rc, best_judge, best_avg = None, None, -1
    was_truncated_ever = False

    while attempt <= MAX_REGENERATIONS:
        try:
            rc_text, gi, go, truncated = generate_rc_set(tier, seed_essay)
        except Exception as e:
            print(f"  [ERROR] Generation call failed: {e}")
            break

        gen_in_total += gi
        gen_out_total += go
        _save_raw_response(conn, tier, "generation", rc_text, gi, go)

        if truncated:
            was_truncated_ever = True
            print(f"  [WARN] [{tier}] Generation hit max_tokens ({cfg['gen_max_tokens']}). "
                  f"Skipping judge call, retrying generation.")
            attempt += 1
            continue

        judge, ji, jo = judge_rc_set(conn, tier, rc_text)
        judge_in_total += ji
        judge_out_total += jo

        avg = judge.get("average", 0) or 0
        if avg > best_avg:
            best_rc, best_judge, best_avg = rc_text, judge, avg

        if avg >= cfg["score_threshold"]:
            break
        attempt += 1

    if best_rc is None:
        reason = "all attempts truncated" if was_truncated_ever else "no successful generation"
        print(f"  [ERROR] [{tier}] {reason} this run — skipping DB insert.")
        return None, None, None, "failed", 0.0

    status = "approved" if best_avg >= cfg["score_threshold"] else "needs_review"
    rc_id = generate_rc_id(conn, tier)

    gen_cost = (gen_in_total / 1_000_000) * gen_rate_in + (gen_out_total / 1_000_000) * gen_rate_out
    judge_cost = (judge_in_total / 1_000_000) * judge_rate_in + (judge_out_total / 1_000_000) * judge_rate_out
    total_cost = gen_cost + judge_cost

    conn.execute(
        """INSERT INTO rc_sets
           (rc_id, tier, rc_text, judge_json, average_score, status,
            essay_doc_id, essay_url,
            gen_input_tokens, gen_output_tokens, judge_input_tokens, judge_output_tokens,
            gen_cost_usd, judge_cost_usd, total_cost_usd, attempts, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rc_id, tier, best_rc, json.dumps(best_judge, ensure_ascii=False), best_avg, status,
            essay_doc_id, essay_url,
            gen_in_total, gen_out_total, judge_in_total, judge_out_total,
            gen_cost, judge_cost, total_cost, attempt + 1,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()

    print(f"  [{rc_id}] [{tier.upper()}] status={status} avg={best_avg} attempts={attempt + 1} | "
          f"gen({cfg['gen_model']})={gen_in_total}/{gen_out_total}tok "
          f"judge={judge_in_total}/{judge_out_total}tok | "
          f"cost=${total_cost:.4f}")

    return rc_id, best_rc, best_judge, status, total_cost


def generate_from_rag(conn=None, tiers: list[str] | None = None, rag_db=None):
    """Pulls ONE unused Aeon essay straight from the RAG vector store (RAG.py)
    and generates all the given tiers from that SAME essay, so difficulty
    scaling can be compared on identical source material.

    Once at least one tier succeeds, the essay is marked "used" in the vector
    store (with a timestamp and the rc_id(s) produced from it), so it won't be
    picked as a seed again.
    """
    from RAG import get_db, get_unused_essay, mark_essay_used

    own_conn = conn is None
    if own_conn:
        conn = init_db()

    rag_db = rag_db or get_db()
    essay = get_unused_essay(rag_db, genre=SEED_GENRE)
    if essay is None:
        print(f"[RAG] No unused '{SEED_GENRE}' essays available in the vector store.")
        if own_conn:
            conn.close()
        return []

    seed_essay = essay["text"]
    essay_title = essay["metadata"].get("title", "Untitled")
    essay_url = essay["metadata"].get("url")
    print(f"[RAG] Seed essay: '{essay_title}' (doc_id={essay['id']}, genre={SEED_GENRE})")

    tiers = tiers or ["medium", "hard", "elite"]
    results = []
    produced_rc_ids = []

    for tier in tiers:
        print(f"\n=== Tier: {tier} ===")
        rc_id, rc_text, judge, status, cost = process_one(
            tier, conn, seed_essay=seed_essay,
            essay_doc_id=essay["id"], essay_url=essay_url,
        )
        if rc_id:
            produced_rc_ids.append(rc_id)
        results.append({
            "rc_id": rc_id,
            "tier": tier,
            "status": status,
            "score": judge.get("average") if judge else None,
            "cost_usd": cost,
            "model": TIER_CONFIGS[tier]["gen_model"],
        })
        time.sleep(1)

    print("\n--- Tier comparison summary (same seed essay) ---")
    for r in results:
        print(f"{str(r['rc_id']):16s} | {r['tier']:8s} | model={r['model']:18s} | "
              f"status={str(r['status']):12s} | score={r['score']} | cost=${r['cost_usd']:.4f}")

    if produced_rc_ids:
        mark_essay_used(rag_db, essay["id"], rc_id=",".join(produced_rc_ids))
        print(f"\n[RAG] Marked essay '{essay_title}' as used (rc_ids: {', '.join(produced_rc_ids)})")
    else:
        print(f"\n[RAG] No tier succeeded — leaving essay '{essay_title}' unused for a future retry.")

    if own_conn:
        conn.close()

    return results


def generate_batch(tier_counts: dict[str, int], conn=None, rag_db=None):
    """Generates the requested number of RCs per tier, e.g. {"hard": 8, "elite": 8}.
    Each RC is pulled from a DIFFERENT unused Aeon essay — so a mix like
    {"hard": 8, "elite": 8} draws on 16 distinct sources, not one shared essay.

    Every essay is marked "used" the moment its RC is generated, so a source
    is never reused across calls (including across different tiers in the
    same batch).
    """
    from RAG import get_db, get_unused_essay, mark_essay_used

    own_conn = conn is None
    if own_conn:
        conn = init_db()
    rag_db = rag_db or get_db()

    results = []
    for tier, count in tier_counts.items():
        if tier not in TIER_CONFIGS:
            print(f"[SKIP] Unknown tier '{tier}' — must be one of {list(TIER_CONFIGS)}.")
            continue
        if count <= 0:
            continue

        for i in range(count):
            essay = get_unused_essay(rag_db, genre=SEED_GENRE)
            if essay is None:
                print(f"[RAG] No more unused '{SEED_GENRE}' essays available — "
                      f"stopping '{tier}' early ({i}/{count} generated).")
                break

            essay_title = essay["metadata"].get("title", "Untitled")
            print(f"\n=== [{tier}] {i + 1}/{count} | seed: '{essay_title}' (doc_id={essay['id']}) ===")

            rc_id, rc_text, judge, status, cost = process_one(
                tier, conn, seed_essay=essay["text"],
                essay_doc_id=essay["id"], essay_url=essay["metadata"].get("url"),
            )

            if rc_id:
                mark_essay_used(rag_db, essay["id"], rc_id=rc_id)
                print(f"[RAG] Marked '{essay_title}' as used (rc_id={rc_id})")
            else:
                print(f"[RAG] Generation failed — leaving '{essay_title}' unused for a future retry.")

            results.append({
                "rc_id": rc_id,
                "tier": tier,
                "status": status,
                "score": judge.get("average") if judge else None,
                "cost_usd": cost,
                "essay_title": essay_title,
            })
            time.sleep(1)

    print("\n--- Batch generation summary ---")
    total_cost = 0.0
    for r in results:
        total_cost += r["cost_usd"] or 0
        print(f"{str(r['rc_id']):16s} | {r['tier']:8s} | status={str(r['status']):12s} | "
              f"score={r['score']} | cost=${r['cost_usd']:.4f} | source='{r['essay_title']}'")
    print(f"\nTotal: {len(results)} RC(s) generated | total cost=${total_cost:.4f}")

    if own_conn:
        conn.close()

    return results


def print_cost_summary(conn, planned_monthly_mix: dict | None = None):
    """planned_monthly_mix example: {'medium': 20, 'hard': 15, 'elite': 15}"""
    usd_to_inr = 87
    print("\n--- Cost summary by tier ---")
    tier_avgs = {}
    for tier in TIER_CONFIGS:
        row = conn.execute(
            "SELECT COUNT(*), AVG(total_cost_usd) FROM rc_sets WHERE tier = ?", (tier,)
        ).fetchone()
        n, avg_cost = row
        if n:
            tier_avgs[tier] = avg_cost
            print(f"{tier:8s}: {n} logged, avg cost/set = ${avg_cost:.4f} (~₹{avg_cost * usd_to_inr:.2f})")
        else:
            print(f"{tier:8s}: no sets logged yet")

    if planned_monthly_mix:
        total_usd = sum(tier_avgs.get(t, 0) * count for t, count in planned_monthly_mix.items())
        print(f"\nProjected monthly cost for mix {planned_monthly_mix}: "
              f"${total_usd:.2f} (~₹{total_usd * usd_to_inr:.0f})")


# ---------------------------------------------------------------------------
# Export — pull generated RC sets out of SQLite as .txt or .pdf
# ---------------------------------------------------------------------------

def export_to_txt(conn, output_dir: str = "exported_rc_sets", only_status: str | None = "approved",
                   tier: str | None = None):
    os.makedirs(output_dir, exist_ok=True)
    query = "SELECT rc_id, id, tier, rc_text, average_score, status, created_at FROM rc_sets WHERE 1=1"
    params = []
    if only_status:
        query += " AND status = ?"
        params.append(only_status)
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    rows = conn.execute(query, params).fetchall()

    for rc_id, id_, tier_, rc_text, avg, status, created_at in rows:
        header = (f"RC ID: {rc_id} | Row #{id_} | Tier: {tier_} | Score: {avg} | Status: {status} | "
                  f"Generated: {created_at}\n{'=' * 70}\n\n")
        path = os.path.join(output_dir, f"{rc_id or f'rc_{tier_}_{id_:04d}'}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + rc_text)

    print(f"Exported {len(rows)} set(s) to .txt in '{output_dir}/'")
    return len(rows)


def _markdown_line_to_flowable(line: str, styles):
    from reportlab.platypus import Paragraph, Spacer
    import re

    raw = line.strip()
    if not raw:
        return Spacer(1, 6)

    escaped = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!<b>)\*(.+?)\*(?!</b>)", r"<i>\1</i>", escaped)

    is_roman_header = bool(re.match(r"^(I|II|III|IV|V|VI|VII)\.\s", raw))
    is_question_header = bool(re.match(r"^Q[1-6]\b", raw))
    is_markdown_heading = raw.startswith("#")
    is_short_titlecase = len(raw) < 60 and raw.endswith(":") is False and raw.isupper()

    if is_roman_header or is_markdown_heading:
        text = re.sub(r"^#+\s*", "", escaped)
        return Paragraph(text, styles["Heading2"])
    if is_question_header:
        return Paragraph(escaped, styles["Heading3"])
    if is_short_titlecase:
        return Paragraph(escaped, styles["Heading4"])
    return Paragraph(escaped, styles["Normal"])


def export_to_pdf(conn, output_dir: str = "exported_rc_sets", only_status: str | None = "approved",
                   tier: str | None = None, combined_filename: str | None = None):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet

    os.makedirs(output_dir, exist_ok=True)
    styles = getSampleStyleSheet()

    query = "SELECT rc_id, id, tier, rc_text, average_score, status, created_at FROM rc_sets WHERE 1=1"
    params = []
    if only_status:
        query += " AND status = ?"
        params.append(only_status)
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    rows = conn.execute(query, params).fetchall()

    def build_story_for_set(rc_id, id_, tier_, rc_text, avg, status, created_at):
        story = [
            Paragraph(f"{rc_id} ({tier_})", styles["Title"]),
            Paragraph(f"Row #{id_} | Score: {avg} | Status: {status} | Generated: {created_at}", styles["Normal"]),
            Spacer(1, 12),
        ]
        for line in rc_text.split("\n"):
            story.append(_markdown_line_to_flowable(line, styles))
        return story

    if combined_filename:
        path = os.path.join(output_dir, combined_filename)
        doc = SimpleDocTemplate(path, pagesize=letter)
        full_story = []
        for i, (rc_id, id_, tier_, rc_text, avg, status, created_at) in enumerate(rows):
            full_story.extend(build_story_for_set(rc_id, id_, tier_, rc_text, avg, status, created_at))
            if i < len(rows) - 1:
                full_story.append(PageBreak())
        doc.build(full_story)
        print(f"Exported {len(rows)} set(s) into combined PDF: {path}")
    else:
        for rc_id, id_, tier_, rc_text, avg, status, created_at in rows:
            path = os.path.join(output_dir, f"{rc_id or f'rc_{tier_}_{id_:04d}'}.pdf")
            doc = SimpleDocTemplate(path, pagesize=letter)
            doc.build(build_story_for_set(rc_id, id_, tier_, rc_text, avg, status, created_at))
        print(f"Exported {len(rows)} set(s) to individual PDFs in '{output_dir}/'")

    return len(rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate CAT VARC RC sets from RAG-sourced Aeon essays.",
        epilog=(
            "Examples:\n"
            "  python rc_pipeline.py --hard 8 --elite 8   "
            "(16 RCs total, each from a DIFFERENT unused essay)\n"
            "  python rc_pipeline.py --medium 5\n"
            "  python rc_pipeline.py --compare             "
            "(1 medium + 1 hard + 1 elite, all from the SAME shared essay)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--medium", type=int, default=0, help="Number of medium-tier RCs to generate")
    parser.add_argument("--hard", type=int, default=0, help="Number of hard-tier RCs to generate")
    parser.add_argument("--elite", type=int, default=0, help="Number of elite-tier RCs to generate")
    parser.add_argument(
        "--compare", action="store_true",
        help="Ignore the counts above; generate ONE RC per tier (medium+hard+elite) from a "
             "SINGLE shared essay for a side-by-side difficulty comparison.",
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export all sets currently in the DB to .txt and a combined .pdf after running.",
    )
    args = parser.parse_args()

    print(f"Running rc_pipeline.py [{SCRIPT_VERSION}]")
    conn = init_db()

    if args.compare:
        # One shared essay run through all three tiers, so you can compare
        # difficulty scaling on identical source material.
        generate_from_rag(conn, tiers=["medium", "hard", "elite"])
    else:
        tier_counts = {"medium": args.medium, "hard": args.hard, "elite": args.elite}
        tier_counts = {t: c for t, c in tier_counts.items() if c > 0}

        if not tier_counts:
            parser.print_help()
        else:
            # Each requested RC pulls its own fresh, never-before-used essay.
            generate_batch(tier_counts, conn=conn)

    print_cost_summary(conn, planned_monthly_mix={"medium": 20, "hard": 15, "elite": 15})

    if args.export:
        export_to_txt(conn, only_status=None)
        export_to_pdf(conn, only_status=None, combined_filename="rc_batch.pdf")

    conn.close()