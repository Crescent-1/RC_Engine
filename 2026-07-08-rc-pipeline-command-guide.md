# RC Pipeline — Command Guide (by scenario)

A task-oriented cheat sheet: find your scenario, run the command. Everything runs **from the project folder** (`RC Gen Project`).

Two engines share the same database (`rc_pipeline.db`):

- **`rc_engine`** — the current engine. Subcommands, cost caps, novelty gates, health/vet tooling. Use this by default.
- **`RC_PIPELINE.py`** — the legacy monolith. Still works, still writes to the same DB. Use only if you specifically want the old single-file flow.

`$0` next to a command means it makes no API calls and costs nothing.

---

## 0. One-time setup

```bash
# API key must be set before any REAL generation (put it in .env — already gitignored)
# .env contains:  ANTHROPIC_API_KEY=sk-...

# install deps
pip install anthropic python-docx openpyxl --break-system-packages
```

Before your first real batch, run these once, in order:

```bash
python -m rc_engine.cli selftest     # $0 — validates config + component libraries end-to-end
python -m rc_engine.cli backfill     # $0 — loads your existing corpus so novelty checks work
python -m rc_engine.cli generate --elite 1   # ~$0.15 live smoke test (hard cap $0.30)
```

Inspect that one RC and its notes, then scale up.

---

## 1. Get / refresh source essays (RAG)

Essays are the seeds. They live in the Chroma vector store (`essay_rc_db/`) and are pulled from RSS feeds (Aeon, Psyche, Nautilus, Smithsonian, JSTOR, etc.).

```bash
# Fetch new essays from all feeds and add unused ones to the vector store
python RAG.py
```

Each essay is marked `used` the moment an RC is generated from it, so it's never picked again. If a generation run says it's out of unused essays, run `python RAG.py` to top up.

> The `essay_rc_db/` folder is gitignored and fully regenerable — re-run `python RAG.py` to rebuild it.

---

## 2. Generate RC sets (current engine)

General form:

```bash
python -m rc_engine.cli generate --medium N --hard N --elite N [flags]
```

| You want… | Command |
|---|---|
| 8 elite + 8 hard, each from a different fresh essay | `python -m rc_engine.cli generate --elite 8 --hard 8` |
| Just 5 medium | `python -m rc_engine.cli generate --medium 5` |
| A single live smoke test | `python -m rc_engine.cli generate --elite 1` |
| Set an explicit spend cap for the batch | `python -m rc_engine.cli generate --elite 8 --max-usd 2.00` |
| Dry run — full pipeline, **$0**, mock client, separate DB/export | `python -m rc_engine.cli generate --dry-run --elite 2` |
| Generate without RAG seed essays (seedless) | `python -m rc_engine.cli generate --elite 4 --no-seed` |
| Skip the embedding novelty channel (faster) | `python -m rc_engine.cli generate --elite 4 --no-embed` |
| Generate but don't auto-export | `python -m rc_engine.cli generate --elite 4 --no-export` |
| Write to a non-default database | `python -m rc_engine.cli generate --elite 4 --db my_test.db` |

**Cost safety is built in:** every call is checked against a per-RC hard cap (medium $0.12 / hard $0.22 / elite $0.30) before it runs, and the batch stops once cumulative spend hits `--max-usd` (default = 1.25× the sum of requested tier budgets). If the API rate-limits or runs out of credit mid-batch, the run stops cleanly — finished work is already saved. **Just re-run the same command to continue**; used essays are skipped automatically.

---

## 3. Generate RC sets (legacy engine)

Same tiers, simpler flags — no cost caps or novelty gates.

| You want… | Command |
|---|---|
| 8 hard + 8 elite, each from a different essay | `python RC_PIPELINE.py --hard 8 --elite 8` |
| Just 5 medium | `python RC_PIPELINE.py --medium 5` |
| One of each tier from the **same** essay (difficulty comparison) | `python RC_PIPELINE.py --compare` |
| Generate but skip the auto-export | `python RC_PIPELINE.py --medium 5 --no-export` |

