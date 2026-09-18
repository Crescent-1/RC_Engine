# CAT RC PYQ 2017–2024 → RC engine: findings handoff for review

> **Correction, later on 2026-09-13.** Section 2 of the implementation plan has
> been completed in `2026-09-13-cat-pyq-baseline.md` (data:
> `2026-09-13-cat-pyq-baseline.json`; tools: `tools/cat_pyq/`). The following
> numbers in this handoff are superseded:
>
> - questions per passage, and the Appendix A "question forms", which came from
>   the old first-match classifier;
> - the negation shares, §4.7;
> - the early-thesis comparison, §4.2 and the P1b rationale;
> - the mixed-tier refusal figure.
>
> The scripts in Appendix C are the original scratch pipeline. They are kept
> for history, not for reproduction.

Written 2026-09-13 by a Claude Code session, for a **second agent to critique**.
Everything I found is in this file, including where I think I may be wrong.
Nothing in the engine has been changed.

**Companion files (repo root)**

| File | What it holds |
|---|---|
| `2026-09-13-cat-pyq-engine-analysis.md` | The polished report. §6 has the paste-ready JSON drafts. |
| `2026-09-13-cat-pyq-labels.json` | Derived per-passage labels, measured words and paragraphs, and regex question types. No passage text. |
| `C:\Users\anshu\Downloads\CAT RC PYQ 2017-2024.pdf` | The source. 90 passages, 515 pages (2IIM compilation). Keep its text **out of git**: it is marked "personal study use", and the repo runs GitHub Actions. |

---

## 0. What the reviewer is being asked to do

1. **Check the facts.**
   - §3 claims about the engine: each is cited to file:line, so open the file.
   - A sample of the per-passage labels in Appendix A, against the PDF.
2. **Judge the proposals in §5.** Are they right? Distinct from what already
   exists? Worth the risk? What would you do differently?
3. **Take a position on the open questions in §7.**

House rules from `CLAUDE.md` that bind the reviewer too:
- No `generate` without `--dry-run` unless asked.
- Don't loosen `NOVELTY_CAPS`.
- Don't delete or move files without approval.
- Run `selftest` plus `python -m pytest tests -q` after any config or library
  change.
- Add a test for every behaviour change.
- Dated, reasoned comments are the house style.

---

## 1. Context in one screen

- `rc_engine/` generates CAT-style RC sets for a paying test-prep client:
  one passage of 500–550 words and **8** MCQs (`config.QUESTIONS_PER_SET = 8`).
  There are three tiers: medium, hard and elite.
- A set is composed from component libraries in `rc_engine/components/`:

  | Library | Size | Role |
  |---|---|---|
  | `families.json` | 58 | Argument arcs, i.e. paragraph "flows" |
  | `topologies.json` | 24 | Question flows, 8 typed slots each |
  | `revelations.json` | 20 | Thesis timing |
  | `endings.json` | 20 | Closing gestures |
  | `rhythms.json` | 20 | Paragraph length shapes |
  | `personas.json` | 20 | Authorial voices |
  | `topic_shapes.json` | 14 | What the passage is about |
  | `render_stances.json` | 8 | How the argument is developed |
  | `distractor_profiles.json` | 20 | Wrong-option mechanisms |

  There is also a closed vocabulary of 27 **rhetorical moves ("beats")** in
  `config.RHETORICAL_MOVES`, planned per passage as one opening, 5–6 middles and
  one closing.
- The engine was previously calibrated against **"RC125"**: 124 CAT, XAT and
  GMAT passages, many of them GMAT-era (the source notes cite Glatthaar,
  deep-focus earthquakes, excess inventory). Six exam-derived families
  (F47–F52) and six more (F53–F58), plus `ARGUMENT_SCHEMAS` and
  `EXAM_MOVE_SHARES`, came from it. **This PYQ set is the first CAT-only,
  modern-format corpus to be analysed.**
- The engine deliberately sets **above** exam level, especially elite, which
  stays literary by a 2026-08-26 decision. So a gap against CAT is a calibration
  fact, not automatically a defect.

---

## 2. Method and its weaknesses

**Pipeline** (scripts in Appendix C; scratchpad copies are gone after the session):

1. PyMuPDF line extraction, dropping boilerplate. A paragraph break is inferred
   from a short line or a vertical gap (`extract.py`).
2. Split into reading text (`build_reading.py`):
   - 2017–21: the 2IIM layout ("Passage N: …"), with the long "Solutions" and
     "Detailed Solutions" sections dropped.
   - 2022–24: the "Qn N" page layout.
3. `stats.py`: word counts; paragraph counts, merging lines that lack terminal
   punctuation; a regex classifier over question stems (n = 389 after dropping
   2IIM navigation junk such as "Q2 Q3").
4. I read every passage and question in full and hand-labelled: opening move,
   closing move, stance at close, thesis timing, nearest family, first person,
   register, and beats detected.
5. The engine side is library composition plus `python -m rc_engine.cli health`
   (read-only, $0), trailing 100 shipped sets for client AA.

**Known weaknesses.** Please weigh these.

- **Single annotator.** I created the categories while reading, so there is
  some risk of seeing gaps I expected. Appendix A is there for spot checks.
- **Openings and closings are not like-for-like** with the RC125 numbers. Those
  came from a blind LLM move extractor. My categories are stricter. Under a
  broad reading my data gives 61% abstract-type openings and 68% bound-type
  closings, against RC125's 77% and 81%. Treat opening and closing shares as
  directional.
- **Thesis timing is subjective for expository passages.** Where there is no
  argument, I counted the stated topic claim as "early".
- **"Nearest family" mapping is loose.** Several "new" clusters could arguably
  be `movement_variants` of F15, F58, F34, F49 or F53.
- **The regex classifier is ±3 pp.** First-match-wins ordering, so e.g.
  "least likely to" lands in author-supports before NOT/EXCEPT. About 4.6% of
  stems are "other".
- **Two eras are pooled.**
  - 2017–19: 5 passages per slot, some 300-word passages with 3 questions, up to
    6 questions per passage.
  - 2020–24: 4 passages, 4 questions each.

  2020–24 is closer to today's CAT, and its shares are given separately where
  they differ.
- **CAT sets are 4 questions; ours are 8.** Shares are per question, and set
  size legitimately changes the mix.
- **Paragraph counts are ±1** where page breaks split paragraphs. Word counts
  are reliable. 2IIM may have edited or truncated some passages ("…" and
  bracketed insertions are common).
- **I did not read shipped engine passages side by side.** The engine side is
  `health` stats plus library composition. A qualitative side-by-side of about
  10 shipped sets against about 10 PYQs would strengthen or weaken several
  claims.

---

## 3. Engine facts I verified (check these)

| # | Fact | Where |
|---|---|---|
| E1 | Render rule 7: "No moralizing, no policy prescriptions, no direct address to the reader." | `rc_engine/renderer.py:36` |
| E2 | Rule 8, architecture invisibility, bans signposting except in "a genre that genuinely signposts" | `renderer.py:37-45`; fixed phrases in `config.GLOBAL_FORBIDDEN_TICS` (`config.py:2116`); regex shapes in `question_engine._SIGNPOST_PATTERNS` (`question_engine.py:455`) |
| E3 | Rule 9 forbids invented studies, figures, quotes, scholars and dated events; real ones are allowed "when you are confident" | `renderer.py:46-61` |
| E4 | Refine is told to "invent CONTENT"; the seed goes in only as an "INSPIRATION ESSAY EXCERPT… do NOT copy its argument" (first 550 words); the renderer "invents all content". No verified-fact channel exists | `composer.py:44-49`, `composer.py:1212-1217`, `renderer.py:19-21` |
| E5 | Paragraph count = max(len(family movement), len(rhythm shape)), padding with `generic_fillers` (EVIDENCE_LAYER, CONCESSION_TRAP, RECURSIVE_REREAD). Rhythms are 3–5 slots; family movements: 3 ×1, 4 ×43, 5 ×13, 6 ×1 (F42) | `composer.py:817-826`, `families.json` top |
| E6 | Revelation timings: early R01, early_hidden R11; the other 18 are mid, split, late, penultimate, retrospective, distributed or never_stated. Sampling has only an exclusion window (10) and decay, no timing weights. R01 is in `incompatible_revelations` of **16** families | `revelations.json`; `config.py:1270`; `composer._revelation_para` (`composer.py:886`) |
| E7 | Closing postures across 58 families: resolution_qualified 22, refusal_suspended 15, resolution_costed 10, reframe_displace 9, refusal_dissolved 1, affirmation_endorsed 1. Posture decay pushes toward balance across fine postures; hard rule caps coarse-class runs at 2 | `families.json`; `config.py:1278-1283` |
| E8 | Topology slot types over 192 slots: thesis 24, detail_check 24, undermine_thesis 13, application 13, contextual_inference 13, author_vs_reported 13, weaken 12, closure_reading 12, phrase_in_context 12, strengthen 12, primary_purpose 8, evidence_function 8, structural_function 8, **except_scan 7 (3.6%)**, stance 5, counterfactual_structure 4, decoy_escape 4 | `topologies.json` |
| E9 | except_scan flips the option contract (3 supported plus 1 unsupported). Implemented as a special slot type (`TRAPLESS_SLOT`, `EXCEPT_MECHANISM`), not a flag | `question_engine.py:19-23`, `:361-397` |
| E10 | `FIRST_PERSON_MAX_SHARE = 0.20`; its comment says an authorial "I" appears in 6% of 129 real CAT/XAT/GMAT passages | `config.py:1428-1445` |
| E11 | `EXAM_FORM_MAX_SHARE` {medium 0.50, hard 0.35, elite 0.0} caps aggregate draws of `EXAM_DERIVED_SHAPES` (six shapes, F47–F52 only) | `config.py:1461-1467` |
| E12 | Move sampler weight = (1 − trailing_share) ** 1.0, so new moves start at weight 1.0; the config itself documents the transient | `config.py:1744-1759` |
| E13 | Every move must be in a `MOVE_GROUPS` group (test), so there is no "recognised but never prescribed" state | `tests/test_move_signature.py:172-177` |
| E14 | The similarity screen prompt cites RC125: "77% open… abstract claim", "81% close… still inside the ongoing argument" | `similarity_screen.py:52-58` |
| E15 | Registry needs ≥3 stem forms per slot type; family required fields id, name, tier_floor, core, movement, question_affinities, closing_posture, arc_shape | `registry.py:25-52` |
| E16 | Personas P01–P20 are all essayist voices: Forensic Skeptic, Genial Contrarian, Systems Cartographer, and so on. None is a news/magazine explainer, a book reviewer, or an advocate op-ed writer | `personas.json` |
| E17 | `DOMAIN_POOL` (8 humanities-theory domains) is used only when there is no seed; seeds come from about 34 RSS feeds in `RAG.py`, which do include science, history, Hakai, Sapiens and more | `composer.py:1144,1219`; `RAG.py:100-263` |

