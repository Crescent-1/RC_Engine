# Batch Comparison — selected-10 (21–22 Aug) vs post-0823 set (24–28 Aug)

Measured on the passages **as generated**, before my revisions to either batch.

---

## 1. Headline

**The newer batch is more homogeneous than the older one.** On every rhetorical marker I tested, concentration rose. On the quality metrics, nothing improved.

| | PREV-10 | NEW-9 |
|---|---|---|
| Mean judge score (excl. disputes) | 8.40 | **8.30** |
| Mean compliance F1 | 0.853 | **0.816** |
| Mean novelty | 0.561 | **0.546** |
| Status mix | 6 review / 3 approved / 1 dispute | 5 / 3 / 1 |
| **House-voice marker score (mean /7)** | **2.6** | **4.7** |
| Function-word cosine, mean pairwise within batch | 0.9000 | **0.9178** |

Quality flat-to-slightly-down; sameness up sharply.

---

## 2. This is not a provider effect

The previous 10 were 7 Claude + 3 OpenAI (per `post_housevoice_fix/_MANIFEST.txt`). The obvious explanation for a homogeneity jump would be that the new batch is single-provider. It isn't the explanation — comparing **Claude to Claude**, the concentration still nearly doubles:

| Marker | PREV Claude (n=7) | PREV OpenAI (n=3) | NEW-9 |
|---|---|---|---|
| "survives" | 43% | 33% | **78%** |
| "nobody" | 57% | 33% | **78%** |
| Reader-directed imperative | 14% | 33% | **78%** |
| Explicit steelman of the rival reading | 29% | 0% | **67%** |
| First-person "I" narrator | 71% | 33% | **78%** |
| Cost / pay / price metaphor | 14% | 0% | **44%** |
| Negation pair ("Not a X. Not a Y.") | 29% | 33% | **44%** |
| **Mean markers per paper (of 7)** | **2.6** | **1.7** | **4.7** |

Function-word cosine tells the same story: PREV Claude-only 0.9052, NEW-9 0.9178. Cross-batch mean is 0.9089 — *between* the two intra-batch figures, which means the batches are not two distinct populations. They are one continuous voice, and the newer end of it is tighter.

---

## 3. Why — and your own manifest already recorded it

`_MANIFEST.txt` lists the interventions in order. Number 3:

> 3. prescribed beat plans replacing the bans **(worked; adherence 33% → 78%)**

That is the same curve I measured independently. My marker rate goes **37% → 67%** across the same window. Within noise, those are one number.

The beat plans did exactly what they were built to do: they raised adherence to a prescribed sequence of rhetorical moves. But "adherence to one beat plan" and "the passages all sound alike" are not two facts — they are the same fact, scored once as a success and once as the defect. **The intervention logged as the fix is the mechanism producing the sameness.**

Interventions 1, 4 and 5 (novelty channel, arc-shape families, tiebreak checks) look neutral on this evidence. Intervention 2 is already recorded as failed.

---

## 4. Your novelty channel cannot see this

Novelty barely moved (0.561 → 0.546) while measured homogeneity rose. That is a measurement gap, not a contradiction: novelty scores each paper against a corpus, so it catches *topic* and *phrase* reuse. Template convergence **inside a batch** is invisible to it — nine papers can each be novel against the corpus and still be interchangeable with each other.

If you want a number that tracks the real problem, the two that worked here are cheap to compute:

- mean pairwise function-word cosine within a batch (target: push **below 0.88**; currently 0.918)
- a marker checklist scored per paper (target: **under 2 of 7**; currently 4.7)

---

## 5. Compliance profile flipped direction

| | PREV-10 | NEW-9 |
|---|---|---|
| In band (500–550) | 8 / 10 | 5 / 9 |
| Over 550 | 1 | **4** |
| Under 500 | 1 | 0 |
| Mean words | 530 | 540 |

Per `review_shippable/_TRIAGE.txt`, the old length failures ran **short** and were 7-of-8 OpenAI. The new ones all run **long**, and three of the four miss by only 1–3 words (551, 552, 553). The generator has moved from undershooting to just overshooting the ceiling — which suggests the target is being aimed at without a hard stop.

**Defect mix also changed:**

| Defect | PREV-10 | NEW-9 |
|---|---|---|
| Assumption question | 2 | 1 |
| Duplicate question pairs | 4 (in 2 papers) | 1 |
| Length out of band | 2 | 4 |
| Option-length failure (>1.35×) | 0 | 2 |
| "Correct answer is longest" tell (5/8) | 0 | 2 |

Redundant questions were the old batch's signature defect; option-length imbalance and length overshoot are the new one. The assumption stem persists at about one per batch — three appearances across 19 papers, always the same "would best license the inference" wording.

---

## 6. Cross-batch collisions

- **RC-ELITE-260821-0048** is the single most-collided paper. It reuses its source article (*"A Different Kind of Populist"*) with **RC-HARD-260824-0064**, and it is one half of the closest stylistic pair across the two batches (with **RC-HARD-260824-0066**, cosine 0.961).
- Tightest pair anywhere: **RC-HARD-260828-0067 ~ RC-MEDIUM-260825-0046**, cosine 0.971 — a livestreamed-Mass passage and a TV-spinoff passage, entirely different subjects, near-identical prose signature.

If you ship both batches into one pool, these are the pairs to separate across forms.

---

## 7. What I would do

1. **Loosen the beat plans before adding the topic-shape layer.** The manifest says the topic-shape fix is not yet active and is aimed at "the remaining sameness." On this evidence topic shape is not the binding constraint — *argument* shape is, and the beat plans are enforcing it. Adding a layer on top of a template that already dictates the moves will not separate the voices.
2. **Require adjudication-refused endings in a minority of papers, not all.** 19 of 19 across both batches end by declining to resolve and naming the cost. That single habit is the strongest marker in the corpus.
3. **Add the two intra-batch metrics above to the scorecard**, so a batch can fail for homogeneity the way it currently fails for length.
4. **Put a hard ceiling check at 550** rather than a target near it.
5. **Take the "license the inference" stem out of the question-type list.**
