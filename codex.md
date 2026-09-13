# Codex change log

This file records completed project changes and their validation. New entries
go first; dates use Asia/Calcutta time. `AGENTS.md` instructs Codex to update this
file whenever it changes project files. Entries are task summaries, not a record
of every intermediate edit. Git remains the source for exact diffs.

## 2026-09-13 — Validation, rollout and pilot preparation (plan sections 7–8), by Claude Code

- `2026-09-13-cat-pyq-validation.md` records:
  - what exists per plan section;
  - the five required checks;
  - a seeded five-policy simulation;
  - rollout and rollback;
  - the pilot protocol with a cost estimate;
  - definition-of-done status.
- `tools/cat_pyq/pilot_review_pack.py` builds the blinded review pack.
  - It reads the DB read-only and refuses to write inside the repository.
  - It mixes pilot and legacy sets of the same tiers, strips RC ids and source
    lines, pre-lists negated questions in `review_sheet.csv`, and writes a
    separate key.
  - Tests: `tests/test_pilot_review_pack.py` (3).
- `simulate_policies.py` accepts `legacy` as a policy name, since PowerShell drops
  empty arguments; its default now covers all five policies.
- README "Generation policies" covers s1/s2/f1 and the new tools. CLAUDE.md gains
  the `policy-report` and opt-in commands, and the rule that medium/hard changes
  go into a new policy version.
- Validation:
  - `python -m pytest tests -q`: 420 passed.
  - `selftest`: passed.
  - Isolated CLI dry runs of legacy, q1, s1, s2 and f1 (f1 with `--workers 2`)
    into one scratch DB, reported by `policy-report`: all batches shipped.
  - Simulation table in the validation doc.
- Not done: the paid pilot, which needs explicit authorization, and the human
  review it feeds. Every policy stays off by default until that review.
- Known leftovers:
  - `.git/worktrees/wt3` (a stale worktree I created for the section-3 commit
    check) cannot be deleted from here: a sandbox ACL denies delete. Git warns on
    commit, harmlessly. Remove it by hand.
  - The pre-existing parallel sibling-topology race is flagged as a separate task.
- `2026-09-13-cat-pyq-engine-analysis.md` and `2026-09-13-cat-pyq-findings-handoff.md`
  stay uncommitted: they quote short PYQ fragments, and the plan keeps PYQ text out
  of git. The baseline and labels files that superseded them are committed.

## 2026-09-13 — Source-supported facts `cat-pyq-f1` (plan section 6), by Claude Code

- Registered policy `cat-pyq-f1`, cumulative on `s2`, medium and hard only,
  not enabled by default.
- `rc_engine/source_facts.py`:
  - Refine proposes at most 8 facts from the same retained excerpt it already
    reads (first 550 words). No wider scraping and no new model call.
  - Each kept fact stores an id, source URL and doc id, the excerpt's SHA-256
    digest, exact span offsets, span, claim, attribution and qualification.
  - Structural rejection when:
    - the span is not in the excerpt, or has fewer than 3 or more than 40
      words;
    - the claim adds a figure;
    - the claim drops or inverts a negation (including "denied");
    - the claim drops a hedge with no qualification;
    - the claim names someone absent from span and attribution;
    - the attribution is not near the span;
    - a quotation is altered.
- Fact beats NEWS_DATA_HOOK, STUDY_WALKTHROUGH, EXPERT_AS_SPINE and
  QUOTE_CLOSE become plannable.
  - A plan whose surviving facts cannot carry one swaps it for its
    source-independent counterpart, or drops it if that would repeat a beat or
    break the stance. Nothing is fabricated to complete a beat.
- Renderer:
  - SOURCE-SUPPORTED FACTS block in the contract.
  - Rule 9 amended by a validated rewrite. Real-reference permissions are
    kept; the block adds nothing beyond itself.
- Compliance traces every factual claim to fact ids (source_fact /
  common_knowledge / unsupported, plus attribution).
  - Unsupported claims become repair directives, an f1 −0.04 and a
    `needs_review` route.
  - `texture_report` silences a fabrication warning only when that matched
    text sits inside a traced, correctly attributed claim.
  - Fixed during testing: a suppressed first match no longer hides a later
    match of the same pattern.
- Evidence lives on the stored blueprint for resume.
  - Exports omit it.
  - Logs and notes carry only counts and rejection reasons, never source
    text.
  - Elite receives no fields, no prompt text and no extra call.