**`health`, client AA, trailing 100 shipped (2026-09-13):**

- **Closing postures realised:**

  | Posture | Sets |
  |---|---|
  | resolution_costed | 29 |
  | reframe_displace | 20 |
  | resolution_qualified | 19 |
  | refusal_suspended | 19 |
  | refusal_dissolved | 9 |
  | affirmation_endorsed | 4 |

  Refusal therefore totals **28%**.
- **Arc shapes:** legacy staged_turn_settled 42%. The 20+ other shapes run
  1–4% each; reviewed_study 1%, superseded_explanation 1%,
  thesis_first_defended 2%.
- **Aphorism endings:** 21 of 91 keyed sets (23%).
- **Move saturation:**

  | Move | Share | Status |
  |---|---|---|
  | MECHANISM_EXPLAINED | 81% | BAN |
  | EASY_READING_DEMOLISHED | 74% | BAN |
  | CONCESSION_GRANTED | 65% | BAN |
  | UNDERLYING_CAUSE_NAMED | 60% | BAN |
  | SCENE_PARTICULAR | 56% | BAN |
  | SYMMETRY_BROKEN | 52% | warn |
  | LEVEL_RELOCATION | 48% | warn |
  | INSTANCE_SURVEY | 47% | warn |
  | AUTHORITY_QUOTED | 46% | warn |

- **Seed genres (66 keyed):**

  | Genre | Sets |
  |---|---|
  | conceptual_essay | 27 |
  | reportage | 10 |
  | narrative_history | 9 |
  | criticism | 9 |
  | technical_explainer | 7 |
  | investigation | 2 |

---

## 4. Findings

### 4.1 Corpus shape

| Year | Passages | Median words | Median paragraphs | Questions / passage |
|---|---|---|---|---|
| 2017 | 10 | 511 | 5 | 6.3 |
| 2018 | 10 | 508 | 5.5 | 5.8 |
| 2019 | 10 | 499 | 3 | 5.5 |
| 2020 | 12 | 502 | 5 | 5.8 |
| 2021 | 12 | 506 | 4 | 4.3 |
| 2022 | 12 | 501 | 5 | 4 |
| 2023 | 12 | 501 | 5 | 4 |
| 2024 | 12 | 503 | 6 | 4 |

- **Paragraph counts** (n = 86 full-length passages):

  | Paragraphs | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
  |---|---|---|---|---|---|---|---|
  | Passages | 3 | 12 | 14 | 25 | 24 | 5 | 3 |

  **37% have 6–8 paragraphs.** The engine effectively maxes at 5, or 6 via F42
  (E5).
- **Paragraph length**: median 91 words.

  | Class | S | M | L | XL | ≥210 |
  |---|---|---|---|---|---|
  | CAT | 18% | 50% | 20% | 9% | 3% |
  | Rhythm library | 22% | 47% | 25% | 6% | — |

  Already fine.
- **Registers:**

  | Register | Share |
  |---|---|
  | Op-ed / opinion / polemic / editorial | ~19% |
  | Academic (incl. book intros, textbooks) | ~20% |
  | Science news / explainers | ~14% |
  | Essays | ~13% |
  | Reviews and retrospectives | 10% |
  | Magazine explainer (Economist-type) | ~6% |
  | Other | ~18% |

- **First person:** structural narrator 17%, incidental 9%, any 26%. The 20%
  cap is right for CAT; E10's 6% rationale is wrong for CAT.

### 4.2 Stance and thesis. Strongest findings; they hold whatever the instrument.

| | CAT (90) | Engine |
|---|---|---|
| Close committed | 79% | 72% realised |
| Close as neutral exposition | 19% | ~0 (every family has a posture) |
| Close genuinely open | **2%** (2 passages: 2019 S2 heritage scans, 2021 S2 fiction and power) | **28%** refusal realised; 16/58 families |
| Affirmation or prescription at close | 13% | 4% realised; rule 7 bans prescriptions (E1) |
| Thesis visible in paragraph 1–2 | **67%** | 2/20 revelations early-timed, uniform draws (E6) |
| Thesis mid | 21% | 4/20 |
| Thesis late | 12% | 7/20 |

### 4.3 Family fit (paragraph flows)

- **49/90 map onto an existing family:**
  - F54 ×6, F35 ×5, F53 ×5, F15 ×4, F17 ×4
  - F47, F50, F55, F24 ×3 each
  - F56, F36, F48 ×2 each
  - F51, F02, F26, F43, F49, F31, F08 ×1 each
- **Grouped:**

  | Group | Passages | Share |
  |---|---|---|
  | Exam-derived F47–F56 | 26 | 29% |
  | Arc-shape families F33–F46 | 8 | 9% |
  | Legacy F01–F32 | 15 | 17% |
  | No adequate fit | 41 | 46% |

- **Zero PYQ matches:** F01, F03–F07, F09–F14, F16, F18–F23, F25, F27–F30, F32.
  The legacy arc is 42% of shipped sets against about 17% of CAT.
- **Under-drawn vs CAT:**

  | Family | CAT | Shipped |
  |---|---|---|
  | F54 | 7% | 1% |
  | F53 + F24 | 9% | 3% |
  | F35 | 6% | 2% |

- **Recurring new shapes (7 each):**
  - **Backfiring remedy.** A popular fix is followed into practice until its
    own mechanism recreates the harm. Instances: electric cars 2017 S2,
    e-governance 2018 S2, choice-fatigue start-ups 2019 S1, renewables 2020 S2,
    second-hand fashion 2023 S2, cultural property laws 2023 S3, streaming vs
    physical media 2024 S1. Nearest existing are F15 (cure re-read as disease,
    no mechanism) and F58 (several remedies weighed, one endorsed).
  - **Typology.** A concept is fixed, then "N kinds" follow, each with a case.
    Instances: metric fixation 2018 S2, topophilia 2019 S1, anarchism 2020 S1,
    aggression 2020 S2, cephalopod camouflage 2022 S2, unintended consequences
    2024 S2, carnivore attacks 2024 S2. Nearest existing are F49 and F34 (F34
    withholds a thesis and is unranked).
  - **Scholarly introduction.** Field frame → difficulty → own approach →
    forestalled misreading → scope. Instances: visual culture 2020 S2,
    financial-crisis preface 2020 S3, nationalism 2021 S2, institutions 2022 S2,
    musicking 2022 S2, Indian Ocean novels 2023 S1, romantic aesthetics 2023 S3.
- **Reviews** are 9/90 (reviews plus one retrospective). The split-verdict close
  ("right about X, wrong about Y") appears in 4 of them plus the retrospective.
