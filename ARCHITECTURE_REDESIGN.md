# RC Generation Engine v2 — Structural Novelty Architecture

**Status:** Design document
**Replaces:** the single-prompt-per-tier design in `RC_PIPELINE.py`
**Implementation deltas** (the shipped `rc_engine/` diverges from this design in four small ways):
component libraries are JSON (`rc_engine/components/*.json`), not YAML;
the compliance threshold is structural F1 ≥ 0.75 (`config.COMPLIANCE_F1_THRESHOLD`), not 0.80;
the CLI verbs are `selftest / estimate / generate / backfill / health / export / avoid`
(§7's `batch / compare / backfill-fingerprints / corpus-health` were renamed);
and the student-simulation probe (§6) is not yet implemented — the
`corpus_health.probe_accuracy` column is reserved for it.
**Problem statement:** After several hundred RCs, students detect *structural* repetition — argumentative rhythm, paragraph movement, reversal timing, question logic — long before any embedding-based similarity check fires. The current pipeline guarantees this failure: the ELITE prompt prescribes one fixed dialectical shape ("early framing destabilized → corrective qualified → ending reopens"), one fixed question order (Q1 thesis … Q6 tone), and one fixed distractor taxonomy. Every elite RC is the same essay wearing a different topic.

**Design principle:** Structure must be a *sampled, tracked, audited variable*, not a prompt constant. Every structural decision the current prompt hardcodes moves into a **Blueprint** drawn from combinatorial component libraries, with usage history and multi-channel structural distance enforcement.

---

## 1. Overall Architecture

```
                      ┌────────────────────────────────────────────┐
                      │        COMPONENT LIBRARIES (YAML)          │
                      │  32 Argument Families · 20 Personas ·      │
                      │  20 Endings · 20 Rhythms · 20 Revelation   │
                      │  Patterns · 20 Distractor Profiles ·       │
                      │  20 Question Topologies · Compat. Rules    │
                      └───────────────┬────────────────────────────┘
                                      │
  RAG seed essay          ┌───────────▼───────────┐     usage history,
  (existing RAG.py) ─────►│ STAGE 1: BLUEPRINT    │◄─── exclusion windows,
                          │ COMPOSER              │     combo hashes
                          │ sample → constrain →  │     (SQLite)
                          │ LLM-refine → validate │
                          └───────────┬───────────┘
                                      │ Blueprint (hidden JSON, never shipped)
                          ┌───────────▼───────────┐
                          │ STAGE 2: PASSAGE      │──► Blueprint Compliance
                          │ RENDERER              │◄── Auditor (cheap model:
                          │ (Opus, blueprint-     │    did the passage realize
                          │  conditioned prompt)  │    the planned structure?)
                          └───────────┬───────────┘
                                      │ passage + realized-structure annotation
                          ┌───────────▼───────────┐
                          │ STAGE 3: QUESTION     │  questions derive from the
                          │ ENGINE                │  blueprint's trap map and
                          │ (topology profile +   │  topology profile — difficulty
                          │  distractor profile + │  is designed in Stage 1,
                          │  trap map → 6 MCQs)   │  not discovered afterwards
                          └───────────┬───────────┘
                                      │ full RC set
                          ┌───────────▼───────────┐
                          │ STAGE 4: NOVELTY      │  9 similarity channels vs.
                          │ AUDITOR               │  corpus history; structural
                          │ (fingerprint → score  │  fingerprints, not just
                          │  vs. history)         │  embeddings
                          └───────────┬───────────┘
                                      │
                          ┌───────────▼───────────┐
                          │ STAGE 5: QUALITY      │  existing layers, retained:
                          │ GATES                 │  prevalidate → blind solver
                          │                       │  → judge
                          └───────────┬───────────┘
                                      │
                              SQLite + export
```

Key inversions relative to the current pipeline:

1. **Structure is decided before prose exists.** The blueprint fixes paragraph functions, reversal locations, thesis-revelation timing, pacing, and ending behavior *as data*. The generation prompt becomes a thin renderer.
2. **Questions are planned with the passage, not after it.** The blueprint's `trap_map` designates specific misreadings the passage will *invite*; the question engine then writes distractors that harvest exactly those misreadings. Difficulty emerges from architecture, not from post-hoc distractor polishing.
3. **Novelty is enforced twice**: at composition time (the composer cannot pick components inside their exclusion windows, and must beat a minimum blueprint distance vs. the trailing window) and at audit time (the finished artifact is fingerprinted and compared on 9 channels — because the renderer can drift from the plan).

---

## 2. Blueprint Schema

The blueprint is hidden metadata. It is stored, versioned, and used for auditing — it never reaches the student. Schema (`blueprint_schema_version: "2.0"`):

```jsonc
{
  "blueprint_id": "BP_2026_07_0142",
  "schema_version": "2.0",
  "tier": "elite",
  "seed": { "essay_doc_id": "...", "essay_url": "...", "domain_hint": "sociology_institutions" },

  // ---- SKELETON: what the argument IS, structurally --------------------
  "skeleton": {
    "family_id": "F07",                       // one of 32 Argument Families
    "family_name": "The Vanishing Object",
    // Ordered paragraph plan. Functions come from the family's movement
    // grammar; lengths from the rhythm template. This is the contract the
    // renderer must satisfy and the compliance auditor checks.
    "movement": [
      { "para": 1, "function": "OBJECT_PRESENTED_AS_STABLE", "len_words": [110, 140], "cadence": "long_periodic" },
      { "para": 2, "function": "FIRST_CRITERION_FAILS",      "len_words": [80, 110],  "cadence": "mixed" },
      { "para": 3, "function": "RIVAL_CRITERION_ALSO_FAILS", "len_words": [120, 160], "cadence": "dense_analytic" },
      { "para": 4, "function": "HINGE_REDESCRIPTION",        "len_words": [30, 55],   "cadence": "staccato" },
      { "para": 5, "function": "QUESTION_DISSOLVED",         "len_words": [90, 120],  "cadence": "long_periodic" }
    ],
    // Author's apparent commitment to the final position, per paragraph,
    // in [-1, 1]. Negative = actively pointing away from it. This curve is
    // what students unconsciously learn — so it must vary across the corpus.
    "commitment_curve": [-0.3, 0.1, 0.2, 0.8, 0.6],
    "recursion_sites": [ { "para": 4, "re_reads": 1, "how": "para 1's confidence now reads as naive" } ]
  },

  // ---- TENSION SYSTEM: what is actually at stake -----------------------
  "tension_system": {
    "primary":   { "axis": "is X a natural kind or an artifact of method", "poles": ["realism", "constructivism"], "fate": "dissolved_not_resolved" },
    "secondary": { "axis": "expertise vs lived experience as arbiter",     "poles": ["expert", "practitioner"],    "fate": "left_open" },
    "interaction": "secondary surfaces only inside para 3 and silently survives the dissolution of the primary",
    "instability_degree": 0.7          // 0 = neat closure … 1 = fully suspended
  },

  // ---- REVELATION: when the reader can first see the thesis ------------
  "revelation": {
    "pattern_id": "R08",               // one of 20 Thesis Revelation Patterns
    "thesis_first_visible": { "para": 4, "mode": "retrospective_reveal" },
    "false_signals": [ { "para": 1, "type": "decoy_stability", "what": "opening treats the object as unproblematic" } ],
    "assumption_breaks": [ { "para": 2, "assumption": "that the classificatory criteria are independent of observers" } ]
  },

  // ---- VOICE ------------------------------------------------------------
  "voice": {
    "persona_id": "P12",               // one of 20 Authorial Personas
    "register": "epistemic_auditor",
    "signature_moves": ["distinguishes what-we-know from how-we-know mid-sentence", "quantifier discipline"],
    "hedging_style": "front_loaded_concessions",
    "forbidden_tics": ["furthermore", "tapestry", "delve", "paradigm", "it is a testament"]
  },

  // ---- RHYTHM & CLOSURE ---------------------------------------------------
  "rhythm":  { "template_id": "T13", "name": "Trapdoor", "shortest_para_position": 4, "sentence_len_profile": "bimodal" },
  "closure": {
    "ending_id": "E13", "name": "The Instrument Doubt",
    "aperture": "widens",              // widens | narrows | displaces | holds
    "final_gesture": "questions the analytic vocabulary the passage itself relied on"
  },

  // ---- TRAP MAP: designed misreadings — the bridge to Stage 3 ----------
  "trap_map": [
    { "trap_id": "TR1", "anchor": { "para": 1 }, "invited_misreading": "object's reality is the author's settled view",
      "mechanism": "premature_closure", "harvested_by": ["Q1"] },
    { "trap_id": "TR2", "anchor": { "para": 3 }, "invited_misreading": "rival criterion is endorsed because it is steelmanned",
      "mechanism": "level_confusion", "harvested_by": ["Q2", "Q5"] },
    { "trap_id": "TR3", "anchor": { "para": 5 }, "invited_misreading": "dissolution = skeptical nihilism about the field",
      "mechanism": "scope_inflation", "harvested_by": ["Q6"] }
  ],

  // ---- QUESTION PLAN ------------------------------------------------------
  "question_plan": {
    "topology_id": "QT10",             // one of 20 Question Topology Profiles
    "distractor_profile_id": "D11",    // one of 20 Distractor Profiles
    "slots": [
      { "q": 1, "type": "decoy_escape",        "targets": ["para1", "para4"], "difficulty": 0.8, "uses_traps": ["TR1"] },
      { "q": 2, "type": "structural_function", "targets": ["para3"],          "difficulty": 0.6, "uses_traps": ["TR2"] },
      { "q": 3, "type": "contextual_inference","targets": ["para4"],          "difficulty": 0.7 },
      { "q": 4, "type": "application",         "targets": ["global"],         "difficulty": 0.9 },
      { "q": 5, "type": "implicit_assumption", "targets": ["para2", "para3"], "difficulty": 0.8, "uses_traps": ["TR2"] },
      { "q": 6, "type": "stance",              "targets": ["global"],         "difficulty": 0.7, "uses_traps": ["TR3"] }
    ],
    "answer_letter_plan": ["C", "A", "D", "B", "A", "D"],    // sampled, audited
    "difficulty_curve_shape": "ambush"                        // from topology profile
  },

  // ---- NOVELTY CONTEXT (filled by the composer) --------------------------
  "novelty": {
    "combo_hash": "sha1(family|persona|ending|rhythm|revelation|distractor|topology)",
    "min_blueprint_distance_vs_window": 0.64,
    "nearest_recent_rc": "RC_E_0621_2",
    "excluded_components_at_sampling": { "families": ["F03","F17"], "personas": ["P05"] }
  }
}
```

Design notes on the schema:

- **`commitment_curve` replaces vague fields like "degree of instability at the end."** It is a per-paragraph signed series, which makes it *comparable* across RCs (correlation/DTW distance) — the single strongest predictor of "this author feels familiar."
- **`trap_map` replaces "reader trap locations."** Traps are first-class objects with IDs, so a question can *reference* the trap it harvests. This is what makes Stage 3 blueprint-driven instead of passage-driven.
- **`movement[].function` values come from a controlled vocabulary** (~60 paragraph-function tokens, defined per family grammar, e.g. `FRAME_PLANT`, `CONCESSION_TRAP`, `SCALE_JUMP`, `HINGE_REDESCRIPTION`, `COST_TALLY`, `RETROSPECTIVE_REREAD`). The finished passage gets annotated back into this same vocabulary, enabling edit-distance comparison between plan, realization, and corpus history.

---

## 3. Component Library

Stored as YAML files under `components/` — one file per library, entries carry structured fields, not prose blobs. Every entry has: `id`, `name`, `spec` (what the renderer receives), `signals` (what the fingerprinter later looks for), `incompatible_with` (constraint hooks), `tier_floor` (some families are too subtle for medium tier).

### 3.1 Argument Families (32)

Each family is a genuinely different *intellectual essay shape* — a different reason the essay exists — with its own movement grammar (allowed paragraph-function sequences) and its own natural difficulty source.

| ID | Family | Core movement | Where difficulty lives |
|----|--------|---------------|------------------------|
| F01 | **The Autopsy** | A debate everyone treats as settled is exhumed; the passage dissects *how* consensus formed rather than who was right; verdict on the process, not the question | separating the author's view of the debate from their view of the debate-about-the-debate |
| F02 | **The Borrowed Lens** | A framework imported from an alien discipline is applied, yields striking results, then the lens is shown to distort more than it reveals; ends on the price of borrowed vision | tracking when the author is *using* the lens vs. *examining* it |
| F03 | **The Scale Shift** | A claim holds at one scale (individual/local); the author zooms out and the claim inverts at the larger scale; the two scales are never reconciled | scope: every option that ignores scale is wrong, and most readers ignore scale |
| F04 | **The Definitional Undertow** | Surface argument about a phenomenon; the real argument is about the definition of the key term, revealed when two camps are shown to be talking past each other | recognizing the argument is semantic without concluding it is "merely" semantic |
| F05 | **The Reluctant Conversion** | Author begins openly resistant to a position and argues themselves, step by contested step, into a version of it — while pricing what conversion cost | distinguishing the adopted version from the version originally resisted |
| F06 | **The Third Thing** | Two rival explanations are rehearsed and *both* rejected for sharing a hidden premise; the passage's contribution is naming the premise, not offering a third theory | resisting the expectation that a third theory arrives; it never does |
| F07 | **The Vanishing Object** | Inquiry into X progressively reveals X may not be a coherent kind at all; the question is dissolved, not answered | the thesis is a redescription, not a position on the original question |
| F08 | **The Costed Victory** | A thesis is defended successfully; the final movement tallies what the defense had to concede; the thesis stands, diminished | the tone question: triumph and loss simultaneously true |
| F09 | **The Time-Lag Argument** | A concept is shown to be judged by criteria inherited from an era whose conditions no longer hold; the historical excavation *is* the argument | inference: what follows for the present is implied, never stated |
| F10 | **The Practitioner's Rebuke** | An elegant theoretical account collides with practitioner detail that breaks it; the author sides with neither and locates the value in the friction itself | refusing both "theory wins" and "practice wins" readings |
| F11 | **The Asymmetry Hunt** | Two things habitually treated as symmetric (memory/anticipation, praise/blame) are shown deeply asymmetric; consequences cascade | every distractor that restores symmetry is tempting and wrong |
| F12 | **The Successful Failure** | Case study of something that failed its stated goal but succeeded at an unstated one; becomes an argument about what goals are *for* | which success the author actually credits |
| F13 | **The Category Refugee** | A phenomenon fits no existing category; each candidate category is tried and shown to mutilate it; ends on what taxonomies do to their misfits | the passage's positive claim is about categorization, not the phenomenon |
| F14 | **The Inheritance Dispute** | Two traditions claim the same idea or figure as ancestor; the contest over lineage reveals more than the idea itself does | author's stance is on the *contest*, not on either claimant |
| F15 | **The Diagnostic Reversal** | What is widely lamented as the disease is re-read as an adaptive response — or the celebrated cure as the pathology | causal-direction traps write themselves |
| F16 | **The Silent Partner** | An argument everyone makes is shown to depend on an invisible enabling condition; the passage makes it visible and asks what happens as it erodes | the assumption question has a real, passage-internal answer |
| F17 | **The Half-Life** | Traces how a concept decays as it migrates from technical origin to public discourse; asks whether the degraded version still does real work | author's ambivalence: decay documented without contempt |
| F18 | **The Double Bind** | An institution faces two legitimate but incompatible demands; the passage refuses to dissolve the bind and instead maps who pays for it | no side is endorsed; distractors that pick a side all fail |
| F19 | **The Wrong Question** | The question as posed is patiently answered; the answer is shown unsatisfying; the question is reframed — and the new question is left unanswered | two-stage structure: readers freeze at the first answer |
| F20 | **The Minority Report** | A discredited or unfashionable view is steelmanned — not to endorse it, but to show what the mainstream lost by winning | endorsement traps: steelmanning read as advocacy |
| F21 | **The Instrument Effect** | The method of studying X is shown to partly produce the X it finds; findings about the world become findings about our instruments | keeping object-level and method-level claims separate |
| F22 | **The Threshold Argument** | A difference of degree becomes a difference of kind past some threshold; the entire argument is about locating — or denying the locatability of — the threshold | quantitative-sounding claims with qualitative stakes |
| F23 | **The Proxy War** | A minor technical dispute is anatomized as a proxy for a deep, unarguable commitment; the passage explains why proxies form where direct argument fails | the surface dispute is never adjudicated; readers expect adjudication |
| F24 | **The Hospitable Critic** | A body of work is reviewed with genuine admiration; a single load-bearing objection then retroactively reframes the admiration | tone: admiration is sincere AND the objection is fatal |
| F25 | **The Ecology** | Agent-level explanation is refused; the phenomenon is redescribed as a system-level equilibrium; ends noting what agency-talk loses and what systems-talk cannot see | level-of-explanation confusions power every distractor |
| F26 | **The Untranslatable** | Organized around a concept from another language or tradition that resists translation; the resistance itself is the evidence for the thesis | the concept is never defined; options that define it are traps |
| F27 | **The Simultaneity Problem** | Two developments always narrated in causal sequence are argued to be simultaneous and mutually causing; the standard story's arrow breaks | temporal-order distractors; the passage denies the order every reader assumes |
| F28 | **The Boring Truth** | Spectacular explanations are rehearsed and deflated in favor of a mundane one; the sting: the mundane truth is far harder to act on | anticlimax as structure; readers over-read drama into the ending |
| F29 | **The Moving Target** | A critique succeeded so thoroughly that its object changed shape; is the critique now obsolete, or more necessary than ever? An argument about critique's lifecycle | three time-slices of the same idea must be kept apart |
| F30 | **The Self-Application** | A theory is applied to itself (expertise-skepticism voiced by an expert); the recursion is managed in the open and the passage ends inside the loop | the author's position is structurally unstatable; stance options must reflect that |
| F31 | **The Load-Bearing Anecdote** | Opens on a small concrete incident; each return to the anecdote extracts a different layer; the final return reverses the initial reading | the anecdote's function changes three times; function questions abound |
| F32 | **The Coalition of Errors** | A true conclusion is widely believed for bad reasons; the passage separates the conclusion from its popular arguments and asks whether bad reasons corrupt good beliefs | agreeing with the conclusion while demolishing its usual defenses |

Each family's YAML entry additionally defines:
- `movement_grammar`: allowed paragraph-function sequences (a small regex/production set over the function vocabulary), so the composer can generate varied *instances* of a family — F03 with the scale-jump in para 2 vs. para 4 are different reading experiences.
- `question_affinities`: which question types this family makes *organically* hard (F06 → assumption questions; F31 → function questions), consumed by the topology sampler.
- `incompatible_endings` / `incompatible_revelations`: e.g. F19 (Wrong Question) forbids E07 (Quiet Verdict); F28 (Boring Truth) forbids R02 (Decoy First — the deflation *is* the decoy structure, doubling it reads as parody).

### 3.2 Authorial Personas (20)

A persona fixes register, sentence signature, hedging style, and characteristic moves — the things stylometry detects. Two RCs with different personas should read as different *people*, not the same writer in different moods.

| ID | Persona | Voice signature |
|----|---------|-----------------|
| P01 | **The Forensic Skeptic** | courtroom precision; weighs evidence in numbered steps hidden inside prose; withholds sympathy; verdicts arrive as subordinate clauses |
| P02 | **The Disenchanted Insider** | writes from within the field being criticized; elegiac authority; "we" that slowly becomes "they" |
| P03 | **The Genial Contrarian** | light touch, courteous demolitions; concedes charmingly before striking; short paragraphs of good humor around long ones of steel |
| P04 | **The Systems Cartographer** | impersonal; spatial and flow metaphors; agents almost never appear as sentence subjects; passive constructions used with intent |
| P05 | **The Moral Accountant** | tallies costs and beneficiaries; quietly indignant, never preachy; numbers and named parties where others use abstractions |
| P06 | **The Historian of the Present** | treats today as a period with a start date; archival calm; the present tense used sparingly, like a loan |
| P07 | **The Reluctant Modernist** | suspicious of novelty but honest about tradition's failures; double concessions; nostalgia flagged as bias in his own prose |
| P08 | **The Analytic Miniaturist** | tiny distinctions; short declaratives; dry wit; one two-word sentence per passage, placed where it hurts |
| P09 | **The Field Reporter Turned Theorist** | concrete sensory detail first, concepts second; theory always arrives late and slightly distrusted |
| P10 | **The Recovering Enthusiast** | once believed, now qualifies; warmth persists under the critique; past-tense self appears as a character |
| P11 | **The Institutional Anthropologist** | familiar institutions described as strange tribes; rituals, totems, kinship metaphors for bureaucracy |
| P12 | **The Epistemic Auditor** | obsessed with how we know, not what; distinguishes evidence-types mid-sentence; quantifier discipline ("some", "most", "the studied cases") |
| P13 | **The Comparative Synthesist** | triangulates across traditions or cultures; never lets one framework speak unaccompanied; comparison as argument |
| P14 | **The Patient Explicator** | generous teacher's pacing; defines terms honestly; turns the knife only in the final third — gentleness as setup |
| P15 | **The Ironic Formalist** | high formal register with controlled irony leaking at the seams; praise phrased so exactly it becomes damning |
| P16 | **The Pragmatist Judge** | "what work does this idea do?"; verdict-oriented; impatient with distinctions that make no difference, and says so |
| P17 | **The Melancholy Realist** | accepts hard truths without cynicism; declines available consolations explicitly; adjectives rationed |
| P18 | **The Precision Provocateur** | provocative claims defended with meticulous, almost pedantic care; the outrage is in the thesis, never the prose |
| P19 | **The Archaeologist of Ideas** | digs origin layers of concepts; sediment, stratum, excavation metaphors; etymology used as evidence, carefully |
| P20 | **The Cold Enthusiast** | evident fascination expressed in deliberately flat prose; exclamation of content, monotone of style; the gap is the voice |

Persona YAML fields: `sentence_length_profile`, `hedge_inventory` (each persona hedges *differently* — this kills the "correct answer is the most hedged option" tell at the corpus level), `metaphor_domains`, `transition_style`, `forbidden_tics`, `pronoun_posture`.

### 3.3 Ending Types (20)

| ID | Ending | Behavior |
|----|--------|----------|
| E01 | **The Widened Aperture** | the local question opens onto a larger one, explicitly unanswered |
| E02 | **The Returned Key** | reprises the opening image or example with its meaning reversed |
| E03 | **The Burden Shift** | ends by relocating the onus of proof onto the previously comfortable side |
| E04 | **The Practical Deflation** | grand theoretical movement lands on a deliberately small practical implication |
| E05 | **The Residue** | states precisely what remains unexplained after the best available account |
| E06 | **The Horizon Clause** | endorses the thesis "until X changes" — conditions its own obsolescence |
| E07 | **The Quiet Verdict** | one flat declarative judgment after sustained even-handedness |
| E08 | **The Displacement** | resolves the original tension by showing a different tension matters more |
| E09 | **The Cost Disclosure** | affirms the position and names its price in the same breath |
| E10 | **The Open Ledger** | enumerates what each side still owes the debate |
| E11 | **The Retrospective Frame** | final paragraph reveals the vantage point the whole passage was written from |
| E12 | **The Scale Exit** | jumps scales in the last lines (individual → species), suspending the argument between them |
| E13 | **The Instrument Doubt** | closes by questioning the analytic tools the passage itself used |
| E14 | **The Minor Character Promotion** | a side consideration becomes, in the last paragraph, the main event |
| E15 | **The Refused Synthesis** | explicitly declines the available middle ground, and gives the reason |
| E16 | **The Time Bomb** | notes a pending fact that will force the question to be re-asked |
| E17 | **The Narrowed Claim** | the thesis survives only at drastically reduced scope; the ending performs the reduction |
| E18 | **The Anti-Conclusion** | argues why concluding now would itself be an error |
| E19 | **The Handover** | passes the question to a different discipline or authority as more competent |
| E20 | **The Earned Banality** | arrives at a truism — and shows that the truism now means something different |

Note: only about half of these "reopen" the tension. The current elite prompt *mandates* reopening; that mandate is itself a learnable pattern. Closure behavior must vary, with `aperture ∈ {widens, narrows, displaces, holds}` tracked and balanced corpus-wide.

### 3.4 Paragraph Rhythm Templates (20)

Encoded as sequences over length classes (S <60w, M 60–110, L 110–160, XL >160) plus cadence directives. The rhythm template and the family movement grammar are unified by the composer (rhythm supplies lengths/pacing; family supplies functions).

| ID | Template | Shape |
|----|----------|-------|
| T01 | **Monolith & Shards** | XL–S–S–S: one dense analytical block, then three short strikes |
| T02 | **Staircase** | S–M–L–XL: paragraphs lengthen as the argument deepens |
| T03 | **Inverted Staircase** | XL–L–M–S: long opening scene tightening to an aphoristic close |
| T04 | **Pendulum** | L–S–L–S–L: thesis work in the long paras, doubt in the short ones |
| T05 | **Twin Peaks** | L–S(hinge)–L: two dense blocks separated by a one-sentence pivot paragraph |
| T06 | **Slow Fuse** | M–M–M–L: three even expository paragraphs; all detonation in the last |
| T07 | **Front-Load** | XL–M–S–S: the hardest analytic work first; consequences cascade after |
| T08 | **Interruption** | M–M–S!–M–M: one anomalously short mid-passage paragraph that breaks frame |
| T09 | **Braid** | M–M–M–L: three strands touched in rotation, woven together only in the final block |
| T10 | **Spiral** | L–M–S: the same question revisited at three depths, paragraphs shrinking each pass |
| T11 | **Ledger** | M–S–M–S–M: paired claim/cost paragraphs, symmetric until one claim goes unpaired |
| T12 | **Wave** | M–M–M–M: uniform lengths as camouflage — all variation lives in sentence cadence |
| T13 | **Trapdoor** | M–M–M–M: even paragraphs; the last sentence of para 3 changes everything; para 4 lives in the aftermath |
| T14 | **Overture** | M–L–L–M: opening touches every theme briefly; the rest develops them out of order |
| T15 | **Long Corridor** | L–L–L: single-minded linear build, no digressions; the door opens sideways in the final line |
| T16 | **Eddy** | M–L–M(recursive)–L: one paragraph explicitly re-reads an earlier one |
| T17 | **Counterweight** | M–S–M–S–M: every assertion followed by a shorter counter — until one assertion goes unanswered |
| T18 | **Cold Open** | M–M–L–M: starts mid-argument as if the reader missed a page; context backfills |
| T19 | **Descent** | L–M–M–S: abstract opening, each paragraph more concrete, ending on a single instance carrying the whole weight |
| T20 | **Ascent** | S–M–L–XL: concrete incident, each paragraph a level up in abstraction |

### 3.5 Thesis Revelation Patterns (20)

| ID | Pattern | Mechanism |
|----|---------|-----------|
| R01 | **Immediate-then-Eroded** | thesis stated in the first lines; the passage spends itself qualifying it; final version barely resembles the first |
| R02 | **Decoy First** | a plausible thesis planted early; the real thesis displaces it mid-passage |
| R03 | **Negative Space** | the thesis is never stated; it emerges from the pattern of what the author refuses to accept |
| R04 | **Late Crystallization** | accumulating observations crystallize into a claim only in the penultimate paragraph |
| R05 | **Two-Stage** | half the thesis mid-passage; the second half — the sting — withheld until the end |
| R06 | **Borrowed Mouth** | the thesis first appears in the mouth of a quoted opponent, then is reclaimed and modified |
| R07 | **Question Form** | the thesis appears only as a question; the answer is implied by the structure, never voiced |
| R08 | **Retrospective Reveal** | the final movement reframes everything; the thesis is visible only on a mental re-read |
| R09 | **Progressive Sharpening** | the same claim stated three times with rising precision; the versions differ in what they surrender |
| R10 | **Casual Aside** | the thesis dropped mid-paragraph as if it were a minor observation |
| R11 | **Definitional Smuggle** | the thesis hidden inside how the key term is defined at the outset; recognized as a thesis only late |
| R12 | **Concessive Carrier** | the thesis lives inside a "granted, …" clause — the concession is the claim |
| R13 | **Split Thesis** | two half-theses in different paragraphs, never joined; joining them is the reader's job (and Q1's) |
| R14 | **Counter-Punch** | the thesis emerges only as the rebuttal to the strongest objection |
| R15 | **Example-Borne** | never abstractly stated; fully embodied in the treatment of one example |
| R16 | **Escalating Denial** | the author repeatedly says what the thesis is *not*; the positive content is the residue |
| R17 | **Frame Shift** | apparent thesis about X revealed as a thesis about how we discuss X |
| R18 | **Delayed Referent** | an abstract phrase used early acquires its referent late; the thesis snaps into focus retroactively |
| R19 | **Convergence** | two independent argumentative lines converge; the thesis is the intersection point, stated once |
| R20 | **Erosion Reversal** | the passage seems to erode a claim; the ending reveals the erosion was to expose its survivable core |

