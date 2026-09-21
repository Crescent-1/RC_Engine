# CAT RC PYQs 2017–2024 vs the RC engine

> **Correction, later on 2026-09-13.** Several numbers in this report are
> superseded by `2026-09-13-cat-pyq-baseline.md`, which re-measured them with
> page-aware parsing, independent task and polarity labels, and a per-tier,
> read-only engine baseline. The text below is kept unchanged as history.
>
> - **Questions per passage.** The 2017–21 values were inflated. The total is
>   390 questions.
> - **Negation.** The corrected shares are 35.6% any negation and 4.1% multiple
>   negation; for 2020–24, 41.5% any negation.
> - **Early thesis.** "About 10% of plans are early-thesis" was a label artefact:
>   medium and hard plan the thesis by paragraph 2 in 45–53% of sets, against
>   74% of thesis-bearing PYQs. A blind 12-set sample found realised prose as
>   early as CAT.
> - **Refusal.** "Refusal 28%" came from a mixed-tier window. Planned refusal is
>   medium 16.7%, hard 30.6%, elite 36.6%, and the realised share is uncertain.
> - **What still holds.** The negation gap holds on shipped engine stems (~7%).

2026-09-13. Source: `CAT RC PYQ 2017-2024.pdf` (2IIM compilation, 90 passages,
515 pages). Every passage and every question was read in full. Per-passage labels
(no passage text) are in `2026-09-13-cat-pyq-labels.json`, so every share below
can be recomputed.

**Scope of this document.** It proposes changes; it changes nothing. No
component library, config lever or prompt has been edited. Section 8 lists the
decisions that need you, because several findings cut against choices made on
purpose (e.g. "this engine deliberately sets above exam level").

**How much to trust each number.**

| Kind of number | Instrument | Trust |
|---|---|---|
| Words, paragraph counts, paragraph lengths | script over extracted text | high |
| Question-type shares (n = 389 stems) | regex classifier, hand-checked | ±3 pp |
| Opening/closing/family/thesis-timing labels | one reader, hand labels | directional; not like-for-like with the blind LLM extractor behind `EXAM_MOVE_SHARES` |
| Engine side | `health` on client AA's trailing 100, plus library composition | high |

---

## 1. Headline findings

1. **CAT passages almost never end unresolved. The engine ends that way 28% of the time.**
   71 of 90 PYQ passages close committed, 17 close as neutral exposition, and
   2 close genuinely open (2%). Engine, last 100 shipped: `refusal_suspended` 19
   plus `refusal_dissolved` 9, so 28%. The library encodes that: 16 of 58
   families carry a refusal posture, and posture decay presses toward balance
   across the fine postures rather than toward the exam's mix.
2. **CAT states its thesis early. The engine's revelation library almost never does.**
   Thesis visible in paragraph 1–2 in 60/90 (67%), mid-passage 21%, late 12%.
   Only 2 of the 20 revelations are early-timed (R01, R11). Revelations are drawn
   with recency decay only, so early plans run near 10%. On top of that, R01 is
   incompatible with 16 families.
3. **NOT/EXCEPT is the modal CAT stem form, and the engine barely asks it.**
   27% of PYQ stems are EXCEPT/NOT scans, and 37% carry some negation
   (EXCEPT, NOT, least likely, if false, none of the following). 6% are double or
   triple negations. Engine: `except_scan` is 7 of 192 topology slots (3.6%),
   so about 0.3 per 8-question set.
4. **About half of CAT passage shapes are already in the library, and those sit mostly in the exam-derived families.**
   49/90 map onto an existing family: 26 onto F47–F56, 8 onto F33–F46, and 15
   onto the 32 legacy staged-turn families. The other 41 need something new, and
   three new shapes recur 7 times each: the **backfiring remedy**, the
   **typology**, and the **scholarly introduction**. Book reviews are 10% of CAT
   (9/90) against 3% of shipped sets (F53 + F24).
5. **The render contract bans or cannot supply four textures CAT uses routinely.**
   Each figure below is a share of the 90 passages.

   | Texture | Share of CAT | Engine status |
   |---|---|---|
   | Policy prescription or endorsed remedy at the close | 13% | rule 7 bans it |
   | Reader address / explicit hypothetical ("imagine…", "consider…") | 13% | rule 7 bans it |
   | Explicit enumeration ("three reasons… First… Second…") | 16% | rule 8 treats it as signposting |
   | Real studies, figures and quoted researchers as the spine | ~30% | rule 9 forbids inventing them, and refine never passes the seed's real facts through |