- **One-offs** (in the labels file): benchmark comparison, elegy for a lost
  function, omission corrected, misdirection exposed, stated aims audited,
  reported controversy, reply to critics, comparative ledger, rule relaxed then
  re-anchored, alien category scheme, bounded hypothesis, scandal deflated,
  myth busted by a distinction, fiction foreshadows the lab, neutral technique
  shown value-laden, bidirectional convergence, why a field resists,
  our field contributes, success against the rules.

### 4.4 Openings and closings (directional; see §2)

**Openings:**

| Opening | Share | In the engine opening group? |
|---|---|---|
| Abstract | 19% | yes |
| Other | 11% | — |
| News / data hook | 10% | missing |
| Historical | 9% | yes |
| Scene | 8% | yes |
| Thesis-first | 7% | partial |
| Definition | 7% | yes |
| Misconception-framed | 6% | missing |
| Reported position | 6% | missing |
| Quote / phrase dissected | 4% | missing |
| Aphorism | 4% | missing |
| Metatext | 4% | missing |
| Question | 3% | yes |
| Finding | 2% | missing |

**Closings:**

| Closing | Share | In the engine closing group? |
|---|---|---|
| Bound / truncated | 29% | yes |
| Aphoristic / wry / pun / callback | 17% | yes |
| Qualified verdict | 13% | partial |
| Concrete | 11% | yes |
| Quoted voice | 9% | missing |
| Prescription | 9% | missing, banned by rule 7 |
| Forecast | 6% | missing |
| Affirmation | 4% | posture only |
| Question left open | 2% | yes |

### 4.5 Beats (hand-detected share of the 90 passages)

| Beat | Share | Status |
|---|---|---|
| TERM_COINED | 22% | proposed |
| EASY_READING_DEMOLISHED | 18% | existing; engine 74% |
| CONCESSION_GRANTED | 17% | existing; engine 65% |
| ENUMERATED_SET | 16% | proposed; conflicts with rule 8 |
| READER_ADDRESS | 13% | banned by rule 7 |
| IRONY_NOTED | 12% | proposed |
| HYPOTHETICAL_CASE | 12% | proposed; conflicts with rule 7 |
| EXPERT_AS_SPINE | 11% | needs real quotes |
| STUDY_WALKTHROUGH | 10% | needs real studies |
| OBJECTION_FORESTALLED | 9% | proposed |
| THEN_NOW_CONTRAST | 9% | proposed |
| SPLIT_VERDICT | 7% | proposed |

The hand counts suggest the existing bans on EASY_READING_DEMOLISHED and
CONCESSION_GRANTED are **more** justified than RC125's blind shares (41% and
33%) implied.

### 4.6 Texture that rule 9 and E4 lock out

About 30% of CAT passages lean on real material:

| Texture | Share |
|---|---|
| Named researcher quoted as the spine | 11% |
| Study walkthrough | 10% |
| News or data hook | 10% |
| Quoted-voice close | 9% |
| Review of a real named book | 10% |

The seed articles contain exactly this material, but E4 means it never reaches
the renderer as usable fact. Question forms that need real numbers (data
falsification, protocol scenarios, quantitative application; about 4% of stems)
are unbuildable for the same reason.

### 4.7 Question flows (n = 389 stems)

| Kind | CAT all | CAT 2020–24 | Engine slots (192) |
|---|---|---|---|
| NOT / EXCEPT scan (any base type) | **27%** | **30%** | except_scan **3.6%** |
| Any negation (EXCEPT, NOT, least likely, if false, none of) | 37% | — | ~4% |
| Double / triple negation | 6% | — | 0 |
| Purpose of example / word / reference / device | 10.5% | 6% | primary + evidence + structural 12.6% |
| Detail | 8% | 7% | 12.5% |
| Gist / main idea | 7% | 7% | 12.5% |
| Inference | 7% | 7% | contextual_inference 6.8% |
| Weaken / undermine / invalidate | 7% | 7% | 13.0% |
| Author would support / advise / approve | **6.4%** | 7% | **none** |
| Application scenario | 5.7% | 7% | 6.8% |
| Meaning / paraphrase | 4.6% | 4% | phrase + contextual 13% |
| Keyword set / flow sequence / odd pair | **2.8%** | 4% | **none** |
| Reported party vs author; similarity AND difference | 2.6% | 3% | author_vs_reported 6.8% |
| Strengthen | 2.3% | 3% | 6.2% |
| Tone / stance of a sentence | 2.3% | 3% | 2.6% |
| Closure / counterfactual / decoy escape | ~0 | ~0 | 10.4% |

Notable CAT forms, paraphrased:
- "The author would be most supportive of which practice or programme?"
- "Which set of 4–5 keywords (or which sequence) best captures the argument?"
- "All of the following, if false, would be consistent… EXCEPT"
- "Which condition would have ensured the pattern did not disappear?"
  (requires modelling the mechanism)
- Near-identical application options that differ in one attribute:
  - copies of a painting that vary by medium, scale or signature;
  - product plans that vary by count × price;
  - experiment setups that vary by symbol × food.
- "Both a reason for X's success and a threat to it"
- "Odd pair out" on relations such as "X : Y"
- "Which would make the reviewer's choice of the pronoun 'who' inappropriate?"
- "If the author wrote a book on {event}, its focus would be…"
- Inference from a hypothetical example: the trap is treating the hypothetical
  as fact.
- Intended vs unintended effect: one option lists the *intended* use.

The closure-reading continuation stem is a client request (Lokesh, 2026-09-12;
`topologies.json` slot_types note). Keep it.

---

## 5. Proposals (critique these)

Full paste-ready JSON is in the companion report §6.

### P1: high impact, low to moderate effort

**P1a. Exam-weighted closing postures** (medium and hard; elite unchanged).
- An `EXAM_POSTURE_SHARES` table on top of the existing decay, following the
  `ARGUMENT_SCHEMAS` precedent:

  | Posture | Share |
  |---|---|
  | resolution_qualified | 0.38 |
  | resolution_costed | 0.20 |
  | affirmation_endorsed | 0.14 |
  | reframe_displace | 0.14 |
  | refusal_suspended | 0.10 |
  | refusal_dissolved | 0.04 |

- Refusal lands at 14%: half today's rate, still 7× CAT.

**P1b. Exam-weighted revelation timing** (medium and hard) plus three new early
revelations.
- Timing weights:

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

- New revelations:
  - R21 "Stated, Then Tested"
  - R22 "Paradox Up Front"
  - R23 "Received View Named First"
- Audit the 16 R01 incompatibilities.

**P1c. Negation as a slot flag.**
- `"negated": true` on detail_check, contextual_inference, author_vs_reported,
  application, weaken and strengthen.
- Reuse the except_scan contract flip.
- Target 2 of 8 slots. At most 1 double negation, hard and elite only.
- A code change across the question prompt, validator, solver comparability and
  trap histogram.

**P1d. Rule 7 exceptions tied to planned beats.**
- A bounded closing prescription only when PRESCRIPTION_STATED is planned or the
  posture is affirmation_endorsed. That also fixes a live contradiction: F58's
  WORKING_REMEDY_ENDORSED against "no policy prescriptions".
- One explicit hypothetical ("imagine", "consider a…") only when
  HYPOTHETICAL_CASE is planned.
- Keep "no moralizing".

### P2: high impact, more work

**P2a. Verified seed facts.**
1. Refine returns ≤8 `verified_facts`, each with a `seed_span` that must be an
   exact substring of `seed.text` (a deterministic check, so none can be
   invented). Each span is ≤25 words.
2. The renderer may cite only those as real; rule 9 stays absolute otherwise.
3. `texture_report` downgrades a figure, quote or study that matches a
   whitelisted span.

This unlocks news hooks, study walkthroughs, expert quotes, quote closes,
real-book reviews and numeric question types.

**P2b. New families and beats.**
- Families:
  - F59 Backfiring Remedy (resolution_costed)
  - F60 Typology (resolution_qualified; needs a rule 8 exception for
    enumeration)
  - F61 Framed Inquiry (hard only; needs a rule 8 exception for scope metatext)
  - F62 Split Verdict (review; real books need P2a)
- Add all four arc shapes to `EXAM_DERIVED_SHAPES` so `EXAM_FORM_MAX_SHARE`
  bounds their zero-usage transient.
- Ten beats:

  | Group | Beats |
  |---|---|
  | Middle | TERM_COINED, ENUMERATED_SET, IRONY_NOTED, HYPOTHETICAL_CASE, OBJECTION_FORESTALLED, THEN_NOW_CONTRAST |
  | Opening | REPORTED_POSITION |
  | Closing | PRESCRIPTION_STATED, FORECAST, SPLIT_VERDICT |

**P2c. New slot types and topologies.**
- `author_would_endorse` and `keyword_set`, each with 3 stem forms.
- QT25 and QT26, each with 2 negated slots.

### P3: lower impact

