# RC Compliance Check — ELITE 0071, 0072 and MEDIUM 0052

All three were found in `flagged_similar/`, generated 1 Sept between 15:28 and 15:36 IST — a later run than the five checked earlier that day (11:04–11:55). All 24 questions solved independently before the keys were read.

---

## Verdict table

| RC ID | Score / F1 | Words (R1) | 8 distinct Qs (R2) | Option length (R3) | No assumption Q (R4) | Verdict |
|---|---|---|---|---|---|---|
| RC-ELITE-260901-0071 | 8.2 / 0.795 | 539 ✅ | ✅ | ✅ **max 1.19×** | ✅ | **PASS** |
| RC-ELITE-260901-0072 | 8.0 / 0.893 | **589 ❌** | ⚠️ Q1/Q5 pair | ✅ (max 1.22×) | ✅ | **FAIL** |
| RC-MEDIUM-260901-0052 | **9.2** / 0.904 | 525 ✅ | ✅ | **❌ Q1 1.36×, Q4 1.33×, Q5 1.33×** | ✅ | **FAIL** |

**1 pass, 2 fails.** All 24 keys correct. No assumption stem anywhere — the regression seen in 0050 has not spread.

---

## RC-ELITE-260901-0071 — the cleanest paper in the corpus

Passes all four with room to spare, and its **worst option spread is 1.19×** — tighter than any of the 27 papers checked before it. Q7 sits at 1.01×, effectively four options of identical length.

Eight genuinely distinct types: primary concern, phrase-in-context, disagree-with, analogy, phrase-in-context (different phrase, different work), final-sentence function, structural function of a parenthesis, and detail. The Q7 item — asking what the parenthetical "a procedural safeguard, not an aesthetic preference, so it might be read as a small technical matter" is doing structurally — is the most sophisticated question type I have seen in this project: it tests recognition of a pre-empted objection.

Nothing to fix.

---

## RC-ELITE-260072 — length only, but badly

**589 words — 39 over the ceiling**, the largest overshoot in the entire corpus. For comparison, the worst previous case was 0068 at 568.

Everything else is sound: keys all correct, option spread ≤1.22×, no assumption question, and a strong question set including a paragraph-removal item (Q3) and two well-differentiated phrase items.

**Trim candidates that no question touches:**
- Para 2's "sometimes four seconds, in the systems built for volume" — the four-second figure recurs in Q4's correct answer, so the clause must stay in some form, but it can shorten.
- Para 4's list "a satellite pass eleven days stale, a phone that changed hands, a courtyard reconfigured since the last collection" — three items where two would carry the point; no option references them.
- Para 5's "There is no midpoint between that admission and the manuals, no formula that splits the difference and leaves the tempo intact." — the second clause restates the first.

**Soft R2 flag:** Q1 (central idea) and Q5 (primary purpose) are the recurring pairing, now in its fifth batch. This instance is more defensible than 0075's was — Q5's answer is about rhetorical *method* ("dismantling the fixes") rather than restating the claim — so I would not fail it, but it is the same pattern. Separately, Q7 and Q8 are both phrase-in-context items; they take different phrases doing different work, so both stand.

---

## RC-MEDIUM-260901-0052 — option lengths, despite the highest score in the corpus

This paper scores **9.2**, the highest judge score anywhere in this project, and is `approved`. It still fails R3 on three questions:

| Q | Ratio | Detail |
|---|---|---|
| Q1 | **1.36×** | correct (A) is 76 chars against (C) at 103 — **the correct answer is the shortest** on the paper's gist question |
| Q4 | 1.33× | 84–112 spread; the correct answer is not the extreme |
| Q5 | 1.33× | 75–100 spread; the correct answer is not the extreme |

Q1 is the one that matters — a candidate who picks the shortest option gets the main-idea question free. Q4 and Q5 exceed the threshold on spread alone and are easier fixes.

Across the paper the correct answer is the shortest option in 4 of 8. Everything else is clean: 525 words, eight distinct types, no assumption question, keys all correct.

**Worth saying plainly:** a 9.2 judge score and an `approved` status did not catch a 1.36× option spread with the correct answer shortest. Whatever the judge measures, it is not this.

---

## Voice: the 1 Sept break holds across all eight

Adding these three to the five checked earlier gives eight papers for the day:

| | PREV-10 | NEW-9 | 0829 | **0901 (all 8)** |
|---|---|---|---|---|
| Markers per paper (of 7) | 2.4 | 4.8 | 4.4 | **2.9** |
| Intra-batch cosine | 0.9000 | 0.9178 | 0.9219 | **0.8955** |
| "survives" | 40% | 78% | 60% | **12%** |
| First-person "I" | 60% | 78% | 60% | **38%** |
| Cost / price metaphor | 20% | 56% | 60% | **38%** |

The break reported this morning survives the larger sample. Marker density stays near the pre-intervention baseline, and cosine at 0.8955 remains the lowest of any batch.

**Five of the eight now reach a verdict** rather than declining to resolve — 0073, 0075, 0051, 0052 and 0072. 0052 ends on a positive definition ("It is a record of connection and choice"); 0072 ends by naming what the honest doctrine costs. Only 0074, 0050 and 0071 keep the withheld ending, and in 0071's case the withholding is the argument rather than a mannerism.

Two markers stay stubbornly high: **reader-directed imperative at 62%** ("Follow the chain link by link", "Consider what the choice consists of", "Granted, the film does dramatise") and **explicit steelman at 62%**. Those are the two habits left to break.

---

## What to fix

1. **0072's length** — 589 → ≤550. Three trim candidates identified above, none touching a question.
2. **0052's Q1, Q4, Q5 option spreads**, with Q1 the priority since the correct answer is shortest.
3. **0071 needs nothing.**
