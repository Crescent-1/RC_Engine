# Revision Changelog — post-0823 set (9 papers)

Sources: `exported_rc_sets/` root (0044, 0064, 0065, 0066) and `exported_rc_sets/flagged_similar/` (0046, 0047, 0067-elite, 0067-hard, 0068). Originals unmodified.

All nine now clear the four requirements: passage 500–550 words, 8 distinct questions with verified keys, comparable option lengths, no assumption question.

---

## Passage-length fixes

| Paper | Before | After | What changed |
|---|---|---|---|
| RC-MEDIUM-260824-0044 | 563 | **544** | Three trims, none touching an option: the Gulf-heat clause shortened; "in a discussion of loss and damage" → "in a loss-and-damage discussion"; the trailing "and which the smallest members have not granted" cut (Q3's key rests on "which it never was," which stays). Australia, the fleets, the concessional-finance line, Malawi, the East Africa/Yemen/Caribbean list and the ledger image were all protected — each is load-bearing for a question. |
| RC-HARD-260824-0066 | 551 | **545** | "the rooming house **on the west side of Providence**" → "the rooming house". Providence appears in no question or option. |
| RC-ELITE-260825-0068 | 552 | **549** | "A quarto notebook**, half-calf,** catalogued…" and "Proverbs, some in Latin**, most not**." Both decorative; the store-genre evidence still rests on the hymn leaves, the proverbs and the tonnages, all of which questions depend on. |
| RC-HARD-260828-0067 | 553 | **546** | The petition list trimmed from three items to two ("for a marriage that had gone quiet" cut). No question references it. |

No key answer changed as a result of any passage edit.

---

## Question replacements

### RC-MEDIUM-260825-0046 — Q7 replaced
**Out:** "why does the term 'spinoff' begin to strain" → (D) "No familiar characters appear and the plot is largely self-contained." That is the same objection Q8 asks about as a described-but-not-endorsed position; Q8's answer restated Q7's.

**In:** **Application / analogous case** — the type the paper lacked. Answer **(C)**: a series following the rival firm glimpsed in the parent, its cases turning on a statute the parent rewrote — both stated conditions met at once. Distractors: a continuation returning to the parent's centre (category_slip, ruled out by "Not a continuation. Not a reunion."); shared craft and styling (terminological_twin — the "borrowed livery" the author dismisses); a marginal figure owing nothing to an altered history (missing_link — the author requires both conditions).

Q5 still works the same objection from a different angle, but as phrase-in-context it tests a different skill and stays.

### RC-MEDIUM-260828-0047 — Q7 replaced
**Out:** "Which one of the following would best **license the inference** the author draws from restorative justice mediation practice?" — the assumption-family stem, third appearance across the two batches. Its own key rationale gave the type away: "supplies the missing evidential link."

**In:** **Application / parallel situation** — absent from the paper. Answer **(A)**: a landlord who calls a tenants' meeting, speaks first about his own regret, and leaves the repairs unscheduled — regret routed through an audience, speaker framing first, appetite for resolution discharged without adjustment to procedure or budget. Distractors: restitution with no audience (causal_inversion); a private admission (category_slip — privately what is repaired is a relation); an apology found insincere (framework_import — the passage holds sincerity constant).

---

## Option-length fixes

**Hard failures repaired:**

- **RC-ELITE-260824-0065 Q2** — was 1.42× (correct 118 chars against 167). (A) and (B) tightened, (C) expanded. Now **1.10×**.
- **RC-ELITE-260824-0067 Q8** — was 1.41× (correct 81 against 114). (B) expanded, (C) and (D) tightened. Now **1.13×**.

**Borderline repaired:**

- **RC-HARD-260828-0067 Q3** — was 1.34× with the correct answer longest. (B) shortened, (A) and (C) lengthened. Now **1.06×**.
- **RC-MEDIUM-260825-0046 Q3** — was 1.34×. Now **1.18×**.

**Systematic length tell repaired.** Two papers had the correct answer as the strict longest option in 5 of 8 questions:

- **RC-ELITE-260825-0068** — correct was longest in Q1–Q5, a run of five, and never shortest anywhere. Distractors padded in Q1, Q2, Q4 and Q5; correct answer tightened in Q2 and Q4. Now **1 of 8**.
- **RC-HARD-260824-0064** — correct was longest in Q3, Q4, Q5, Q6, Q8. This paper *passed* all four requirements, so the change is discretionary; the tell was strong enough to be worth removing. Now **1 of 8**.

Every wording change here preserves the option's meaning and its elimination tag — only length was adjusted.

---

## Verification performed after revision

- **Word counts:** 512 / 525 / 533 / 535 / 536 / 544 / 545 / 546 / 549 — all inside 500–550, none within 2 words of a boundary.
- **Assumption stems:** zero matches for "license the inference" across all nine.
- **Key integrity:** every stated correct letter has exactly one CORRECT line, and every question carries all four option rationales.
- **Option ratios:** worst per paper now 1.10–1.29×; nothing above 1.30. Both replacement questions sit at 1.05×.
- **Length position:** correct-is-longest now ≤3 of 8 in every paper (was 5 in two), with no runs.
- **Answer-letter distribution:** 0046 D C C B C B C B and 0047 A D C A D B A B — no letter runs beyond two.
- Every revised paper was re-solved end to end; all keys match.

---

## Left as they are — flagged, not changed

- **RC-HARD-260824-0064 reuses a source you have already shipped.** It is built from *"A Different Kind of Populist"* (Commonweal), the same article behind **RC-ELITE-260821-0048** in the selected-10. Different passages and different arguments, so nothing here is wrong — but if both reach the same candidate pool it is a collision, and that is a call for you rather than an edit.
- **RC-ELITE-260824-0065 scores 6.8**, the only paper here under the 7.0 judge bar used in `review_shippable/_TRIAGE.txt`. Outside the four requirements, so untouched.
- **RC-ELITE-260824-0067 Q1/Q5** pair a gist question with a primary-purpose question. They are distinguishable — Q1 concerns the behaviour, Q5 the discipline — so both stay, but it is the same pairing that made 0034 redundant in the previous batch.
- **Two-weakener papers:** 0044 (Q4, Q5) and 0067-hard (Q7, Q8) each carry two weaken questions aimed at different targets. Legitimate, but it costs each paper a question type.
- **The screen column is unreliable for 0044, 0064 and 0066** — the root and `flagged_similar` copies differ only in `Screen: green` vs `Screen: red`, with identical scores, F1, timestamps and bodies. The revisions here are built from the root copies.
