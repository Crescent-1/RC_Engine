# rc_engine — Operations Guide

Production implementation of the architecture in `ARCHITECTURE_REDESIGN.md`.
Legacy `RC_PIPELINE.py` is untouched and still works; both write to the same
`rc_pipeline.db` (the engine adds its own tables and keeps `rc_sets` compatible).

## Commands (run from the project folder)

```bash
# $0 — validate everything without spending a cent. Run after ANY config/library edit.
python -m rc_engine.cli selftest

# $0 — per-tier cost table: typical cost, worst case, enforced cap
python -m rc_engine.cli estimate

# $0 — full pipeline against the mock client (separate DB + export folder, never
#      touches production data)
python -m rc_engine.cli generate --dry-run --elite 2

# $0 — fingerprint your existing corpus so new RCs are audited against it.
#      Reads rc_sets rows AND exported .txt folders. Run once (idempotent).
python -m rc_engine.cli backfill

# REAL generation (needs ANTHROPIC_API_KEY). Seeds pull from RAG.py if available,
# else runs seedless.
python -m rc_engine.cli generate --elite 8 --hard 8
python -m rc_engine.cli generate --elite 8 --max-usd 2.00   # explicit batch cap

# $0 — corpus health: family/topology drift, answer-letter chi-square
python -m rc_engine.cli health

# export approved sets
python -m rc_engine.cli export --status approved

# $0 — paste-ready AVOID line for MANUAL_GENERATION_PROMPT.md (last N shipped sets)
python -m rc_engine.cli avoid --n 4

# $0 — free gates on a manually generated RC .txt (novelty vs corpus, letter
#      balance, length bias); --ingest stores it with source='manual' so the
#      corpus stays in sync and manual sets stay filterable
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260707-1.txt --tier elite --ingest
```

## Cost guarantees (what "no surprises" means concretely)

1. **Per-RC hard cap** (`config.TIER_BUDGET_USD`: medium $0.12, hard $0.22,
   **elite $0.30**). Before *every* API call, `CostLedger.guard()` computes the
   call's worst case (over-estimated input tokens + the full `max_tokens`
   output ceiling) and refuses the call if it couldn't fit in the remaining
   budget. Solver/judge get skipped (RC → `needs_review`); core stages abort
   the RC with status `budget_abort`. There is no code path that spends past
   the cap.
2. **Batch cap**: `run_batch` stops starting new work once cumulative spend
   reaches `--max-usd` (default 1.25 × sum of requested tier budgets).
3. **Typical costs** (from `estimate`): elite happy path ≈ **$0.15**, hard ≈
   $0.15, medium ≈ $0.07. Novelty rejections abort *before* the expensive
   question call, so a rejected attempt costs ≤ ~$0.09.
4. **API exhaustion** (rate limit / credits) stops the batch cleanly; finished
   work is already committed. Re-run the same command to continue.

## What each stage does

| Stage | Model (elite) | Purpose |
|---|---|---|
| compose | local (free) | sample family/persona/ending/rhythm/revelation/distractor/topology under exclusion windows, decay weights, compatibility rules, distance pre-check |
| refine | Sonnet | fill content slots (topic, tensions, trap anchors, paragraph gists) — never structure |
| render | Opus | write the passage from the structural contract |
| compliance | Haiku | verify realized structure vs plan; extract commitment curve; targeted re-render directives |
| novelty gate B | local (free) | movement/curve/rhythm/stylometry/embedding channels vs corpus — runs BEFORE the expensive question call |
| questions | Opus | 6 MCQs from the question plan + trap map; letters assigned locally from the sampled letter plan |
| novelty gate C | local (free) | adds topology + distractor-mechanism channels; corpus-level flags |
| solver | Sonnet | blind key-defensibility check; disputes → `solver_dispute` for human review |
| judge | Haiku | blueprint-aware rubric (judges the set against ITS OWN intended structure) |

## Statuses

- `approved` — passed everything; sellable after normal review
- `needs_review` — complete but judge score < 7, compliance below threshold, or a stage was budget-skipped (notes say which)
- `solver_dispute` — blind solver disagrees with the key; human decides
- `rejected_novelty` — structurally too close to an existing RC; auto-recomposed up to 3× per slot
- `budget_abort` — cap would have been exceeded; nothing shipped, spend logged

## Tuning

- Everything cost-related: `rc_engine/config.py` (budgets, models, max_tokens, retries).
- Component libraries: `rc_engine/components/*.json` — edit/add entries freely;
  `selftest` validates them. Adding a family/persona/etc. requires no code change.
- Novelty strictness: `NOVELTY_CAPS`, `MIN_COMPOSITE_NOVELTY`, `EXCLUSION_WINDOWS`.
- After ANY edit: `python -m rc_engine.cli selftest` (it is the pre-flight check).

## First production run (recommended sequence)

```bash
python -m rc_engine.cli selftest          # must pass
python -m rc_engine.cli backfill          # once, so history is loaded
python -m rc_engine.cli generate --elite 1   # single live smoke test (≈ $0.15, hard cap $0.30)
# inspect the exported RC + its notes, then scale up:
python -m rc_engine.cli generate --elite 8 --hard 8
```
