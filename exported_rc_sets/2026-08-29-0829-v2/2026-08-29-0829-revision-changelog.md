# Revision Changelog — 0829 set (5 papers)

Sources: `exported_rc_sets/` root. Originals unmodified.

All five now clear the four requirements: passage 500–550 words, 8 distinct questions with verified keys, comparable option lengths, no assumption question.

---

## Passage-length fixes

| Paper | Before | After | What changed |
|---|---|---|---|
| RC-HARD-260829-0068 | 568 | **549** | Four trims, none touching an option: "A copied excerpt sits in front of me now" → "The excerpt in front of me"; the redundant gloss "Observation, then consequence." cut (the preceding sentence already says it); "or watched the fever's timing" cut; "the shepherd brought in" cut and the verdict list trimmed from three items to two. The correspondence clause Q5 depends on ("also learned by heart and also did not devise") was protected, as was the ruled-line imagery Q4 turns on. |
| RC-ELITE-260829-0069 | 566 | **545** | One cut: the closing flourish of paragraph 1, "It has the clean indifference of any construction that works because its terms are defined in advance and cannot argue back." Pure ornament — no question or option references it, and the parallax sentence Q8 depends on is untouched. |
| RC-HARD-260829-0069 | 561 | **543** | "He says it kindly and he says it clearly." (redundant after "Not coldly."), "squares and circles," and the aside "— less visibly at first —". The graph-paper image is preserved intact, since Q8 closes on it. |

No key answer changed as a result of any passage edit. The two medium papers were already in band at 529 and needed no length work.

---

## Question replacements

### RC-HARD-260829-0069 — Q7 replaced
**Out:** "The passage as a whole is best understood as an attempt to" → (C) *unsettle a settled moral verdict…* This duplicated Q1's primary-purpose question, whose answer (A) says the same thing — trace the two jobs, question the resulting verdict.

**In:** **Weaken** — the type the paper lacked. Answer **(B)**: couples' decisions prove unaffected by the order in which risk figures and disease descriptions are presented. The final paragraph's whole claim is that ordering and emphasis steer even under non-directiveness; if sequence provably makes no difference, the dinner-host argument collapses. Distractors: adoption timing (scope_inflation), an exception in Reed's own era (adjacent_answer), session-time allocation (half_truth — that *is* one of the steering choices, so it confirms rather than damages).

### RC-MEDIUM-260829-0049 — Q6 replaced
**Out:** "The primary purpose of the passage is to" → (A) *caution that a real improvement has left an older habit intact.* This duplicated Q1's central-idea answer (B), which makes the same claim.

**In:** **Application / analogous case** — absent from the paper. Answer **(B)**: a hospital that renames its ward closures "service reconfiguration", consults widely, and shuts the wards on schedule. That is paragraph 4 exactly — impeccable vocabulary and real consultation conducted *around* the ethical problem rather than settling it. Distractors: a maintenance-cost comparison (level_confusion), a scheme abandoned after objections (causal_inversion — that is the reversal the author credits), open removal without the euphemism (category_slip — the pattern requires the honourable language).

---

## Option-length fixes

**Six hard failures repaired.** Every one had the correct answer sitting at the extreme:

| Paper | Q | Before | After |
|---|---|---|---|
| MEDIUM-0049 | Q3 | 1.55× (correct longest, 181 vs 117) | **1.21×** |
| HARD-0069 | Q1 | 1.49× (correct **shortest**, 100 vs 149) | **1.11×** |
| ELITE-0069 | Q3 | 1.48× (correct longest) | **1.18×** |
| MEDIUM-0048 | Q1 | 1.45× (correct longest, 116 vs 80) | **1.10×** |
| ELITE-0069 | Q5 | 1.42× (correct longest) | **1.12×** |
| MEDIUM-0049 | Q5 | 1.35× (correct longest) | **1.09×** |

Worst spread anywhere in the set is now **1.29×**.

**The systematic tells are gone.** RC-HARD-260829-0069 had the correct answer as the shortest option in **7 of 8 questions** — a candidate picking the shortest every time scored 7/8. Six questions were rebalanced (Q1, Q2, Q3, Q6, Q8 plus the Q7 replacement); it now sits at 1 of 8. RC-ELITE-260829-0069 went from correct-is-longest in 5 of 8 to 1 of 8.

Every wording change preserves the option's meaning and its elimination tag — only length moved.

---

## Verification performed after revision

- **Word counts:** 529 / 529 / 543 / 545 / 549 — all inside 500–550, none within a word of a boundary.
- **Assumption stems:** zero matches across all five (this set never had any — noted here as a regression check).
- **Key integrity:** every stated correct letter has exactly one CORRECT line, and every question carries all four option rationales.
- **Option ratios:** worst per paper 1.21–1.29×; both replacement questions sit at 1.06× or better.
- **Length position:** correct-is-longest and correct-is-shortest are now ≤3 of 8 in every paper, with no runs.
- **Answer-letter distribution:** 0069-hard A B B C B A B D and 0049 B C D B D B B C — no letter runs beyond two.
- Every revised paper was re-solved end to end; all 40 keys match.

---

## Left as they are — flagged, not changed

- **RC-HARD-260829-0069 scores 7.0**, exactly at the floor used in `_TRIAGE.txt`, and **RC-MEDIUM-260829-0049 has F1 0.68**, the weakest in any batch. **RC-ELITE-260829-0069 has novelty 0.478**, the lowest single score in the corpus. All three sit outside the four requirements.
- **RC-HARD-260829-0069 Q2 and Q6** are both phrase-in-context items drawn from the same paragraph ("had been carrying two opposed jobs all along" and "a word that changed employers"). They test different phrases and different aspects of the claim, so both stay — but the pairing is worth watching if a third phrase question ever joins them.
- **All five remain `needs_review`.** Nothing here changes a judge score; these are compliance fixes only.
- **The voice profile is untouched** by this work. Markers per paper stay at 4.4 and the reader-directed imperative is still in all five. That is a generator-level problem, addressed in the batch-comparison note rather than here.
