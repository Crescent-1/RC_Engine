# CAT PYQ implementation plan — medium and hard; elite preserved

Date: 2026-09-13, Asia/Calcutta.
Status: planned, not implemented. User direction: plan the implementation;
elite stays the same. This plan incorporates the review of
`2026-09-13-cat-pyq-engine-analysis.md`; its drafts are inputs, not approved
paste-ready specifications. No paid generation is authorized by this plan.

## 1. Scope and decisions

Improve medium and hard exam realism through question forms, earlier visible
claims, a broader range of committed and expository passages, and more natural
source genres. Retain eight questions and the 500–550-word passage range.

Elite retains its existing component pools, sampling policy, prompts, question
forms, difficulty settings, models, budgets, and quality/novelty behavior.
Do not add double negation to elite, despite that suggestion in the analysis.

Keep novelty caps, first-person share, client isolation, global seed/combo
exclusivity, and current export/status routing. Voice observations remain
observational. Do not modify historical passages, statuses, exports, or trackers.

Working rollout choices, subject to measurement rather than treated as CAT facts:

| Area | Medium | Hard | Elite |
|---|---|---|---|
| Negated forms | Target two slots per set; single negation | Target two slots; single negation initially | Existing behavior |
| Double negation | Excluded | Later experimental phase, at most one per set | Existing behavior |
| Refusal | Provisional 14% planning objective | Provisional 14% planning objective | Existing behavior |
| Early thesis | Provisional 40% explicit-early planning objective among thesis-bearing plans | Same | Existing behavior |
| New question types and stem variants | Enabled as staged below | Enabled as staged below | Excluded |
| New passage families, rhythms, personas and beats | Compatible subset | Compatible subset, including framed inquiry | Excluded |
| Source-supported facts | Later stage | Later stage | Existing behavior |

These shares are initial engineering objectives, not guaranteed realized rates,
floors, or approval gates. Reconcile the evidence before activating the passage
weights. A neutral exposition is not a refusal and must be counted separately.

## 2. Establish trustworthy baselines

1. Reconcile question counts in the report against the labels. The current JSON
   has 389 questions; the yearly counts are 48, 48, 47, 54, 48, 48, 48, 48 for
   2017–2024. Its yearly means disagree with the report. Validate extraction
   boundaries against the local PDF before choosing the corrected counts.
2. Preserve reproducible analysis code and derived, question-level records:
   passage ID, question index, underlying task, stem polarity, and negation
   operator/scope. Retain stable source page references, without PYQ prose.
   Classify task and polarity independently; do not use a first-match classifier
   to infer both. Report unresolved labels and denominators explicitly.
3. Use one thesis rubric on both corpora: explicit central claim, implicitly
   recoverable claim, or no thesis; record first-visible paragraph separately.
   A planned paragraph 2 can count as early even when its library label is mid.
   Resolve the overlapping "never stated" row rather than adding it to 100%.
4. Record current code revision, client, tier, plan version, status inclusion,
   window, denominator and timestamp for engine baselines. Separate planned
   structures from extracted structures. Do not compare a mixed-tier health
   window directly with the proposed medium/hard policy.
5. Sample medium/hard passage–question sets alongside PYQs for qualitative
   checks of actual thesis visibility, closure, and negation. This can start
   locally without another LLM call. A new paid extractor run is a later option.

Deliverable: corrected evidence with reproducible counts, uncertainty notes,
and a baseline suitable for before/after comparison. Preserve the original
analysis history; make corrections explicit.

## 3. Put tier boundaries and versioning in place first

Introduce a persisted generation-policy version for new medium/hard blueprints.
Missing version means legacy behavior. Resolve policy using both blueprint
version and tier; elite always resolves to the existing policy. Permit the new
policy to be disabled for future medium/hard plans without rewriting old plans.

Keep existing global definitions as the legacy defaults. Add policy-specific
overlays/accessors for eligible components, schema compatibility, move vocabulary,
stem forms, prompt extensions and calibration weights. Include registry
validation, mock clients, extraction, repair and resume in this boundary.

Important implementation details:

- `tier_max` currently filters families; do not assume it filters revelations,
  rhythms or personas. Add explicit policy eligibility for every new component.
- Apply the boundary before recency fallbacks, and also in topology replacement
  (`pipeline._resolve_topology` / `_tier_topologies`). Fallbacks must never admit
  a component from another policy.