- Tests: `tests/test_source_facts.py` (19), using an invented excerpt.
  - Adversarial fixtures from the plan: altered figure, accurate substring
    used in a false claim, denied claim restated, qualification dropped,
    misattributed quotation, altered quotation, invented span, unnamed
    person; short and missing seeds; resumed plans.
  - Beat fallback, trace handling, suppression, routing, and exports/elite.
  - Elite golden with `f1` on the side. Mutation check: 7 breaks, all caught
    after strengthening the routing test.
- `simulate_policies.py --invented-seeds` feeds invented excerpts.
  - 40 medium + 40 hard under f1: shipped 37/53 and 32/73, 4 facts per set,
    fact-beat swaps 2 medium / 8 hard, 0 composition failures.
  - Hard exam-form share was 0.406 on 32 ships, against the 35% draw
    ceiling. Earlier runs gave 0.343 and 0.308, so this is within sampling
    noise but should be watched.
- Validation: `python -m pytest tests -q` 417 passed; `selftest` passed.
- Limits:
  - Entailment and attribution are semantic and rest on the compliance read;
    no deterministic check can prove a claim true.
  - The mock proposes unattributed facts, so attributed-fact beats were
    exercised only in unit tests.
  - Refine output grows (~60-80 tokens a fact) against unchanged max_tokens;
    truncation is a pilot measurement.

## 2026-09-13 — Structure releases `cat-pyq-s1` / `cat-pyq-s2` (plan section 5), by Claude Code

- Two registered policies, neither enabled by default. Both are cumulative on
  `cat-pyq-q1` and cover medium and hard only.
  - `s1` plans the first five PYQ beats and recognises all ten.
  - `s2` makes the other five plannable, so `s1` can be measured first.
- Families F59–F62, tagged. Each ships with its schema reachability, topic
  shapes, endings, revelations, closing beats and permissions:
  - F59 Backfiring Remedy: reached through S4/S5. S8 was rejected because its
    "each remedy" directive contradicts tracing one fix.
  - F60 Typology: new S9 and TS15, closing posture `exposition_neutral`.
  - F61 Framed Inquiry: hard only, new S10 and TS16, new ending E21 "The Scope
    Fixed" (bound to F61).
  - F62 Split Verdict: new S11, SPLIT_VERDICT close only.
  - New arc shapes count toward the exam-form caps (medium 50%, hard 35%).
- Closing semantics:
  - Policy overlays for ending beats, posture limits, and family-only closing
    beats (SPLIT_VERDICT only for F62/F53/F24).
  - The neutral exposition has its own label, band and render instruction,
    and is reported apart from refusal. Historical and elite passages are not
    reclassified.
- Revelations R21–R23 are tagged, and schema directives exclude contradicting
  timings.
  - The R01 audit is recorded in `families.json`: of the 16 R01-excluded
    families only F01/F04 (R23), F13 (R22, R23) and F33 (R22) can take an
    early thesis.
  - Families that withhold their thesis exclude all three.
- Rhythms T21/T22 exclude CONCESSION_TRAP padding; tested to fit 525 words.
- Personas P21–P23 carry compatible genres, drawn only for those seed genres.
  Pronouns are explicit (P22/P23 first person, within the 20% cohort), with no
  invented credential.
- Refusal objective of 14%, applied per posture category after normalising
  within each category.
  - The early-thesis timing objective is not activated: the section-2
    baseline already exceeds 40%. This is recorded in `policy_catalog.py`.
- Permissions (`passage_permissions.py`): one grant table from the plan and
  family, used by all three readers:
  - renderer: rules 7, 8 and 11 rewritten through validated anchors, plus a
    PERMISSIONS block;
  - compliance: the same block, `unpermitted_devices` turned into repair
    directives and an f1 −0.04;
  - `texture_report`: legacy scan unchanged when no grants are passed.
- Composition fix found by simulation:
  - TS15→S9→F60 exhausted its pair window and killed 10 of 80 hard attempts.
  - Non-legacy plans now fall back to another seed-compatible topic shape
    (at most two), bringing composition failures to 0. Legacy is unchanged.
- `tools/cat_pyq/simulate_policies.py`: seeded sequential mock simulations
  that ship into temporary history, reporting planned mix and yield.
  - 40 medium + 40 hard per policy, `PYTHONHASHSEED=0`:

    | Policy | Medium shipped | Hard shipped | Composition failures | Refusal (medium / hard) |
    |---|---|---|---|---|
    | legacy | 38/58 | 37/70 | — | 6/38, 8/37 |
    | s1 | 37/55 | 35/73 | 0 | 3/37, 4/35 |
    | s2 | 39/53 | 39/62 | 0 | 4/39, 3/39 |

  - Neutral closes: 1–2 per tier.
  - Exam-form share: s1 medium 0.459 / hard 0.343; s2 0.462 / 0.308.
  - Every new component and beat shipped at least once across runs, except
    FORECAST, which was plannable but not shipped in these 160 sets.
