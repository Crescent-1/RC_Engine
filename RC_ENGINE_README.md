# rc_engine — Operations Guide

Production implementation of the architecture in `ARCHITECTURE_REDESIGN.md`.
Legacy `RC_PIPELINE.py` is untouched and still works; both write to the same
`rc_pipeline.db` (the engine adds its own tables and keeps `rc_sets` compatible).

## Voice planning and observational review (updated 2026-09-13)

New blueprints carry `voice_plan_version=2026-09-12`. After source-shape selection,
the composer chooses an eligible reasoning schema before selecting the family
and stance. Refinement and rendering both receive that schema and the paragraph
beat allocation. A non-bipolar `content_frame` survives into rendering. Endings,
closing beats and surface registers are sampled together for compatibility.
`rc_engine/voice_plan.py` records the eligibility rules; existing novelty caps
and tier restrictions still apply. Legacy saved blueprints remain resumable.
If refinement supplies both content fields, two-pole topic shapes retain their
tension system and use the frame as supporting material. Non-bipolar shapes
use the frame; legacy plans without a topic shape retain existing poles.

Schema recency pressure now uses **realized primary schemas** from shipped
passages, scoped to the client, with a softer other-client pressure. Unknown
reads do not count as successful execution of the plan. Compatibility and
recency condition the configured exam weights: they do not guarantee that
shipped frequencies equal the reference distribution. F30 and F37 remain in
the library but have no compatible fit among the current eight schemas.

After questions, a separate `voice_review_status` / `voice_review_json` records
schema, opening, closing, body-plan and commitment deviations. During this
observational launch, these reasons do **not** change the set's approval status.
The existing compliance, novelty, length and question-quality checks still apply.
Missing move/schema reads remain visible as unknowns. This adds no extraction
calls or automatic re-renders. `review` means observations were recorded, not
that the set must become `needs_review`; `clear` is not a human quality approval.
Reasons appear internally in the console and library detail, never in exported
client text. Export does not read or parse the voice-review JSON.

This supersedes the initial 2026-09-12 status gate: the user's read-only replay
reported flags on all 30 recent AA ships, including all five approved sets.
The old-plan cohort cannot establish new-plan precision, but it is sufficient
reason not to use these rules as an additional approval gate yet.

The reader screen selects up to the existing `compare_n` reference count from
recent sets, older structural neighbours, and completed-batch siblings. It
uses a fixed per-client snapshot and saves reference IDs with each result.
For large batches it selects the closest siblings rather than testing every
pair. The screen retains its existing red-to-flagged-folder routing and budget.
Reciprocal sibling reds are listed once as a pair for review. Compare both and
retain the stronger usable set when appropriate; repetition alone does not
justify dropping both. No set is automatically selected, deleted or regraded.

`python -m rc_engine.cli health --client AA` separates legacy/new plan cohorts and shows
measured counts and primary/secondary schema and beat agreement. Blank review
fields on old sets mean unreviewed, not clear. It also reports observed voice
flags with checked/unreviewed counts. No historical production records
are backfilled by this change. `pytest` isolates legacy default-DB tests in a
temporary database before collection.

Validation uses mocked model calls. A blinded, matched-seed pilot remains
necessary to establish whether the passages actually sound more varied without
reducing readability or question quality; no paid pilot has been run.
For the first explicitly requested paid pilot, save pre/post health snapshots,
inspect flagged and unflagged prose, and compare schema/beat obedience,
unplanned moves, readability, question validity, novelty rejection rate and
cost per usable set. Do not recalibrate novelty caps from that small batch alone.
The S3 schema still supplies its own stance and S8 still uses RS09. These narrow
pools are a known diversity constraint; expanding them requires compatible
stance designs and evaluation, rather than silently relaxing their restrictions.

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

# REAL generation (needs the selected provider's API key). Seeds pull from
# RAG.py if available, else runs seedless.
python -m rc_engine.cli generate --elite 8 --hard 8
python -m rc_engine.cli generate --elite 8 --max-usd 2.00   # explicit batch cap
python -m rc_engine.cli generate --hard 4 --provider openai # non-Claude run
python -m rc_engine.cli generate --hard 6 --elite 6 --workers 3 # parallel (2-3 is the useful range)

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

## Providers (one per run)

The engine runs against **Claude (default), OpenAI, or Gemini** — pick one per
run with `--provider {claude,openai,gemini}` on `generate`, `retry-questions`,
and `estimate` (or the provider dropdown in the GUI). Each provider maps three
model roles (big / mid / small) onto the same stage plan; the per-tier budget
caps and the pre-call cost guard apply identically.