Legacy runs auto-export everything in the DB to `.txt` + a combined `rc_batch.docx` when they finish (unless `--no-export`).

---

## 4. Manual RC sets (write by hand, then vet)

For RCs you generate manually via `MANUAL_GENERATION_PROMPT.md` instead of the pipeline.

```bash
# $0 — get a paste-ready "AVOID" line (last N shipped sets) to drop into the manual prompt,
#      so your hand-written RC doesn't repeat recent structures
python -m rc_engine.cli avoid --n 4

# $0 — run the free quality gates on a manual RC .txt (novelty vs corpus, answer-letter
#      balance, length bias). Add --tier to also check passage word count for that band.
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260708-1.txt --tier elite

# same, but on pass store it in the corpus (source='manual') so novelty stays in sync
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260708-1.txt --tier elite --ingest

# force ingest even if there are warnings/breaches
python -m rc_engine.cli vet manual_rc_sets/RC-MANUAL-260708-1.txt --ingest --force
```

---

## 5. Export sets to files

```bash
# current engine — export by status
python -m rc_engine.cli export --status approved
python -m rc_engine.cli export                       # everything, default folder exported_rc_sets/
python -m rc_engine.cli export --status approved --out my_folder

# legacy engine auto-exports on every run; to force it, just run any legacy command
# without --no-export
```

---

## 6. Check corpus health

```bash
# $0 — family/topology drift, answer-letter chi-square balance, corpus snapshot
python -m rc_engine.cli health

# $0 — per-tier cost table: typical cost, worst case, enforced cap
python -m rc_engine.cli estimate
```

---

## 7. Update the tracker spreadsheet

`RC_Tracker.xlsx` is a reporting view rebuilt from the DB. Your manual columns
(**Shared to Institute / Shared On / Remarks**) are preserved across rebuilds, matched by `RC_ID`.

```bash
python build_tracker.py
```

Re-run any time after generating to refresh counts, costs, and shipped totals.

---

## 8. Preview the portfolio / website locally

```bash
# serve the portfolio on http://localhost:8734
python -m http.server 8734 --directory portfolio

# or the website folder
python -m http.server 8734 --directory website
```

---

## 9. After editing config or component libraries

Any time you change `rc_engine/config.py` (budgets, models, token limits) or add/edit a
`rc_engine/components/*.json` file (families, personas, endings, etc.), run the pre-flight check:

```bash
python -m rc_engine.cli selftest     # $0 — must pass before you generate again
```

Adding a new family/persona/topology needs **no code change** — just edit the JSON and re-run `selftest`.

---

## Status meanings (what the engine tags each set)

| Status | Meaning |
|---|---|
| `approved` | Passed everything; sellable after normal review |
| `needs_review` | Complete but judge score < 7, low compliance, or a stage was budget-skipped (notes say which) |
| `solver_dispute` | Blind solver disagreed with the answer key; a human decides |
| `rejected_novelty` | Structurally too close to an existing RC; auto-recomposed up to 3× |
| `budget_abort` | Cap would have been exceeded; nothing shipped, spend still logged |

---

## Quick troubleshooting

- **"Out of unused essays"** → `python RAG.py` to fetch more seeds.
- **A batch died mid-run (rate limit / credits)** → re-run the exact same `generate` command; used essays are skipped, so you resume where you stopped.
- **Novelty gate keeps rejecting** → you likely haven't loaded history: run `python -m rc_engine.cli backfill` once, or loosen `NOVELTY_CAPS` / `MIN_COMPOSITE_NOVELTY` in `config.py`.
- **Want to test logic without spending** → add `--dry-run` (writes to a separate DB and export folder, never touches production data).
- **Tracker shows stale numbers** → re-run `python build_tracker.py`.

---

*Full engine internals and stage-by-stage behavior: see `RC_ENGINE_README.md`, `ENGINE_WALKTHROUGH.md`, and `ARCHITECTURE_REDESIGN.md`.*