- Tests:
  - `tests/test_structure_release.py` (23): visibility, recognised-before-
    plannable, reachability per tier (elite never), every topic shape
    composes, closing beats, neutral plans with no rebuttal or open close,
    the category maths, the R01 audit, schema exclusions, rhythm fit, persona
    genres, the E21 binding, shared permissions across the three readers, the
    fallback, and mock batches under both versions.
  - Elite pre-policy golden tests with s1 and s2 running on the side.
  - Legacy-view scoping for two older tests that iterated the whole library.
- Mutation check: 10 deliberate breaks, 9 caught. The exposition-discard
  mutant is equivalent on today's library (F60, the only neutral family,
  carries its own closing-beat list).
- Validation:
  - `python -m pytest tests -q`: 397 passed.
  - `selftest`: passed.
  - Simulations as above.
- Limits:
  - Mock plans only; realised prose behaviour of the new families, beats and
    permissions is unmeasured.
  - Beat and planning weights are provisional.
  - Refusal realised on ships sits below the 14% draw objective, because
    posture runs and rejections still act after the draw.

## 2026-09-13 — Per-policy reporting and re-reads (plan 7.5; section 3 follow-up), by Claude Code

- `policy-report` ($0): planned and realised metrics by client, tier and
  generation policy. Policies and tiers are never pooled.
  - Yield, composition failures, novelty rejections, question failures,
    solver disputes, cost.
  - Early thesis, planned and realised (realised read is plan-anchored).
  - Closure as committed / neutral / refusal.
  - Schema match; family and beat coverage.
  - Planned negation by task and negated-stem share.
  - Answerability flags.
- `attempts.generation_policy` (additive column): every attempt records its
  policy, including attempts that died before a blueprint existed.
- Fingerprints of non-legacy sets record `_answerability_flags`.
- `move-audit` re-reads each set with the vocabulary of the policy its plan
  was composed under.
- Tests: `tests/test_policy_reporting.py` (4).

## 2026-09-13 — Question release `cat-pyq-q1` (plan section 4), by Claude Code

- Implemented section 4 as the first production generation policy,
  `cat-pyq-q1`, for medium and hard only. It is registered in
  `rc_engine/policy_catalog.py` but not enabled by default:
  - `config.GENERATION_POLICY_FOR_NEW_PLANS` stays legacy.
  - A run opts in with `generate --generation-policy cat-pyq-q1` or
    `RC_ENGINE_NEW_PLAN_POLICY`, and parallel workers inherit it.
  - Reason: the plan requires a human-reviewed paid pilot before new question
    forms reach client batches.
- `rc_engine/question_contracts.py`:
  - Each slot resolves to task, polarity, contract and marker (plan 4.1 table).
  - Only the support and application negatives are released. Strengthen,
    weaken, reported-view and author-endorsement are specified but blocked by
    validation. There is no double negation.
  - Exactly two negative slots per set on both tiers. Existing EXCEPT and
    authored negatives count. Negations are placed deterministically per
    blueprint and never on Q1.
  - A topology that cannot carry two is ineligible, in the composer and in the
    pipeline re-pick, so no inversion is invented. On current libraries that
    drops QT05 and QT19. Medium's pool stays at 18, the headroom floor.
  - Deterministic checks: stem negation count, markers, `failure_mode` (never
    "not mentioned"), `why_wrong` present, allowed mechanisms, keyword-set
    format (4–5 items, variant separators, equal counts, no duplicates), exact
    quoted spans (curly quotes, apostrophes, ellipses) and existing paragraph
    numbers.
- Question engine (contract plans only; legacy branches unchanged):
  - Polarity is resolved before traps; negative slots take no trap.
  - Stems deal from `<type>/negative` and `<type>/<variant>` pools.
  - Per-slot contract lines are added to the question plan.
  - Contract validation gets one corrective retry, then `failed_questions`
    (resumable).
  - Trap harvests are reported as `question contract:` notes.
  - Markers are kept out of `trap_usage`.
  - Questions record the planned slot type and polarity.
