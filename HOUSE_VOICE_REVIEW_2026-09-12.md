# House-voice review — 12 September 2026

The work identifies the right problem, but the generation controls are not yet reliably changing the prose. The system varies its plans more successfully than it varies the reasoning that appears in finished passages. The next intervention should make the plan coherent and close the feedback loop, rather than add more component labels or lower novelty caps.

## Evidence and scope

Reviewed the current production engine, its uncommitted house-voice changes, the existing August voice review, and the production database through a read-only SQLite connection. The database contains 124 RC rows, 170 fingerprints, and 119 persisted rendered passages. No generation calls were made, and no production records, exports, or engine files were changed.

The most relevant cohort is the 11 RC rows dated 7 and 12 September, all generated under the Claude provider. These are generated records, not a claim that all 11 were delivered. One has `solver_dispute` status. All have saved planned and realized argument-schema fields.

| Measure | Latest 11 records |
| --- | ---: |
| Planned primary schema matches blind primary classification | 1/11 |
| Planned schema matches either blind primary or secondary | 4/11 |
| Opening beat follows the plan | 10/11 |
| Closing beat follows the plan | 6/11 |
| Mean planned middle-beat retention | 66.4% |
| Passes the existing middle-beat check | 0/11 |
| Reader similarity screen returns red | 5/11 |
| Reader similarity screen returns red on 12 September alone | 4/5 |

The move counts are especially informative:

| Move | Planned in | Detected in |
| --- | ---: | ---: |
| EASY_READING_DEMOLISHED | 1/11 | 9/11 |
| CONCESSION_GRANTED | 0/11 | 6/11 |
| STACCATO_TRIAD | 6/11 | 0/11 |
| SELF_CORRECTION | 7/11 | 5/11 |
| MECHANISM_EXPLAINED | 1/11 | 10/11 |

These are saved model annotations, not independent human ground truth. A mechanism is also ordinary expository material, so its prevalence is not itself a defect. The important result is that avoiding an operation in the plan does not reliably prevent it in the prose. The zero middle-check pass rate could reflect excessive policing of legitimate unplanned operations as well as actual disobedience; it should not become an automatic rejection rule without calibration.

I also read the current library-digitisation, puppet-workshop, and bell-founding passages. The first two share a recognizable evaluative progression despite their different subjects: a useful institutional practice, a concession to its apparent benefits, an overlooked mechanism or burden, and a narrowed verdict expressed as a cost. The bell passage spends more space on a concrete process and is meaningfully different, but still introduces rival camps, demolishes a tempting interpretation, and closes on an asymmetry of costs.

## What the existing work gets right

- Blind rhetorical-move extraction measures finished prose rather than simply comparing blueprint labels.
- Argument schemas address the reasoning operation above the level of topic or vocabulary.
- Paragraph-level beat placement and word budgets make prescriptions more executable. The latest opening-beat compliance is encouraging, though this small uncontrolled cohort cannot establish causality.
- Expanding seed and topic-shape eligibility removes real sources of forced repetition.
- Recording topic-shape usage repairs a previously disconnected recency mechanism.
- The reader similarity screen examines full passages and recognizes forms of repetition the numeric proxies miss.
- Avoiding repeated, ineffective re-renders is sensible. A failed control should be diagnosed, not financed indefinitely.

## Findings

### 1. The argument schema is absent when the actual argument is planned

`compose()` samples `argument_schema_id`, but `_refine_user_prompt()` never includes it. The refiner fixes the topic, paragraph briefs, tensions/content frame, and traps using the family and topic shape. The schema first becomes an explicit instruction in the renderer, after those choices have been made.

I reconstructed the refinement prompts for the latest 11 stored blueprints: the selected schema directive is absent in all 11. Primary schema agreement is only 1/11. This does not prove the omission explains every mismatch, but it is a direct break in the intended control path.

**Change:** Choose the high-level reasoning purpose before content refinement. Include it in refinement and validate that the resulting paragraph briefs support it. Do not require the renderer to retrofit a new argument onto already fixed content.

Relevant code: [composer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/composer.py:1097>), [renderer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/renderer.py:285>).

### 2. The non-adversarial content frame never reaches the renderer

For topic shapes that do not use opposing poles, `_apply_refined()` stores `content_frame` inside `bp.tension_system`. The renderer only reads `primary`, `secondary`, and `interaction`; it never renders `content_frame`. It consequently prints an empty tension scaffold for these passages.

All 11 recent blueprints contain a content frame, and its full text is absent from every reconstructed render contract. Paragraph gists still carry some content, so the passage is not wholly ungrounded, but the specific instruction introduced to support non-adversarial material is lost.

**Change:** Render the content frame explicitly and omit the tension section when it does not apply.

Relevant code: [composer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/composer.py:992>), [renderer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/renderer.py:299>).

### 3. Independent instructions can demand incompatible essays

Family, stance, schema, move plan, and closing register all claim authority over overlapping aspects of the argument. Schema and closing register are sampled independently of the move plan. The compatibility checks do not integrate all these layers.

For example, RC-ELITE-260912-0085 asks for S7_CASE_AGAINST_RULE while its RS05 stance requires a procedural mechanism explanation; its planned final beat is BOTHSIDES_REFUSED while its final-sentence register is concrete_particular. Its saved classification is S4_MECHANISM_TRACED. Elsewhere, 15 persisted RC blueprints pair a HEDGED_APHORISM closing beat with a non-aphoristic register.

**Change:** Use a hierarchy: source/material suitability → reasoning purpose → compatible article form and family → supporting operations → compatible ending. Keep variation within each form, but validate the complete contract before any paid rendering. Generate one paragraph plan from these decisions instead of several parallel plans.