- **Rhythms:** T21 "Newsroom" [M,S,M,M,S,M] and T22 "Short Takes"
  [S,M,M,S,M,M,S]. Consider excluding CONCESSION_TRAP from the filler padding
  for these.
- **Personas:** P21 Magazine Explainer, P22 Reviewer, P23 Advocate.
- **Stem forms:** tone of a quoted sentence; word purpose; where two reported
  parties disagree; similarity AND difference; sense of a quoted sentence.
- **Application design note:** near-identical scenario options.
- **Recalibration run:** run the existing blind move extractor over the 90 PYQs
  (paid, needs approval). Then update `EXAM_MOVE_SHARES`, the
  `similarity_screen.py` calibration block and the E10 comment.

---

## 6. Things I noticed but did not pursue

- **Excerpt texture.** CAT passages from 2019 on are visibly excerpted, with
  "…" and bracketed insertions, and some open mid-list or close mid-argument.
  Cosmetic, and arguably misleading to imitate. Not proposed.
- **The Economist** supplies roughly 10% of CAT passages: Saturn,
  decentralisation, wolves, Netflix, the liberalism review, crafts, Moutai,
  Harari on AI. It is paywalled and not a feed. The P21 persona is the
  workaround.
- **Title-less passages.** 2022–24 carry no titles, and 2017–21 titles are
  2IIM's own. Irrelevant to the engine.
- **Solutions.** 2IIM's detailed solutions for 2017–21 carry answer keys and
  distractor explanations. They were not mined, and would be a useful source
  for distractor-mechanism frequencies (`distractor_profiles.json`) if someone
  wants that next.
- **Option length in 2024.** 2024 options are much longer and more elaborate
  than 2017's. The engine's length-bias guard (`MAX_CORRECT_LONGEST`) already
  handles the tell.

---

## 7. Open questions for the reviewer

1. **Exam realism.** Does exam-weighting postures and revelations (P1a, P1b)
   make medium and hard sets *easier* in a way the client would dislike? Or is
   CAT difficulty really carried by content density, negation and option
   granularity, as I argue?
2. **Negation design.** Is a negation flag across slot types (P1c) better than
   simply adding more except_scan slots to topologies? What breaks in the solver
   or validator?
3. **Distinctness.** Are F59–F62 distinct enough from F15, F58, F34, F49 and F53
   to justify new families? Or should they be `movement_variants` of existing
   families, which carries no rarity transient and no new arc shape?
4. **Fingerprint comparability.** Does adding 10 moves distort
   `move_signature` comparisons against historical fingerprints, which were
   extracted with the old vocabulary? Should new moves get a seeded trailing
   share (e.g. the median) for N sets instead of starting at weight 1.0?
5. **Seed facts.** Is a substring check sufficient for P2a? What are the
   plagiarism, copyright and novelty (embedding-channel) side effects of
   passages carrying seed facts?
6. **Enumeration.** How do you allow ENUMERATED_SET and scope metatext (F60,
   F61) without reopening the signposting tells rule 8 was written against
   (architecture narration in LLM prose)?
7. **Label audit.** Spot-check 15 random rows of Appendix A against the PDF. Do
   you agree with the open, close, stance, thesis and family labels? Report the
   disagreement rate.
8. **Stale assumptions.** Is RC125 still the right baseline for anything, now
   that a CAT-only corpus exists?

---

## Appendix A: per-passage labels

- **id** = YY-slot-passage.
- **stance**: COMMITTED / NEUTRAL (exposition with no evaluative close) / OPEN.
- **thesis**: when the main claim becomes visible.
- **1P** = first person: 0 none, 1 incidental, 2 structural narrator.
- **beats detected** covers only the 12 beats tracked in §4.5.
- **question forms** come from the regex classifier. "gist" includes "what is
  the passage trying to do".