### 3.6 Distractor Profiles (20)

A profile is a *distribution* over trap mechanisms plus placement strategy — which slots get which trap types — so distractor logic varies set-to-set instead of every question carrying the same four error flavors.

| ID | Profile | Dominant mechanisms |
|----|---------|---------------------|
| D01 | **The Premature Closer** | options resolve tensions the passage left open; punishes readers who crave closure |
| D02 | **The Scope Inflater** | local claims globalized; paragraph-level truths presented as passage-level theses |
| D03 | **The Time Traveler** | correct content attributed to the wrong *stage* — early framings presented as final views |
| D04 | **The Sympathetic Import** | plausible frameworks the passage never used; punishes outside knowledge |
| D05 | **The Half-Truth Ledger** | accurate for one strand of the argument, silent about the other |
| D06 | **The Inversion Artist** | causal and priority reversals; effect as cause, evidence as conclusion |
| D07 | **The Tone Deaf** | content-right, stance-wrong; attributes advocacy where there is analysis |
| D08 | **The Vocabulary Magnet** | recycles the passage's most memorable phrases in structurally wrong roles |
| D09 | **The Reasonable Extremist** | moderate wording concealing logically extreme content — the inverse of lexical extremity |
| D10 | **The Straw Vendor** | attributes the weaker version of positions the passage steelmanned |
| D11 | **The Category Slipper** | swaps claim types: empirical↔normative, descriptive↔definitional, is↔ought |
| D12 | **The Consensus Peddler** | what an educated reader already believes, independent of this passage |
| D13 | **The Symmetry Faker** | treats asymmetric relations as mutual; "each shapes the other" where only one does |
| D14 | **The Level Confuser** | confuses the author's view with views the author reports |
| D15 | **The Necessary/Sufficient Swapper** | conditions promoted or demoted; enabling factors as guarantees |
| D16 | **The Example Promoter** | elevates an illustrative example into load-bearing evidence |
| D17 | **The Missing Link** | valid-sounding inference that skips the passage's actual bridge |
| D18 | **The Overqualifier** | adds hedges the passage doesn't license; sounds safe, is wrong — trains students off the "pick the moderate one" heuristic |
| D19 | **The Adjacent Answer** | the correct answer to the neighboring, unasked question |
| D20 | **The Terminological Twin** | near-synonyms whose technical meanings diverge exactly where it matters |

