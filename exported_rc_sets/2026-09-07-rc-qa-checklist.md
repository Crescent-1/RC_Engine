# RC Paper QA Checklist

The standing check, as it has accumulated across Weeks 5–8. Six rules you stated, plus the thresholds and structural checks that were added when a defect got through the stated rules.

---

## A. The six rules

| # | Rule | Threshold applied | Origin |
|---|---|---|---|
| **R1** | Passage length | **500–550 words** inclusive | Stated |
| **R2** | Eight different questions, each with correct reasoning in the key | Exactly 8; no two of the same type; every key answer independently confirmed | Stated |
| **R3** | Options of comparable length | See B below | Stated |
| **R4** | No assumption question | Zero matches on the stem patterns in C | Stated |
| **R5** | Every option ends with a full stop | Zero exceptions | Feedback, Week 7 |
| **R6** | Every option's first letter is capitalised | Zero exceptions | Feedback, Week 7 |

---

## B. Option length — three separate tests

"Comparable length" turned out to need three tests, not one. A paper can pass the spread test and still be broken.

| Test | Threshold | What it catches |
|---|---|---|
| **B1. Spread** — longest ÷ shortest option, per question, in characters | **< 1.30×** | One option conspicuously out of line |
| **B2. Correct-is-longest**, counted per paper | **≤ 3 of 8** | "Pick the longest" heuristic |
| **B3. Correct-is-shortest**, counted per paper | **≤ 3 of 8** | "Pick the shortest" heuristic |

**B2 and B3 are the ones that matter most, and they are the ones nothing upstream catches.** Week 8 had three papers where the correct answer sat in the same length position in *every* question — 6 of 6 — making 18 questions answerable without reading the passage. All three scored 8.4–8.6 from the judge.

Measure in characters, excluding the `(A) ` prefix.

---

## C. Assumption-stem patterns

Match case-insensitively against **question stems only** (the word "assumption" appears legitimately inside elimination rationales):

- `license the inference`
- `unstated assumption` ← added Week 8
- `presuppose` / `presupposition`
- `takes for granted`

Both forms have now appeared: "would best **license the inference**" (0052, 0056, 0047, 0050) and "depends on which **unstated assumption**?" (0032, 0025). Assume more variants exist.

---

## D. Answer-key integrity

Structural, cheap to automate, catches malformed output:

- [ ] Exactly 8 `Qn — Correct answer: (X)` blocks
- [ ] Each block has exactly four rationale lines, one per option letter A–D
- [ ] Exactly one line marked `CORRECT`, and its letter matches the stated answer
- [ ] No stray `CORRECT` on a distractor line
- [ ] Every phrase quoted inside the key still appears verbatim in the passage — **essential after any passage trim**

---

## E. Answer-letter distribution

- [ ] Aim for **2/2/2/2** across A–D; never allow a letter to be absent
- [ ] No run of the same letter longer than **two**

Worth watching when questions are added or options reordered — rebalancing option lengths is exactly when clustering gets introduced by accident.

---

## F. Question-type distinctness (R2, the part that isn't a count)

Eight questions is not eight *different* questions. The recurring failure is duplication of near-identical types.

**Known generator habit:** emitting both a **central-idea** and a **primary-purpose** question in the same paper. Seen in six consecutive batches. Not always fatal — it passes if the purpose option describes rhetorical *method* rather than restating the claim — but always worth a look.

Also check for two phrase-in-context items on different phrases (usually fine), and two counterfactual/removal items (usually fine).

**Types available**, useful when replacing or adding:

central idea/gist · primary purpose · inference · detail · EXCEPT-detail · phrase or vocabulary in context · function of an example · role of a paragraph · paragraph-removal counterfactual · strengthen · weaken/undermine · application or analogous case · tone/attitude/posture · described-but-not-endorsed · likely-to-disagree · structural function of a sentence

---

## G. Solving discipline

- [ ] **Solve every question before reading any key.** Not after, not alongside.
- [ ] Compare, and treat any mismatch as a genuine dispute to adjudicate rather than a personal error — of four disputes so far, all four resolved in the key's favour, but each one surfaced a real weakness in the item.
- [ ] **Newly written questions get solved cold by someone who has not seen the key.** This caught three real defects in the ten Week-8 additions that self-review had missed.

---

## H. Verification after any edit

- [ ] Word counts, spreads and length positions re-measured **from the rebuilt file**, not the source
- [ ] Every retained question keeps its original correct letter — check programmatically
- [ ] Passage diffs read word by word; confirm no removed text is referenced by any question, option or rationale
- [ ] docx: `validate.py` passes, `python-docx` round-trip gives 8 questions / 32 options / 8 key headers, paragraph count matches
- [ ] At least one file rendered to PDF and looked at

---

## I. Voice and sameness (separate track)

Not part of the six rules, but the metric that caught the house-voice regression:

| Metric | Target | Notes |
|---|---|---|
| **Marker density** — count of 7 house tics per paper | **< 2 of 7** | "survives", "nobody", reader-directed imperative, explicit steelman, first-person "I", cost/price metaphor, negation pair |
| **Intra-batch function-word cosine similarity** | **< 0.88** | Mean pairwise. 0.9219 was the worst batch, 0.8955 the best |

The novelty channel cannot see intra-batch template convergence — these two can.

---

## What the judge score does *not* measure

Worth stating plainly, because it has now misled three times:

- **Option balance.** 0052 scored 9.2 and was `approved` with a 1.36× spread and the correct answer shortest. Three Week-8 papers scored 8.4–8.6 with perfect length tells.
- **Compliance generally.** In Week 8 the only fully clean paper had the *lowest* score in the batch (7.6); the highest (8.8) failed.

Treat the score as orthogonal to this checklist, not as a pre-filter for it.

---

## Cheapest wins if any of this moves into the generator

1. **B2/B3 length-position check** — four lines, would have caught the worst defect found so far.
2. **The assumption-stem regex**, with both known forms.
3. **R5/R6 formatting** at export time — two lines, and it stops a recurring 200+ violation cleanup every week.
4. **The central-idea + primary-purpose pair** as a warning, not a block.