| id | topic | register | words / paras | open | close | stance | thesis | nearest family | 1P | beats detected | question forms (regex) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 17-1-1 | map orientation | reportage | 518 / 5 | ABSTRACT | BOUND | NEUTRAL | mid | F56 | 0 | EXPERT_AS_SPINE, EASY_READING_DEMOLISHED | gist, NOT/EXCEPT, detail, infer, other, other |
| 17-1-2 | printing press vs iPhone | op-ed | 541 / 5 | SCENE | APHORISTIC | COMMITTED | late | new: benchmark_comparison | 2 | READER_ADDRESS, EASY_READING_DEMOLISHED, CONCESSION_GRANTED | detail, NOT/EXCEPT, other, purpose, detail, gist |
| 17-1-3 | malls as public square | feature | 510 / 5 | NEWS_DATA_HOOK | QUOTE_CLOSE | COMMITTED | mid | new: elegy_for_a_function | 0 | IRONY_NOTED, HYPOTHETICAL_CASE, READER_ADDRESS, CONCESSION_GRANTED | gist, NOT/EXCEPT, meaning, detail, purpose, purpose |
| 17-1-4 | speciation debate | science_history | 298 / 3 | ABSTRACT | BOUND | NEUTRAL | mid | F54 | 0 | - | gist, NOT/EXCEPT, purpose |
| 17-1-5 | Olympic host cities | op-ed | 340 / 4 | QUESTION | BOUND | COMMITTED | early | F35 | 0 | ENUMERATED_SET | gist, NOT/EXCEPT, NOT/EXCEPT |
| 17-2-1 | creativity and cities | op-ed | 513 / 7 | THESIS_FIRST | PRESCRIPTION | COMMITTED | early | new: diagnosis_oped | 2 | TERM_COINED, IRONY_NOTED | NOT/EXCEPT, purpose, gist, other, purpose, infer |
| 17-2-2 | subnivium | science_explainer | 529 / 6 | SCENE | CONCRETE | NEUTRAL | early | F47 | 0 | HYPOTHETICAL_CASE, READER_ADDRESS, EASY_READING_DEMOLISHED | purpose, NOT/EXCEPT, author-supports, purpose, infer, purpose |
| 17-2-3 | electric cars | editorial | 522 / 5 | ABSTRACT | APHORISTIC | COMMITTED | late | new: backfiring_remedy | 0 | IRONY_NOTED, CONCESSION_GRANTED | gist, NOT/EXCEPT, detail, infer, purpose, purpose |
| 17-2-4 | typewriters | editorial | 256 / 1 | OTHER | APHORISTIC | COMMITTED | early | F15 | 0 | - | gist, detail, NOT/EXCEPT |
| 17-2-5 | Viking traders | science_news | 320 / 2 | MISCONCEPTION | BOUND | COMMITTED | early | F55 | 0 | STUDY_WALKTHROUGH, EASY_READING_DEMOLISHED | purpose, purpose, NOT/EXCEPT |
| 18-1-1 | elephant trauma | science_feature | 510 / 6 | QUOTE | QUOTE_CLOSE | COMMITTED | early | F54 | 0 | EXPERT_AS_SPINE, OBJECTION_FORESTALLED | gist, purpose, NOT/EXCEPT, author-supports, meaning |
| 18-1-2 | India in WWII | op-ed | 490 / 8 | NEWS_DATA_HOOK | PRESCRIPTION | COMMITTED | early | new: omission_corrected | 0 | - | stance, NOT/EXCEPT, meaning, NOT/EXCEPT, detail |
| 18-1-3 | plastic blame | op-ed | 511 / 5 | APHORISM | PRESCRIPTION | COMMITTED | early | new: misdirection_exposed | 2 | EASY_READING_DEMOLISHED, CONCESSION_GRANTED | author-supports, NOT/EXCEPT, purpose, meaning, infer |
| 18-1-4 | quantified happiness | op-ed | 493 / 6 | HISTORICAL | PRESCRIPTION | COMMITTED | late | F17 | 0 | THEN_NOW_CONTRAST, CONCESSION_GRANTED | detail, weaken, stance, author-supports, detail |
| 18-1-5 | epigenetic inheritance | essay | 519 / 6 | SCENE | CONCRETE | COMMITTED | early | F56 | 0 | HYPOTHETICAL_CASE, STUDY_WALKTHROUGH, READER_ADDRESS, EASY_READING_DEMOLISHED | purpose, gist, other, weaken |
| 18-2-1 | meritocracy and diversity | essay | 501 / 4 | ABSTRACT | APHORISTIC | COMMITTED | early | F36 | 0 | HYPOTHETICAL_CASE, READER_ADDRESS | weaken, NOT/EXCEPT, weaken, apply, purpose |
| 18-2-2 | grove snails | science_news | 511 / 5 | FINDING | QUOTE_CLOSE | COMMITTED | late | F51 | 0 | STUDY_WALKTHROUGH, EXPERT_AS_SPINE | gist, strengthen, infer, detail |
| 18-2-3 | metric fixation | book | 439 / 4 | DEFINITION | BOUND | COMMITTED | early | new: typology | 0 | TERM_COINED, ENUMERATED_SET | NOT/EXCEPT, keywords, purpose, NOT/EXCEPT, purpose |
| 18-2-4 | Saturn's rings | science_news | 506 / 5 | APHORISM | BOUND | COMMITTED | early | F55 | 0 | STUDY_WALKTHROUGH | gist, infer, NOT/EXCEPT, meaning, other |
| 18-2-5 | e-governance | op-ed | 512 / 6 | QUESTION | PRESCRIPTION | COMMITTED | early | new: backfiring_remedy | 0 | EASY_READING_DEMOLISHED | purpose, meaning, NOT/EXCEPT, detail, weaken |
| 19-1-1 | Aladdin's author | news | 505 / 3 | MISCONCEPTION | QUOTE_CLOSE | COMMITTED | early | F54 | 0 | TERM_COINED, EASY_READING_DEMOLISHED | NOT/EXCEPT, author-supports, detail, NOT/EXCEPT |
| 19-1-2 | choice fatigue | essay | 501 / 3 | ABSTRACT | APHORISTIC | COMMITTED | late | new: backfiring_remedy | 0 | IRONY_NOTED | apply, purpose, apply, weaken, NOT/EXCEPT |
| 19-1-3 | penguin plumage | science_news | 493 / 3 | FINDING | CONCRETE | NEUTRAL | early | F47 | 0 | STUDY_WALKTHROUGH | meaning, purpose, weaken, other |
| 19-1-4 | British folk | culture_essay | 499 / 3 | QUOTE | BOUND | COMMITTED | early | F17 | 0 | THEN_NOW_CONTRAST | detail, NOT/EXCEPT, apply, purpose, NOT/EXCEPT |
| 19-1-5 | topophilia | encyclopedic | 505 / 3 | DEFINITION | BOUND | NEUTRAL | early | new: typology | 0 | TERM_COINED, ENUMERATED_SET | other, purpose, meaning, apply, weaken |
| 19-2-1 | dispersing capitals | magazine_explainer | 493 / 7 | NEWS_DATA_HOOK | BOUND | COMMITTED | mid | new: stated_aims_audited | 0 | ENUMERATED_SET | detail, purpose, author-supports, infer, NOT/EXCEPT |
| 19-2-2 | 3D scans of heritage | news | 483 / 7 | NEWS_DATA_HOOK | QUOTE_CLOSE | OPEN | early | new: reported_controversy | 0 | TERM_COINED, EXPERT_AS_SPINE | reported, other, weaken, reported, author-supports |
| 19-2-3 | squatter cities | book | 494 / 6 | APHORISM | APHORISTIC | COMMITTED | early | F15 | 2 | CONCESSION_GRANTED | weaken, NOT/EXCEPT, infer, purpose, NOT/EXCEPT |
| 19-2-4 | learning Arabic | memoir_essay | 499 / 5 | SCENE | APHORISTIC | COMMITTED | mid | new: reply_to_critics | 2 | TERM_COINED | infer, apply, reported, NOT/EXCEPT |
| 19-2-5 | colonial modernity | academic | 511 / 3 | HISTORICAL | BOUND | COMMITTED | early | F02 | 0 | TERM_COINED, OBJECTION_FORESTALLED | NOT/EXCEPT, strengthen, NOT/EXCEPT, keywords, NOT/EXCEPT |
| 20-1-1 | anarchism | encyclopedic | 490 / 6 | HISTORICAL | BOUND | NEUTRAL | early | new: typology | 0 | - | other, NOT/EXCEPT, detail, NOT/EXCEPT, keywords |
| 20-1-2 | elephant seal dialects | science_journalism | 504 / 5 | HISTORICAL | BOUND | NEUTRAL | late | F50 | 0 | STUDY_WALKTHROUGH, EXPERT_AS_SPINE | NOT/EXCEPT, NOT/EXCEPT, gist, infer |
| 20-1-3 | Tang currency | history | 486 / 5 | MISCONCEPTION | CONCRETE | NEUTRAL | early | new: comparative_ledger | 0 | - | infer, NOT/EXCEPT, NOT/EXCEPT, apply |
| 20-1-4 | grammar | craft_book | 502 / 5 | OTHER | APHORISTIC | COMMITTED | mid | new: rule_relaxed_reanchored | 2 | HYPOTHETICAL_CASE, READER_ADDRESS | gist, if-false, NOT/EXCEPT, apply, author-supports |
| 20-2-1 | visual culture studies | academic | 488 / 6 | METATEXT | BOUND | COMMITTED | early | new: scholarly_introduction | 0 | ENUMERATED_SET | meaning, NOT/EXCEPT, meaning, meaning, keywords |
| 20-2-2 | piracy (review) | review | 505 / 5 | NEWS_DATA_HOOK | BOUND | COMMITTED | mid | F53 | 0 | SPLIT_VERDICT | infer, infer, stance, NOT/EXCEPT |
| 20-2-3 | renewables' costs | academic | 484 / 5 | ABSTRACT | FORECAST | COMMITTED | early | new: backfiring_remedy | 0 | EASY_READING_DEMOLISHED | strengthen, if-false, infer, gist, author-supports |
| 20-2-4 | aggression | textbook | 503 / 2 | DEFINITION | BOUND | NEUTRAL | early | new: typology | 0 | - | purpose, NOT/EXCEPT, detail, NOT/EXCEPT |
| 20-3-1 | travel writing | academic | 514 / 3 | ABSTRACT | BOUND | NEUTRAL | early | F48 | 0 | - | NOT/EXCEPT, apply, infer, other, detail |
| 20-3-2 | human nature (review) | review | 511 / 6 | ABSTRACT | VERDICT_QUALIFIED | COMMITTED | late | F24 | 0 | TERM_COINED, SPLIT_VERDICT, CONCESSION_GRANTED | reported, detail, NOT/EXCEPT, detail |
| 20-3-3 | screen time and class | op-ed | 511 / 7 | THESIS_FIRST | VERDICT_QUALIFIED | COMMITTED | early | F35 | 0 | IRONY_NOTED, THEN_NOW_CONTRAST, CONCESSION_GRANTED | author-supports, strengthen, author-supports, detail |
| 20-3-4 | financial crisis (preface) | preface | 493 / 2 | OTHER | FORECAST | COMMITTED | early | new: scholarly_introduction | 2 | IRONY_NOTED | if-false, infer, gist, strengthen, author-supports |
| 21-1-1 | tea (review) | review | 492 / 5 | REPORTED_POSITION | AFFIRMATION | COMMITTED | early | F53 | 1 | - | strengthen, reported, NOT/EXCEPT, apply |
| 21-1-2 | Maya personhood | scholar_essay | 482 / 3 | ABSTRACT | VERDICT_QUALIFIED | COMMITTED | early | new: alien_category_scheme | 2 | HYPOTHETICAL_CASE, READER_ADDRESS | weaken, weaken, apply, purpose |
| 21-1-3 | utopia and dystopia | academic | 494 / 3 | OTHER | VERDICT_QUALIFIED | COMMITTED | late | new: bounded_hypothesis | 1 | OBJECTION_FORESTALLED, CONCESSION_GRANTED | other, keywords, NOT/EXCEPT, NOT/EXCEPT |
| 21-1-4 | cuttlefish self-control | science_news | 503 / 5 | OTHER | QUESTION_OPEN | NEUTRAL | early | F55 | 0 | STUDY_WALKTHROUGH, EXPERT_AS_SPINE | NOT/EXCEPT, strengthen, apply, NOT/EXCEPT |
| 21-2-1 | scandal of knowledge | essay | 523 / 3 | QUOTE | BOUND | COMMITTED | mid | new: scandal_deflated | 1 | - | author-supports, NOT/EXCEPT, detail, NOT/EXCEPT |
| 21-2-2 | endangered languages | op-ed | 511 / 6 | MISCONCEPTION | APHORISTIC | COMMITTED | late | F15 | 2 | TERM_COINED, EASY_READING_DEMOLISHED | author-supports, NOT/EXCEPT, purpose, NOT/EXCEPT |
| 21-2-3 | nationalism's dichotomies | academic | 500 / 4 | METATEXT | VERDICT_QUALIFIED | COMMITTED | early | new: scholarly_introduction | 2 | TERM_COINED, OBJECTION_FORESTALLED | weaken, reported, NOT/EXCEPT, weaken |
| 21-2-4 | fiction and power | pop_intellectual | 512 / 4 | MISCONCEPTION | QUESTION_OPEN | OPEN | early | new: myth_busted_by_distinction | 0 | ENUMERATED_SET, EASY_READING_DEMOLISHED | other, gist, infer, author-supports |
| 21-3-1 | the unconscious | intellectual_history | 508 / 4 | HISTORICAL | VERDICT_QUALIFIED | COMMITTED | early | F17 | 0 | THEN_NOW_CONTRAST | keywords, gist, apply, NOT/EXCEPT |
| 21-3-2 | clocks and entropy | science_news | 522 / 4 | THESIS_FIRST | FORECAST | COMMITTED | early | F47 | 0 | STUDY_WALKTHROUGH, EXPERT_AS_SPINE | purpose, NOT/EXCEPT, keywords, NOT/EXCEPT |
| 21-3-3 | language instinct (review) | review | 505 / 4 | HISTORICAL | AFFIRMATION | COMMITTED | early | F53 | 0 | OBJECTION_FORESTALLED, THEN_NOW_CONTRAST | gist, NOT/EXCEPT, NOT/EXCEPT, reported |
| 21-3-4 | soft robots | column | 514 / 5 | SCENE | CONCRETE | COMMITTED | early | new: fiction_foreshadows_lab | 2 | - | gist, meaning, if-false, infer |
| 22-1-1 | copies East and West | essay | 482 / 5 | DEFINITION | QUOTE_CLOSE | COMMITTED | early | F26 | 0 | TERM_COINED | apply, NOT/EXCEPT, apply, NOT/EXCEPT |
| 22-1-2 | Stoics on emotion | textbook | 515 / 4 | HISTORICAL | BOUND | NEUTRAL | early | F48 | 0 | HYPOTHETICAL_CASE | infer, if-false, tone, purpose |
| 22-1-3 | critical theory of technology | academic | 523 / 5 | DEFINITION | VERDICT_QUALIFIED | COMMITTED | early | F43 | 1 | - | NOT/EXCEPT, gist, weaken, strengthen |
| 22-1-4 | the Undead | popular_history | 505 / 5 | ABSTRACT | CONCRETE | NEUTRAL | early | F50 | 0 | - | gist, purpose, if-false, NOT/EXCEPT |
| 22-2-1 | cephalopod camouflage | pop_science | 498 / 6 | ABSTRACT | BOUND | NEUTRAL | early | new: typology | 0 | ENUMERATED_SET | NOT/EXCEPT, weaken, infer, NOT/EXCEPT |
| 22-2-2 | institutions | academic | 487 / 3 | METATEXT | BOUND | COMMITTED | early | new: scholarly_introduction | 1 | HYPOTHETICAL_CASE, READER_ADDRESS | NOT/EXCEPT, NOT/EXCEPT, gist, NOT/EXCEPT |
| 22-2-3 | engineering pedagogy | op-ed | 507 / 6 | ABSTRACT | AFFIRMATION | COMMITTED | early | new: neutral_technique_value_laden | 2 | TERM_COINED, EASY_READING_DEMOLISHED | gist, NOT/EXCEPT, NOT/EXCEPT, author-supports |
| 22-2-4 | musicking | academic | 508 / 5 | THESIS_FIRST | BOUND | COMMITTED | early | new: scholarly_introduction | 1 | TERM_COINED, OBJECTION_FORESTALLED | keywords, infer, meaning, weaken |
| 22-3-1 | automation and skill | essay | 484 / 6 | THESIS_FIRST | AFFIRMATION | COMMITTED | early | F35 | 0 | TERM_COINED | stance, infer, apply, infer |
| 22-3-2 | bios and technos | visionary_essay | 497 / 6 | OTHER | APHORISTIC | COMMITTED | early | new: bidirectional_convergence | 0 | TERM_COINED | meaning, keywords, NOT/EXCEPT, meaning |
| 22-3-3 | Orientalist India | academic | 492 / 4 | ABSTRACT | BOUND | COMMITTED | early | F17 | 0 | - | NOT/EXCEPT, strengthen, apply, NOT/EXCEPT |
| 22-3-4 | Chicago School | textbook | 504 / 4 | ABSTRACT | BOUND | NEUTRAL | early | F49 | 0 | - | gist, weaken, NOT/EXCEPT, keywords |
| 23-1-1 | geographic explanations | essay | 480 / 6 | ABSTRACT | BOUND | COMMITTED | mid | new: why_a_field_resists | 0 | ENUMERATED_SET, EASY_READING_DEMOLISHED | NOT/EXCEPT, NOT/EXCEPT, purpose, NOT/EXCEPT |
| 23-1-2 | Indian Ocean novels | author_essay | 506 / 5 | OTHER | VERDICT_QUALIFIED | COMMITTED | early | new: scholarly_introduction | 2 | OBJECTION_FORESTALLED | NOT/EXCEPT, NOT/EXCEPT, keywords, weaken |
| 23-1-3 | Sahlins at fifty | retrospective_essay | 496 / 5 | QUESTION | VERDICT_QUALIFIED | COMMITTED | mid | F24 | 0 | SPLIT_VERDICT | gist, purpose, reported, purpose |
| 23-1-4 | wolves return | magazine_explainer | 529 / 4 | SCENE | FORECAST | NEUTRAL | mid | F50 | 0 | EXPERT_AS_SPINE | NOT/EXCEPT, NOT/EXCEPT, other, weaken |
| 23-2-1 | second-hand fashion | feature | 491 / 6 | NEWS_DATA_HOOK | QUOTE_CLOSE | COMMITTED | mid | new: backfiring_remedy | 0 | IRONY_NOTED, READER_ADDRESS | weaken, detail, author-supports, NOT/EXCEPT |
| 23-2-2 | liberalism (review) | review | 505 / 4 | REPORTED_POSITION | VERDICT_QUALIFIED | COMMITTED | mid | F53 | 0 | IRONY_NOTED, SPLIT_VERDICT, CONCESSION_GRANTED | reported, author-supports, NOT/EXCEPT, purpose |
| 23-2-3 | historical facts | classic_historiography | 492 / 3 | REPORTED_POSITION | APHORISTIC | COMMITTED | mid | F54 | 0 | ENUMERATED_SET, EASY_READING_DEMOLISHED | weaken, apply, detail, NOT/EXCEPT |
| 23-2-4 | Netflix and Europe | magazine_explainer | 506 / 5 | QUOTE | APHORISTIC | COMMITTED | late | F15 | 0 | IRONY_NOTED, CONCESSION_GRANTED | NOT/EXCEPT, stance, weaken, apply |
| 23-3-1 | climate and colonialism (review) | review | 507 / 2 | REPORTED_POSITION | BOUND | COMMITTED | early | F54 | 1 | ENUMERATED_SET | NOT/EXCEPT, purpose, NOT/EXCEPT, weaken |
| 23-3-2 | rationality (review) | review | 497 / 6 | REPORTED_POSITION | VERDICT_QUALIFIED | COMMITTED | mid | F24 | 0 | SPLIT_VERDICT, CONCESSION_GRANTED | purpose, purpose, NOT/EXCEPT, author-supports |
| 23-3-3 | cultural property laws | op-ed | 485 / 6 | NEWS_DATA_HOOK | CONCRETE | COMMITTED | mid | new: backfiring_remedy | 2 | STUDY_WALKTHROUGH, OBJECTION_FORESTALLED | author-supports, infer, weaken, other |
| 23-3-4 | romantic aesthetics | academic | 522 / 4 | METATEXT | BOUND | COMMITTED | mid | new: scholarly_introduction | 0 | - | detail, NOT/EXCEPT, other, detail |
| 24-1-1 | bandicoots | nature_feature | 467 / 8 | SCENE | CONCRETE | COMMITTED | late | F31 | 0 | TERM_COINED, EXPERT_AS_SPINE | detail, NOT/EXCEPT, detail, gist |
| 24-1-2 | economists and borders | review | 512 / 6 | APHORISM | VERDICT_QUALIFIED | COMMITTED | early | F53 | 0 | TERM_COINED, HYPOTHETICAL_CASE, THEN_NOW_CONTRAST, SPLIT_VERDICT, READER_ADDRESS | other, tone, reported, meaning |
| 24-1-3 | crafts and work | magazine_explainer | 506 / 6 | OTHER | APHORISTIC | COMMITTED | early | F08 | 0 | ENUMERATED_SET, CONCESSION_GRANTED | infer, NOT/EXCEPT, detail, NOT/EXCEPT |
| 24-1-4 | streaming and lost films | culture_essay | 504 / 5 | NEWS_DATA_HOOK | APHORISTIC | COMMITTED | early | new: backfiring_remedy | 0 | TERM_COINED, THEN_NOW_CONTRAST | NOT/EXCEPT, purpose, weaken, meaning |
| 24-2-1 | peer review data | opinion | 488 / 8 | THESIS_FIRST | PRESCRIPTION | COMMITTED | early | F35 | 0 | CONCESSION_GRANTED | author-supports, NOT/EXCEPT, NOT/EXCEPT, NOT/EXCEPT |
| 24-2-2 | medieval spices | history | 501 / 6 | ABSTRACT | CONCRETE | COMMITTED | mid | F54 | 0 | EASY_READING_DEMOLISHED | NOT/EXCEPT, NOT/EXCEPT, apply, author-supports |
| 24-2-3 | unintended consequences | pop_history | 502 / 6 | DEFINITION | FORECAST | COMMITTED | early | new: typology | 0 | TERM_COINED, ENUMERATED_SET, HYPOTHETICAL_CASE, READER_ADDRESS | author-supports, purpose, gist, NOT/EXCEPT |
| 24-2-4 | carnivore attacks | science_journalism | 512 / 6 | OTHER | QUOTE_CLOSE | NEUTRAL | early | new: typology | 0 | ENUMERATED_SET, EXPERT_AS_SPINE | apply, detail, if-false, infer |
| 24-3-1 | planetary protection | polemic | 496 / 4 | OTHER | PRESCRIPTION | COMMITTED | early | F36 | 0 | IRONY_NOTED | NOT/EXCEPT, stance, author-supports, other |
| 24-3-2 | languages and liberal arts | op-ed | 508 / 6 | ABSTRACT | CONCRETE | COMMITTED | mid | new: our_field_contributes | 2 | - | NOT/EXCEPT, NOT/EXCEPT, weaken, apply |
| 24-3-3 | Moutai | magazine_explainer | 491 / 7 | NEWS_DATA_HOOK | APHORISTIC | COMMITTED | early | new: success_against_the_rules | 0 | TERM_COINED, ENUMERATED_SET, IRONY_NOTED | detail, NOT/EXCEPT, detail, meaning |
| 24-3-4 | AI and language | op-ed | 509 / 5 | HISTORICAL | PRESCRIPTION | COMMITTED | early | F35 | 1 | HYPOTHETICAL_CASE, THEN_NOW_CONTRAST, READER_ADDRESS, EASY_READING_DEMOLISHED, CONCESSION_GRANTED | NOT/EXCEPT, NOT/EXCEPT, stance, author-supports |

