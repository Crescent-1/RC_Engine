# CAT PYQ evidence baseline — corrected

Date: 2026-09-13, Asia/Calcutta. This completes section 2 of
`2026-09-13-cat-pyq-implementation-plan.md` ("Establish trustworthy
baselines"). No engine code, component library, config, prompt, production
data or export was changed. The production DB was opened read-only (SQLite
URI `mode=ro`). No paid model call was made.

**Data:** `2026-09-13-cat-pyq-baseline.json` (text-free: page numbers,
counts and labels only).

**Tools:** `tools/cat_pyq/`. Run order is in §7.

**Where this sits.** This file supersedes the numbers that section 1 lists,
in these three earlier files, which are kept as history:
- `2026-09-13-cat-pyq-engine-analysis.md`
- `2026-09-13-cat-pyq-findings-handoff.md`
- `2026-09-13-cat-pyq-labels.json`

Their per-passage register, family, opening/closing and beat labels are not
re-examined here and still stand as single-reader labels.

---

## 1. Corrections to the earlier documents

| Earlier claim | Corrected | Cause |
|---|---|---|
| Questions per passage 6.3, 5.8, 5.5, 5.8, 4.3 (2017–21) | 4.8, 4.8, 4.8, 4.5, 4.0; 2022–24 4.0. Total **390** (48, 48, 48, 54, 48, 48, 48, 48) | 2IIM's navigation strip ("Q1 Q4 Q5 Q2 Q3") was counted as questions in the first run. The regex share tables had already dropped it (n = 389). One real question (19-1-1) was also lost. Now matches every slot's printed numbering |
| 27% EXCEPT/NOT scans, 37% any negation, 6% double negation | **25.6%** EXCEPT-bearing, **35.6%** any negation operator, **4.1%** multiple negation. For 2020–24: **41.5%**, 6.1% multiple | Task and polarity came from one first-match classifier, and quoted passage text ("doesn't", "not quite alive") was counted as negation. Now scanned independently, quotes stripped, all 390 stems hand-reviewed (§2) |
| Strengthen 2.3% | New-fact strengthen **1.0%**; a separate **consistency** task **3.1%** ("if false…", "not inconsistent", "contradicts the passage") | The two were merged; they need different option contracts |
| Engine plans an early thesis ~10% of the time; CAT 67% early | Engine plans the thesis by **paragraph 2 in 45–53%** of shipped sets (medium 53%, hard 45%, elite 51%). CAT: **74%** of thesis-bearing passages (68% of all 90) | The earlier figure counted *revelation labels*. `_revelation_para` puts "mid", "split" and "distributed" on paragraph 2 of a 4-paragraph plan. Measured by paragraph, the gap is much smaller |
| Engine closes open 28% (health, last 100, mixed tiers) | Planned refusal posture, all shipped sets: **medium 16.7%, hard 30.6%, elite 36.6%**. The realised reading is uncertain (§4) | Mixed-tier window, and planned and realised were not separated |
| "Never stated 2%" added onto a 100% timing row | Separate class: **8 passages (9%) have no thesis** (descriptive surveys and reports); 4 implicit, 78 explicit | Overlapping rows |

Unchanged and re-verified:
- Words and paragraph counts: identical on all 90 passages under the new page-aware parser (within 25 words, same paragraph count).
- The 6–8 paragraph share (37%).
- The negation gap itself. It is **larger** than first stated for 2020–24.

---

## 2. Question-level evidence (n = 390)

Each question has one task label and, independently, one polarity label, with
its operators and a negation mode. `question_records.py` holds the rules. A full
read of every stem produced **73 recorded overrides**, each with a reason:

- 63 task-only corrections;
- 10 cases where a "not" belongs to the asked content rather than the question
  (e.g. "facilities are not fully utilised… because"), 3 of which also correct
  the task;
- plus 2 quote-stripping fixes made in the rules.

No label is unresolved. Two items have source defects in the PDF:
- 18-1-3 Q5: the option marker is misplaced;
- 22-3-2 Q2: two options are both labelled "C".

Their stems are unaffected.

### Polarity

| Polarity | All | 2017–19 (144) | 2020–24 (246) |
|---|---|---|---|
| Affirmative | 251 (64.4%) | 107 (74.3%) | 144 (58.5%) |
| Single negation | 123 (31.5%) | 36 (25.0%) | 87 (35.4%) |
| Multiple negation | 16 (4.1%) | 1 (0.7%) | 15 (6.1%) |

**Operators.** 100 questions carry EXCEPT or "only … NOT". The remaining
negations are:

| Operator | Count |
|---|---|
| not / cannot | 22 |
| least / unlikely | 11 |
| if false | 6 |

The EXCEPT-bearing 100 include 5 "none of … EXCEPT", 2 EXCEPT with
"unlikely", and 1 "if false … EXCEPT".

Excluding questions whose only operator is "least" leaves 130 negated
(33.3%). Reviewers who do not count "least" as negation should use that figure.

### Task, and how often CAT negates it

| Task | n | Share | Negated | Engine equivalent |
|---|---|---|---|---|
| detail | 96 | 24.6% | 57 (59%) | detail_check |
| inference | 62 | 15.9% | 30 (48%) | contextual_inference |
| meaning (phrase, referent, paraphrase) | 37 | 9.5% | 1 (3%) | phrase_in_context / contextual_inference |
| gist (passage or paragraph main idea/purpose) | 32 | 8.2% | 0 | thesis / primary_purpose |
| purpose_of_part | 31 | 7.9% | 2 (6%) | evidence / structural_function |
| reported_view | 24 | 6.2% | 7 (29%) | author_vs_reported |
| weaken (new fact) | 24 | 6.2% | 6 (25%) | weaken / undermine_thesis |
| author_endorse | 23 | 5.9% | 12 (52%) | none |
| application | 23 | 5.9% | 9 (39%) | application |
| consistency | 12 | 3.1% | 10 (83%) | none |
| keyword_set | 9 | 2.3% | 0 | none |
| tone_stance | 8 | 2.1% | 0 | stance |
| argument_evaluation (least depth, direct extension, over-emphasis) | 4 | 1.0% | 2 | none |
| strengthen (new fact) | 4 | 1.0% | 3 | strengthen |
| relation_pair (odd pair out) | 1 | 0.3% | 0 | none |

**Implication for plan §4.1.** CAT negates support scans (detail and
inference), author endorsement and application often. It essentially never
negates gist, meaning, keyword or tone questions. The plan's first stage
(support scans, then negative application) matches where CAT puts its
negations. Gist, meaning, keyword and tone slots should stay affirmative.
Consistency questions are mostly negated, and most of CAT's multiple
negations live there; they belong in the later double-negation phase.

---

## 3. Thesis evidence, one rubric

The rubric for both corpora:

- **kind:**
  - *explicit*: the central claim is stated as a proposition;
  - *implicit*: recoverable, never stated as one;
  - *none*: a survey or report that advances no central claim.
- **first_visible**: the paragraph where a reader could first state the claim.
- **fully_stated**: the paragraph where it is stated in full.
- **"Early"** means first_visible ≤ 2, whatever the revelation label says.

For 17-2-2 and 17-2-3, a trustworthy 2IIM answer key for the gist question
anchored the claim.

**PYQ (90):**
- Kind: explicit 78, implicit 4, none 8.
- Early: **61 of 82 thesis-bearing passages (74.4%)**, which is 67.8% of all 90.
- 2017–19: 75.0%; 2020–24: 74.1%.

**Engine, planned** (stored blueprint, all shipped sets, client AA):

| Tier | Sets | Planned thesis paragraph ≤ 2 | Timing labels |
|---|---|---|---|
| medium | 36 | 52.8% | early 11%, mid 17%, late 17%, never_stated 17%, distributed 14%, split 11%, retrospective 8%, penultimate 6% |
| hard | 49 | 44.9% | mid 20%, late 16%, penultimate 14%, never_stated 14%, split 10%, retrospective 10%, distributed 6%, early 4%, early_hidden 4% |
| elite | 41 | 51.2% | reference only; unchanged by the plan |

**Engine, realised** (compliance read): paragraph ≤ 2 in medium 57.1%
(n = 35), hard 51.1% (47), elite 51.4% (35).

**This read is not blind.** `compliance.py:121-122` gives the auditor
"PLANNED THESIS VISIBILITY: paragraph N". In a 12-set check (§5), its answer
equalled the planned paragraph in 8 of 12.

**Blind qualitative check** (my rubric, plan values hidden until after
labelling): the 6 most recent medium and 6 most recent hard shipped passages.
**10 of 12 were early.** In 4 of the 5 sets planned late or never-stated
(M-260912-0068, M-260907-0066, M-260907-0065, H-260907-0087), the renderer
made the claim visible in paragraph 1–2, earlier than planned.

**Reading.**
- On realised prose, early thesis visibility is **not** an established gap for
  medium or hard. If anything, the renderer states the claim earlier than its
  plan.
- The plan's provisional "40% explicit-early" objective (§1, §5.2) should not
  drive revelation weights until a blind, plan-free extraction on a larger
  sample says otherwise.
- Twelve sets is directional, not a rate.

---

## 4. Closing posture

| Tier | Planned refusal posture | Compliance posture guess: refusal | Not read |
|---|---|---|---|
| medium | 16.7% (6/36) | 19.4% | 1 |
| hard | 30.6% (15/49) | 30.6% | 2 |
| elite | 36.6% (15/41) | 26.8% | 6 |

**PYQ comparison.** 2 of 90 passages close genuinely open. 8 are neutral
surveys; they are neither committed nor refusals and are counted separately.

**The realised refusal rate is uncertain.** In the 12-set check the posture
guess and my reading disagreed on 3 closes:
- H-260912-0093: guess refusal_dissolved; my reading is a committed reframe.
- H-260912-0092: guess refusal_dissolved; my reading is a committed "break
  locatable only afterward".
- H-260912-0089: planned resolution_qualified, guess refusal_suspended, and I
  read it as a hand-over close.

The planned shares above are exact. Realised shares need a blind read before
they set a target.

---

## 5. Negation on shipped engine stems (same scanner)

`engine_baseline.py` runs `question_records.classify_polarity` over the
first-occurrence Q1..Q8 stems of every shipped set:

| Tier | Stems | Negated (any) | Per set | Planned except_scan slots per set |
|---|---|---|---|---|
| medium | 278 | 6.8% | 0.53 | 0.31 |
| hard | 368 | 7.3% | 0.55 | 0.35 |
| elite | 304 | 6.9% | 0.51 | 0.29 |

CAT 2020–24 runs at 41.5% of stems, about 1.7 negated questions per
4-question passage.

**Reading.**
- This is the one gap that holds under every instrument used so far.
- The engine's realised negation (~7%) is higher than its planned except_scan
  share (~4%). Some affirmative slot types evidently come out with negated
  wording already; per-stem review should precede any quota.
- Early-set stems were 6-question; set sizes are counted as found.

---

## 6. What the plan should carry forward

1. **Negated question forms (plan §4).** Priority confirmed and strengthened.
   Enable negation where CAT negates (detail, inference, application,
   author_endorse). Leave gist, meaning, keyword and tone affirmative.
2. **A separate `consistency` task.** Plan it separately from new-fact
   strengthen/weaken. It is where most CAT multiple negation lives, so it
   belongs in the later double-negation phase.
3. **Thesis timing (plan §5.2).** Do not activate early-thesis weights yet.
   The measured gap is small on plans and absent in the blind sample.
   Prerequisite: a blind, plan-free thesis and closure read (no
   "PLANNED THESIS VISIBILITY" in the prompt) over, say, 30 medium and hard
   shipped passages. That is a paid extractor run and needs authorisation;
   alternatively, a larger manual sample.
4. **Refusal (plan §1, §5.2).** The planned shares are reliable; realised ones
   are not. Plan-level targeting still makes sense for hard (30.6% planned).
   Measure realised closure blind before tuning.
5. **Neutral exposition.** Track it as its own class. 9% of PYQs have no
   thesis, and no engine family supports that close.

---

## 7. Reproduce

```bash
python tools/cat_pyq/parse_pyq.py "C:/Users/anshu/Downloads/CAT RC PYQ 2017-2024.pdf" "C:/Users/anshu/rc_data/cat_pyq_private"
```
```bash
python tools/cat_pyq/question_records.py "C:/Users/anshu/rc_data/cat_pyq_private/pyq_parsed.json" "C:/Users/anshu/rc_data/cat_pyq_private/question_records.json" "C:/Users/anshu/rc_data/cat_pyq_private/question_review.tsv"
```
```bash
python tools/cat_pyq/engine_baseline.py rc_pipeline.db "C:/Users/anshu/rc_data/cat_pyq_private/engine_baseline.json"
```
```bash
python tools/cat_pyq/build_baseline.py "C:/Users/anshu/rc_data/cat_pyq_private/pyq_parsed.json" "C:/Users/anshu/rc_data/cat_pyq_private/question_records.json" "C:/Users/anshu/rc_data/cat_pyq_private/engine_baseline.json" 2026-09-13-cat-pyq-baseline.json
```

- **Private outputs.** `parse_pyq.py` and the review TSV refuse to write inside
  the repository, because they carry PYQ text.
- **Engine baseline reproducibility.** The engine baseline reflects the DB at
  run time: all shipped AA sets as of 2026-09-13, code revision `23e3d49`, no
  uncommitted `rc_engine/` changes. Re-running after new ships will change it.
- **Tests.** `tests/test_cat_pyq_tools.py` pins the classifier corrections.

---

## 8. Limits

- **Single reader.** One reader for task overrides, thesis rubric and the
  12-set check. The rubric and every override are in the JSON and the scripts
  for audit.
- **Engine realised thesis and closure** come from a plan-anchored auditor.
  The blind check is 12 sets.
- **PYQ text quality.** The PYQ text is a third-party compilation, with some
  typos, excerpting and one 2IIM answer-key misalignment risk. Keys were used
  only where their count matched the questions.
- **Client scope.** Client AA only; mixed providers; plan versions pooled.
  `blueprint_json` carries `voice_plan_version` if a split is needed later.