Things that already fit, so no change is needed:
- Passage length. PYQ median is 503 words against the engine's 500–550 band.
- Paragraph-length mix (S/M/L/XL) is close to the rhythm library's.
- The first-person cap of 20% sits right on CAT, although the config comment's
  6% figure is wrong for CAT (§3.6).
- The move bans on EASY_READING_DEMOLISHED and CONCESSION_GRANTED are
  well-founded. In CAT each shows up in about 17–18% of passages; the engine
  realises them at 74% and 65%.

---

## 2. The corpus

| Year | Passages | Median words | Median paragraphs | Questions / passage |
|---|---|---|---|---|
| 2017 | 10 | 511 | 5 | 6.3 (two short 3-Q passages per slot) |
| 2018 | 10 | 508 | 5.5 | 5.8 |
| 2019 | 10 | 499 | 3 | 5.5 (Slot 1: all five passages are 3 long paragraphs) |
| 2020 | 12 | 502 | 5 | 5.8 |
| 2021 | 12 | 506 | 4 | 4.3 |
| 2022–24 | 36 | 501–503 | 5–6 | 4 |

Source registers (hand label):

| Register | Passages | Share |
|---|---|---|
| Op-ed / opinion / polemic / editorial | 17 | 19% |
| Academic prose (incl. book introductions and textbooks) | 18 | 20% |
| Science news / journalism / explainers | 13 | 14% |
| Book reviews and retrospectives | 9 | 10% |
| Essays (Aeon-type, pop-intellectual) | 12 | 13% |
| Magazine explainer (Economist-type) | 5 | 6% |
| History, features, memoir, columns, other | 16 | 18% |

---

## 3. Passage-level fit

### 3.1 Shape

- **Paragraph count** (n = 86 full-length passages):

  | Paragraphs | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
  |---|---|---|---|---|---|---|---|
  | Passages | 3 | 12 | 14 | 25 | 24 | 5 | 3 |

  37% have 6–8 paragraphs. The engine sets paragraph count to
  `max(len(family movement), len(rhythm shape))`: rhythms are 3–5 slots, 43 of
  58 families are 4 functions, and only F42 has 6. So 6+ paragraph passages are
  effectively elite-only (F42). The CAT 6–8 paragraph passages are mostly
  magazine and news registers: short working paragraphs, including one-sentence
  quote or figure paragraphs.
- **Paragraph length**: median 91 words.

  | Class | S (<60) | M (60–109) | L (110–159) | XL (160–209) | ≥210 |
  |---|---|---|---|---|---|
  | CAT | 18% | 50% | 20% | 9% | 3% |
  | Rhythm library | 22% | 47% | 25% | 6% | — |

  Close enough; no change.

### 3.2 Family fit (flows)

| Where PYQ passages land | n | Families hit |
|---|---|---|
| Exam-derived (F47–F56) | 26 (29%) | F54 ×6, F53 ×5, F47 ×3, F50 ×3, F55 ×3, F48 ×2, F56 ×2, F49, F51 |
| Arc-shape families (F33–F46) | 8 (9%) | F35 ×5, F36 ×2, F43 |
| Legacy staged-turn (F01–F32) | 15 (17%) | F15 ×4, F17 ×4, F24 ×3, F02, F08, F26, F31 |
| No adequate fit | 41 (46%) | see below |

No PYQ passage matched F01, F03–F07, F09–F14, F16, F18–F23, F25, F27–F30 or
F32. Those are the most elaborate designed arcs. They are legitimate
above-exam material for elite, but the legacy arc is 42% of shipped sets against
about 17% of CAT.

Under-drawn exam families, CAT vs last 100 shipped:

| Family | CAT | Shipped |
|---|---|---|
| F54 superseded explanation | 7% | 1% |
| F53 + F24 reviews | 9% | 3% |
| F35 front-loaded thesis | 6% | 2% |

F53–F58 are recent, so recency may explain part of this; re-check after 30 sets.

Recurring shapes with no family (≥7 instances each):

| Proposed family | PYQ instances |
|---|---|
| **The Backfiring Remedy** | electric cars (2017 S2), e-governance (2018 S2), choice-fatigue start-ups (2019 S1), renewables (2020 S2), second-hand fashion (2023 S2), cultural property laws (2023 S3), streaming vs physical media (2024 S1) |
| **The Typology** | metric fixation (2018 S2), topophilia (2019 S1), anarchism (2020 S1), aggression (2020 S2), cephalopod camouflage (2022 S2), unintended consequences (2024 S2), carnivore attacks (2024 S2) |
| **The Framed Inquiry** (scholarly introduction) | visual culture (2020 S2), financial-crisis preface (2020 S3), nationalist dichotomies (2021 S2), institutions (2022 S2), musicking (2022 S2), Indian Ocean novels (2023 S1), romantic aesthetics (2023 S3) |
| **The Split Verdict** (review) | human nature (2020 S3), liberalism (2023 S2), rationality (2023 S3), economists at borders (2024 S1), plus Sahlins retrospective (2023 S1) |