- Policy content:
  - New slot types `author_would_endorse` (4 forms) and `keyword_set` (3
    keyword and 3 sequence forms). Negative forms for detail, inference and
    application.
  - New stem variants: word purpose, tone of a quoted sentence, reported
    party vs author, similarity and difference, sense of a quoted sentence.
    All forms are original paraphrased templates, not PYQ text.
  - System extensions for questions, answerability, tiebreak, solver and
    judge. The solver stays blind to keys, traps and rationales.
- `topologies.json`: added QT25 "The Commitment Map" and QT26 "The Reported
  Voices", tagged `cat-pyq-q1`.
  - Each has two authored negatives; the analysis draft of QT26 had three and
    used unreleased contracts, so it was revised.
  - Both include `author_would_endorse` and `keyword_set`, and both are
    medium-eligible.
  - Maximum topology similarity to the library is 0.56 against the 0.75 cap.
- Also changed:
  - `GenerationPolicy` gained contract fields, tier-aware
    `eligible_ids(..., tier)`, `stem_pool` and contract validation.
    Registration handles either import order.
  - Registry: tagged topologies may use their policy's slot types.
  - Fingerprints of contract plans record `_negated_slots` and
    `_negated_tasks`.
  - The mock emits contract-conforming questions.
  - `cli vet` excludes all contract markers from trap histograms.
  - `tests/conftest.py` and the harness pin `RC_ENGINE_NEW_PLAN_POLICY=""`.
  - README section "Generation policies".
- Tests:
  - Added `tests/test_question_contracts.py` (47 tests) and
    `tests/fixtures/question_contracts.json`: an original passage with a valid
    item per contract and new type, 17 structural counterexamples, and 3
    semantic counterexamples recorded as NOT caught deterministically.
  - The tests cover resolution for every eligible topology, capacity
    refusal, traps, stem polarity, the histogram, a mock end to end, resume
    under the stored policy after disabling it, retry-then-fail, validation,
    the CLI opt-in and the env override.
  - `tests/test_question_blueprint.py` invariants now run per view (legacy and
    `cat-pyq-q1`), with a policy pool-starvation test.
  - A new golden test runs the production policy between elite attempts; elite
    still equals the pre-policy `23e3d49` output.
  - Mutation check: 10 deliberate breaks, 9 caught. The one survivor only
    differs when legacy data contains the new marker `rule_satisfied`, which
    legacy sets never emit.
- Validation:
  - `python -m pytest tests -q`: 368 passed on two full runs. One other full
    run failed `test_run_parallel_dry_run_ships_records_and_cleans_up` (4
    `rc_sets` rows, not 3).
    - Cause: two workers took the same topology (or a close rhythm), so a
      sibling set was rejected at Gate C.
    - It is pre-existing: the untouched `23e3d49` engine failed 4 of 60 probe
      runs, the current tree 2 of 60, with the same failure types. It was not
      fixed here and is flagged as a separate task (in-flight topology
      reservation race).
  - `python -m rc_engine.cli selftest`: passed.
  - `generate --dry-run --hard 2`: legacy, ran.
  - Isolated scratch-DB simulations:
    - `--medium 12 --hard 12 --elite 4 --generation-policy cat-pyq-q1`: 28 of
      36 attempts shipped; the 8 rejections were mock novelty.
      - Every medium/hard set had exactly 2 negatives: 16 detail, 13
        inference, 11 application, 8 EXCEPT across 24 sets.
      - QT25/QT26 were drawn 3 times; elite stayed legacy with no extensions.
    - `--medium 4 --hard 4 --workers 2` under the policy: 8 of 8 shipped,
      each with 2 negatives.
- Limits:
  - Mock success is not prose or question quality. No paid run; the pilot is
    pending authorization.
  - The real-model retry rate from the stricter checks (quotes, allowed
    mechanisms, `failure_mode`) is unmeasured and could raise question cost.
  - The new types appear only through QT25/QT26: 3 of 24 simulated sets.
  - Uniqueness of negated keys is semantic; there is no deterministic check.
  - Family `question_affinities` is not read anywhere in the engine, so
    "compatible family affinities" has no mechanism to attach to.
  - Reporting negation by task in `health` is not built; the fingerprint
    fields exist.
  - The `move-audit` follow-up from section 3 is still open.
- Changes are uncommitted. The plan asks for separate commits for the policy
  boundary (section 3) and questions (section 4).

## 2026-09-13 — Generation-policy boundary (plan section 3), by Claude Code

