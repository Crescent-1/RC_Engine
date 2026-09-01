# RC Compliance Check — 5 sets dated 1 Sept

Same four requirements. All 40 questions solved independently before the keys were read.

---

## Verdict table

| RC ID | Score / F1 | Words (R1) | 8 distinct Qs (R2) | Option length (R3) | No assumption Q (R4) | Verdict |
|---|---|---|---|---|---|---|
| RC-MEDIUM-260901-0051 | 8.6 / 0.770 | 537 ✅ | ✅ | ✅ (max 1.24×) | ✅ | **PASS** |
| RC-HARD-260901-0074 | 7.6 / 0.860 | 545 ✅ | ✅ | ✅ (max 1.22×) | ✅ | **PASS** |
| RC-HARD-260901-0073 | 8.8 / 0.850 | 540 ✅ | ⚠️ Q2/Q3 adjacent | ⚠️ Q1 1.30×; shortest 5/8 | ✅ | **BORDERLINE** |
| RC-HARD-260901-0075 | 8.6 / 0.803 | 534 ✅ | ⚠️ Q1/Q6 pair | **❌ Q1 = 1.38×** | ✅ | **FAIL** |
| RC-MEDIUM-260901-0050 | 0.0 / 0.784 | 513 ✅ | ⚠️ Q3/Q8 same material | **❌ four questions ≥1.38×** | **❌ Q8** | **FAIL** |

**2 clean passes, 1 borderline, 2 fails — the best batch so far.** All 40 keys correct.

**Every one of the five is in the 500–550 band** (513–545). That is the first batch with a perfect length record; the previous three ran 8/10, 5/9 and 2/5. Whatever ceiling check went in has worked.

---

## Failures in detail

### RC-MEDIUM-260901-0050 — the assumption stem is back

**R4: Q8** — *"Which one of the following would best **license the inference** the author draws from the sailors' divergent court-martial statements?"* This is the fourth appearance of that exact template (0052 Q4, 0056 Q8, 0047 Q7, now this). It was absent from the entire 0829 batch, so it has regressed rather than persisted.

**R3: four questions fail** — Q3 1.38×, Q4 1.39×, Q5 1.42×, Q6 1.43×, and the correct answer is the longest option in **5 of 8**. Worst single case is Q6, where the correct (C) runs 173 characters against (A) at 121.

**R2 (soft):** Q3 and Q8 both work the divergent court-martial statements — Q3 asks why the author cites them, Q8 what would license the inference from them. Replacing Q8 on R4 grounds fixes this too, provided the replacement uses different material.

**On the solver dispute:** I solved all eight independently and agree with the key on every one, including Q8. As with 0068 and 0034 before it, the dispute looks resolvable in the key's favour rather than indicating a wrong answer.

### RC-HARD-260901-0075 — option length, plus the recurring pair

**R3: Q1 at 1.38×.** Correct answer (C) is 112 characters against (A) at 154 — the correct answer is the shortest, by a wide margin, on the paper's main-idea question.

**R2 (soft): Q1 and Q6 again pair gist with primary purpose.** Q1 (C) *"a model whose limits were exposed by one rupture survives as a quantified tendency rather than a mechanical law"*; Q6 (D) *"defend a field's decision to keep a flawed model while making its flaws explicit."* Closer than the equivalent pair in 0074, and this is the fourth batch running in which the pairing appears.

### RC-HARD-260901-0073 — borderline only

Q1 sits at 1.30× with the correct answer shortest (82 chars against 107), and across the paper the correct answer is the shortest option in 5 of 8. No individual question breaks the threshold, but the pattern is usable.

Q2 and Q3 both concern the heat-wave run in paragraph 3 — one asks its function, the other why the "calibration curiosity" impression does not survive. Different enough to stand, but they sit close together.

Also worth noting outside the four requirements: **novelty 0.499**, the second-lowest in the corpus.

---

## The passes

**RC-MEDIUM-260901-0051** (537 words) and **RC-HARD-260901-0074** (545 words) clear all four requirements with the two tightest option-length profiles in the batch (1.24× and 1.22×). Both carry eight genuinely distinct question types and correct keys throughout.

---

## Voice: the batch that finally breaks the pattern

This is the significant finding.

| | PREV-10 | NEW-9 | 0829 | **0901** |
|---|---|---|---|---|
| Markers per paper (of 7) | 2.3 | 4.7 | 4.4 | **2.6** |
| Intra-batch function-word cosine | 0.9000 | 0.9178 | 0.9219 | **0.8915** |
| "survives" | 40% | 78% | 60% | **0%** |
| Reader-directed imperative | 20% | 78% | 100% | **40%** |
| Cost / price / invoice metaphor | 20% | 44% | 60% | **20%** |
| First-person "I" narrator | 60% | 78% | 60% | **40%** |

Marker density has fallen back to the pre-intervention baseline, and **intra-batch cosine is 0.8915 — the lowest of any batch measured, below even the 21–22 Aug figure.** The word "survives," which appeared in 7 of 9 papers in the 24–28 Aug batch and did identical structural work in four of them, is absent from all five.

**More importantly, the argumentative shape has changed.** Across the previous 24 papers, every single one ended by declining to resolve and naming the cost. Here, **three of five reach an actual verdict**:

- **0073** — "must be conceded only for nights when nothing external holds the body still, and abandoned for exactly the nights that now matter most."
- **0075** — "twenty-two years, in the trenches near Parkfield, still means twenty-two years — with the wider bounds now printed beside it."
- **0051** — "it will remain the correct one for as long as resistance genes can still travel through shared water."

0051 in particular argues a side and wins: it endorses a layered treatment procedure outright ("and it works"). That is the first paper in this corpus to do so. Only 0074 and 0050 keep the old withheld ending.

This is what the batch comparison predicted would be needed — varying the *argument* shape, not just the topic. On this evidence it has been done.

---

## What to fix

1. **The assumption stem, once more.** 0050 Q8. It was gone from the entire 0829 batch, so this is a regression, not a persistence — worth finding out why it came back.
2. **Option-length balancing** remains the weakest control: six questions across the batch exceed 1.30×, all in two papers, and in every case the correct answer is the extreme option.
3. **The gist + primary-purpose pairing** (0075 Q1/Q6) is now four batches old. It should be a generator rule, not an editing catch.

Nothing here needs passage-length work, which is new.
