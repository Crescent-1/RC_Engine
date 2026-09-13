# Codex change log

This file records completed project changes and their validation. New entries
go first; dates use Asia/Calcutta time. `AGENTS.md` instructs Codex to update this
file whenever it changes project files. Entries are task summaries, not a record
of every intermediate edit. Git remains the source for exact diffs.

## 2026-09-13 — CAT PYQ evidence baseline (plan section 2), by Claude Code

- Completed section 2 of `2026-09-13-cat-pyq-implementation-plan.md`.
- Added `tools/cat_pyq/`:
  - `parse_pyq.py`: page-aware parse; PYQ text written only outside the repo.
  - `question_records.py`: task and polarity labelled independently; all 390
    stems hand-reviewed; 73 recorded overrides.
  - `engine_baseline.py`: read-only, `mode=ro`; per tier, planned vs realised;
    shipped stems scanned with the same polarity rules.
  - `build_baseline.py`: one thesis rubric applied to all 90 passages.
- Outputs: `2026-09-13-cat-pyq-baseline.json` (text-free) and
  `2026-09-13-cat-pyq-baseline.md`.
- Added correction notices, without rewriting the earlier text, to
  `2026-09-13-cat-pyq-engine-analysis.md` and
  `2026-09-13-cat-pyq-findings-handoff.md`.
- Corrected findings:
  - 390 questions (per passage 4.8/4.8/4.8/4.5/4.0/4.0/4.0/4.0), not the
    report's 6.3–4.3.
  - Negation: 35.6% of stems, 41.5% in 2020–24; multiple negation 4.1%.
  - Shipped engine stems ~7% negated (0.5 per set); the gap holds.
  - Planned thesis by paragraph 2: medium 52.8%, hard 44.9%, against 74.4% of
    thesis-bearing PYQs. The "10% early" claim was a label artefact.
  - The stored compliance thesis read is plan-anchored (`compliance.py:121-122`).
    A blind 12-set medium/hard check found 10/12 early, so do not activate
    early-thesis weights yet.
  - Planned refusal: medium 16.7%, hard 30.6%; realised closure uncertain.
- Added `tests/test_cat_pyq_tools.py` to pin the classifier corrections.
- Validation:
  - `python -m pytest tests -q`: 299 passed (the earlier `feedparser` failures
    no longer occur in this environment).
  - Parser re-run is byte-identical; words and paragraph counts match the first
    analysis on all 90 passages; JSON checked text-free.
  - `selftest` not run: no engine config or library change.
- Limits:
  - Single reader for overrides, rubric and the 12-set check.
  - Engine baseline is client AA as of this date at `23e3d49`.
  - No paid extractor run. No engine code, production data or exports changed.
- Changes are uncommitted.

## 2026-09-13 — CAT PYQ implementation plan with elite preserved

- Added `2026-09-13-cat-pyq-implementation-plan.md` for the requested medium/hard
  implementation, incorporating the analysis review and the instruction that
  elite stays unchanged. Staged evidence repair, policy isolation, question
  contracts, passage compatibility/rendering, and source-supported facts.
- Specified elite prompt/pool/RNG regression checks, legacy resume, rolling mock
  validation, provisional calibration objectives, and a separately authorized
  paid pilot. No engine code, production data, or exports changed.
- Validation: inspected current composition, compatibility, question, extraction,
  topology fallback and model contracts; checked documentation whitespace and
  file readback. Documentation only; no engine tests or paid calls ran.
- Limits: this is an implementation plan, not a completed implementation or a
  verified CAT calibration. Changes are uncommitted.

## 2026-09-13 — Soft-launch voice observations after review

- Corrected the earlier hard voice gate after the user reported that its rules
  flagged all 30 recent AA ships, including all five approved sets. Removed
  approval-status changes from both `pipeline.py` and `HistoryStore.record_voice_review`.
  Reasons remain recorded; existing quality and novelty gates still apply.
- Removed voice-review blocks from client exports, including `clear`. Export
  no longer reads the review JSON, so malformed review data cannot crash it.
