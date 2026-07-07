# RC Engine — Full Walkthrough

A single document that follows **one elite RC** from the moment you type a
command to the moment it lands in the database, explaining what every component
does and why it exists. Read this top to bottom and you understand the system.

If you want the *design rationale*, read `ARCHITECTURE_REDESIGN.md`.
If you want the *commands*, read `RC_ENGINE_README.md`.
This document is the *mental model*.

---

## 0. The one idea behind everything

Your old pipeline wrote a great RC from a single prompt. The problem was never
quality — it was that after a few hundred RCs, every elite passage had the
**same skeleton**: same argument shape, same "reversal near the end," same six
question types in the same order. Students learn skeletons, not topics.

So the whole redesign rests on one move:

> **Decide the structure first, as data, before any prose exists — then force
> that structure to be different from everything we've shipped before.**

Structure becomes a *sampled, tracked, audited variable* instead of a constant
baked into a prompt. Everything below is machinery to make that happen reliably
and cheaply.

---

## 1. The shape of the system

```
   YOU: python -m rc_engine.cli generate --elite 1
        │
        ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ cli.py         parses the command, picks real vs mock client │
   │ pipeline.py    the conductor — runs the 5 stages in order    │
   └─────────────────────────────────────────────────────────────┘
        │
        ▼   (one RC = the five stages below, in sequence)

   STAGE 1  composer.py     ── invent a unique BLUEPRINT  (mostly free)
   STAGE 2  renderer.py     ── write the PASSAGE from the blueprint
            compliance.py   ── check the passage matches the plan
   GATE B   novelty.py      ── is the passage too similar to past ones?  (free)
   STAGE 3  question_engine ── write 6 QUESTIONS from the blueprint
   GATE C   novelty.py      ── full similarity check incl. questions     (free)
   STAGE 5  quality.py      ── blind SOLVER + blueprint-aware JUDGE
        │
        ▼
   history.py   ── save blueprint, passage, fingerprint, audit trail to SQLite
```

Two supporting layers wrap all of it:

- **`config.py`** — every number that matters (budgets, models, thresholds).
- **`llm.py`** — the only thing that talks to the API, and the thing that
  guarantees an RC can never cost more than its cap.

Everything in `components/*.json` is the **library of building blocks** the
composer samples from. `registry.py` loads and validates them.

---

## 2. The building blocks (the `components/` folder)

Before any RC is made, the engine loads seven libraries. These are plain JSON
files you can edit without touching code. Think of them as **the alphabet the
engine writes essays with.**

| Library | Count | What one entry is | Example |
|---|---|---|---|
| `families.json` | 32 | an argument *shape* — the reason the essay exists | "The Vanishing Object": inquiry into X reveals X isn't a coherent thing at all |
| `personas.json` | 20 | an author *voice* | "The Moral Accountant": tallies who pays, quietly indignant |
| `endings.json` | 20 | how the essay *closes* | "The Instrument Doubt": questions the tools it just used |
| `rhythms.json` | 20 | paragraph *length pattern* | "Trapdoor": even paragraphs, then the floor drops |
| `revelations.json` | 20 | *when* the thesis becomes visible | "Retrospective Reveal": only clear on a mental re-read |
| `distractor_profiles.json` | 20 | what *kinds of wrong answers* dominate | "The Time Traveler": right content, wrong stage of the argument |
| `topologies.json` | 20 | the *6-question plan* — types, order, difficulty curve | "The Ambush": four easy, then a brutal final pair |

**Why this matters:** pick one from each and you get one blueprint. The number
of combinations is 32 × 20⁶ ≈ **2 billion**, and after removing incompatible
pairings still ~800 million. A student will never see the same skeleton twice.

