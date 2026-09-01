# RC Gen Project

Generates CAT-style Reading Comprehension sets (passage + 6 MCQs) for a
paying test-prep client. `rc_engine/` is the production engine; everything
else in the root is docs, exports, the GUI, or legacy. Full operations guide:
`RC_ENGINE_README.md`; scenario cheat-sheet: `2026-07-08-rc-pipeline-command-guide.md`.

## Hard rules

- **Never delete or move files without explicit approval in the same
  conversation.** This includes anything under `exported_rc_sets/` (shipped
  client deliverables), `manual_rc_sets/`, the trackers, and the DB. Git
  history is not a substitute for asking.
- **Real generation costs money.** Only run `generate` without `--dry-run`
  when asked to. `--dry-run` uses the mock client, a separate DB
  (`rc_engine_dryrun.db`) and a separate export folder; it is always safe.
- **The DB lives in a OneDrive-synced folder by decision.** Do not propose
  relocating the project or the DB. Every real run backs the DB up to
  `~\rc_data\backups\`. Do not switch SQLite to WAL mode here: the sync client
  would upload `-wal`/`-shm` files mid-write.
- `.env` holds the API keys and is gitignored. Never print or commit it.
- The novelty gates are calibrated against the shipped corpus. Do not loosen
  a cap in `config.NOVELTY_CAPS` to make a batch pass; measure first with
  `health` and the attempts table.

## Commands (run from this folder)

```bash
python -m pytest tests -q                          # ~70 s, no API calls
python -m rc_engine.cli selftest                   # $0 config + libraries check
python -m rc_engine.cli generate --dry-run --hard 2 # $0 end-to-end on the mock
python -m rc_engine.cli health                     # corpus drift, window mix, batch yield
python -m rc_engine.cli estimate                   # per-tier cost table
python -m rc_engine.cli export --status approved
python -m gui                                      # web console on :8730
```

Run `selftest` and the test suite after any change to `rc_engine/config.py`
or a component library. Add a test for every behaviour change; the suite in
`tests/` is the spec.

## Layout

| Path | What |
|---|---|
| `rc_engine/pipeline.py` | `generate_one` (stages + gates) and `run_batch` (retry loop, cost cap, attempts table) |
| `rc_engine/config.py` | every lever: models, budgets, novelty caps, windows, backoff |
| `rc_engine/novelty.py`, `fingerprints.py` | pairwise novelty channels and the corpus window |
| `rc_engine/history.py` | SQLite store: `rc_sets`, `blueprints`, `fingerprints`, `novelty_audits`, `attempts` |
| `rc_engine/llm.py`, `providers.py` | Claude / OpenAI / Gemini clients, cost ledger, backoff |
| `rc_engine/cli.py` | all subcommands |
| `gui/` | FastAPI console; reads the DB read-only, runs the CLI in subprocesses |
| `RAG.py` | RSS seed sync into the Chroma store `essay_rc_db/` (optional deps) |
| `RC_PIPELINE.py`, `rc_pipeline_old.py` | legacy monolith, kept for reference only |

## Conventions

- Dated, reasoned comments are the house style: say what was measured and
  when a lever was set, not just what it does.
- Files are LF (`.gitattributes`). Commit engine changes and export batches
  separately.
- Branch off `master`; `master` is what the client-facing batches ship from.
- Statuses: `approved` / `needs_review` / `solver_dispute` are shipped;
  `rejected_*` and `failed_*` are not. `solver_dispute` and `rejected_novelty`
  sets are hidden from the novelty window (`NOVELTY_WINDOW_EXCLUDE_STATUSES`).
