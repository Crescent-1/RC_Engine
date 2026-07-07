# Volume Guardrails, Blind Spots, 30-Day GTM, Commoditization Answer

## Exception handling at volume (the ≤1 hr/day design)

Weekly cadence, never ad hoc: **generate Mon → review windows Tue/Thu → ship Fri.**

Three review lanes:
- **Lane A (auto-pass)**: all gates passed, judge ≥ 8, compliance F1 ≥ 0.85 →
  20% random spot-check only. Expect ~70% of volume here.
- **Lane B (`needs_review`)**: full human pass. Notes column says why.
- **Lane C (`solver_dispute`)**: adjudication rule — if the solver's alternative
  reading is plausible to two readers, regenerate that question slot; never
  argue a defensible dispute into the ground. Disputes are batched into the
  Tue/Thu windows.

Telemetry that gates growth:
- Track dispute rate per (family, topology). Trailing-20 dispute rate > 15% →
  cool that component off (ties into the component lifecycle plan).
- Client-facing SLA is 72h on disputes/corrections — internally you have two
  review windows inside any 72h period, so the SLA is safe by construction.

**Reviewer bench (build before client #3):** single faculty reviewer is the real
bottleneck. 5 clients ≈ 150–200 sets/month; full review at 10 min/set = 30+ hrs.
Hire 2–3 VARC-strong reviewers (recent 99+ percentilers) at ₹100–150/set
piece-rate for Lane A spot-checks and first-pass Lane B; the faculty reviewer
becomes final authority on Lane C + calibration audits of the bench. Budget
≈ ₹15–25k/month at 5 clients — priced into the tiers already.

## Blind spots (non-obvious risks) and structural counters

1. **Client faculty as silent saboteur.** The founder buys, but faculty evaluates —
   and your content replaces their labor. Counter: trap-map teaching notes make
   faculty the beneficiary (debrief material); name their faculty "final editorial
   authority" in the workflow. Sell *to* founders, position *for* faculty.
2. **IP structure.** License, never assign copyright. Retain all rights to
   structural metadata (blueprints, fingerprints, component libraries) explicitly
   in the MSA. Exclusivity is defined at the structural level (argument-skeleton
   disjointness), never at topic level ("no philosophy passages for anyone else"
   is unfulfillable).
3. **Leakage & provenance.** Test-prep content gets resold/shared on Telegram.
   The fingerprint DB doubles as a watermark: letter plans + structural
   fingerprints identify which client's batch a leaked set came from. MSA needs
   a no-redistribution clause + liquidated damages; enforcement credibility
   matters more than enforcement.
4. **Seed-essay copyright hygiene.** Passages are original prose, but document the
   policy now (seeds are domain hints only; no quoted phrases; embedding distance
   from seed enforced) so a platform client's legal diligence is a form-fill, not
   a crisis.
5. **Model dependency.** A model deprecation silently changes house style.
   Counter: pin model IDs in config; keep a 10-set golden regression batch and
   re-run + review it on ANY model change before production batches. (Budget caps
   already handle cost spikes.) Multi-provider fallback is premature; the
   regression harness is not.
6. **Seasonality cliff.** CAT mock buying window Jul–Sep; usage peaks to Nov;
   trough Dec–Apr. Counter: 12-month contracts with flexed delivery — mock season
   heavy, off-season converts to question-bank building and CLAT/OMET/GRE
   variants (component libraries are exam-agnostic; only topologies/lengths need
   adapting).
7. **Payments & compliance.** Quarterly advance billing (edu pays late). Clients
   deduct TDS 194J @10% — price gross. GST registration required as revenue run-rate
   crosses ₹20L/yr. Register a proprietorship/OPC with current account before
   pitching platforms — they can't vendor-onboard individuals easily.
8. **Existing obligations.** Check the current vendor contract for
   exclusivity/non-compete before pitching adjacent institutes. Employment notice
   ends 2026-07-17 — sign new MSAs after that date if the employment contract has
   outside-work clauses.
9. **Exclusivity trap in reverse.** The biggest new client will demand exclusivity
   broad enough to block growth. Cap it: category + city, 12 months, priced
   +30–40%, auto-expires if retainer lapses.
10. **Quality sag ≠ novelty failure.** The 9 channels stop repetition, not
    mediocrity. Watch judge-score drift in `corpus_health`; once any client is a
    platform, the real KPI is second-exposure accuracy lift (<5 points, per
    ARCHITECTURE_REDESIGN §11.6).

## 30-Day GTM ("Scale to 1.5L" playbook)

Honest revenue physics: institutional cycles are 3–6 weeks, so day-30 exit is
**₹60–90k MRR + a full pipeline**; ₹1.5L lands day 45–75. July timing is ideal —
CAT 2026 mock series lock Aug–Sep, which is the urgency lever in every email.

**Days 1–7 — Arsenal.**
- Upgrade founding client: ₹18–20k grandfathered, in exchange for testimonial,
  reference calls, case-study rights (sets shipped, dispute rate, novelty stats).
- Build the audition kit: repetition-report template, blind-pack SOP + scoring
  sheet, 9-channel explainer PDF, per-RC dossier template.
- MSA + price card (from pricing-packaging.md). Target list: 40 qualified names
  (boutique CAT coachings in metros, online VARC mentors, 3–4 platforms).
- Milestone gate: kit tested end-to-end on the founding client's own content.

**Days 8–14 — Wave 1.**
- 20 outreach sequences (Email 1 → day-3 Email 2 → day-7 LinkedIn → day-14 final).
- Goal: 6–8 free-audit acceptances. Every audit returned within 48h.
- Milestone gate: ≥5 repetition audits delivered.

**Days 15–22 — Auditions.**
- Convert audits → blind auditions (goal 5), auditions → paid pilots (goal 3).
- Wave 2 outreach: next 20 targets.
- Milestone gate: ≥3 paid pilots invoiced (advance payment).

**Days 23–30 — Close & industrialize.**
- Close 2–3 retainers (≥1 Mock Vault). Ops calendar live (Mon/Tue/Thu/Fri cadence).
- Hire 2 piece-rate reviewers; run calibration batch against faculty reviewer.
- Milestone gates at day 30: ≥2 signed retainers · ≥₹60k MRR · ≥6 live pipeline
  · reviewer bench calibrated · founding client upgraded.

**Days 31–75 — Compounding.** Wave 3 outreach with anonymized audit findings as
social proof; convert pipeline; first platform conversation using per-student
novelty guarantee as the headline feature. ₹1.5L MRR target: day 60–75.

## The commoditization objection ("if every institute uses this, what's left?")

Four-layer answer — use in sales conversations in this order:

1. **Scarcity is engineered, not promised.** Exclusivity is a database constraint:
   no two clients ever receive sets sharing an argumentative skeleton (combo-hash
   disjointness, auditable on demand). Clients buy *structural territory*. With 32
   families × 20⁶ component combinations (~10⁹ usable blueprints), disjointness
   across even 50 clients is trivially sustainable.
2. **The moat is memory, not generation.** The value isn't producing a good RC —
   it's knowing everything *your students have already seen* and guaranteeing
   distance from it. That corpus history is inherently per-client; a competitor
   buying an identical engine tomorrow starts with amnesia about your students.
3. **Scarcity as policy.** We serve one institute per category-catchment and say
   so publicly. The objection converts into urgency: the slot your competitor
   could take.
4. **Reframe the premise.** Unpredictable content is becoming hygiene, not edge.
   Institutes differentiate on faculty, results, and brand; the real question is
   what happens to mock credibility when students discover a series is
   pattern-matchable and post it on forums. And practically: "everyone" won't have
   this — the generation code is the easy 20%; the component libraries, thresholds
   calibrated on a real corpus, and the faculty-review loop are the 80% that
   doesn't copy.