---

## Appendix B: labels file schema

2026-09-13-cat-pyq-labels.json holds passages[] with:
- id, 	opic, 
egister, open, close, stance, 	hesis, amily, irst_person
- words, paragraphs, para_words[]
- question_types[] (regex classes, in question order)

It also holds eats{beat: [ids]}.

Beat and question shares are recomputed straight from it: Counter over
passages[*].open and so on, divided by 90; question shares are divided
by 389.

---

## Appendix C: reproduction scripts

Run in this order, with SP a scratch directory: python extract.py SP\clean.txt,
then python build_reading.py SP, then python stats.py SP.

stats.py reads 
eading.txt and 
eading2.txt and writes pyq_stats.json
plus stems_classified.txt. The words, paragraphs and question types in the
labels file came from pyq_stats.json, zipped in paper order. Requires pymupdf.

### C.1 extract.py
`python
"""Extract CAT PYQ PDF into a clean line stream with paragraph markers.

Output: clean.txt  -- one logical line per paragraph (passage prose), with
page markers and section markers preserved so the second pass can segment.
"""
import re, statistics, sys
import pymupdf

SRC = r"C:\Users\anshu\Downloads\CAT RC PYQ 2017-2024.pdf"
OUT = sys.argv[1]

BOILER = [
    r"^online\.2IIM\.com", r"^For more CAT Level", r"^CAT\s+20\d\d Question Paper",
    r"^Click", r"^To Download", r"^Download the free", r"^Original CAT 20\d\d",
    r"^CAT 20\d\d Slot\s*-\s*\d", r"^Explanation\s*Video Solution", r"^Video Solution",
    r"^Explanation$", r"^- (Rajesh|Bharathwaj|Jatin)", r"^40 hrs of free", r"^questions from 2IIM",
    r"^Questions\s*$", r"^Question\s*$", r"^Answer\s*$", r"^Passage\s*$", r"^Q1 Q2",
    r"^Click here", r"^Comprehension\s*$", r"^\d+\s*$", r"^Set \d+\s*$",
    r"^CAT 20\d\d – Verbal", r"^Text Solutions", r"^CAT Syllabus",
]
BOILER_RE = re.compile("|".join(BOILER))

doc = pymupdf.open(SRC)
out = open(OUT, "w", encoding="utf-8")
for pno in range(1, len(doc)):
    page = doc[pno]
    d = page.get_text("dict")
    lines = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"]).strip()
            if not t:
                continue
            x0, y0, x1, y1 = l["bbox"]
            lines.append([x0, y0, x1, y1, t])
    lines.sort(key=lambda r: (round(r[1]), r[0]))
    # merge lines sharing a baseline (spans split into separate lines)
    merged = []
    for r in lines:
        if merged and abs(merged[-1][1] - r[1]) < 2.5:
            m = merged[-1]
            m[2] = max(m[2], r[2]); m[4] = m[4] + " " + r[4]
        else:
            merged.append(r)
    body = [r for r in merged if not BOILER_RE.search(r[4])]
    out.write(f"\n@@PAGE {pno+1}\n")
    if not body:
        continue
    right = max(r[2] for r in body)
    heights = [r[3] - r[1] for r in body]
    lh = statistics.median(heights) if heights else 12
    buf = ""
    prev = None
    for r in body:
        t = r[4]
        gap = (r[1] - prev[3]) if prev else 0
        if prev is not None and (gap > 0.9 * lh):
            out.write(buf + "\n"); buf = ""
        if buf.endswith("-") and not buf.endswith(" -"):
            buf = buf[:-1] + t
        else:
            buf = (buf + " " + t).strip()
        # short line => paragraph end
        if r[2] < right - 60:
            out.write(buf + "\n"); buf = ""
        prev = r
    if buf:
        out.write(buf + "\n")
out.close()
print("ok")
`

