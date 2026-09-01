# RC Compliance Check — 5 sets dated 29 Aug

Same four requirements. All 40 questions solved independently before the keys were read.

---

## Verdict table

| RC ID | Score / F1 | Words (R1) | 8 distinct Qs (R2) | Option length (R3) | No assumption Q (R4) | Verdict |
|---|---|---|---|---|---|---|
| RC-MEDIUM-260829-0048 | 8.4 / 0.895 | 529 ✅ | ✅ | **❌ Q1 = 1.45×** | ✅ | **FAIL** |
| RC-MEDIUM-260829-0049 | 8.6 / **0.68** | 529 ✅ | **❌ Q1 ≈ Q6** | **❌ Q3 1.55×, Q5 1.35×** | ✅ | **FAIL** |
| RC-HARD-260829-0068 | 7.4 / 0.900 | **568 ❌** | ✅ | ✅ (max 1.23×) | ✅ | **FAIL** |
| RC-HARD-260829-0069 | **7.0** / 0.922 | **561 ❌** | **❌ Q1 ≈ Q7** | **❌ Q1 1.49×; shortest 7/8** | ✅ | **FAIL** |
| RC-ELITE-260829-0069 | 8.6 / 0.843 | **566 ❌** | ✅ | **❌ Q3 1.48×, Q5 1.42×** | ✅ | **FAIL** |

**0 of 5 pass.** Every one of the 40 keys is correct — again, the defects are structural, not errors of fact. No assumption question anywhere, which is the one clean result: that stem has finally gone.

---

## Failures in detail

### Length — 3 of 5 over the ceiling, by the widest margins yet

**568, 566, 561.** The previous batch's overshoots were 551, 552, 553 and 563; these are 11–18 words over. The trend is going the wrong way: 21–22 Aug missed in both directions, 24–28 Aug missed only long by 1–13, 29 Aug misses only long by 11–18.

The two medium papers land at **529 and 529** — identical, and comfortably in band. Whatever governs length is working for medium and failing for hard/elite.

### Option length — 4 of 5 papers, and the spreads are the worst in the corpus

| Paper | Question | Ratio | Correct answer |
|---|---|---|---|
| MEDIUM-0049 | Q3 | **1.55×** | (D) 181 chars vs (A) 117 — longest by 33 over the next |
| HARD-0069 | Q1 | **1.49×** | (A) 100 chars vs (B) 149 — **shortest by 39** |
| ELITE-0069 | Q3 | **1.48×** | (B) 105 vs (D) 71 — longest |
| MEDIUM-0048 | Q1 | **1.45×** | (A) 116 vs (B) 80 — longest |
| ELITE-0069 | Q5 | **1.42×** | (C) 142 vs (D) 100 — longest |
| MEDIUM-0049 | Q5 | **1.35×** | (D) 171 vs (C) 127 — longest |

For comparison, the worst spread in the whole revised post-0823 set is 1.29×. Six questions here beat that, and in every case **the correct answer is the extreme option**.

**RC-HARD-260829-0069 is the serious one.** The correct answer is the shortest option in **7 of its 8 questions**. A candidate who reads nothing and picks the shortest option every time scores 7/8. That is the strongest single tell I have seen anywhere in this corpus — worse than the 5-of-8 runs I flagged in 0068 and 0064 last round.

Only **RC-HARD-260829-0068** is clean here (max 1.23×).

### Duplicate questions — 2 of 5

- **HARD-0069: Q1 and Q7.** Q1 "The primary purpose of the passage is to" → (A) *trace how one term came to serve two opposed jobs, and question the comfort of the resulting verdict.* Q7 "The passage as a whole is best understood as an attempt to" → (C) *unsettle a settled moral verdict by showing that the reform renamed steering rather than removing it.* Two primary-purpose questions, one answer.
- **MEDIUM-0049: Q1 and Q6.** Q1 central idea → (B) *the reversal is real but the polite new vocabulary can still treat residents as someone else's variable.* Q6 primary purpose → (A) *a real improvement in planning ethics has left an older habit of treating residents instrumentally intact.* Same claim twice.

This is the identical central-idea-plus-primary-purpose pairing that made 0034 and 0037 redundant in the first batch and 0046 redundant in the second. Third batch running.

### Metrics worth noting outside the four requirements

- **RC-HARD-260829-0069 scores 7.0** — exactly at the floor used in `_TRIAGE.txt`.
- **RC-MEDIUM-260829-0049 has F1 0.68**, the weakest compliance figure in any batch so far.
- **RC-ELITE-260829-0069 has novelty 0.478**, the lowest single novelty score in the corpus.
- All five are `needs_review`; none approved. All five screen green.

---

## Voice: the plateau holds

| | PREV-10 | NEW-9 | **NEW-5** |
|---|---|---|---|
| Markers per paper (of 7) | 2.4 | 4.8 | **4.4** |
| Intra-batch function-word cosine | 0.9000 | 0.9178 | **0.9219** |
| Reader-directed imperative | 20% | 78% | **100%** |
| Cost / price / invoice metaphor | 20% | 44% | **60%** |

The marker count is flat against the 24–28 Aug batch (4.4 vs 4.8, well within noise at n=5) and still nearly double the 21–22 Aug baseline. Intra-batch cosine is the **highest of the three batches at 0.9219**.

The reader-directed imperative is now in **all five**: *"Take the testimony apart"* · *"Consider the remedy as a course of surgery"* · *"Work both readings out"* · *"Reopen the same file twenty years later"* · *"Take a second station"* · *"Consider two towers"*.

The template is intact in all five: object-with-a-number cold open → stipulate → steelman the rival account → turn on one overlooked detail → machine or surgical metaphor → refuse the middle position → name the cost. Two of the five even use the same explicit refusal-of-the-middle move — *"The middle position is available and I decline it"* (0048) and *"splits a difference that is not there to split"* (0068).

**Closest pair in the whole corpus is now cross-batch:** RC-MEDIUM-260824-0044 ~ RC-MEDIUM-260829-0049 at **0.9709** — COP28 labels and postwar housing clearance, near-identical prose signature.

Nothing in these five suggests the topic-shape layer has been switched on yet.

---

## What to fix, in order

1. **A hard ceiling check at 550.** Three of five fail on this alone and two of those three are otherwise sound. This is the cheapest possible win.
2. **An option-length balancer.** Cap longest/shortest at ~1.25× per question, and separately forbid the correct answer from being the strict extreme more than twice per paper. HARD-0069 at 7-of-8-shortest would have been caught by either rule.
3. **Never emit both a central-idea and a primary-purpose question in the same paper.** Three batches, three occurrences; it is a generator rule, not an editing problem.
4. The assumption stem is gone — whatever removed it worked. Same approach should work for item 3.