Each profile fixes: primary mechanism (~2 distractors/set), secondary (~1/set), placement rules ("the trap option in Q1 must be the *shortest*"), and a hedging-parity policy. Corpus-level constraint: per-slot conditional patterns are audited (if "Q1's best trap is always premature closure" holds across the corpus, that's a leak — see §6, channel 6).

### 3.7 Question Topology Profiles (20)

A topology fixes: the multiset of question types, their order, the difficulty curve, and dependency structure. The fixed Q1-thesis…Q6-tone sequence is abolished.

| ID | Topology | Structure |
|----|----------|-----------|
| QT01 | **Classic Gauntlet** | thesis first, hardest inference last; canonical, used sparingly |
| QT02 | **Inverted** | opens micro (phrase-in-context), thesis question *last* — forces full-passage retention |
| QT03 | **Structural Emphasis** | three of six questions on function/role of specific moves |
| QT04 | **Application Heavy** | two new-scenario application questions, one easy, one brutal |
| QT05 | **Local–Global Ladder** | strict alternation between local and global questions |
| QT06 | **The Ambush** | four accessible openers, then a brutal final pair |
| QT07 | **Assumption Cluster** | two implicit-assumption questions on *different* argumentative moves |
| QT08 | **Tone Split** | separate stance questions: toward the subject vs. toward rival positions |
| QT09 | **Cross-Paragraph Weave** | every question requires integrating two or more non-adjacent paragraphs |
| QT10 | **The Decoy Mirror** | first question directly tests whether the reader escaped the passage's planted decoy |
| QT11 | **Evidence Audit** | questions about what work the examples do, not what they say |
| QT12 | **Counterfactual Set** | "if this paragraph were removed/replaced" structural questions |
| QT13 | **The Compression Test** | long analytical stems, terse options; discrimination lives in the stem |
| QT14 | **The Expansion Test** | terse stems, options carrying fine distinctions; discrimination lives in the options |
| QT15 | **Sequential Dependency** | a later question is much easier if an earlier question's territory was understood — rewards integrative readers |
| QT16 | **Deep Drill** | two questions on the single densest paragraph, from different angles |
| QT17 | **Author vs. Reported** | two questions dedicated to separating the author's voice from voiced positions |
| QT18 | **Strengthen/Weaken Pair** | CR-style: one question strengthens a passage claim, another weakens it |
| QT19 | **The Ending Interrogation** | two questions on closure behavior: why end there, and what is implied next |
| QT20 | **The Uniform Field** | six questions of identical moderate difficulty — no rhythm cue about where the danger is |

---

## 4. Combination Strategy

**Raw space:** 32 × 20⁶ = 2.05 × 10⁹ combinations. After compatibility pruning (~40–60% survival) the usable space is still ≥ 8 × 10⁸ — three orders of magnitude beyond the 10⁶ requirement. Family movement-grammar variation (each family admits multiple movement instantiations) multiplies this further.

**Sampling algorithm (BlueprintComposer):**

1. **Hard exclusion windows** (per component type, tuned to corpus velocity):
   - Argument family: not reusable within the last **25** RCs
   - Question topology: **12**; Persona: **10**; Revelation pattern: **10**; Distractor profile: **8**; Ending: **8**; Rhythm: **6**
   - Exact combo hash (all 7 IDs): **never** reused
   - Pairwise combos (family × revelation, family × ending, topology × distractor): not reusable within **60** RCs — pairs are what students actually learn ("Vanishing Object essays always end in Instrument Doubt")
2. **Usage-decay weighting** on the survivors: `weight(c) = base(c) · λ^(uses in trailing 100)`, λ ≈ 0.5 — soft pressure toward under-used components on top of the hard windows.
3. **Compatibility filter:** rule-based (`constraints.py`), not a dense matrix — each rule names the components and the reason (auditability). ~80–120 rules expected.
4. **Distance pre-check:** candidate blueprint's categorical distance (see §6, channel 1) against every blueprint in the trailing 50 must exceed **0.55**; resample up to K times, then relax least-important dimension (rhythm) first.
5. **Coverage steering:** a low-discrepancy scheduler nudges sampling so that over any 100-RC window, family usage stays within ±50% of uniform (KL divergence alarm at 0.15). Novelty for one student is a *distributional* property of the corpus, not just adjacent-pair dissimilarity.
6. **LLM refinement pass:** the sampled skeleton goes to a mid-tier model that fills the free slots — tension axes appropriate to the seed essay's domain, concrete trap anchors, movement-grammar instantiation — *without* changing any sampled ID. Deterministic sampler owns structure; LLM owns content.

**Tier mapping:** medium = simpler families only (`tier_floor`), instability ≤ 0.4, topology restricted to QT01/02/05/20; hard = full family list, instability ≤ 0.7; elite = full space. Tiers become *parameter regions*, not separate prompt universes.

---

## 5. Stage Details

### Stage 2 — Passage Renderer
- System prompt is assembled from the blueprint: persona spec (verbatim voice card), movement table (function + length + cadence per paragraph), revelation schedule, trap map ("para 1 must *invite* the misreading that…"), ending directive, forbidden tics. The seed essay supplies subject matter only.
- Explicit instruction: the blueprint is a **structural contract**; the model invents all content.
- **Blueprint Compliance Auditor** (Haiku-class): receives passage + blueprint, annotates each realized paragraph with a function token, locates realized thesis-visibility and assumption-break points, verifies trap anchors exist and forbidden tics don't. Output = realized-structure JSON in the same vocabulary as the plan. Compliance score = weighted structural F1 (movement-function match ≥ 0.8, thesis-visibility paragraph within ±1, all traps present). Fail → targeted regeneration with diff-based directives ("para 3 performed HINGE early; move the redescription to para 4").
- The **realized** structure annotation (not the planned one) is what enters the fingerprint store — plans drift, and the audit must reflect what students actually read.

### Stage 3 — Question Engine
- Input: passage + blueprint (`question_plan`, `trap_map`, realized-structure annotation). Each slot is generated to spec: type, target span, difficulty, and — where designated — the specific trap it harvests. Distractors for trap-harvesting questions must *quote the misreading the passage was built to invite*: difficulty is inherited from architecture.
- The distractor profile fixes mechanism distribution; hedging-parity and letter-plan rules move here from the old monolithic prompt (the letter plan is *sampled per-set* and audited corpus-wide, replacing per-set-only constraints).
- Answer-key explanations name the trap_id → mechanism, so review humans see the design intent.

### Stage 4 — Novelty Auditor: see §6.

### Stage 5 — Quality Gates
- Existing `prevalidate_rc`, `blind_solve`, and judge are retained with two changes: (a) judge rubrics are generated *from the blueprint* — "structural asymmetry" is no longer a universal virtue; a T15 Long Corridor passage must be judged linear-and-dense, not penalized for lacking reversals; (b) prevalidation checks the sampled letter plan instead of a fixed distribution rule.

---

## 6. Similarity Scoring Algorithm (Novelty Auditor)

Nine channels. Embeddings are one of nine. Every channel produces similarity ∈ [0,1] against (i) each RC in a trailing window (default 100) and (ii) corpus-level distributions.

| # | Channel | Representation | Metric | Pairwise cap |
|---|---------|----------------|--------|--------------|
| 1 | **Blueprint categorical distance** | 7 component IDs + instability + aperture | weighted Hamming (family mismatch weight 0.35; topology 0.2; revelation 0.15; persona 0.1; others 0.2 total) | sim > 0.45 vs any RC in window → reject at composition |
| 2 | **Movement-string distance** | realized paragraph-function string, e.g. `FRAME_PLANT·CONCESSION_TRAP·SCALE_JUMP·HINGE·COST_TALLY` | normalized Levenshtein over the function alphabet, plus Jaccard on function-transition bigrams | Levenshtein sim > 0.7 **or** bigram Jaccard > 0.6 |
| 3 | **Commitment-curve correlation** | per-paragraph signed commitment series (extracted by the compliance auditor from the *finished* passage) | DTW distance, normalized; Pearson r as fast pre-filter | r > 0.85 with same-sign endpoints |
| 4 | **Rhythm fingerprint** | vector: [para count, length variance, shortest-para position (normalized), pivot position, per-para mean & std sentence length, question-mark and em-dash densities] | cosine after z-scoring against corpus | cos > 0.92 |
| 5 | **Question topology distance** | multiset of (type, target-span class, difficulty-bin) + order string | Earth-mover's over the type distribution + order edit distance, averaged | sim > 0.75 |
| 6 | **Distractor mechanism distribution** | per-set histogram over the 20 mechanisms + per-slot conditional table (slot → mechanism) corpus-wide | Jensen–Shannon vs. trailing-window per-set histograms; χ² test on slot-conditional table | JSD < 0.1 vs window mean (too *predictable*) → flag; any slot-conditional cell > 3× expected → flag |
| 7 | **Stylometric distance (voice)** | Burrows' Delta over top-150 function words + hedge-marker inventory + transition inventory + sentence-length distribution | Burrows' Delta (lower = more same-author) | Delta < 0.9 vs any RC with a *different* persona ID → persona leakage flag |
| 8 | **Answer-behavior pattern** | letter sequence, correct-option length-rank sequence, correct-option hedge-rank sequence over trailing 20 sets | runs test + χ² against uniform on each series | p < 0.01 non-randomness → flag (this is corpus-level, blocks export not the single RC) |
| 9 | **Semantic embedding** | existing bge-small passage embedding | cosine | > 0.80 (tightened from 0.85, since it is no longer the only gate) |

**Composite:** `novelty = 1 − max_over_window( Σ wᵢ · simᵢ )` with weights `w = [.20, .18, .14, .08, .14, .10, .08, —, .08]` (channel 8 is corpus-level, applied separately). Verdict:
- any single pairwise cap breached → **reject** (regenerate: composition-time breaches resample the blueprint; render-time breaches re-render with directives). *As implemented since `25800c3`: channels 3 and 9 (curve, embedding) additionally require a supporting structural channel or an extreme score before they veto — see `novelty.py::_coarse_channel_supported` and `config.NOVELTY_SUPPORT_CAPS`; the curve cap stays dormant below `CURVE_CAP_MIN_CORPUS = 75` fingerprints.*
- composite novelty < 0.35 vs any window RC → reject
- corpus-level flags (channels 6, 8, coverage KL) → **hold export batch**, not the RC — these are distributional leaks fixed by scheduling, not regeneration.

**The student-simulation probe (run weekly, the metric that matters):** feed a strong model the last 10 shipped RCs (passages only), then the *opening paragraph* of a candidate; ask it to predict — where the thesis becomes visible, where the first reversal lands, whether the ending widens or narrows, which question types will appear. Score its predictions against the blueprint. Prediction accuracy is the direct operationalization of "students start predicting the author's rhythm." Trend it; alarm if it rises above a floor (~30% structured-prediction accuracy). This is the end-to-end test the nine channels approximate.

---

## 7. Class Structure

```
rc_engine/
├── components/
│   ├── families.yaml            # 32 argument families (movement grammars, affinities, constraints)
│   ├── personas.yaml            # 20 voice cards
│   ├── endings.yaml             # 20
│   ├── rhythms.yaml             # 20
│   ├── revelations.yaml         # 20
│   ├── distractor_profiles.yaml # 20
│   ├── topologies.yaml          # 20
│   └── constraint_rules.yaml    # named incompatibility rules
├── models.py                    # frozen dataclasses: ArgumentFamily, Persona, EndingType,
│                                #   RhythmTemplate, RevelationPattern, DistractorProfile,
│                                #   QuestionTopology, Blueprint, RealizedStructure, NoveltyReport
├── registry.py                  # ComponentRegistry — loads/validates YAML, resolves IDs
├── composer.py                  # BlueprintComposer — sampling, exclusion windows, decay
│                                #   weights, coverage steering, distance pre-check, LLM refine
├── constraints.py               # CompatibilityRules — rule engine over component tuples
├── renderer.py                  # PassageRenderer — prompt assembly + generation call
├── compliance.py                # ComplianceAuditor — realized-structure extraction, structural F1
├── question_engine.py           # QuestionEngine — slot-by-slot generation from plan + trap map
├── fingerprints.py              # Fingerprinter — movement string, curves, rhythm vector,
│                                #   trap histogram, stylometry, embedding
├── novelty.py                   # NoveltyScorer (9 channels) + CorpusHealth (KL, χ², probe)
├── history.py                   # HistoryStore — component_usage, fingerprints, combo hashes
├── quality.py                   # existing prevalidate / blind_solve / judge, blueprint-aware
├── pipeline.py                  # RCPipeline orchestrator (stages 1–5, retries, cost ledger)
└── cli.py                       # batch / compare / backfill-fingerprints / corpus-health
```

Key classes (signatures):

```python
class BlueprintComposer:
    def __init__(self, registry: ComponentRegistry, history: HistoryStore,
                 rules: CompatibilityRules, config: ComposerConfig): ...
    def compose(self, tier: str, seed: SeedEssay) -> Blueprint:
        """sample components → validate constraints → distance pre-check →
        LLM refinement (fills tension axes, trap anchors, movement instance) →
        final Blueprint. Raises CompositionExhausted after K resamples."""

class ComplianceAuditor:
    def audit(self, passage: str, bp: Blueprint) -> tuple[RealizedStructure, float, list[str]]:
        """returns (realized structure, structural F1, regeneration directives)"""

class NoveltyScorer:
    def score(self, fp: Fingerprint, window: list[Fingerprint]) -> NoveltyReport:
        """per-channel similarities, nearest neighbor per channel, composite, verdict"""

class RCPipeline:
    def generate_one(self, tier: str, seed: SeedEssay) -> RCResult:
        """Stage 1..5 with bounded retries; every artifact persisted"""
```

---

## 8. Database Schema Additions

```sql
-- The hidden metadata. One row per generated blueprint (including rejected ones —
-- rejected blueprints are training data for tuning windows and weights).
CREATE TABLE blueprints (
    blueprint_id     TEXT PRIMARY KEY,
    rc_id            TEXT REFERENCES rc_sets(rc_id),   -- NULL until an RC ships from it
    tier             TEXT NOT NULL,
    family_id        TEXT NOT NULL,
    persona_id       TEXT NOT NULL,
    ending_id        TEXT NOT NULL,
    rhythm_id        TEXT NOT NULL,
    revelation_id    TEXT NOT NULL,
    distractor_profile_id TEXT NOT NULL,
    topology_id      TEXT NOT NULL,
    instability      REAL,
    aperture         TEXT,                              -- widens|narrows|displaces|holds
    combo_hash       TEXT NOT NULL,                     -- full 7-tuple hash
    pair_hashes      TEXT NOT NULL,                     -- JSON: the audited pairwise hashes
    blueprint_json   TEXT NOT NULL,
    status           TEXT NOT NULL,                     -- composed|rendered|shipped|rejected_<stage>
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_bp_family ON blueprints(family_id, created_at);
CREATE UNIQUE INDEX idx_bp_combo ON blueprints(combo_hash) WHERE status = 'shipped';

-- Per-component usage ledger driving exclusion windows and decay weights.
CREATE TABLE component_usage (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    component_type TEXT NOT NULL,        -- family|persona|ending|rhythm|revelation|distractor|topology
    component_id   TEXT NOT NULL,
    blueprint_id   TEXT NOT NULL REFERENCES blueprints(blueprint_id),
    shipped        INTEGER NOT NULL DEFAULT 0,
    used_at        TEXT NOT NULL
);
CREATE INDEX idx_cu_lookup ON component_usage(component_type, component_id, used_at);

-- Structural fingerprints of the FINISHED artifact (realized, not planned).
CREATE TABLE fingerprints (
    rc_id              TEXT PRIMARY KEY REFERENCES rc_sets(rc_id),
    movement_string    TEXT NOT NULL,     -- e.g. "FRAME_PLANT|CONCESSION_TRAP|SCALE_JUMP|HINGE|COST_TALLY"
    commitment_curve   TEXT NOT NULL,     -- JSON array of floats
    rhythm_vector      TEXT NOT NULL,     -- JSON array
    topology_signature TEXT NOT NULL,     -- JSON: [(type, span_class, difficulty_bin), ...] + order
    trap_histogram     TEXT NOT NULL,     -- JSON: mechanism -> count
    letter_sequence    TEXT NOT NULL,
    stylometry         TEXT NOT NULL,     -- JSON: function-word freqs, hedge inventory, sentence-length stats
    embedding          TEXT,              -- moved here from rc_sets.passage_embedding
    created_at         TEXT NOT NULL
);

-- Audit trail: one row per novelty evaluation (including failures).
CREATE TABLE novelty_audits (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    rc_id             TEXT,
    blueprint_id      TEXT NOT NULL,
    channel_scores    TEXT NOT NULL,      -- JSON: channel -> {sim, nearest_rc_id}
    composite         REAL NOT NULL,
    verdict           TEXT NOT NULL,      -- pass|reject_pairwise|reject_composite|flag_corpus
    details           TEXT,
    created_at        TEXT NOT NULL
);

-- Weekly corpus-health snapshots (KL drift, slot-conditional χ², probe accuracy).
CREATE TABLE corpus_health (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    window_size        INTEGER NOT NULL,
    family_kl          REAL, topology_kl REAL,
    slot_chi2_flags    TEXT,              -- JSON
    probe_accuracy     REAL,              -- student-simulation structured-prediction accuracy
    letter_runs_p      REAL,
    created_at         TEXT NOT NULL
);

-- rc_sets additions (via the existing _ensure_column migration helper):
--   blueprint_id TEXT, compliance_f1 REAL, novelty_composite REAL
```

---

## 9. Generation Pseudocode

```python
def generate_one(tier: str, seed: SeedEssay) -> RCResult:
    # ---------- STAGE 1: BLUEPRINT ----------
    for attempt in range(MAX_COMPOSE_ATTEMPTS):                    # cheap: sampling is local
        bp = composer.sample_skeleton(tier)                        # IDs only, respects windows/rules/decay
        if novelty.blueprint_distance(bp, history.window(50)) < 0.55:
            continue                                               # channel-1 pre-check, no LLM cost yet
        bp = composer.llm_refine(bp, seed)                         # fills tensions, trap anchors, movement instance
        if rules.validate(bp):
            break
    history.record(bp, status="composed")

    # ---------- STAGE 2: PASSAGE ----------
    directives = []
    for attempt in range(MAX_RENDER_ATTEMPTS):
        passage = renderer.render(bp, seed, directives)            # Opus, blueprint-conditioned
        realized, f1, directives = compliance.audit(passage, bp)   # Haiku
        if f1 >= 0.80:
            break                                                  # else: re-render with targeted directives
    else:
        return fail(bp, "compliance")

    # ---------- STAGE 3: QUESTIONS ----------
    questions = question_engine.build(bp.question_plan, bp.trap_map, passage, realized)
    #   slot-by-slot; trap-harvesting distractors quote the blueprint's invited misreadings;
    #   letter plan and hedging-parity enforced mechanically post-hoc (regex/count checks, free)

    # ---------- STAGE 4: NOVELTY ----------
    fp = fingerprinter.extract(passage, questions, realized)       # deterministic + one Haiku call (curve)
    report = novelty.score(fp, history.fingerprint_window(100))
    if report.verdict == "reject_pairwise":
        # structural collision: decide layer — blueprint collision → resample (Stage 1);
        # voice/rhythm collision with different components → re-render (Stage 2)
        return retry_at(report.colliding_channel)
    if report.composite < 0.35:
        return retry_at("stage1")

    # ---------- STAGE 5: QUALITY (existing, blueprint-aware) ----------
    rc_text = assemble(passage, questions)
    pv = prevalidate(rc_text, bp)                                  # letter plan from bp, not fixed rule
    solver = blind_solve(rc_text)                                  # unchanged; disputes → human review
    judge  = judge_with_rubric(rc_text, rubric_from(bp))           # rubric derived from blueprint

    persist(bp, rc_text, fp, report, solver, judge)                # blueprints/fingerprints/audits tables
    history.mark_shipped(bp)                                       # activates exclusion windows
    return RCResult(...)
```

Cost note: Stages 1 and 4 add roughly one mid-tier refine call + two Haiku calls (compliance, curve extraction) per RC — a few cents against the existing Opus generation cost, and the compliance loop *reduces* wasted full regenerations by converting them into targeted re-renders.

---

## 10. Integration Plan (into the existing pipeline)

Phased so revenue generation never stops:

**Phase 0 — Backfill (no behavior change).** Build `fingerprints.py`; run it over every RC already in `rc_sets` (fingerprints require only the text + a Haiku annotation pass). Create the new tables. This gives the novelty auditor a history on day one and produces the first honest measurement of how repetitive the existing corpus is.

**Phase 1 — Shadow mode.** Implement registry, composer, and the blueprint schema. On every generation run, compose a blueprint and store it — but keep the current monolithic prompts. Compare: does the *unconstrained* generator keep landing on the same 3–4 implicit families? (It will; this is the business case made measurable.)

**Phase 2 — Blueprint-conditioned rendering.** Replace `ELITE_GENERATION_PROMPT`'s structural sections (I.3–I.6) with the assembled blueprint contract; add `compliance.py`. The question sections still ride along in one call. `process_one()` in `RC_PIPELINE.py` gains a `blueprint` parameter; `prevalidate_rc` reads the letter plan from it.

**Phase 3 — Split question generation.** Extract Stage 3 into its own call driven by `question_plan` + `trap_map`. Retire the fixed Q1–Q6 ordering and the global "no letter more than twice" rule in favor of sampled plans + corpus-level channel-8 auditing.

**Phase 4 — Novelty auditor live.** Enable the 9-channel scorer as a gate; tune caps on the backfilled corpus (set caps so ~10% of the *historical* corpus would have been rejected — that calibrates thresholds to observed human-noticeable repetition). Add the weekly student-simulation probe and `corpus_health` snapshots.

**Phase 5 — Retire the old path.** `rc_pipeline_old.py` and the monolithic prompts move to an archive; tiers become composer parameter regions. Keep `--compare` mode: same seed, three tiers — now also same family, escalating instability, which makes the comparison cleaner than today's.

Existing assets preserved: `RAG.py` unchanged (seed sourcing); solver/judge/export unchanged in interface; the SQLite migration pattern (`_ensure_column`) is reused.

---

## 11. Validation Strategy (summary)

1. **Composition-time:** constraint rules + exclusion windows + blueprint-distance pre-check (deterministic, free).
2. **Render-time:** compliance audit — structural F1 between planned and realized structure ≥ 0.80; targeted re-render directives on failure.
3. **Artifact-time:** 9-channel novelty scoring with pairwise caps and composite floor.
4. **Corpus-time:** weekly health snapshot — family/topology KL drift, slot-conditional χ², letter runs test, and the student-simulation probe (the ground-truth metric for "students are learning the rhythm").
5. **Quality (existing):** prevalidate → blind solver disputes → blueprint-aware judge → human review queue.
6. **Empirical (once on platform):** track per-student accuracy on their 2nd/3rd exposure to the same family vs. first exposure. If second-exposure accuracy jumps > ~5 points controlling for ability, the family is leaking a learnable signature → rotate it out and commission a replacement.

---

## 12. Future Scaling Recommendations

1. **Component lifecycle management.** Families are consumables. After ~40 shipped uses, a family enters *cool-off*; the student-simulation probe decides whether it returns. Commission new families quarterly: an LLM proposes candidates → each candidate must beat the movement-string and topology distance thresholds against ALL existing families before admission → human editor approves. The libraries are versioned (`families.yaml` carries `library_version`; blueprints record it).
2. **Per-student exposure guarantees.** Once the platform knows which RCs a student saw, enforce novelty *per student*, not just per corpus: no student sees the same family twice within a mock series, or the same (family × ending) pair ever. This is a simple join against `blueprints` and turns the architecture into a direct product feature ("no two RCs you receive share an argumentative skeleton").
3. **Parallel generation with component reservation.** At batch scale, workers must reserve component tuples from `HistoryStore` transactionally before composing, or concurrent workers will sample colliding blueprints that only fail at audit time.
4. **Difficulty calibration loop.** Blueprint difficulty fields are currently design intent. Once student response data exists, fit item-response models per (family, topology, slot-type) and feed measured difficulty back into the composer — the blueprint's `difficulty` numbers become empirically calibrated.
5. **Cross-tier structural sharing.** A medium RC and an elite RC may share a family with different instability — deliberately: it teaches the *skill* transfer while the surface remains unpredictable. Track family exposure across tiers in per-student guarantees.
6. **Threshold auto-tuning.** Log every rejected artifact with its channel scores. Quarterly, re-fit channel weights so that the composite score maximally separates human-flagged "feels familiar" pairs from clean pairs (a few hundred human pair-judgments are enough for logistic-regression weight fitting).
7. **Move history to Postgres when corpus > ~5k RCs** — the pairwise novelty scan is O(window) per candidate and fine in SQLite for years, but stylometric channel 7 benefits from pgvector for the function-word profiles alongside embeddings.
