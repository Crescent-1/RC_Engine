# CAT PYQ implementation — validation, rollout and status

Date: 2026-09-13 (Asia/Calcutta). Branch `cat-pyq-plan`. This closes sections 7 and 8 of
[2026-09-13-cat-pyq-implementation-plan.md](2026-09-13-cat-pyq-implementation-plan.md) as far
as can be done without paid generation. The paid pilot (below) is the one remaining step and
needs explicit authorization.

**Correction, 2026-09-14:** quick review reproduced two gaps in f1: numeric roles
could be reversed in an extracted claim while the auditor saw only that claim,
and omitted trace/attribution fields could pass as successful checking. The new,
default-off `cat-pyq-f2` policy supplies original spans plus source context and
requires complete explicit evidence/trace verdicts. Use f2 for future source-fact
pilots; f1 stays registered for stored plans. The historical test and simulation
results below describe the original releases, not f2 validation; current checks
and limitations are recorded in `codex.md`.

## 1. What exists

| Plan section | Delivered as | Default |
|---|---|---|
| 2 Baselines | `tools/cat_pyq/`, `2026-09-13-cat-pyq-baseline.{md,json}` | — |
| 3 Boundaries and versioning | `rc_engine/generation_policy.py`; policy stored on every blueprint; elite pinned to legacy | dormant |
| 4 Questions | policy `cat-pyq-q1`: contracts, two negatives per set, QT25/QT26, new types and stems | registered, off |
| 5 Structure and rendering | `cat-pyq-s1` (F59–F62, five beats, R21–R23, T21–T22, P21–P23, neutral exposition, refusal objective, permissions); `cat-pyq-s2` (ten beats) | registered, off |
| 6 Source-supported facts | `cat-pyq-f1`: validated facts, fact beats with fallbacks, claim tracing | registered, off |
| 7.5 Reporting | `policy-report`, `attempts.generation_policy` | — |

Versions are cumulative: `q1 ⊂ s1 ⊂ s2 ⊂ f1`. A version's content is fixed once plans can
carry it; any change is a new version.

## 2. Required implementation checks (plan 7)

1. **Focused behaviour and legacy tests.** Current suite (added this work):
   - `test_generation_policy.py`: goldens from the untouched `23e3d49` engine (see 4).
   - `test_question_contracts.py`: 47 tests.
   - `test_structure_release.py`: 23 tests.
   - `test_source_facts.py`: 19 tests.
   - `test_policy_reporting.py`: 4 tests.
   - `test_pilot_review_pack.py`: 3 tests.
   - Deliberate-break (mutation) checks per release: 7/7, 9/10, 9/10 and 7/7
     caught. The two survivors are equivalent on today's library (see codex.md).
2. **Runtime and suite.**
   - `python` resolves in this environment, and the earlier `feedparser` failures
     do not occur.
   - `python -m pytest tests -q` passes (count in codex.md for the final commit).
   - `python -m rc_engine.cli selftest` passes.
   - One pre-existing intermittent test (parallel sibling topology race) fails on
     the untouched engine too and is tracked separately.
3. **Isolated mock dry runs.**
   - One scratch DB received:
     - legacy medium 3 / hard 3 / elite 2;
     - `q1`, `s1`, `s2` at medium 3 / hard 3 each;
     - `f1` at medium 4 / hard 4 with `--workers 2`.
   - Every batch shipped, and `policy-report` separated all eleven client/tier/policy
     rows.
   - Every enabled component is exercised explicitly in the release tests.
   - Seeded sequential simulations (`tools/cat_pyq/simulate_policies.py`) append
     mock ships to temporary history, so recency and exclusions evolve (table below).
4. **Elite before/after at fixed inputs.**
   - The elite scenario is compared with the pre-policy golden, prompt hashes and
     RNG path included:
     - with a test policy, `q1`, `s1`, `s2` and `f1` each running medium/hard
       attempts in the same process;
     - with every tagged library present but the policy disabled.
   - All match. Legacy pools, fallbacks and prompts expose zero new components,
     beats or stems (release tests).
5. **Metrics by client, tier and policy.**
   - `python -m rc_engine.cli policy-report [--all-clients] [--json]` covers:
     - negation by task and negated-stem share;
     - early thesis (planned; realised read, plan-anchored);
     - closure as committed / neutral / refusal;
     - family and beat coverage;
     - composition failures, novelty rejections, question failures, solver
       disputes, answerability flags and cost.
   - Voice flags stay observational.

### Seeded sequential simulation (mock, $0)

Settings: 40 medium + 40 hard attempts per policy, `PYTHONHASHSEED=0`, seed 20260913,
invented seed excerpts (`--invented-seeds`), production novelty caps. Prose metrics from the
mock mean nothing; these are **planning-path** and **batch-viability** figures.

