# RC_ENGINE_DEV — cheap-first sandbox

Isolated from production `rc_engine/`. **Do not confuse the two.**

| | Production `rc_engine/` | **This folder** |
|--|------------------------|-----------------|
| Goal | Structural factory (multi-stage) | Cheap + quality experiments |
| Default path | render → compliance → questions | **One fullset call** (passage + Qs) |
| DB | `rc_pipeline.db` (project root) | `RC_ENGINE_DEV/rc_engine_dev.db` |
| Code edits | Untouched | Safe to change here |

## Architecture (cheap mode)

```
compose (free) → refine (cheap) → topology precheck (free re-pick)
  → topic precheck (1 re-refine max)
  → ONE fullset LLM call  (passage + 6 MCQs)
  → free novelty (persona_leak / rhythm / curve = soft → needs_review)
  → judge (optional) → ship
```

Factory mode (`--mode factory`) keeps the multi-stage path for audits.

## Commands

```powershell
cd "C:\Users\anshu\OneDrive - eLitmus\RC Gen Project\RC_ENGINE_DEV"

# $0 checks
python -m rc_engine.cli selftest
python -m rc_engine.cli estimate

# live cheap generation (uses parent .env for ANTHROPIC_API_KEY)
python -m rc_engine.cli generate --elite 1 --hard 1 --medium 1

# against production corpus fingerprints (shared novelty window)
python -m rc_engine.cli generate --hard 2 --db ..\rc_pipeline.db

# multi-stage factory (expensive; parity with production)
python -m rc_engine.cli generate --elite 1 --mode factory
```

Exports go to `RC_ENGINE_DEV/exported_rc_sets/`.

## Cost targets (typical happy path)

| Tier | Cheap | Factory (ref) |
|------|-------|-----------------|
| medium | ~$0.06 | ~$0.07 |
| hard | ~$0.12–0.18 (**Opus** fullset + optional Sonnet length-fix) | ~$0.19 |
| elite | ~$0.17 (1× Opus) | ~$0.15+ dual Opus + more rejects |

## Quality patches (v0.2)

1. Fullset prompt: length parity hard rules (correct longest ≤2/6; spread ≤8).
2. If still length-biased → **questions-only** Sonnet rewrite (`length_fix`), keep passage.
3. Novelty/topic/topology reads from production **`../rc_pipeline.db`** (`CORPUS_DB_PATH`) while writes stay on `rc_engine_dev.db`.

## Knobs (`rc_engine/config.py`)

- `DEFAULT_MODE` — `cheap` | (cli `--mode factory`)
- `QUALITY_OPUS_HARD` — hard fullset model (default True = Opus)
- `CHEAP_LENGTH_FIX` — questions-only repair on length bias
- `CORPUS_DB_PATH` — production corpus for novelty window
- `MAX_SLOT_ATTEMPTS = 1` — no recompose storm
- `SOFT_NOVELTY_BREACH_PREFIXES` — stylometry etc. → review, not reject
- `CHEAP_RUN_SOLVER` / `CHEAP_RUN_JUDGE`
- `TIER_BUDGET_USD`

## What stays for quality

- Blueprint libraries (family / persona / topology / …)
- Free topology + topic prechecks before the big call
- Letter plan assigned locally (anti letter-bias)
- Fingerprints written so the next RC stays diverse
- Soft novelty flags still surface in `needs_review`

Production code under `../rc_engine/` was reverted and is unchanged by this sandbox.