- Do not add new stems to a shared pool that elite reads. Preserve the old pool
  order and avoid additional RNG consumption on the legacy path.
- `compliance.py` builds extraction vocabularies from global definitions. Give
  upgraded medium/hard their own vocabulary and keep elite prompts identical.
- Resolve effective question slots once and preserve their polarity/contract
  through retries and resume. Do not change existing component hash definitions
  or reinterpret a stored legacy topology silently.
- Keep history queries explicit about client and tier/version scope. New
  calibration reports may filter tiers; do not change existing novelty windows.

Acceptance: for identical seeds, history, RNG state and mocked model responses,
elite component choices, prompt bodies, effective slots and decisions match the
pre-change baseline. Test nonempty history, exhausted pools, topology replacement,
repairs, resume, and source-backed seeds—not just empty-history happy paths.

This preserves elite's policy, not identical future live prose: model output is
stochastic, and new medium/hard ships still enter the existing shared per-client
novelty history. Removing that interaction would change the current policy and
is outside scope.

## 4. First functional release: questions

### 4.1 Model question polarity explicitly

Use task type plus polarity and a resolved option contract. A boolean alone is
insufficient to represent "if false ... EXCEPT" or to tell the validator what
the three distractors must establish. Retain `except_scan` compatibility for old
plans; new plans resolve it to its existing support-scan semantics.

| Underlying task | Correct answer in a negated form | Other three options |
|---|---|---|
| Passage support/detail/inference | Fails the stated support relation for a defensible reason | Meet that support relation |
| Reported view | Fails the specified person's attributed position | Fit that person's position |
| Application | Fails the passage-derived rule in a new scenario | Satisfy the rule in new scenarios |
| Strengthen | Does not strengthen the specified argument | Strengthen it if true |
| Weaken | Does not weaken the specified argument | Weaken it if true |
| Author endorsement | Least supported by the author's commitments | More consistent with those commitments |

For strengthen/weaken, the candidate facts need not occur in the passage. For
application, scenarios must be new. Specify meaningful distinctions and a unique
key; do not equate "not supported" with "false" across all question types.

Update prompt construction, polarity-specific stem selection, trap assignment,
mechanism metadata, validation, answer explanations, trap histograms, mocks and
QA. A negative stem must never be paired randomly with an affirmative template.
Keep blind solving blind to keys, traps and generator rationales. Solver success
on semantic questions is not deterministic verification.

Start with support scans and negative application; enable negated strengthen /
weaken and reported-view variants only with their own semantic examples and
checks. Defer double negation until single-negation quality is demonstrated.

### 4.2 Add task variety and topologies

- Add `author_would_endorse` with at least three affirmative forms and separately
  specified negative forms. Its answer must follow the passage's commitments.
- Add `keyword_set` with keyword and sequence variants. Check option formatting
  deterministically; validate conceptual coverage and ordering through existing
  semantic QA and human review, not a claimed deterministic solver.
- Add the proposed structural-function, stance, reported-view and paraphrase
  variants to the medium/hard pools only. Require exact passage spans for quoted
  words/sentences and valid paragraph references.
- Add application guidance requiring close scenario alternatives and combined
  passage constraints, while respecting medium's difficulty limits.
- Create QT25/QT26 with full target/difficulty/curve metadata, tier eligibility,
  and compatible family affinities. QT26 in the analysis actually contains three
  negative forms (EXCEPT plus two flags); revise it to two total.
- Preserve the requested continuation question capability. Avoid increasing
  negative counts by blindly layering two new flags on an existing EXCEPT slot.
- Resolve two compatible negative slots across upgraded medium/hard plans;
  count pre-existing negative forms in that total. If a topology cannot support
  this, choose a compatible topology before questions are purchased. Do not
  silently invent a semantically invalid inversion to satisfy the quota.

Main areas: `question_engine.py`, `components/topologies.json`, `registry.py`,
`pipeline.py`, `qa_checks.py`, `quality.py`, `llm.py`, and question tests.

Acceptance: fixtures demonstrate each contract with a valid unique key and
counterexamples; malformed metadata, incompatible stems, missing quote spans,
and wrong trap accounting are caught. Medium difficulty scaling, letter balance,
option-length checks, solver disputes and legacy resume remain intact.

## 5. Second release: passage structure and rendering

### 5.1 Complete the family/schema/beat design