### C.2 build_reading.py
`python
"""clean.txt (from extract.py) -> reading.txt (2017-21) + reading2.txt (2022-24).
2017-21: drops 'Passage N: Solutions/Detailed Solutions' sections.
2022-24: one prose block per passage, 'Qn N' blocks after it."""
import re, sys

SP = sys.argv[1]
L = open(SP + r"\clean.txt", encoding="utf-8").read().split("\n")
INTRO = re.compile(r"^(Read the passage and answer|The passage below is accompanied|passage, choose the best|"
                   r"choose the best answer|each question|question\.$)", re.I)

# ---- 2017-2021 (pages 2-290)
out, skip, page = [], False, 0
for t in L:
    if t.startswith("@@PAGE"):
        page = int(t.split()[1]); continue
    s = t.strip()
    if not s or page > 290:
        continue
    m = re.match(r"^Passage\s*(\d+)\s*:\s*(.*)$", s)
    if m:
        skip = bool(re.search(r"solution", m.group(2), re.I))
        if not skip:
            out.append("\n### " + s)
        continue
    if s.startswith("Verbal CAT"):
        skip = False; out.append("\n\n######## " + s); continue
    if skip or INTRO.match(s):
        continue
    out.append(s)
open(SP + r"\reading.txt", "w", encoding="utf-8").write("\n".join(out))

# ---- 2022-2024 (pages 291-515)
SLOTS = {291: "2022 S1", 316: "2022 S2", 341: "2022 S3", 366: "2023 S1", 391: "2023 S2",
         416: "2023 S3", 441: "2024 S1", 466: "2024 S2", 491: "2024 S3"}
out, page, prevq, newpage = [], 0, False, False
for t in L:
    if t.startswith("@@PAGE"):
        page = int(t.split()[1])
        if page in SLOTS:
            out.append("\n\n######## " + SLOTS[page])
        newpage = True; continue
    s = t.strip()
    if page < 291 or not s:
        continue
    if re.match(r"^(The passage below is accompanied|passage, choose the best|choose the best answer|each question|"
                r"question\.$|Based on the passage, choose|CAT 20\d\d .*Verbal|Verbal Ability|Comprehension$|"
                r"Download|Original CAT)", s, re.I):
        continue
    if re.match(r"^Qn\s*\d+", s):
        out.append("\n" + s); prevq = True; newpage = False; continue
    if newpage and prevq and not re.match(r"^[A-D]\.", s):
        out.append("\n### PASSAGE"); prevq = False
    newpage = False
    out.append(s)
open(SP + r"\reading2.txt", "w", encoding="utf-8").write("\n".join(out))
`