- **API keys** (environment or the project `.env` file, which is now loaded
  automatically): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GOOGLE_API_KEY`/`GEMINI_API_KEY`.
- **Models and $/Mtok rates** live in the EDITABLE `PROVIDER_MODELS` and
  `MODEL_RATES` dicts in `rc_engine/config.py`. After any change, run
  `estimate --provider X` (happy path must fit every tier budget) and `selftest`.
- Each shipped RC records its provider in the `rc_sets.provider` column.
- Provider clients live in `rc_engine/providers.py`; `--dry-run` uses the $0
  mock regardless of provider.

## GUI

`python -m gui` (or double-click `run_gui.bat`) starts a local web console at
**http://127.0.0.1:8730** covering the full surface: dashboard, generate with
live log streaming, resume queue, RC library, manual-RC vetting, corpus
health, seed inventory (by genre and source), tracker rebuild, and settings.
The GUI reads the DB strictly read-only and runs all actions through the CLI
in subprocesses, so every cost guarantee below applies unchanged. API keys are
shown as present/missing only — edit `.env` by hand and restart to change them.

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
   $0.15, medium ≈ $0.07. A **Gate-B** (passage-level) novelty rejection aborts
   *before* the expensive question call, so it costs ≤ ~$0.09; a **Gate-C**
   (full) rejection has already paid for questions and costs close to the full
   happy path.
4. **API exhaustion** (rate limit / credits) stops the batch cleanly; finished
   work is already committed. Re-run the same command to continue.
5. **Question failures don't re-pay for passages**: once a passage clears the
   passage-level novelty gate it is persisted (`rendered_passages`); if the
   question stage then fails, the batch retries questions-only on the same
   passage, and `retry-questions` can resume it later. Prior spend still
   counts against the tier cap — the per-RC guarantee is unchanged.

## DB safety

`rc_pipeline.db` lives in a OneDrive-synced folder; live sync + SQLite is a
known corruption risk. Every real `generate` run and `vet --ingest` therefore
backs the DB up (SQLite online-backup API + `PRAGMA integrity_check`) to a
local non-synced folder — default `%USERPROFILE%\rc_data\backups\`, override
with `RC_ENGINE_BACKUP_DIR`; the newest 10 are kept.

## Clients (added 2026-09-12)

One DB serves every client. Sets, blueprints, fingerprints, rendered passages,
attempts and health snapshots each carry a `client_id`. Everything that existed
before 2026-09-12 belongs to the founding client **AA**: the column default
migrated it on first open, and a pre-migration copy is in the backups folder as
`pre-multiclient-rc_pipeline-*.db`.

| Scope | What |
|---|---|
| **Per client** (a new client starts fresh) | novelty window and every gate channel, exclusion windows, usage decay, posture runs, move saturation, seed-genre saturation, seed ancestry, topic precheck, similarity screen, in-flight holds, resume queue, attempts/yield, `health` |
| **Global** (structural exclusivity) | shipped argument skeletons (`combo_hash`; the `ux_shipped_combo` unique index refuses a second ship), seed essays (RAG `used` flag plus a ship-time check against other clients), rc ids, the ship lock |
| **Soft global term** | components and rhetorical moves recently given to *other* clients get a gentle pull-away (`GLOBAL_*` in `config.py`). An exact no-op while one client exists |

```bash
python -m rc_engine.cli client add BB --name "Second institute"
python -m rc_engine.cli client list
python -m rc_engine.cli generate --client BB --hard 4
python -m rc_engine.cli health --client BB --all        # + cross-client exclusivity audit
python -m rc_engine.cli export --client BB --status approved   # -> exported_rc_sets/BB/
```

- `--client` works on `generate`, `retry-questions`, `health`, `export`, `avoid`, `vet`,
  `backfill` and `move-audit`. The default is `AA`, or `RC_ENGINE_CLIENT` if set. An
  unknown client is an error, never an empty corpus: an empty window auto-passes
  novelty.
- Dry runs use `rc_engine_dryrun.db`, so add the client there too:
  `client add BB --db rc_engine_dryrun.db`.
- For clients other than AA, `backfill` and `move-audit` have no default `--from-txt`,
  because the defaults are AA's delivery folders. Pass the new client's own folders
  explicitly.
- AA keeps the top-level `exported_rc_sets/` layout. The trackers (`build_tracker.py`,
  `build_shipping_tracker.py`) cover AA only.
- The legacy `RC_PIPELINE.py` does not know about clients; its rows default to AA.
- GUI: the sidebar client picker scopes every page, job and export.

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
- Length-bias: per set, the correct option may be strictly longest in at most 2
  of 6 questions (`CORRECT_LONGEST_MAX`). Corpus-wide, the **thesis** question's
  correct option may be strictly longest in at most 1 of every 3 keyed sets
  (`THESIS_LONGEST_WINDOW`/`THESIS_LONGEST_MAX`); breaches surface as corpus
  flags in `generate`, `vet`, and `health`.
- After ANY edit: `python -m rc_engine.cli selftest` (it is the pre-flight check).

## First production run (recommended sequence)

```bash
python -m rc_engine.cli selftest          # must pass
python -m rc_engine.cli backfill          # once, so history is loaded
python -m rc_engine.cli generate --elite 1   # single live smoke test (≈ $0.15, hard cap $0.30)
# inspect the exported RC + its notes, then scale up:
python -m rc_engine.cli generate --elite 8 --hard 8
```