`registry.py` is the librarian: it loads these files at startup and **fails
loudly** if anything is malformed (missing fields, a topology without 6 slots, a
rule pointing at a component that doesn't exist). This is why `selftest` catches
library mistakes before you ever spend money.

`constraint_rules.json` + `constraints.py` are the **compatibility checker**:
some combinations are silly or self-defeating (e.g. a "Wrong Question" family
that ends on a neat verdict — those fight each other). The rules forbid ~26 such
pairings so the composer never ships a self-contradicting blueprint.

---

## 3. STAGE 1 — The Blueprint (`composer.py`)

This is the heart of the redesign. It runs in two halves.

### 3a. Sampling the skeleton (free, no API call)

The composer picks one component from each library — but not randomly. It
respects three things drawn from history:

1. **Exclusion windows** — don't reuse a family for 25 RCs, a topology for 12, a
   persona for 10, etc. (all in `config.EXCLUSION_WINDOWS`). So the same
   building block can't reappear too soon.
2. **Decay weighting** — among the allowed blocks, prefer the ones used *least*
   recently. Gentle pressure toward even coverage.
3. **Compatibility rules** — drop any pick that clashes with an earlier pick.

Then it does a **distance pre-check**: compare this candidate blueprint against
the last 50 shipped ones. If it's more than 55% similar to any of them (by
component overlap), throw it away and resample. This is the *cheap* novelty
gate — it rejects clones before spending a cent.

It also samples, deterministically:
- **paragraph movement** — merges the family's function sequence with the
  rhythm's length pattern (e.g. paragraph 4 = "the hinge redescription,"
  30–55 words, staccato).
