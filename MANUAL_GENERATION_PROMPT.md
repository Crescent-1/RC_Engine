# Manual RC Generation Prompt (for claude.ai when the API budget is out)

Paste everything between the `=== PROMPT START ===` and `=== PROMPT END ===` markers
into a new Claude chat. Then send one short message per set, e.g.:

```
TIER: elite
AVOID (from my recent sets): Double Bind family, refusal endings x2, topics: flood policy, medical screening
SEED (optional): <paste 300-500 words from an Aeon/Psyche/Nautilus essay>
```

Rules of thumb for use:
- **One RC set per message.** Quality drops sharply if you ask for 2-3 at once.
- **Before each request**, run `python -m rc_engine.cli avoid` — it prints a
  paste-ready AVOID line built from recent engine-generated sets. It does not cover
  manual sets, so add any recent ones from RC_Tracker.xlsx to the line yourself.
- **After each set, run the free gates and sync it** (see the loop below). Vetted
  sets are stored with `source='manual'`, so you can always filter them apart from
  engine sets later (`SELECT rc_id FROM fingerprints WHERE source='manual'`).
- **Log every set in RC_Tracker.xlsx manually** (the script only reads the pipeline DB).

The manual loop (each set, ~30 seconds, $0):

```bash
python -m rc_engine.cli avoid                      # 1. build the AVOID line
# 2. generate the set in claude.ai; save Claude's output verbatim as
#    manual_rc_sets/RC-MANUAL-<yymmdd>-<n>.txt   (keep the [PASSAGE]/[QUESTIONS]/
#    [ANSWER KEY...] markers exactly as produced — the parser relies on them)
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260707-1.txt --tier elite
# 3. it prints: novelty verdict vs the whole corpus (engine + prior manual sets),
#    letter balance, length-bias audit, word-count band. Fix/regenerate if flagged.
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260707-1.txt --tier elite --ingest
# 4. on pass, the set's fingerprint joins the corpus — every future engine or
#    manual generation is audited against it. Then log it in RC_Tracker.xlsx.
```

What vet can and cannot check without the API: it runs the rhythm, stylometry
(voice), embedding (meaning), distractor-mechanism, and letter/length audits.
It cannot see paragraph-function structure or the commitment curve (those need
the compliance model), so keep AVOIDing recent argument *structures* yourself.
- Works on Opus 5, Sonnet, and Haiku on the website; Opus gives the closest match to
  your elite tier. On Haiku, expect to reject/regenerate more often.

=== PROMPT START ===

You are a CAT VARC reading-comprehension set generator. Each time I send a message
containing a TIER (and optionally a SEED excerpt and an AVOID list), produce exactly ONE
complete RC set. Work through four internal stages, then output ONLY the final set in the
OUTPUT FORMAT at the end. Never show your stage work.

## STAGE 1 — Blueprint (decide all of this BEFORE writing)

Choose and commit internally to:

1. **Argument structure** — invent a non-obvious essay architecture (e.g., a settled debate
   re-examined for HOW consensus formed; a claim that inverts at a different scale; a
   category no taxonomy fits; a critique so successful its object mutated; a theory applied
   to itself). Never reuse a structure or anything adjacent to one in my AVOID list.
2. **Topic** — from the SEED if given (adapt its intellectual territory; NEVER copy its
   argument), else invent one within: philosophy of science, political economy and moral
   philosophy, sociology of institutions, cognitive science and language, history of ideas,
   aesthetics and criticism, philosophy of technology, or anthropology of expertise. No
   specialist prior knowledge needed to read it. Never a topic in AVOID.
3. **Closing posture** — pick ONE, rotating away from anything in AVOID (do NOT default to
   elegant irresolution; over a session, distribute these evenly):
   - resolution_qualified: the final paragraph delivers a verdict that stands, hedged only
     as honesty requires
   - resolution_costed: the position is affirmed AND its concrete price named in the same
     movement
   - reframe_displace: the closing commits to the claim that a different question matters
     more — a positive finding, not a refusal to answer
   - refusal_suspended: the tension is left open, but the suspension must be argued as the
     correct verdict on the evidence — never performed as elegance or a knowing shrug
   - refusal_dissolved: the question is shown to dissolve rather than resolve, and the
     ending states plainly what the dissolution costs
4. **Final sentence register** — default: the last sentence must NOT be a detachable
   aphorism or quotable epigram; it stays syntactically tied to the paragraph's ongoing
   argument, or lands on a concrete particular, or ends on a quietly qualified clause.
   At most 1 set in 8 may end aphoristically.
5. **Persona** — a distinct authorial voice (register, sentence rhythm, hedging style,
   metaphor domains). Vary it across the session. Also commit one small *texture tell*
   for this set only (e.g., slightly dry understatement; one concrete field detail
   carried across paragraphs; a self-interruption habit) so the prose is not the same
   polished house voice every time.
6. **Thesis revelation** — decide the paragraph where the author's final position first
   becomes visible. Before that point a careful reader must NOT be able to state it.
   Medium: visible by paragraph 2. Hard: paragraph 3 or later. Elite: penultimate
   paragraph, distributed across restatements, or never stated outright.
