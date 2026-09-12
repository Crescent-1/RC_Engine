# Codex change log

This file records completed project changes and their validation. New entries
go first; dates use Asia/Calcutta time. `AGENTS.md` instructs Codex to update this
file whenever it changes project files. Entries are task summaries, not a record
of every intermediate edit. Git remains the source for exact diffs.

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