Do not load F59–F62 with empty compatibility work. Add their schema reachability,
topic-shape compatibility, stance choices, allowed endings/revelations, required
beats and closing-register mappings together.

| Family | Planned integration |
|---|---|
| F59 Backfiring Remedy | Test compatibility with mechanism-traced / practice-versus-theory schemas; trace one fix and its backfire rather than imposing multiple remedies |
| F60 Typology | Add a medium/hard typology schema; permit neutral exposition and an optional boundary case instead of forcing every classification to fail |
| F61 Framed Inquiry | Add a hard-only inquiry schema and a compatible scope-setting stance/ending |
| F62 Split Verdict | Add a medium/hard review schema that separates reported and reviewing voices |

Use policy-specific schema overlays so these new schemas do not enter elite's
sampling or extraction. Do not add nominal allowlist entries if the existing
schema directive contradicts the family. Expand supported closure semantics for
new neutral plans without reclassifying historical or elite passages.

Keep the current combined exam-family allocation at medium 50%, hard 35%, elite
0%; include the new shapes in the upgraded cohort. Verify coverage under source
compatibility and fallback rules rather than promising exact marginal shares.

Release the five first-stage beats with their supporting mappings:
`ENUMERATED_SET`, `HYPOTHETICAL_CASE`, `PRESCRIPTION_STATED`, `FORECAST`,
`SPLIT_VERDICT`. Then add `TERM_COINED`, `IRONY_NOTED`,
`OBJECTION_FORESTALLED`, `THEN_NOW_CONTRAST`, and `REPORTED_POSITION`.
Keep explicit recognized-versus-plannable policy sets so vocabulary expansion
does not force immediate sampling. Give new beats explicit conservative weights;
do not rely on the claim of a guaranteed 20-set rarity transient.

### 5.2 Change timing and closure weights carefully

Add R21–R23 only to the upgraded pools. Check early-thesis compatibility against
family movements and schema directives, including R23's received view versus
the author's actual thesis. Audit R01 exclusions individually.

Implement category-level targeting: normalize candidate weights within each
eligible timing/posture category before applying category objectives. Simply
multiplying each component by 0.40 or 0.14 makes the result depend on how many
components inhabit the category. Existing schema selection, compatibility,
recency and rejection still alter output; instrument and simulate the complete
selection path. Never override compatibility to hit a percentage.

Use the provisional objectives in section 1 only after baseline reconciliation.
Do not copy the full posture table as CAT calibration: it currently omits neutral
exposition. Report neutral, committed and refusal plans separately, with realized
readings beside them. Keep exact weights documented as provisional choices.

### 5.3 Align every render and repair instruction

Allow bounded prescriptions only for a compatible planned closure, and one
explicit hypothetical when the beat calls for it. Allow content enumeration and
scope-setting where the family/genre needs them. Update both rule 7 and the
duplicate reader-address prohibition in rule 11, plus compliance/repair prompts.
Do not create an exception in one prompt while another prompt bans it.

Keep the anti-moralizing and anti-fabrication rules. Existing rule 8 already has a
genre exception; make the new permissions precise, not a blanket signposting
waiver. `_SIGNPOST_PATTERNS` does not ban all enumeration; test actual patterns.
Use identical permissions in renderer, compliance and `texture_report`.

Add T21/T22 with useful interior functions and no automatic concession padding
for those plans. Check 6–7 paragraphs still fit the existing total word target.
Add P21/P22/P23 only after their genres have compatible material and stances;
omit the proposed invented personal credential for the advocate. Preserve the
first-person allocation and audit pronoun eligibility explicitly.

Main areas: `config.py`, `composer.py`, `voice_plan.py`, `renderer.py`,
`compliance.py`, `question_engine.py`, component libraries, `models.py`,
`history.py`, `cli.py`, and mocks.

Acceptance: every enabled family/beat is reachable in an appropriate tier and
unreachable in elite; every supported topic shape composes; new neutral plans do
not acquire an invented thesis or obligatory rebuttal. Full rolling mock batches
remain viable with novelty thresholds unchanged.

## 6. Third release: source-supported facts

Call the feature `source_supported_facts`, not verified facts. Extraction from a
source proves provenance, not truth. Keep real-reference permissions in rule 9;
this feature adds explicit evidence and attribution rather than claiming the
current engine prohibits all real references or numerical hypotheticals.