| Policy | Tier | Shipped / attempts | Novelty rejections | Composition failures | Refusal share | Neutral closes | Early thesis (planned) | Exam-form share | Negative slots per set | Facts per set |
|---|---|---|---|---|---|---|---|---|---|---|
| legacy | medium | 39/59 | 20 | 0 | 15% | 0 | 0.576 | 0.333 | 0 | 0 |
| legacy | hard | 37/64 | 27 | 0 | 27% | 0 | 0.645 | 0.216 | 0 | 0 |
| q1 | medium | 38/55 | 17 | 0 | 13% | 0 | 0.594 | 0.368 | 2 in all 38 | 0 |
| q1 | hard | 35/67 | 32 | 0 | 26% | 0 | 0.667 | 0.257 | 2 in all 35 | 0 |
| s1 | medium | 39/53 | 14 | 0 | 10% | 1 | 0.639 | 0.410 | 2 in all 39 | 0 |
| s1 | hard | 35/71 | 36 | 0 | 17% | 1 | 0.586 | 0.371 | 2 in all 35 | 0 |
| s2 | medium | 38/58 | 20 | 0 | 8% | 1 | 0.667 | 0.421 | 2 in all 38 | 0 |
| s2 | hard | 34/69 | 35 | 0 | 15% | 1 | 0.552 | 0.324 | 2 in all 34 | 0 |
| f1 | medium | 39/57 | 18 | 0 | 10% | 1 | 0.529 | 0.462 | 2 in all 39 | 4 in all 39 |
| f1 | hard | 34/66 | 32 | 0 | 15% | 1 | 0.633 | 0.412 | 2 in all 34 | 4 in all 34 |

Reading it:
- **Yield.** No release reduces batch viability against legacy.
  - Composition failures are 0 everywhere. `s1` hard lost 10 of 80 attempts before
    the topic-shape fallback was added.
- **Refusal.** Drops from 15%/27% (legacy) toward the 14% objective on hard
  (15–17%), and below it on medium (8–10%).
  - Posture runs and rejections still act after the draw.
  - These are single seeded runs, not calibrated shares.
- **Early thesis.** Unchanged, by design: no timing objective was activated, because
  the baseline already exceeds 40%.
- **Exam-form share** sits near the 50%/35% ceilings. `f1` hard at 0.412 on 34 ships
  is within sampling noise of the 35% draw ceiling but should be watched.
- **Negatives.** Exactly two per medium/hard set in every release from `q1` on.
- **Coverage.**
  - Every new family, revelation, rhythm, persona, topic shape, ending and topology
    shipped at least once across these runs.
  - Every plannable beat shipped at least once, except STUDY_WALKTHROUGH,
    EXPERT_AS_SPINE and QUOTE_CLOSE. The mock proposes unattributed facts, so those
    beats correctly fell back; they are covered by unit tests.

## 3. Rollout and rollback

Nothing reaches client batches until a tier is switched on.

- **One run:**
  - `python -m rc_engine.cli generate --medium N --hard N --generation-policy cat-pyq-f1`;
  - or set `RC_ENGINE_NEW_PLAN_POLICY`, which parallel workers inherit.
- **Default:** set the medium/hard entries of `config.GENERATION_POLICY_FOR_NEW_PLANS`.
  Elite is refused anything but legacy.
- **Rollback:** switch the tier back to `""`, or pass `--generation-policy ""`.
  - Stored plans keep their policy and question contracts on resume. They are never
    reinterpreted with legacy rules, history is not rewritten, and novelty caps are
    untouched.
- **Staging** follows the plan:
  - `q1` (questions) before `s1` (structure);
  - `s1` measured before `s2` widens the beat vocabulary;
  - `f1` last.

## 4. Paid pilot (not run — needs your authorization)

Plan protocol:
- **Sample:** 10 medium and 10 hard sets under the release being enabled.
- **Review:** alongside existing sets with origin hidden. Inspect each negated question
  for a unique key and the proper option relation. Review prose for thesis visibility,
  usable source detail and repeated house voice.
- **Limits:** this is qualitative, and not enough to validate the 14% or 40% objectives.
- **Elite:** no elite pilot is needed.

Procedure:
1. Run the pilot, keeping it out of client export folders:
   `python -m rc_engine.cli generate --medium 10 --hard 10 --generation-policy <release> --no-export`
   - Estimated cost: ~$0.16 per shipped set on the happy path (`estimate`), with
     per-set caps of $0.34 (medium) and $0.36 (hard), so about $4–7 including
     rejected attempts.
   - Default batch cap: $8.75.
   - Pilot ships enter the client's novelty history, as the plan notes.
2. Build the blinded pack:
   `python tools/cat_pyq/pilot_review_pack.py --db rc_pipeline.db --policy <release> --out <private dir>`
   - The pack holds the set files, `review_sheet.csv` (negated questions pre-listed) and a
     separate key file.
3. Measure the pilot:
   - `python -m rc_engine.cli policy-report` for question failures, solver disputes,
     answerability flags and cost against legacy.
   - Refine truncation and question retry rate, which the mock cannot show.

## 5. Definition of done (plan 8)

| Item | Status |
|---|---|
| Medium/hard question and passage changes satisfy the specified semantic tests | Structural and contract tests pass. Semantic key uniqueness and prose quality are **pending the pilot review**. |
| Evidence reproducible, uncertainty and small samples stated | Done (`tools/cat_pyq`, baseline docs, codex.md limits). |
| All enabled families and beats compatible and reachable | Done: reachability tests per tier, elite never; simulations above. |
| Elite legacy passes fixed-input regression across full paths | Done: pre-policy goldens with every release running beside elite. |
| Old plans resume; exports keep client format | Done: resume under the stored policy tested for q1/s1/f1; export text unchanged and evidence omitted. |
| Selftest, suite and isolated dry runs recorded | Done (codex.md). |
| Real prose-quality claims pending an authorized human-reviewed pilot | **Open.** Mock success is not presented as that pilot. |