- **the answer-letter plan** — e.g. `[C, A, D, B, A, D]`, guaranteed no letter
  more than twice and never 3 in a row. (This is why answer-letter bias is
  impossible — it's decided here, mechanically, not left to the model.)

Output so far: a **structural contract** — but with no topic yet.

### 3b. Refining the content (one cheap API call — Sonnet)

The skeleton says "paragraph 3 rehearses a rival framework and undermines it,"
but not *about what*. The refine call fills that in: it invents the topic, the
two competing tensions, a concrete **trap map** (3 specific misreadings the
passage will invite), and a one-line brief per paragraph — **without changing
any structural choice.**

> The deterministic sampler owns *structure*; the LLM owns *content*. That split
> is what makes the structure controllable.

**Robustness:** if that call comes back empty or malformed (which happens
occasionally with any live model — it's the crash you hit earlier), it retries 3
times, then falls back to a deterministic plan built from the family's own
description. A refine hiccup degrades content slightly; it never crashes the run.

**The trap map is the bridge to Stage 3.** Each trap is a first-class object:
`{trap_id: TR2, anchor_para: 3, invited_misreading: "the rival is endorsed",
mechanism: level_confusion}`. Later, questions will *reference these by ID* — so
the difficulty is designed here, in the blueprint, not bolted on afterward.

---

## 4. STAGE 2 — The Passage (`renderer.py` + `compliance.py`)

### 4a. Rendering (one expensive call — Opus)

`renderer.py` assembles a prompt entirely from the blueprint: the persona's
voice card, the paragraph-by-paragraph plan (function + word range + cadence),
the thesis-revelation schedule, the trap directives, the ending directive, and a
forbidden-words list. The seed essay (if any) supplies only subject matter.

The model's job is narrow: **write prose that fills this exact structure.** It
invents all the actual sentences, but it cannot choose the shape.

### 4b. Compliance audit (one cheap call — Haiku)

Here's the safeguard against the model quietly ignoring the plan. `compliance.py`
takes the finished passage *and* the blueprint and asks a cheap model to check:

- did each paragraph actually perform its assigned function?
- does the thesis first appear where it was supposed to?
- are the planted traps actually present?
- did any forbidden phrase slip in?

It also extracts the **commitment curve** — how committed the author sounds to
their final position in each paragraph, as a number per paragraph. (This curve
is the single most "learnable" signature of an author's rhythm, so we measure it
to police it later.)

It produces a **compliance F1 score** (0–1). If it's below threshold, the
passage is re-rendered with *targeted directives* ("paragraph 3 performed the
hinge too early — move it to paragraph 4"), up to 2 attempts. Cheap re-renders
instead of throwing the whole RC away.

> **Important subtlety:** what gets stored and compared later is the *realized*
> structure (what the auditor actually found), not the *planned* structure.
> Because prose drifts, and we must police what students actually read.

---

## 5. GATE B — Novelty on the passage (`novelty.py`, free)

Before spending the most expensive call (questions), we ask: **is this passage
structurally too close to one we already shipped?**

This is the part that makes the whole system worth building. Humans notice
*structural* repetition long before *topic* repetition. So we compare on
**multiple channels**, not just meaning:

| Channel | What it catches | How |
|---|---|---|
| Blueprint categorical | same combination of building blocks | weighted overlap of the 7 IDs |
| Movement string | same paragraph-function sequence | edit distance on the function tokens |
| Commitment curve | same author "rhythm" of conviction | correlation of the per-paragraph curves |
| Rhythm vector | same paragraph-length music | cosine on length/sentence statistics |
| Stylometry | same *voice* wearing a different topic | Burrows' Delta on function words |
| Embedding | same *meaning* | cosine on the passage embedding (this is the *only* channel your old pipeline had) |

Each channel has a hard cap. If any single channel is breached against any RC in
the trailing window, the RC is **rejected** and a fresh blueprint is composed
(up to 3 tries). There's also a composite score: if the weighted blend is too
similar overall, reject even if no single channel tripped.

The key insight: **embeddings are 1 of 6 channels here.** Two passages can be
about totally different topics (low embedding similarity) yet have the identical
skeleton — the other five channels catch that. That's the whole point.

Rejecting here is deliberate: it happens *before* the pricey question call, so a
rejected attempt is cheap.

---

## 6. STAGE 3 — The Questions (`question_engine.py`, expensive — Opus)

Now we write 6 MCQs — but **from the blueprint, not by reverse-engineering the
finished passage.**

The topology profile already dictated the 6 slots (types, order, difficulty).
The engine attaches each blueprint trap to the slot best able to harvest it,
then instructs the model: for this slot, one wrong option must be *exactly the
misreading the passage was built to invite.* So the distractor difficulty is
inherited from the passage's architecture — designed, not sprinkled on.

**Two mechanical guarantees enforced here, for free:**

1. **Answer letters** — the model returns options *unlabeled* with the correct
   one marked. The engine then assigns letters from the blueprint's sampled
   letter plan. So answer-letter distribution is provably clean — the model
   never gets to cluster answers on B/C.

2. **Length-bias audit** (`length_bias_report`) — counts, per set, how often the
   correct option is the strictly longest. If that happens in **3+ of 6
   questions**, or if the **thesis question's** answer is the longest, the set is
   flagged as biased and can **never be auto-approved** — it routes to
   `needs_review` for a human. One or two long-correct answers is normal and
   allowed; systematic "longest = right" is blocked. (This is the safeguard you
   asked about; the corpus-wide trend is visible in `health`.)

---

## 7. GATE C — Full novelty (`novelty.py`, free)

Same as Gate B, but now that questions exist it adds two more channels:

- **Question topology** — same distribution and order of question types?
- **Distractor mechanisms** — same *kinds* of wrong answers, set after set?
  (Here, *too little* variety is the failure — if every set leans on the same
  traps, students learn the traps.)

Plus corpus-level flags (e.g. answer-letter chi-square across the last 20 sets)
that don't reject this RC but warn you the *corpus* is drifting.

---

## 8. STAGE 5 — Quality gates (`quality.py`)

These survive from your old pipeline, now blueprint-aware:

1. **Blind solver (Sonnet)** — a strong model solves the questions *without the
   answer key*. If it disagrees with your key, that's a `solver_dispute`: either
   the key is broken or the question is genuinely brutal — a human decides. Never
   auto-regenerated.

2. **Judge (Haiku)** — scores the set, but against **its own blueprint's
   intent.** A "Long Corridor" passage is judged for being linear and dense, not
   penalized for lacking a reversal it was never supposed to have. This fixes a
   real flaw: your old single judge assumed every RC should have the same shape.

Both are *optional under budget*: if the remaining money can't cover them, they
skip and the RC routes to `needs_review` rather than overspending.

---

## 9. The two things that wrap everything

### Cost control (`llm.py` + `config.py`) — the "no surprises" guarantee

Every API call goes through `CostLedger.guard()`. Before the call, it computes
the **worst case** (deliberately over-estimated input + the full output ceiling)
and refuses the call if it would push this RC past its cap
(`config.TIER_BUDGET_USD`: medium $0.12, hard $0.22, **elite $0.30**).

> An elite RC **cannot** cost $0.31. Not "usually won't" — *cannot*, because the
> money is checked before it's spent, not after. Worst case, the RC aborts with
> status `budget_abort` and logs what it spent.

At the batch level, `run_batch` stops starting new work once the batch cap is
reached, and any single-RC crash is caught so it can never kill the whole run.
API rate-limit/credit exhaustion stops the batch cleanly with all finished work
saved — re-run to continue.

Typical real cost: elite happy path ≈ **$0.15**; a novelty-rejected attempt ≤
~$0.09 because it dies before the question call.

### Memory (`history.py`) — how "don't repeat" is possible

Everything lands in SQLite (`rc_pipeline.db`), sharing the file with your old
pipeline. New tables:

- `blueprints` — every blueprint (even rejected ones), with its component IDs
  and combo hash. Drives the exclusion windows.
- `component_usage` — which block was used when. Drives decay weighting.
- `fingerprints` — the structural signature of every shipped RC (movement
  string, commitment curve, rhythm vector, stylometry, embedding, letter
  sequence, length-bias stat). This is what novelty compares against.
- `novelty_audits` — a record of every similarity check, pass or fail.
- `corpus_health` — periodic snapshots of drift.

`rc_sets` stays backward-compatible, so your existing export tooling still works.

---

## 10. The status an RC ends with

| Status | Meaning | Sellable? |
|---|---|---|
| `approved` | passed compliance, novelty, solver, judge, and length-bias | yes, after normal review |
| `needs_review` | complete but a human should look (low judge score, length-bias flag, or a stage was budget-skipped) | after review |
| `solver_dispute` | the blind solver disagrees with the key | fix key first |
| `rejected_novelty` | too structurally close to an existing RC; auto-recomposed up to 3× | never shipped |
| `budget_abort` | would have exceeded the cap; nothing shipped, spend logged | n/a |
| `failed_*` | composition/render/question failure; batch continues | n/a |

---

## 11. How you actually operate it

```bash
python -m rc_engine.cli selftest        # $0 — run after ANY edit; validates everything
python -m rc_engine.cli estimate        # $0 — per-tier cost table
python -m rc_engine.cli backfill        # $0 — fingerprint your existing 20 RCs (run once)
python -m rc_engine.cli generate --elite 1     # 1 live RC, hard-capped at $0.30
python -m rc_engine.cli health          # $0 — drift dashboard (run weekly)
python -m rc_engine.cli generate --dry-run --elite 3   # $0 — full pipeline on the mock client
```

The `--dry-run` mock client is worth dwelling on: it runs the **entire pipeline
end to end for $0**, using canned outputs. It's how you verify plumbing,
budgets, and the novelty gates without spending anything. The `selftest` command
uses it to prove the system is runnable before every real batch.

---

## 12. One-paragraph summary

You type a command. The **composer** invents a structurally unique blueprint by
sampling from seven libraries under history-aware rules (this is where novelty is
*born*). The **renderer** writes a passage that obeys that blueprint, and the
**compliance auditor** confirms it did. A free **multi-channel novelty gate**
rejects it if it's too close to anything shipped — on structure, rhythm, and
voice, not just topic. The **question engine** writes six MCQs that harvest traps
the blueprint designed, with answer-letters and length-bias controlled
mechanically. A **blind solver** and a **blueprint-aware judge** check quality.
A **cost ledger** makes it physically impossible to exceed $0.30 for an elite RC.
**History** remembers everything so the next RC is forced to be different again.
That loop, run a few hundred times, is a corpus with no learnable skeleton.