For each fact retain an ID, source URL/doc ID, excerpt digest, exact span offsets,
short supporting span, factual claim, attribution, and qualification/context.
Accept at most eight candidate facts per seed. Validate span matching and offsets
against the exact retained seed excerpt; use the existing excerpt limit rather
than expanding scraping scope. Keep source material private and out of git/logs.

The refiner proposes claims and evidence; validation rejects mismatched spans,
invented names/quotes, or claims that lose source qualification. Structural checks
are deterministic; entailment and attribution need semantic review. Rendering
may paraphrase supported facts but must not add unsupported dates, statistics,
causal conclusions or borrowed credentials. Direct quotations must be exact and
attributed. Do not represent a per-span word cap as a complete copying safeguard.

Trace each generated factual claim back to its supporting fact IDs. Suppress a
texture warning only after the complete claim and attribution are supported,
not because a number or surname occurs in a whitelist. Reuse existing semantic
QA budgets where feasible; measure added cost and do not raise budgets silently.
If no trustworthy fact survives, use existing source-independent material or
select a compatible non-reportage plan; do not fabricate to complete a beat.

After this path works, enable `NEWS_DATA_HOOK`, `STUDY_WALKTHROUGH`,
`EXPERT_AS_SPINE` and `QUOTE_CLOSE` for eligible upgraded plans. Named-book reviews
must have support for the book's attributed claims. Persist enough evidence for
resume; omit internal evidence metadata from client exports.

Acceptance: adversarial fixtures cover an accurate substring used in a false
claim, a denied/qualified source claim, misattributed quotes, altered figures,
short or missing seeds, and resumed plans. Elite does not receive these fields in
its prompts or any extra model call.

## 7. Validation, rollout and rollback

Complete each release before enabling the next. Use separate reversible commits
for policy boundaries, questions, structure/rendering, and source-supported facts.
Update `codex.md` with actual checks and limitations after every change batch.

Required implementation checks:

1. Focused behavior tests and legacy compatibility tests after each change.
2. `python -m rc_engine.cli selftest` and `python -m pytest tests -q` after every
   config/library change. Establish the runtime first: this review shell did not
   resolve bare `python`; earlier logs report missing `feedparser` failures.
   Record actual new results rather than carrying those old failures forward.
3. Isolated mock dry runs for medium, hard, elite, and parallel workers. Exercise
   every enabled component explicitly, then run seeded sequential simulations
   that append mock ships to temporary history so recency and exclusions evolve.
   A frozen-corpus replay alone is not evidence of sustained batch viability.
4. Compare elite before/after at fixed inputs, including prompts and RNG path.
   Confirm zero new component/beat/stem exposure and unchanged legacy decisions.
5. Report planned and realized metrics by client, tier and policy version:
   negation by underlying task, early-thesis visibility, neutral/committed/refusal
   closure, family/beat coverage, composition failures, novelty rejection, solver
   disputes, question ambiguity and cost. Do not turn observational voice flags
   into status gates.

Paid pilot, only after explicit authorization: a suggested first sample is 10
medium and 10 hard sets, reviewed alongside existing examples with origin hidden.
Inspect each negated question for a unique key and the proper option relation;
review prose for thesis visibility, usable source detail and repeated house voice.
This is a qualitative pilot, not enough data to validate 14% or 40% targets.
Broaden distribution measurement over subsequent authorized batches. No paid elite
pilot is needed to authorize these medium/hard changes.

Roll back a failing feature by disabling it for future upgraded plans. Persisted
plans retain their policy and question contracts on resume. Do not reinterpret
them with legacy rules, rewrite history, or loosen novelty caps. Fix composition
starvation, source errors and semantic ambiguities before widening rollout.

## 8. Definition of done

- Medium/hard question and passage changes satisfy the specified semantic tests.
- Evidence is reproducible, with uncertain labels and small-sample limits stated.
- All enabled families and beats are compatible and demonstrably reachable.
- Elite legacy behavior passes fixed-input regression checks across full paths.
- Old plans resume and exports preserve their existing client format.
- Selftest, required suite and isolated dry runs have recorded results.
- Real prose-quality claims remain pending until an authorized human-reviewed
  pilot is completed; mock success is never presented as that pilot.

The next implementation step is baseline capture and policy isolation, followed
by the question release. This document itself authorizes no code execution,
paid generation, production-data mutation, or deployment beyond the user's
current planning request.