F15 and F58 are the nearest existing families to the backfiring remedy, but
neither fits. F15 re-reads a cure as the disease without a mechanism. F58 weighs
several remedies and endorses one. The CAT pattern follows one prescribed fix
into practice until its own mechanism reproduces the harm.

One-off shapes, recorded in the labels file but not proposed: benchmark
comparison, elegy for a lost function, omission corrected, misdirection exposed,
stated aims audited, reply to critics, comparative ledger, alien category scheme,
bounded hypothesis, success against the rules, and others.

### 3.3 Openings and closings

These are hand labels with strict categories. They are **not** like-for-like with
the 77% / 81% figures in `similarity_screen.py`, which came from the blind
extractor over RC125. Read broadly, my data gives 61% abstract-type openings
(any general proposition, definition, history, received view, metatext) and
68% bound-type closings.

| Opening | CAT share | In `MOVE_GROUPS["opening"]`? |
|---|---|---|
| Abstract claim | 19% | yes |
| News / data hook (event, figure, announcement, trend) | 10% | **no** (needs real facts, §3.7) |
| Historical / then-vs-now / etymology | 9% | yes (HISTORICAL_ORIGIN) |
| Scene / anecdote | 8% | yes |
| Thesis-first, blunt or paradoxical | 7% | partly (ABSTRACT_CLAIM_OPEN does not say *the thesis*) |
| Definition / foreign-term pair | 7% | yes |
| Misconception framed ("despite its reputation", "few realise") | 6% | no (EASY_READING_DEMOLISHED is middle-only) |
| Reported position (a book's, school's or doctrine's claim) | 6% | **no** |
| Quote / phrase dissected | 4% | no (AUTHORITY_QUOTED is middle-only) |
| Metatext ("the claims advanced here…", "we begin with…") | 4% | no |
| Aphorism | 4% | no |
| Question | 3% | yes |
| Finding ("scientists recently discovered…") | 2% | no |
| Other (cold open mid-list, opponent caricature, immersive rules, author backstory…) | 11% | — |

| Closing | CAT share | In `MOVE_GROUPS["closing"]`? |
|---|---|---|
| Bound continuation / truncated mid-argument | 29% | yes |
| Aphoristic, wry, pun or callback | 17% | yes (HEDGED_APHORISM; engine realises 23%) |
| Qualified verdict (split, concession, disclaim-restate, synthesis) | 13% | partly (CONCESSION_COSTED) |
| Concrete particular / evidence / callback | 11% | yes |
| Quoted voice | 9% | no (needs real quotes) |
| Prescription (what should change) | 9% | **no, banned by rule 7** |
| Forecast | 6% | **no** |
| Affirmation of a remedy or work | 4% | posture only (affirmation_endorsed) |
| Question left open | 2% | yes (QUESTION_LEFT_OPEN) |

### 3.4 Thesis timing

| Timing | CAT | Engine revelation library |
|---|---|---|
| Early (paragraphs 1–2) | 67% | 2 of 20 (R01, R11) |
| Mid | 21% | 4 (R02, R06, R10, R12) |
| Late / penultimate / retrospective | 12% | 7 |
| Never stated | 2% (the two open passages) | 3 (R03, R07, R15) |

CAT's difficulty does not come from withholding the thesis. It comes from dense
content, fine-grained options and negated stems. A withheld thesis is a
legitimate above-exam lever, but at ~10% early against 67% it is currently the
*default* rather than a lever.

### 3.5 Stance at the close

| | CAT | Engine realised (last 100) |
|---|---|---|
| Committed (resolution / affirmation / reframe) | 79% | 72% |
| Of which affirmation or prescription | 13% | 4% |
| Neutral exposition, no evaluative close | 19% | ~0 by construction; every family carries a posture |
| Open / refusal | 2% | 28% |

### 3.6 Voice and register

- **First person.** 15/90 have a structural "I" or "we" narrator (17%); 8 more
  use it incidentally (26% any). `FIRST_PERSON_MAX_SHARE = 0.20` is right for
  CAT. The comment's 6% came from RC125, which includes GMAT passages that are
  never first-person. Fix the comment so nobody lowers the cap later on its
  strength.
- **Personas.** All 20 are essayist voices. Three frequent CAT registers have no
  persona:
  - the magazine explainer: compact and wry, quick verdicts, figures (Economist,
    about 6–10% of CAT);
  - the reviewer, whose voice stays audibly separate from the reviewed author's
    (10%);
  - the advocate op-ed writer: committed, credentialed once, states what should
    change (about 15%).

### 3.7 Rule 9 against CAT texture

About 30% of CAT passages lean on material the engine cannot legitimately invent:

| Texture | Share |
|---|---|
| A named researcher quoted as the spine | 11% |
| A study walked through: design → result → caveat | 10% |
| A news or data hook | 10% |
| A close on a quoted voice | 9% |
| A review of a real, named book | 10% |

Rule 9 is correct. The gap is upstream: `_refine_user_prompt` passes the seed as
an "INSPIRATION ESSAY EXCERPT… do NOT copy its argument", and the refine system
prompt says "invent CONTENT". So the verified facts sitting in every seed
(names, dates, figures, direct quotes) never reach the renderer as usable
material. Question types that need real numbers can't be built either: data
falsification, protocol scenarios, quantitative application (about 4% of CAT
stems).

---

## 4. New beats (rhetorical moves)

Frequencies are hand-detected across the 90 passages. Only fabrication-safe,
recurring moves that are distinct from the existing 27 are proposed.

| Move | Group | CAT share | Gloss (proposed `RHETORICAL_MOVES` text) | Conflicts to resolve |
|---|---|---|---|---|
| `TERM_COINED` | middle | 22% | introduces a short plain label for the thing under discussion and makes later sentences depend on it; the label names content, never the passage's own argumentative steps | house-metaphor soft ban (rule 11) must still apply to the label |
| `ENUMERATED_SET` | middle | 16% | announces a fixed number of reasons, factors, kinds or channels and works through them in order; the count is content, not a narration of the argument's own moves | rule 8 and `_SIGNPOST_PATTERNS`; needs an explicit exception when this beat is planned |
| `IRONY_NOTED` | middle | 12% | points to one specific fact in which an action, institution or product produces the opposite of what it was for, stated once without commentary on the irony | none |
| `HYPOTHETICAL_CASE` | middle | 12% | sets up an explicitly hypothetical case ("suppose", "imagine", "consider a…") detailed enough to test the claim on, and uses it; never presented as a real event | rule 7 (reader address) |
| `OBJECTION_FORESTALLED` | middle | 9% | names a specific misreading or attack the claim invites from an identified audience and answers it before moving on; distinct from DISCLAIM_RESTATE, which corrects the passage's own wording | none |
| `THEN_NOW_CONTRAST` | middle | 9% | sets how the matter stood at a placed earlier time against how it stands now, and makes the difference carry the argument | overlaps GENEALOGY_TRACED at the edges |
| `REPORTED_POSITION` | opening | 6% (+ reviews) | opens by stating another writer's, book's or school's position in its own terms, before the passage's own view appears | a real work needs §7 P2a, or a described-but-unnamed one |
| `PRESCRIPTION_STATED` | closing | 9% | closes on what should be done or which norm should change, stated plainly and bounded by what the passage has shown; no exhortation or moral lecture | rule 7 (policy prescriptions) |
| `FORECAST` | closing | 6% | closes by projecting one specific consequence the argument implies for the near future, hedged no more than the evidence requires | none |
| `SPLIT_VERDICT` | closing | 7% | closes by saying in one movement where a reported or reviewed position is right and where it goes wrong | none |

**Not proposed until P2a (seed facts) exists:** `STUDY_WALKTHROUGH`,
`EXPERT_AS_SPINE`, `NEWS_DATA_HOOK`, `QUOTE_CLOSE`. Each needs real, checkable
material.

**Rollout risk.** The move sampler weights a move by `(1 - trailing_share)`, so
a new move starts at weight 1.0 and will be over-drawn for about 20 sets. The
config already warns about this transient under `MOVE_PLAN_RARITY_POWER`, and
`tests/test_move_signature.py` requires every move to sit in a planner group. So
there is no "recognise but don't prescribe yet" state. Options:
- ship all ten and accept the transient; or
- ship the three closings plus `ENUMERATED_SET` / `HYPOTHETICAL_CASE` first,
  since they fill the biggest measured gaps.

---

## 5. Question flows

### 5.1 Shares

| Question kind | CAT 2017–24 (n = 389) | CAT 2020–24 only | Engine topology slots (n = 192) |
|---|---|---|---|
| EXCEPT / NOT scan (any underlying type) | **27%** | **30%** | except_scan **3.6%** |
| Any negated stem (EXCEPT, NOT, least likely, if false, none of) | 37% | — | ~4% |
| Double / triple negation ("if false… EXCEPT", "unlikely to disagree… EXCEPT") | 6% | — | 0 |
| Purpose of an example, word, reference or device | 10.5% | 6% | evidence + structural + primary_purpose 12.6% |
| Detail | 8% | 7% | 12.5% |
| Main idea / gist | 7% | 7% | 12.5% (Q1 in every topology) |
| Inference | 7% | 7% | contextual_inference 6.8% |
| Weaken / undermine / invalidate | 7% | 7% | 13.0% |
| **Author would support / advise / approve** (normative) | **6.4%** | 7% | **none** (application is mechanism-to-scenario) |
| Application scenario (near-identical options, two constraints combined) | 5.7% | 7% | application 6.8% |
| Meaning / paraphrase of a dense sentence | 4.6% | 4% | phrase + contextual 13% |
| **Keyword set / flow sequence / odd pair** | **2.8%** | 4% | **none** |
| Reported party vs author, similarity/difference of two parties | 2.6% | 3% | author_vs_reported 6.8% |
| Strengthen | 2.3% | 3% | 6.2% |
| Tone / stance of a sentence | 2.3% | 3% | stance 2.6% |
| Closure reading / counterfactual / decoy escape | ~0 | ~0 | 10.4% |

Caveats:
- CAT sets are 4 questions and ours are 8. More higher-order types per set are
  legitimate, so this does not argue for copying CAT's shares.
- The gaps it *does* argue for are **negation** (a stem form, independent of set
  size) and the **two missing types**.
- Closure reading stays: the client asked for the continuation stem on
  2026-09-12.

### 5.2 Proposed

1. **Negation as a slot flag, not a slot type.**
   - Add `"negated": true` to topology slots of type `detail_check`,
     `contextual_inference`, `author_vs_reported`, `application`, `weaken` and
     `strengthen`.
   - The option contract flips exactly as `except_scan` already does:
     `TRAPLESS_SLOT` / `EXCEPT_MECHANISM` in `question_engine.py`.
   - Target 2 negated slots per 8. At most 1 double negation per set, hard and
     elite only.
   - This is a code change (validator, solver comparability, trap histogram),
     not just JSON.
2. **New slot type `author_would_endorse`.**
   - Definition: which practice, policy, programme or view the author would most
     (or least) likely support. The key follows from commitments stated in the
     passage, not from what sounds reasonable in general.
   - Stem forms (≥3 required by `MIN_STEM_FORMS`):
     - "Based on the passage, the author would be most supportive of which one of the following practices?"
     - "Which one of the following interventions would the author most strongly support?"
     - "The author is least likely to agree with which one of the following views about {X}?"
3. **New slot type `keyword_set`.**
   - Definition: which set of four or five keywords, or which ordered sequence of
     phrases, best maps the passage's argument. Wrong sets use vivid but
     peripheral terms, or the right terms in the wrong order.
   - Stem forms:
     - "Which one of the following sets of keywords best captures the arguments of the passage?"
     - "Which one of the following sequences of words and phrases best captures the flow of the passage?"
     - "Which one of the following sets of terms is closest to mapping the main concerns of the passage?"
   - Cheap to generate. The solver can verify it deterministically against the
     passage.
4. **Stem forms added to existing types**, with no new types:
   - `structural_function`: "Why does the author use the word '{X}' in {the specified paragraph}?"
   - `stance`: "In the sentence '{quoted sentence}', the author's tone is best described as:"
   - `author_vs_reported`: "On which one of the following points would {the reported writer} and the author most likely disagree?"
   - `author_vs_reported`: "Which one of the following best expresses both the similarity and the difference between {X} and {Y}?"
   - `contextual_inference`: "Which one of the following best captures the sense of '{quoted sentence}'?"
5. **Application option design note** for the question prompt. CAT's hardest
   application items give four near-identical scenarios that differ in one
   attribute: copies of a painting, product plans by count × price, experiment
   protocols by symbol × food. The key needs two passage constraints combined.
   Worth stating explicitly in the application slot guidance.
6. **Topologies** (after 1–3 exist), for medium/hard:
   - **QT25** thesis · detail_check(negated) · evidence_function · author_would_endorse · contextual_inference · application(negated) · weaken · keyword_set — flat_mid
   - **QT26** thesis · except_scan · author_vs_reported(negated) · phrase_in_context · strengthen(negated) · structural_function · application · detail_check — rising

   Leave the elite topologies as they are.

---

## 6. Ready-to-apply component specs

These are drafts. None is applied. Field sets match `registry.REQUIRED_FIELDS`.

### 6.1 Families (`families.json`)

```json
{
 "id": "F59", "name": "The Backfiring Remedy", "tier_floor": "medium", "tier_max": "hard",
 "arc_shape": "backfiring_remedy", "closing_posture": "resolution_costed", "withholds_thesis": false,
 "core": "A real problem and the fix now widely prescribed for it are set out; the fix is followed into practice until its own mechanism reproduces, relocates or deepens the harm; the close says what a working fix would have to do differently.",
 "difficulty_source": "the passage endorses the goal while faulting the fix, so options rejecting the goal and options endorsing the fix are both wrong; the backfire mechanism is stated once, mid-passage, and the closing condition is easy to overstate as a flat recommendation",
 "movement": ["PROBLEM_STATED", "PRESCRIBED_FIX", "FIX_IN_PRACTICE", "BACKFIRE_MECHANISM", "CONDITION_FOR_A_WORKING_FIX"],
 "movement_variants": [["PRESCRIBED_FIX", "PROBLEM_STATED", "FIX_IN_PRACTICE", "BACKFIRE_MECHANISM", "CONDITION_FOR_A_WORKING_FIX"]],
 "question_affinities": ["undermine_thesis", "application", "structural_function"],
 "incompatible_endings": [], "incompatible_revelations": [],
 "source_note": "CAT 2017-24, 7 of 90: electric cars (2017 S2), e-governance (2018 S2), choice-fatigue start-ups (2019 S1), renewables (2020 S2), second-hand fashion (2023 S2), cultural property laws (2023 S3), streaming vs physical media (2024 S1)."
},
{
 "id": "F60", "name": "The Typology", "tier_floor": "medium", "tier_max": "hard",
 "arc_shape": "typology_enumerated", "closing_posture": "resolution_qualified", "withholds_thesis": false,
 "core": "A concept or phenomenon is fixed in a sentence, divided into a stated number of kinds, and each kind is given its own case; a last case sits across two kinds and qualifies the division without dissolving it.",
 "difficulty_source": "the kinds look parallel but are defined by different features, so EXCEPT and detail questions turn on which feature belongs to which kind, and the crossing case is easy to misread as a further kind or as a refutation",
 "movement": ["CONCEPT_FIXED", "KINDS_ANNOUNCED", "KIND_WITH_CASE", "KIND_WITH_CASE", "CROSSING_CASE_QUALIFIES"],
 "question_affinities": ["except_scan", "detail_check", "phrase_in_context"],
 "incompatible_endings": [], "incompatible_revelations": [],
 "source_note": "CAT 2017-24, 7 of 90: metric fixation (2018 S2), topophilia (2019 S1), anarchism (2020 S1), aggression (2020 S2), cephalopod camouflage (2022 S2), unintended consequences (2024 S2), carnivore attacks (2024 S2)."
},
{
 "id": "F61", "name": "The Framed Inquiry", "tier_floor": "hard", "tier_max": "hard",
 "arc_shape": "scholarly_introduction", "closing_posture": "resolution_qualified", "withholds_thesis": false,
 "core": "The way a field usually frames a subject is set out, the difficulty that framing cannot absorb is named, the writer's own approach is stated and defended against the misreading it most invites, and the close fixes what the inquiry will cover and why.",
 "difficulty_source": "the register is abstract and nominal, so questions turn on paraphrasing dense sentences; the forestalled misreading is stated in full and is the most attractive wrong option",
 "movement": ["PREVAILING_FRAME", "FRAME_DIFFICULTY", "APPROACH_STATED", "MISREADING_FORESTALLED", "SCOPE_FIXED"],
 "movement_variants": [["APPROACH_STATED", "PREVAILING_FRAME", "FRAME_DIFFICULTY", "MISREADING_FORESTALLED", "SCOPE_FIXED"]],
 "question_affinities": ["contextual_inference", "author_vs_reported", "primary_purpose"],
 "incompatible_endings": [], "incompatible_revelations": [],
 "source_note": "CAT 2017-24, 7 of 90: visual culture (2020 S2), financial-crisis preface (2020 S3), nationalist dichotomies (2021 S2), institutions (2022 S2), musicking (2022 S2), Indian Ocean novels (2023 S1), romantic aesthetics (2023 S3)."
},
{
 "id": "F62", "name": "The Split Verdict", "tier_floor": "medium", "tier_max": "hard",
 "arc_shape": "split_verdict_review", "closing_posture": "resolution_qualified", "withholds_thesis": false,
 "core": "A work's central claim is stated in its own terms and its case summarised fairly; two objections follow, the second pressed with a counter-case; the close says where the work is right and where it goes wrong.",
 "difficulty_source": "the reviewed author's claims and the reviewer's run in the same prose for half the passage, and the verdict is split, so options that report the work's view as the reviewer's and options that make the reviewer wholly hostile are both wrong",
 "movement": ["WORK_CLAIM_IN_ITS_TERMS", "CASE_SUMMARISED", "FIRST_OBJECTION", "COUNTER_CASE_PRESSED", "SPLIT_VERDICT"],
 "movement_variants": [["WORK_CLAIM_IN_ITS_TERMS", "FIRST_OBJECTION", "CASE_SUMMARISED", "COUNTER_CASE_PRESSED", "SPLIT_VERDICT"]],
 "question_affinities": ["author_vs_reported", "stance", "evidence_function"],
 "incompatible_endings": [], "incompatible_revelations": [],
 "source_note": "CAT 2017-24: 9 of 90 are reviews or retrospectives; split close in human nature (2020 S3), liberalism (2023 S2), rationality (2023 S3), economists at borders (2024 S1)."
}
```

Notes that must ship with the families:

- **Share cap.** Add all four arc shapes to `EXAM_DERIVED_SHAPES`. Their
  zero-usage transient then falls under `EXAM_FORM_MAX_SHARE` (medium 50%,
  hard 35%, elite 0). The existing six shapes share that cap, so their draw
  share falls a little.
- **F60 and F61 need rule 8 exceptions.** Enumeration (F60) and scope metatext
  (F61) currently read as signposting under render rule 8 and
  `_SIGNPOST_PATTERNS`. Without an exception tied to these families, compliance
  will fight the plan.
- **F62 reviews a work.** Until P2a exists it must use a described-but-unnamed
  work, or a seed that is itself a review (NYRB, The Millions and Paris Review
  are already feeds).

### 6.2 Revelations (`revelations.json`)

```json
{"id": "R21", "name": "Stated, Then Tested", "timing": "early",
 "mechanism": "the central claim is stated flatly in the first two sentences; each later paragraph tests it against a case, and the close says how much of it survived"},
{"id": "R22", "name": "Paradox Up Front", "timing": "early",
 "mechanism": "the passage opens on a claim that sounds self-contradictory and spends its length showing the claim is literally true"},
{"id": "R23", "name": "Received View Named First", "timing": "early",
 "mechanism": "the first paragraph states what is usually believed and signals doubt; the passage's own position is the correction, visible in outline from paragraph one and in full by the middle"}
```

### 6.3 Rhythms (`rhythms.json`)

```json
{"id": "T21", "name": "Newsroom", "shape": ["M", "S", "M", "M", "S", "M"],
 "cadence_note": "six working paragraphs, two of them a single sentence carrying a figure, a remark or the turn; the short ones carry facts, never flourishes"},
{"id": "T22", "name": "Short Takes", "shape": ["S", "M", "M", "S", "M", "M", "S"],
 "cadence_note": "seven compact paragraphs in an explainer register; each does one job and hands on"}
```

`_build_movement` pads a 4–5 function family up to 6–7 paragraphs with
`generic_fillers`. One of those fillers is `CONCESSION_TRAP`, which feeds the
concede-then-pivot spine the move bans are fighting. Consider excluding it when
padding to these two rhythms.

### 6.4 Personas (`personas.json`), outline only

- **P21 The Magazine Explainer.** Compact, wry, verdict in a clause; one pun at
  most; figures only from verified seed facts; impersonal.
- **P22 The Reviewer.** Reports a work in its own terms, then judges; the two
  voices stay audibly separate; an occasional first person for the verdict.
- **P23 The Advocate.** Committed; states a credential once; argues toward what
  should change; plain first person.

P22 and P23 would draw against `FIRST_PERSON_MAX_SHARE`.

---

## 7. Improvements, ranked

### P1: high impact, low to moderate effort

**a. Weight closing postures to the exam** (medium and hard; elite unchanged).
- *Evidence:* refusal 28% shipped vs 2% CAT; affirmation 4% vs 13%.
- *Change:* an `EXAM_POSTURE_SHARES` table applied on top of the existing
  posture decay, the same pattern as `ARGUMENT_SCHEMAS`. Suggested starting
  point, deliberately still more contested than CAT:

  | Posture | Share |
  |---|---|
  | resolution_qualified | 0.38 |
  | resolution_costed | 0.20 |
  | affirmation_endorsed | 0.14 |
  | reframe_displace | 0.14 |
  | refusal_suspended | 0.10 |
  | refusal_dissolved | 0.04 |

  Refusal at 14% halves today's rate and is still 7× CAT.
- *Files:* `config.py`, `composer.py`; test in `tests/`.
- *Verify:* `health` closing postures after 20–30 sets.

**b. Weight revelation timing to the exam** (medium and hard), and add R21–R23.
- *Evidence:* 67% early in CAT vs about 10% of plans.
- *Change:* timing weights applied on top of the existing recency decay. Suggested:

  | Timing | Weight |
  |---|---|
  | early | 0.40 |
  | early_hidden | 0.05 |
  | mid | 0.25 |
  | split | 0.05 |
  | distributed | 0.05 |
  | late | 0.08 |
  | penultimate | 0.05 |
  | retrospective | 0.04 |
  | never_stated | 0.03 |

  Also audit the 16 R01 incompatibilities, since many exist only because R01 was
  the sole early option.
- *Files:* `config.py`, `composer.py`, `revelations.json`, `constraint_rules.json`.

**c. Negated stems across slot types** (§5.2 item 1).
- *Evidence:* 27–37% of CAT stems vs 3.6%.
- *Why it matters most to the client:* it is the one gap a student sitting a
  real paper would notice immediately.
- *Files:* `question_engine.py` (prompt contract + validator), `topologies.json`
  (flags), solver comparability, trap histogram. Tests for the flipped contract
  on non-except types.

**d. Tie render rule 7 exceptions to planned beats.**
- *Evidence:* prescriptions 13% and reader address 13% of CAT.
- *Change:* allow a bounded closing prescription only when
  `PRESCRIPTION_STATED` is planned or the posture is `affirmation_endorsed`. That
  also removes a live contradiction with F58, whose close endorses a remedy.
  Allow one explicitly hypothetical "imagine / consider" case only when
  `HYPOTHETICAL_CASE` is planned. Keep "no moralizing".
- *Files:* `renderer.py`; compliance audit of the exception.

### P2: high impact, more work

**a. Verified seed facts.** This is the largest structural gap.
- *Evidence:* about 30% of CAT texture depends on real studies, figures, quotes
  and reviews (§3.7).
- *Change:*
  1. Refine returns up to 8 `verified_facts`, each with a `seed_span` that must
     be an exact substring of `seed.text`, checked deterministically so the
     model cannot invent one. Each span is ≤25 words.
  2. The renderer gets them as "checkable facts you may use", and rule 9 stays
     absolute for everything else.
  3. `texture_report` downgrades a figure, quote or study that matches a
     whitelisted span.
- *Unlocks:* `NEWS_DATA_HOOK`, `STUDY_WALKTHROUGH`, `EXPERT_AS_SPINE`,
  `QUOTE_CLOSE`, real-book F62, and numeric question types.
- *Risks:*
  - Passages leaning on one source's facts. Seeds are already globally
    exclusive per client.
  - Copying prose. Spans are facts, not sentences, and are capped.
- *Files:* `composer.py` (refine schema + validation), `renderer.py`,
  `question_engine.py`.

**b. Families F59–F62 and the ten beats** (§4, §6.1), shipped under
`EXAM_DERIVED_SHAPES`. Needs the rule 8 exceptions for F60 and F61. Run
`selftest`, the test suite and a `--dry-run` batch; watch `health` arc-shape and
move saturation for 20 sets.

**c. New slot types `author_would_endorse` and `keyword_set`**, and QT25–QT26
(§5.2).

### P3: worth doing, lower impact

- **Rhythms T21–T22.** 37% of CAT passages have 6–8 paragraphs.
- **Personas P21–P23.**
- **Stem-form additions** (§5.2 item 4) and the application option-design note
  (item 5).
- **Recalibrate the calibration text.** RC125 mixes CAT, XAT and GMAT and
  predates this corpus. Re-run the existing blind move extractor over these 90
  passages (cheap-model cost, paid, so it needs your go-ahead) to get like-for-like
  CAT shares. Then update `EXAM_MOVE_SHARES`, the calibration block in
  `similarity_screen.py` (77% / 81%) and the `FIRST_PERSON_MAX_SHARE` comment.
  My hand counts suggest the existing move bans will only look more justified.
- **Keep PYQ text out of git.** The PDF is marked "personal study use", and the
  repo has a GitHub Actions workflow (`.github/workflows/tests.yml`). Only the derived labels file belongs in the
  repo.

---

## 8. Decisions this needs from you

1. **Exam-realism for medium and hard?** P1a and P1b move those tiers toward
   CAT's committed, early-thesis norm. Elite would keep the literary,
   above-exam design. Yes or no, per tier.
2. **Refusal floor.** 14% (proposed), or closer to CAT's ~2–5%?
3. **Rule 7.** Allow bounded prescriptions and explicit hypotheticals when
   planned?
4. **New beats: all ten at once, or staged?** Rarity weighting means each new
   beat is over-drawn for about 20 sets on live client AA batches.
5. **P2a (verified seed facts).** Worth the build? It is the only route to
   CAT's reportage and science-news texture that doesn't break rule 9.
6. **Blind-extractor run over the 90 PYQs.** A small paid run to replace the
   RC125 baseline with a CAT-only one.