- Completed section 3 of `2026-09-13-cat-pyq-implementation-plan.md`. The
  boundary is dormant: no non-legacy policy is registered, and every tier maps
  to legacy in `config.GENERATION_POLICY_FOR_NEW_PLANS`.
- Added `rc_engine/generation_policy.py`:
  - The legacy version `""` returns the shared objects themselves, with no
    copies and no extra RNG.
  - A non-legacy policy may only add. It can own tagged components
    (`"policies": [version]`), beats, slot types, stem forms, schemas and
    schema forms, closing registers, prompt/system extensions and a weight
    hook.
  - `policy_for_new_plan` always maps elite to legacy.
  - `policy_for_blueprint` resolves from the stored plan and raises
    `PolicyError` for an unknown version or a tier the policy does not admit.
  - `validation_errors` runs inside registry validation.
- Blueprint fields:
  - Added `generation_policy` (missing means legacy) and `question_slots`.
  - Neither is in `component_ids`, so `combo_hash` and pair hashes are
    unchanged.
- Plumbing:
  - The policy is applied first in `_eligible`, topic-shape eligibility and
    its fallback, rhythm/movement options, and the pipeline topology re-pick
    and least-colliding fallback.
  - Move plans, schema forms, closing registers, the refine/render/compliance/
    question prompts, the blind move-signature and argument-schema vocabularies,
    compliance scoring, stem shapes and slot definitions all go through it.
  - Resume resolves the stored policy and returns `failed_resume` on
    `PolicyError`.
  - Non-legacy plans store their effective question slots before the first
    questions call (`history.update_blueprint_json`, client-scoped, status and
    `created_at` untouched). Retry and resume reuse them.
  - `_generation_policy` is written to the fingerprint only for non-legacy
    plans.
  - History schema counts accept schemas from registered policies.
  - Tagged topologies may use slot types that every one of their policies adds.
- Tests:
  - Added `tests/policy_harness.py`: a deterministic mock scenario run in a
    subprocess with `PYTHONHASHSEED=0`, pinned ids and clock, and SHA-1 prompt
    hashes.
  - Added `tests/policy_fixtures.py`: a test-only policy with one tagged
    component of each sampled type and a 1e6 weight boost.
  - Added `tests/test_generation_policy.py` (14 tests).
  - Two goldens were captured from an untouched `git archive` of `23e3d49`
    (in the scratchpad, with the repo `.env` loaded into the environment only):
    - `generation_policy_legacy_golden.json`: 14 interleaved attempts, a
      forced question failure and resume, topology re-picks, and 24
      exhausted-pool probes.
    - `generation_policy_elite_isolation_golden.json`: six mixed attempts, the
      policy enabled for medium/hard, then four elite attempts with a resume.
      A side pipeline in the same process runs a policy attempt before each
      elite attempt.
  - The current engine matches both goldens, including the legacy golden with
    the policy registered and tagged libraries present. The export reproduced
    the first golden exactly.
  - In-process tests cover:
    - new plans storing the policy and using its additions;
    - no shared pool widening;
    - elite staying legacy even when config names the policy;
    - disabling the policy;
    - ban/recency/topic-shape fallbacks never admitting tagged components;
    - topology re-pick;
    - resume with stored slots after a library edit;
    - unknown versions;
    - hash invariance;
    - legacy accessor identity;
    - validation errors.
  - Mutation check: 7 deliberate boundary breaks were each caught. They were
    legacy seeing tagged items, the stem pool widened in place, re-pick
    ignoring the policy, elite following config, stored slots not reused,
    resume using today's policy, and legacy prompt text altered.
  - Updated the source-grep assertion in
    `test_schema_directive_reaches_the_render_contract` to the policy accessor.
- Found, not changed: `_eligible` re-admits missing arc shapes by iterating a
  set, so composition depends on `PYTHONHASHSEED` across processes. The
  harness pins it.
- Follow-up for section 4: `move-audit` (`cli.py:668`) re-extracts corpus
  signatures with the legacy vocabulary. It must use each passage's stored
  policy once policy plans ship.
- Validation:
  - `python -m pytest tests -q`: 313 passed.
  - `python -m rc_engine.cli selftest`: passed.
  - `generate --dry-run --hard 2`: ran.
  - `generate --dry-run --hard 2 --medium 2 --workers 2`: ran.
  - Both dry runs rejected some attempts on mock rhythm-cosine collisions
    against the dry-run DB.
- No paid run. No production DB, exports or libraries were changed.
- Changes are uncommitted.

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