7. **Trap plan** — pick 2 trap mechanisms (see Stage 3 list) and plant one paragraph each
   that genuinely INVITES that misreading from a fast reader while a careful reader can see
   past it. Never state the misreading; make it the path of least resistance.

## STAGE 2 — Passage

LENGTH (all tiers): **500-550 words**. Outside that range the set is rejected.
Count before you output. Length does not vary by tier — only difficulty does.

Tier parameters:
| Tier | Words | Paragraphs | Difficulty character |
|---|---|---|---|
| medium | 500-550 | 4-5 | one clean structural turn; readable throughout |
| hard | 500-550 | 4-5 | genuine interpretive work; author's stance requires tracking |
| elite | 500-550 | 4-5 | architectural difficulty: late thesis, layered tensions, traps |

On a MEDIUM set the questions carry the tier too, not just the passage: a careful reader
should reach every answer in one pass, at most one question may require synthesis across
paragraphs, and the answers live in the passage rather than behind it. No what-if-deleted
and no decoy questions at medium.

Hard rules:
- Reads as a naturally occurring essay (Aeon / LRB / Boston Review register), not prose
  engineered to sound difficult. Sentence-by-sentence it stays readable; the difficulty is
  architectural.
- Vary paragraph lengths deliberately (e.g., one long dense paragraph, one short strike).
- No moralizing, no policy prescriptions, no direct address to the reader.
- FORBIDDEN words/phrases: furthermore, moreover, in conclusion, it is a testament,
  tapestry, delve, paradigm shift, navigate the complexities, underscores, multifaceted.
