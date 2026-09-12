# RC Pipeline — Command Guide (by scenario)

A task-oriented cheat sheet: find your scenario, run the command. Everything runs **from the project folder** (`RC Gen Project`).

Two engines share the same database (`rc_pipeline.db`):

- **`rc_engine`** — the current engine. Subcommands, cost caps, novelty gates, health/vet tooling. Use this by default.
- **`RC_PIPELINE.py`** — the legacy monolith. Still works, still writes to the same DB. Use only if you specifically want the old single-file flow.

`$0` next to a command means it makes no API calls and costs nothing.

---

## 0. One-time setup

```bash
# API keys must be set before any REAL generation (put them in .env — already
# gitignored; the engine and GUI load .env automatically). One line per provider:
#   ANTHROPIC_API_KEY=sk-...        (claude — default)
#   OPENAI_API_KEY=sk-...           (openai)
#   GOOGLE_API_KEY=...              (gemini; GEMINI_API_KEY also works)

# install deps (see requirements.txt for the full pinned list)
pip install -r requirements.txt
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
| Run on OpenAI instead of Claude | `python -m rc_engine.cli generate --hard 4 --provider openai` |
| Run on Gemini instead of Claude | `python -m rc_engine.cli generate --hard 4 --provider gemini` |
| Price a batch for a provider before running | `python -m rc_engine.cli estimate --provider gemini` |

**Providers:** one per run (`--provider claude|openai|gemini`, default claude);
`retry-questions` takes the same flag. Model IDs and rates are the EDITABLE
`PROVIDER_MODELS` / `MODEL_RATES` dicts in `rc_engine/config.py` — after editing,
run `estimate --provider X` and `selftest`. The per-tier hard caps apply to every
provider identically.

**Cost safety is built in:** every call is checked against a per-RC hard cap (medium $0.12 / hard $0.22 / elite $0.30) before it runs, and the batch stops once cumulative spend hits `--max-usd` (default = 1.25× the sum of requested tier budgets). If the API rate-limits or runs out of credit mid-batch, the run stops cleanly — finished work is already saved. **Just re-run the same command to continue**; used essays are skipped automatically.

---

## 2b. Clients — a fresh start per institute (2026-09-12)

Every existing set belongs to the founding client **AA**, which is the default.
A new client gets its own novelty window: families, beats, movement, usage decay,
seed genre and the similarity screen all start empty for it. Argument skeletons
and seed essays stay **exclusive across clients**, so no two institutes ever
receive the same structure.

| You want… | Command |
|---|---|
| Add a client ($0) | `python -m rc_engine.cli client add BB --name "Second institute"` |
| See clients and shipped counts ($0) | `python -m rc_engine.cli client list` |
| Try the new client at $0 first | `python -m rc_engine.cli client add BB --db rc_engine_dryrun.db` then `python -m rc_engine.cli generate --dry-run --client BB --hard 2` |
| Generate for a client | `python -m rc_engine.cli generate --client BB --hard 4` |
| That client's health, plus the cross-client exclusivity audit ($0) | `python -m rc_engine.cli health --client BB --all` |
| Export a client's sets (goes to `exported_rc_sets/BB/`) | `python -m rc_engine.cli export --client BB --status approved` |
| Resume a client's stranded passages | `python -m rc_engine.cli retry-questions --client BB --all` |
| AVOID line / vet a manual set for a client | add `--client BB` to `avoid` or `vet` |

Leaving out `--client` means AA, so every command above behaves exactly as it did
before. A typo in the slug stops the command; it never runs against an empty
corpus. In the GUI, pick the client in the sidebar before doing anything else.

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

## 4b. The similarity screen (pre-export)

After generation and before export, a cheap model reads each new passage beside
the last 10 shipped ones and asks whether a person would notice the repetition.
It judges **shape** — how the argument opens, where it turns, how it closes —
and explicitly ignores topic overlap, because two passages on unrelated subjects
can still be the same essay.

- **green** -> exports normally to `exported_rc_sets/`
- **red** -> exports to `exported_rc_sets/flagged_similar/` for a human look
- **unchecked** -> the screen could not run; the set exports normally and says so

It routes; it never blocks, deletes, or changes a set's status.

```bash
# runs automatically with every generate; to skip it:
python -m rc_engine.cli generate --elite 2 --no-screen
```

Pinned to its own provider and model (`gpt-5.6-luna`) independent of
`--provider`, on purpose: asking the model that wrote the passage whether the
passage is repetitive asks the judgement that produced the sameness to notice
it. **Needs `OPENAI_API_KEY` in `.env` and `pip install openai`** — without
them every set comes back `unchecked` and exports normally.

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

`health` also reports **move saturation** — how often each rhetorical move shows
up in the trailing corpus. Any move above 55% is automatically banned in new
render contracts; anything above 40% is flagged. This is the house-voice metric:
when the first audit ran (2026-08-21) `LEVEL_RELOCATION` was in 96% of 85
shipped sets and `EASY_READING_DEMOLISHED` in 86%.

### Rhetorical-move audit

Every passage gets a blind rhetorical-move signature — a sequence like
`SCENE_PARTICULAR > TWO_CAMP_SPLIT > LEVEL_RELOCATION > HEDGED_APHORISM` read
off the prose by a cheap model that is never shown the blueprint. It is the only
channel that measures the passage's *argumentative choreography* rather than its
plan, its topic, or its sentence statistics.

```bash
# extract signatures for any set that lacks one, then report ($0 for sets already done)
python -m rc_engine.cli move-audit

# report on what is already stored, no API calls
python -m rc_engine.cli move-audit --report-only

# also drop near-duplicate sets from the NOVELTY BASELINE (nothing is deleted;
# rows, statuses and exported files are untouched — it only hides them from the
# window new renders are scored against, keeping one set per cluster)
python -m rc_engine.cli move-audit --quarantine
```

> Read the cluster report before running `--quarantine`. Note that the pair which
> prompted this whole channel scored at the corpus *median* — a pairwise gate is
> a backstop here, not the cure. The cure is the saturation bans above.

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

## 9. The GUI (everything above, in a browser)

```bash
python -m gui          # or double-click run_gui.bat
```

Opens **http://127.0.0.1:8730** — a local web console with: dashboard (counts,
spend, recent RCs, health), generate (tier steppers, provider dropdown, dry-run,
live log console with a Stop button), resume queue, RC library with full-text
viewer and export, manual-RC vetting + AVOID line, corpus-health trends, seed
inventory by genre and source with one-click feed sync, tracker rebuild, and a
read-only settings view (API keys shown only as present/missing). It reads the
DB read-only and runs every action through the CLI, so all cost caps and resume
mechanics apply unchanged. Localhost only.

---

## 10. After editing config or component libraries

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