Relevant code: [composer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/composer.py:928>), [constraints.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/constraints.py:13>).

### 4. The measured defects do not reliably affect acceptance or future sampling

The current composite compliance threshold is 0.75. A middle-beat violation costs only 0.06, and a wrong closing beat costs 0.04. Other structural scores can compensate. RC-MEDIUM-260912-0068 has a wrong closing beat, a failed middle check, a schema mismatch, and a red similarity screen, yet its stored status is approved with F1 0.765.

Schema classification is recorded but is neither an acceptance criterion nor the source of schema usage counts. `mark_shipped()` counts the requested schema, so a passage that actually repeats an instrument-blind argument can reduce the sampling weight of a different schema instead. Move sampling does use realized frequencies, which is a useful distinction.

**Change:** Separate format/compliance, question quality, and voice review states. Surface the exact violations to the reviewer. After classifier calibration, let realized schema frequencies steer distribution; retain planned frequencies separately to diagnose failed control. Do not immediately make every middle violation trigger another paid render.

Relevant code: [compliance.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/compliance.py:500>), [pipeline.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/pipeline.py:275>), [history.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/history.py:411>).

### 5. The reader screen has a large-corpus and same-batch blind spot

The reader screen examines only ten preceding database passages and excludes every member of the current batch from the reference set. Consequently it cannot catch two batch siblings that are close to each other but unlike the previous ten. It also cannot recognize an old recurring essay template outside its short window. Earlier fingerprint gates help, but they measure the proxies that this screen was introduced to supplement.

**Change:** Retrieve a compact mixture of recent passages, older structural neighbours, and representatives of repeated argument clusters. Also compare batch members symmetrically and assess the actual four-passage mock bundle. All-pairs checks or a fixed, unordered batch evaluation avoid dependence on which candidate is processed first.

Run the passage screen before questions where practical, so a passage requiring editorial intervention does not automatically incur the full question/solver/judge cost. Record review state without deleting the candidate.

Relevant code: [similarity_screen.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/similarity_screen.py:180>).

### 6. Sampling diversity and exam-like diversity are different targets

The move sampler discounts common operations without using exam shares as its base distribution. It can therefore promote devices merely because they are rare in the generated corpus. STACCATO_TRIAD was prescribed in six of the latest eleven plans, despite being absent from the configured list of exam moves above 15%. It is a sentence-cadence device, not the same kind of variable as explaining a mechanism.

Schema sampling does use exam weights, but multiplying those by rolling usage penalties changes the long-run distribution. A 30,000-draw simulation of the actual sampler, discarding 1,000 warm-up draws, produced S4 at 23.4% against its configured 30.6% target and S2 at 21.2% against 25.8%; S5 rose from 2.4% to 4.1%. Reduced local repetition may justify some shift, but the weights alone do not establish target matching.

**Change:** Separate argument operations from surface devices. Set targets by relevant source genre/exam population, allow common expository moves, and measure generated distributions after all acceptance filters. Treat recency control and long-run distribution matching as separate objectives.

Relevant code: [composer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/composer.py:583>), [composer.py](<C:/Users/anshu/OneDrive - eLitmus/RC Gen Project/rc_engine/composer.py:884>).

## Further improvements, in order

1. **Repair the information flow and compatibility first.** Forward schema and content frame; reconcile stance, movement, and endings. These are concrete changes that can be verified without paid generation.
2. **Build a small fixed evaluation set.** Have a human mark clear repeats, ordinary shared expository structure, and genuinely different passages. Include same-topic/different-argument and different-topic/same-argument pairs. Hold out examples from prompt tuning. Recheck classifier evidence and label meanings before converting scores into hard gates.
3. **Measure realized voice over time.** Track schema confusion, unplanned recurring moves, actual opening/closing forms, repeated phrase templates, fragments, sentence-length distributions, and paragraph progression. Store prompt/config/model/extractor versions so a before/after comparison has meaning. Keep an immutable delivery-history view for exposure counts and a separate balanced reference sample for stylistic comparison; quarantining duplicates should not erase how often customers encountered them.
4. **Try distinct article forms with smaller contracts.** The shared renderer asks every piece to inhabit the same serious-magazine register and adds the same texture obligations. Test different briefs for a scientific explainer, chronological history, close reading, sustained defence, or comparison. Each should get only the instructions it needs. This is an experiment, not a proven fix; preserve question quality and factual grounding.
5. **Evaluate batches as reading experiences.** Individual passages can all pass while the bundle sounds repetitive. Select a mock bundle with varied actual reasoning, cadence, and endings, then read it consecutively. Prefer selecting among coherent candidates to repeatedly rewriting one overloaded contract.
6. **Compare a small intervention against the current system.** Use matched seeds, comparable tiers, randomized presentation, and blinded human judgements. Measure repetition, readability, question validity, and cost per usable set. Start with a pilot; do not treat a small win as a stable effect. A second provider is worth testing only under this evaluation, not as an assumed cure.

Research supports keeping lexical, syntactic, and semantic diversity distinct ([Guo et al., TACL 2025](https://aclanthology.org/2025.tacl-1.69/)). Model judges can be useful but have documented position, verbosity, and self-enhancement biases ([Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685)); neither a green screen nor schema agreement should substitute for a calibrated human check.

## Verification limits

The review used saved annotations and direct prompt reconstruction, not fresh paid extraction. The reference-exam proportions are the values recorded in config; the underlying 124 reference passages and their annotations were not independently re-audited here. Recent cohorts are small, and changes in prompts, source selection, and providers overlap. The evidence establishes concrete control-path defects and persistent repetition signals; it does not establish the causal contribution of each previous intervention.
