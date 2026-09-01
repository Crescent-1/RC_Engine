# Revision Changelog — 0901 set

Sources: `exported_rc_sets/` root (0051, 0074, 0075) and `exported_rc_sets/flagged_similar/` (0050, 0073). Originals unmodified.

Three papers revised — **0050**, **0075**, **0073**. **0051** and **0074** already passed all four requirements and are copied through untouched, so this folder is the complete set of five.

No passage was edited. Every one of the five was already inside the 500–550 band, which is a first for this project; all changes here are to questions and options.

---

## Question replacements

### RC-MEDIUM-260901-0050 — Q8 replaced
**Out:** *"Which one of the following would best **license the inference** the author draws from the sailors' divergent court-martial statements?"* — the assumption-family stem, fourth appearance in the corpus. It also duplicated Q3's material, since Q3 already asks why the author cites those same divergent statements.

**In:** **EXCEPT-detail** — the type the paper lacked, and deliberately drawn from different material (paragraph 1's close-range Navy account rather than paragraph 2's testimony). Answer **(D)**, the unsupported one: that the account recorded the men's varied statements of motive without treating them as evasion. The passage says the opposite — the prosecution treated the variety as evasion, and the close-range account has a few men talking and the rest following. The other three are lifted from paragraph 1 verbatim.

### RC-HARD-260901-0075 — Q6 replaced
**Out:** *"The primary purpose of the passage is to"* → (D) *defend a field's decision to keep a flawed model while making its flaws explicit.* This duplicated Q1's gist answer (C), which makes the same claim. Fourth batch running that the gist + primary-purpose pairing has appeared.

**In:** **Application / analogous case** — absent from the paper. Answer **(A)**: a bank that keeps a credit model mispricing a minority of loans and publishes the error band beside each score. That is the closing posture exactly — "a locally wrong model, run with its wrongness quantified" with "the wider bounds now printed beside it." Distractors: replacing the model after one failure (premature_closure), defending it by citing data quality (phrase_misuse — paragraph 4 forbids exactly that alibi), abandoning statistical scoring altogether (scope_inflation).

---

## Option-length fixes

**Six hard failures repaired**, all with the correct answer at the extreme:

| Paper | Q | Before | After |
|---|---|---|---|
| MEDIUM-0050 | Q6 | 1.43× (correct longest, 173 vs 121) | **1.23×** |
| MEDIUM-0050 | Q5 | 1.42× (correct longest, 142 vs 100) | **1.11×** |
| MEDIUM-0050 | Q4 | 1.39× (correct longest, 159 vs 114) | **1.14×** |
| MEDIUM-0050 | Q3 | 1.38× (correct longest) | **1.16×** |
| HARD-0075 | Q1 | 1.38× (correct **shortest**, 112 vs 154) | **1.13×** |
| HARD-0073 | Q1 | 1.30× (correct **shortest**, 82 vs 107) | **1.09×** |

Worst spread anywhere in the set is now **1.24×**.

**Both systematic tells removed:**

- **RC-MEDIUM-260901-0050** had the correct answer as the longest option in 5 of 8 — now **3 of 8**.
- **RC-HARD-260901-0073** had it as the shortest in 5 of 8. Six questions were rebalanced (Q1, Q2, Q4, Q6, Q7, Q8) — now **1 of 8**.

Every wording change preserves the option's meaning and its elimination tag; only length moved.

---

## Verification performed after revision

- **Word counts:** 513 / 534 / 537 / 540 / 545 — unchanged, all inside 500–550.
- **Assumption stems:** zero matches for "license the inference" or "unstated assumption" across all five.
- **Key integrity:** every stated correct letter has exactly one CORRECT line, and every question carries all four option rationales.
- **Option ratios:** worst per paper 1.15–1.24×; both replacement questions sit at 1.10× or better.
- **Length position:** correct-is-longest ≤3 of 8 and correct-is-shortest ≤4 of 8 in every paper, with no runs.
- **Answer-letter distribution:** 0050 B C A D B C A D and 0075 C A D C A A D C — no letter runs beyond two.
- Every revised paper was re-solved end to end; all 40 keys match.

---

## Left as they are — flagged, not changed

- **RC-HARD-260901-0074 has the correct answer as the shortest option in 4 of 8.** It passed all four requirements and was outside this brief, so I have not touched it. Mildly above chance; worth a pass if you want the set uniform.
- **RC-MEDIUM-260901-0050 carries `solver_dispute` at score 0.0.** I solved all eight independently and agree with the key on every one, including the replaced Q8. As with 0068 and 0034 before it, the dispute appears resolvable in the key's favour rather than indicating a wrong answer.
- **RC-HARD-260901-0073 Q2 and Q3** both concern the heat-wave run in paragraph 3 — one asks its function, the other why the "calibration curiosity" reading fails. They test different things and both stand, but they sit close together.
- **Novelty 0.499 on 0073**, the second-lowest in the corpus. Outside the four requirements.

---

## Note on the voice work

Nothing in this revision touches the passages, and nothing needed to. This batch broke the house-voice pattern on its own: marker density fell from 4.4 to 2.6 per paper, intra-batch cosine to 0.8915 (the lowest measured), "survives" disappeared entirely, and three of the five reach an actual verdict rather than declining to resolve. That is the argument-shape change the batch comparison called for, and it arrived in the generator rather than in editing.