### C.3 stats.py (classifier + shape statistics)
`python
import re, json, sys, statistics as st
from collections import Counter, defaultdict

SP = sys.argv[1]
TERM = re.compile(r"[.?!\"'”’)\]…:]\s*$")

def merge(lines):
    paras = []
    for l in lines:
        l = l.strip()
        if not l:
            continue
        if paras and not TERM.search(paras[-1]):
            paras[-1] += " " + l
        else:
            paras.append(l)
    return paras

def wc(s):
    return len(re.findall(r"[A-Za-z][A-Za-z’'\-]*", s))

passages = []  # dict(year, text_paras, stems)

# ---- 2017-2021
cur_year = None
cur = None
mode = None
for line in open(SP + r"\reading.txt", encoding="utf-8").read().split("\n"):
    m = re.match(r"^######## Verbal CAT (\d{4})", line)
    if m:
        cur_year = int(m.group(1)); mode = None; continue
    if cur_year is None or cur_year > 2021:
        continue
    m = re.match(r"^### Passage (\d+):\s*(.*)$", line)
    if m:
        rest = m.group(2).strip()
        if rest.startswith("Questions") or rest == "":
            mode = "q"; continue
        cur = {"year": cur_year, "title": rest, "plines": [], "qtext": []}
        passages.append(cur); mode = "p"; continue
    if mode == "p":
        if re.match(r"^Q1\.", line):
            mode = "q"
        elif line.startswith("Answer the question") or not line.strip():
            continue
        else:
            cur["plines"].append(line); continue
    if mode == "q" and cur is not None:
        cur["qtext"].append(line)

# ---- 2022-2024
year = None
cur = None
mode = None
for line in open(SP + r"\reading2.txt", encoding="utf-8").read().split("\n"):
    m = re.match(r"^######## (\d{4}) S\d", line)
    if m:
        year = int(m.group(1)); mode = "await"; continue
    if line.startswith("### PASSAGE") or (mode == "await" and line.strip() and not line.startswith("Qn")):
        cur = {"year": year, "title": "", "plines": [], "qtext": []}
        passages.append(cur); mode = "p"
        if not line.startswith("### PASSAGE") and not line.startswith("Access ALL"):
            cur["plines"].append(line)
        continue
    if re.match(r"^Qn\s*\d+", line):
        mode = "q"; cur["qtext"].append("@@Q"); continue
    if mode == "p":
        if line.strip() and not line.startswith("Access ALL"):
            cur["plines"].append(line)
    elif mode == "q":
        cur["qtext"].append(line)

def stems_1721(qlines):
    txt = " ".join(qlines)
    parts = re.split(r"(?:^|\s)Q\s?\d+\s?\.?\s*(?=[A-Z\"“'‘])", txt)
    out = []
    for p in parts[1:]:
        s = re.split(r"(?:^|\s)A[\.\)]\s", p, maxsplit=1)[0]
        out.append(s.strip())
    return out

def stems_2224(qlines):
    out = []
    blocks = " ".join(qlines).split("@@Q")
    for b in blocks[1:]:
        b = re.sub(r"Correct Answer:.*$", "", b)
        s = re.split(r"(?:^|\s)A[\.\)]\s", b, maxsplit=1)[0]
        out.append(s.strip())
    return out

RULES = [  # (type, regex) first match wins
    ("reported_view_vs_author", r"critics would argue|differing views|disagree with each other|perception of|characterise dr|view of the author of this|according to rappaport|in dr\. thompson|views mentioned|criticises .*essay for|critiques schiller|faults deneen|the author of the passage faults"),
    ("stance_evaluation", r"author sees|laments|in the author.s opinion|author is apprehensive|tone"),
    ("keyword_or_flow_set", r"set of (key)?words|keywords|sequence|sets of concepts|set of concepts|set of terms|sets of words|odd pair"),
    ("tone_attitude", r"\btone\b|attitude|being:?$|author is being|sarcastic|best described as being"),
    ("negated_support_if_false", r"if false"),
    ("weaken_undermine", r"weaken|undermine|invalidate|negate|contradict|inappropriate|call into question"),
    ("strengthen_support", r"strengthen|supporting the arguments|support(s|ed)? (the|his|this)|complement|best support|supported by which"),
    ("application_scenario", r"scenario|hypothetical|most similar|closest in meaning|closest to that|analogous|akin to|if a trader|if the author .*write|which of the following teams|product plans|new food brand|decision for|would a chinese museum|following copies|examples of human-centered|similar except|would be most successful|style of research|none of the following statements can be seen as similar|at a conference|french ethnographer|comes closest|conflating consumption|study the culture|most likely to be the view"),
    ("author_would_support", r"(most|least)? ?likely to (support|agree|disagree|endorse|advise|cite)|would (most )?(strongly )?(support|approve|like|agree)|is in favour|most supportive|least likely to|author .* support|unlikely to disagree|endorses"),
    ("except_or_not_scan", r"\bexcept\b|\bnot\b|cannot|least|none of the following|only reason not"),
    ("purpose_of_part", r"purpose of|in order to|to illustrate|refers? to .* to|mention(s|ed)? .* to|uses? .* (to|in order)|to (show|demonstrate|argue|highlight|point out)|why does the author|the example|examples? of|reference to"),
    ("meaning_paraphrase", r"means?\b|meaning|best (explains|expresses|captures|reflects|conveys|explicates) (this|the (claim|sense|point|argument|meaning)|the larger)|suggested by the sentence|suggests that|refer to|trying to communicate|best describes the word|phrase|term|in the sense|interpretation|sense of"),
    ("thesis_main_idea", r"central (idea|point|theme)|main (idea|argument|conclusion|point|objective|purpose|concern|message|goal)|primary purpose|best (sums|describes what|summarises|represents the essence)|gist|overall argument|essence|passage is (about|trying)|what the passage is|author'?s argument|fundamental conclusion|the passage outlines|claim that"),
    ("inference", r"infer|implied|implies|deduce|conclu|valid|can be regarded as true|true"),
    ("detail", r"according to|author (claims|lists|ascribes|faults|critiques|criticises|believes|says|suggests|notes|identifies|questions|discusses)|the text|reason|why|because"),
]

def classify(stem):
    s = stem.lower()
    for t, rx in RULES:
        if re.search(rx, s):
            return t
    return "other"

rows = []
for p in passages:
    paras = merge(p["plines"])
    words = sum(wc(x) for x in paras)
    p["paras"] = paras
    p["words"] = words
    p["para_words"] = [wc(x) for x in paras]
    p["stems"] = stems_1721(p["qtext"]) if p["year"] <= 2021 else stems_2224(p["qtext"])
    p["stems"] = [s for s in p["stems"] if len(s) > 25 and not re.match(r"^(Q\s?\d+\s*)+$", s)]
    p["types"] = [classify(s) for s in p["stems"]]

print("passages:", len(passages))
by_year = defaultdict(list)
for p in passages:
    by_year[p["year"]].append(p)
print("\nYEAR  n  words(med)  paras(med)  q/passage")
for y in sorted(by_year):
    ps = by_year[y]
    print(y, len(ps), int(st.median([p["words"] for p in ps])), st.median([len(p["paras"]) for p in ps]),
          round(st.mean([len(p["stems"]) for p in ps]), 2))

allp = [p for p in passages if p["words"] > 350]
pc = Counter(len(p["paras"]) for p in allp)
print("\nparagraph count distribution (passages >350w):", sorted(pc.items()))
print("median words/para:", st.median([w for p in allp for w in p["para_words"]]))
def cls(w):
    return "S" if w < 60 else "M" if w < 110 else "L" if w < 160 else "XL" if w < 210 else "XXL"
cc = Counter(cls(w) for p in allp for w in p["para_words"])
print("para length classes:", dict(cc))
tot = sum(cc.values())
print({k: round(v / tot, 3) for k, v in cc.items()})
xxl = [p for p in allp if any(w >= 210 for w in p["para_words"])]
print("passages with any para >=210w:", len(xxl), "of", len(allp))

tc = Counter(t for p in passages for t in p["types"])
n = sum(tc.values())
print("\nquestion types (n=%d):" % n)
for t, c in tc.most_common():
    print(f"  {t:28s} {c:4d}  {c/n:.1%}")

# except/negation prevalence
neg = sum(1 for p in passages for s in p["stems"] if re.search(r"\bEXCEPT\b|\bNOT\b|\bnot\b|cannot|least|if false|none of", s))
print("\nstems with EXCEPT/NOT/least/if-false/none-of:", neg, f"{neg/n:.1%}")
dbl = sum(1 for p in passages for s in p["stems"] if re.search(r"if false|none of the following.*except|not .*except|unlikely to disagree|not inconsistent|not contradict|least likely to (agree|endorse)|would not undermine", s, re.I))
print("double/triple-negation stems:", dbl, f"{dbl/n:.1%}")

by_era = {"2017-19": [p for p in passages if p["year"] <= 2019], "2020-24": [p for p in passages if p["year"] >= 2020]}
for k, ps in by_era.items():
    c = Counter(t for p in ps for t in p["types"]); m = sum(c.values())
    print(k, {t: f"{v/m:.0%}" for t, v in c.most_common()})

json.dump([{k: v for k, v in p.items() if k not in ("plines", "qtext")} for p in passages],
          open(SP + r"\pyq_stats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(SP + r"\stems_classified.txt", "w", encoding="utf-8") as f:
    for p in passages:
        for s, t in zip(p["stems"], p["types"]):
            f.write(f"{p['year']}\t{t}\t{s[:160]}\n")
`