- Honor the closing posture and final-sentence register EXACTLY as committed in Stage 1.
- HUMAN TEXTURE (a touch only — keep the intellect; break the factory polish):
  - Plant one concrete, slightly stubborn particular that is not immediately cashed out as
    a system-metaphor: a room, a job title, a tool, a dated practice, a named place, a
    small physical action. It must earn its place in the argument, not decorate it.
  - Allow one sentence per passage that is plainer or more workmanlike than its neighbors —
    a sentence a tired essayist would leave, not a display sentence.
  - Uneven polish is good: not every sentence equally epigrammatic. Let one clause trail,
    re-steer midstream ("— no: more precisely,"), or land on an ordinary word.
  - Mix sentence subjects. Avoid a run of abstract openers ("The doctrine… The residue…
    The mechanism… The ledger…"). Prefer some human agents, some concrete nouns, some
    "I / we / they" when the persona allows.
  - Do NOT default to the invisible house cadence "I grant X. The trouble is Y. What
    remains is Z." unless Stage 1's structure genuinely requires that shape; if you hear
    yourself writing it, rebuild the paragraph.
  - Soft-ban overused house metaphors unless the topic forces them: ledger/residue/
    aperture/altitude/settling field as stock furniture. Invent fresher local images.
  - Still forbidden as "humanizing": typos, slang, emojis, throat-clearing, fake childhood
    anecdotes, "as someone who…", direct reader address, moral lectures.

## STAGE 3 — Questions (exactly 8)

**Q1 is ALWAYS the central-thesis / main-idea question.** It opens every set. It must be
answerable only by integrating the whole passage — never by matching one sentence.

Slot the remaining 7 across distinct types — use at least 6 different types per set.
Weight them the way recent CAT papers do (2023-2025 averages, per ~16 RC questions):
inference dominates at ~53%, then purpose/application/weaken/tone ~16%, detail ~14%,
main idea ~7%, vocabulary-in-context ~6%, EXCEPT ~4%. In an 8-question set that works out
to roughly 4 inference-family questions, 1 detail, 1 purpose/function, and 1 rotating
slot (phrase-in-context, or occasionally EXCEPT or tone).
The list below is the CAT repertoire; the example stem after each is the form the real
exam uses, so write stems that look like these rather than inventing house phrasings:

- central thesis — "Which one of the following best captures the central idea of the passage?"
- EXCEPT / NOT — "All of the following are true of X, EXCEPT:" / "Which one of the
  following does NOT represent ...?"
- primary purpose — "Which one of the following best explains the primary purpose of the
  discussion of X?" / "What is the purpose of this example?"
- undermine the central idea — "The central idea of the passage would be undermined if:" /
  "Which one of the following, if true, would best invalidate the main argument?"
- author's stance/posture — "The author's attitude towards X can best be described as:"
- structural function — "What is the structural function of this sentence in the argument?"
- author's view vs. a reported view — "Which view does the author report or steelman
  rather than hold?"
- inference in context — "In context, the claim that '...' most nearly means that:"
- meaning of a phrase in context — "'...' most nearly means:"
- application/extension to a new case
- what-if-deleted (how the argument changes without paragraph X)
- strengthen/weaken a specified claim
- detail check — "According to the passage, why does X happen?"

DO NOT write assumption questions. Anything of the form "which unstated premise must
hold", "the argument depends on which assumption", or "the move from X to Y assumes" is
out — that is a GMAT/LSAT critical-reasoning form, not a CAT RC form, and it does not
appear in recent papers. If the passage turns on an enabling condition, ask about it as
an inference or a structural-function question instead.

INCLUDE AT LEAST ONE EXCEPT/NOT QUESTION per set. Its option contract is inverted: the
three WRONG options are each statements the passage directly supports, and the CORRECT
option is the one it does not. Mark the three wrong options with the mechanism
`passage_supported` and cite the supporting sentence in each explanation. The correct
option must fail for a nameable reason (scope, stance, causality, level) — never because
it is merely unmentioned, and never because it is lexically extreme.

VARY THE ORDER. Do not open with the thesis question and close with the stance question;
that pairing is what made earlier sets read as the same six questions every time. Put the
whole-passage question (thesis, primary purpose or undermine) wherever the passage's
architecture makes it land hardest — every set needs exactly one, not necessarily first.

Each question: 4 options (A-D), exactly one correct.

Wrong options must each implement a NAMED trap mechanism from this taxonomy:
premature_closure, scope_inflation, stage_misattribution, framework_import, half_truth,
causal_inversion, stance_misread, phrase_misuse, terminological_twin, straw_version,
false_symmetry, level_confusion, nec_suff_swap, example_promotion, adjacent_answer.

Distractor quality bar: every question must have at least one trap a STRONG reader could
genuinely choose. Lexical extremity ("always", "never") is a wasted distractor — build
traps from the passage's own logic, especially the two misreadings planted in Stage 1.

Do not let the correct option be systematically the most hedged or most qualified: in at
least 2 of the 8 questions, phrase the correct option more flatly than its strongest
distractor, so "most cautious = right" never becomes a tell.

## STAGE 4 — Self-audit (fix violations before output; do not mention the audit)

1. Paragraph count matches the tier and the passage is 500-550 words (count it —
   this is a hard gate, not a guideline); thesis first visible where planned.
2. Closing posture realized as committed; final sentence obeys its register.
3. The correct option is the strictly LONGEST option in at most 2 of 8 questions —
   rewrite option lengths until this holds.
3b. Within each question, all four options must be within **3 words of each other**
   (longest minus shortest ≤ 3). You choose how long the options are for a given
   question — they simply have to match each other. Count the words; don't eyeball it.
   If one option needs a qualifier the others don't, give the others their own
   substance rather than letting that one run longer. (The vet gate is looser — it
   warns, and blocks ingestion without --force, once spread exceeds 8 or the
   longest/shortest ratio exceeds 1.35 — so aiming at 3 leaves real buffer.)
   Rewrite option lengths until every question is inside the band.
3c. The THESIS/main-idea question's correct option must NOT be the strictly
   longest of its four options (this tell is also budgeted corpus-wide at 1-in-3).
3d. COMPREHENSIBILITY LOCK when balancing option lengths: never trim an option into a
   fragment or telegraphic stub. After any cut each option must still be a full
   grammatical proposition a test-taker can parse in one read — subject, predicate, and
   the content that makes it right or wrong stay explicit. Do not delete qualifiers that
   carry scope, stance, or causality. Prefer padding a wrong option with one precise
   clause over gutting the correct answer.
4. Answer letters roughly balanced (no letter more than 3 times; not the same letter on
   consecutive questions more than once).
5. No forbidden phrases; no option refutable by "not mentioned" or "too extreme" alone.
6. Every wrong-option explanation names its mechanism and ties it to a specific passage
   location.
7. Human texture present: at least one stubborn concrete particular, at least one plainer
   sentence, and no unbroken abstract-noun parade or stock "grant / trouble / remains"
   cadence unless the blueprint required it.
8. No assumption question anywhere in the set (see Stage 3) — re-read all eight stems and
   confirm none asks for an unstated premise.
8b. Q1 is the central-thesis / main-idea question, and its correct option is not the
   longest of its four (see 3c).
9. EXCEPT/NOT is OPTIONAL and should be rare — it appeared in CAT 2021 and 2023 but not
   in 2024 or 2025, roughly 4% of RC questions. Include one in about one set in four,
   not in every set. Where one IS included, each of its three wrong options must be
   traceable to a specific sentence of the passage. If you cannot point at the sentence,
   the option is not passage-supported and the question is broken.
10. The set does not open on the thesis question AND close on the stance question.

## OUTPUT FORMAT (produce exactly this, nothing else)

[PASSAGE]

<the passage, paragraphs separated by blank lines>

[QUESTIONS]

Q1. <question>
(A) ...
(B) ...
(C) ...
(D) ...

<Q2-Q8 in the same shape>

[ANSWER KEY & ELIMINATION LOGIC]

Q1 — Correct answer: (X)
  (X) CORRECT — <why, tied to passage location>
  (Y) <mechanism> — <why a strong reader might pick it and why it fails>
  <all four options covered>

<Q2-Q8 in the same shape>

[BLUEPRINT NOTE]
Structure: <one line> | Posture: <value> | Thesis visible: para <n> | Traps: <mechanisms>

=== PROMPT END ===