- Made the renderer follow the topic shape when both material fields arrive:
  two-pole and legacy tension plans retain their poles, with the frame used as
  supporting material. Non-bipolar shapes continue to use the content frame.
- Added one console review item per flagged sibling pair, plus GUI guidance to
  compare both and retain the stronger usable set when appropriate. Preserved
  both screen verdicts and existing export routing; no automatic discarding.
- Health now prints observed flag counts and distinguishes unchecked sets.
  Updated `RC_ENGINE_README.md` to describe the observational launch and pilot.
- Validation: 287 tests passed, two skipped; the same three RAG tests failed
  on the missing `feedparser` dependency. Selftest, JavaScript syntax and
  whitespace checks passed. Tests cover unchanged approval for schema/closing
  deviations and unknown reads, malformed export metadata, mixed material fields,
  reciprocal sibling flags and client-scoped health counts.
- Limits: no paid pilot ran and no production data or existing exports were
  modified. The earlier renderer changes had mock tests, not a real prose-quality
  evaluation. S3/S8 stance pools remain narrow pending compatible designs and
  evidence; novelty caps are unchanged. Historical statuses are not auto-restored.
- Commit: `0f6abfe` — Soft-launch voice review as observation and keep QA notes
  out of exports. This entry supersedes the status-gating and client-export
  behavior described in the original house-voice entry below.

## 2026-09-13 — Persistent change tracking

- Created `codex.md` and backfilled the recent checkpoint and house-voice work.
- Added root `AGENTS.md` so future Codex tasks read the project rules and update
  this log before finishing changes.
- Validation: checked the existing project rules and Git history; documentation
  only, so no code tests were needed.
- Commit: committed together with this log's first tracked version (see Git
  history for `AGENTS.md`).

## 2026-09-13 — House-voice planning and independent review

- Aligned schema, family, stance, paragraph beats and closing instructions before
  refinement. Both refinement and rendering now receive the reasoning schema and
  beat allocation; non-bipolar content frames reach the renderer.
- Added compatibility rules in `rc_engine/voice_plan.py` and a plan-version field.
  Preserved legacy blueprint loading and existing novelty caps.
- Changed schema recency feedback to use realized primary schemas rather than
  planned labels, with client-scoped history and softer other-client pressure.
- Added persisted voice-review reasons and routing to `needs_review`, independent
  of high aggregate scores. Solver disputes retain their status. Reasons appear
  in console output, the GUI's passage detail and subsequent text exports.
- Expanded similarity-screen references to include older structural neighbours
  and completed-batch siblings within the existing reference limit and budget.
- Added health reporting by plan version, regression tests, test-database
  isolation, and documentation in `RC_ENGINE_README.md` and
  `HOUSE_VOICE_REVIEW_2026-09-12.md`.
- Main areas: `rc_engine/composer.py`, `renderer.py`, `history.py`, `pipeline.py`,
  `similarity_screen.py`, `models.py`, `cli.py`, `gui/static/app.js`, and tests.
- Validation: 275 tests passed, two skipped; three existing RAG tests failed
  because the runtime lacked `feedparser`. Selftest and JavaScript syntax checks
  passed. All 126 mocked composition trials against a temporary corpus copy
  succeeded at $0. Final focused checks passed 33 tests.
- Limits: no paid generation or blinded prose-quality pilot ran. The replay used
  a frozen corpus; it did not simulate 126 newly shipped passages. Production
  data and existing exports were untouched by these improvements.
- Commit: `3828e9c` — Align house-voice plans and persist independent voice review.

## 2026-09-12 — Checkpoints before house-voice changes

- Saved the existing code, client-isolation work, generation controls, Passage
  Works sites and house-voice review before starting the improvements.
- Saved the September 12 exports and reconciled delivery records separately.
- These were checkpoints of work already present, not a claim that all earlier
  code-review findings had been resolved.
- Commits: `cede664` — Checkpoint client isolation, generation controls, and
  Passage Works sites; `e63b9c5` — Checkpoint September 12 exports and reconciled
  delivery records.
