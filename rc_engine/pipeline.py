"""RCPipeline — the Stage 1..5 orchestrator.

Cost topology (why the gates run in this order):
  compose (local sampling: free) -> refine (cheap)
  -> render -> compliance                 [loop, bounded]
  -> passage-level novelty gate           [free — rejects BEFORE the expensive
                                           question call is made]
  -> questions                            [most expensive call]
  -> full novelty gate (adds topology/distractor channels; free)
  -> solver (optional under budget) -> judge (optional under budget)

Every paid call passes through CostLedger.guard(); an RC cannot exceed its
tier budget. When the budget can't cover an optional stage the stage is
skipped and the RC routes to needs_review instead of approved — never a
silent overspend.
"""

from __future__ import annotations

import json
import random

from . import config
from .compliance import ComplianceAuditor
from .composer import (BlueprintComposer, CompositionExhausted,
                       blueprint_categorical_similarity)
from .constraints import CompatibilityRules
from .fingerprints import (embed_text, extract_fingerprint, movement_similarity,
                           topology_similarity)
from .generation_policy import (LEGACY_POLICY, PolicyError, policy_for_blueprint,
                                policy_for_new_plan)
from .history import HistoryStore
from .llm import APIExhausted, BudgetExceeded, CostLedger
from .models import Blueprint, RCResult, RealizedStructure, SeedEssay
from .novelty import NoveltyScorer
from .question_engine import (QuestionEngine, QuestionEngineError,
                              assemble_rc_text, length_bias_report,
                              passage_word_report)
from .quality import blind_solve, judge_rc
from .registry import ComponentRegistry
from .renderer import PassageRenderer, TruncatedRender


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def _topic_doc(topic: str, tension_system: dict, gists: list[str]) -> str:
    """The text embedded by the pre-render topic precheck: topic + tension
    axes + paragraph gists — the refined blueprint's semantic footprint."""
    parts = [topic]
    ts = tension_system or {}
    for k in ("primary", "secondary"):
        ax = (ts.get(k) or {}).get("axis")
        if ax:
            parts.append(str(ax))
    parts.extend(g for g in gists if g)
    return ". ".join(p.strip() for p in parts if p and str(p).strip())


class RCPipeline:
    def __init__(self, history: HistoryStore, llm, embed: bool = True,
                 rng: random.Random | None = None, parallel: bool = False,
                 worker_id: str = ""):
        self.registry = ComponentRegistry()
        self.history = history
        self.llm = llm
        self.embed = embed
        # Set by workers.py. Turns on in-flight reservations at compose and
        # the locked late-sibling recheck at ship; a no-op when sequential.
        self.parallel = parallel
        self.worker_id = worker_id
        rules = CompatibilityRules(self.registry)
        self.composer = BlueprintComposer(self.registry, history, rules, llm, rng)
        if parallel:
            self.composer.inflight_worker = worker_id
        self.renderer = PassageRenderer(self.registry, llm)
        self.auditor = ComplianceAuditor(llm, self.registry)
        self.qengine = QuestionEngine(self.registry, llm)
        self.novelty = NoveltyScorer(history)
        self._topic_vecs: dict[str, list[float] | None] = {}   # precheck cache

    # ------------------------------------------------------------------ main

    def generate_one(self, tier: str, seed: SeedEssay | None = None,
                     ban_families: set[str] | None = None,
                     ban_movements: set[str] | None = None) -> RCResult:
        seed = seed or SeedEssay()
        ledger = CostLedger(budget_usd=config.TIER_BUDGET_USD[tier])
        notes: list[str] = []
        ban_f: set[str] = set(ban_families or ())
        ban_m: set[str] = set(ban_movements or ())
        if self.parallel:
            # Siblings' skeletons are not in the window yet; ban them now so the
            # collision is avoided for free instead of caught after a render.
            held = self.history.inflight_bans(exclude_worker=self.worker_id)
            if held["families"] or held["movements"]:
                print(f"  [inflight] banning {len(held['families'])} family, "
                      f"{len(held['movements'])} movement held by other workers")
            ban_f |= held["families"]
            ban_m |= held["movements"]

        # ---- Stage 1 + free structural prechecks (topology / topic / movement) --
        # Movement collisions are family-level skeletons: recompose with bans
        # BEFORE render so we never pay Opus for a movement string Gate B would
        # hard-reject. Topology re-picks are free; topic collisions re-refine.
        max_mov = max(1, getattr(config, "MOVEMENT_PRECHECK_MAX_RECOMPOSES", 3)
                      if getattr(config, "MOVEMENT_PRECHECK_ENABLED", True) else 1)
        bp = None
        # Stage 0 — what KIND of source is this? Runs before any paid stage,
        # so a genre the corpus is already saturated with costs ~$0.001 to skip
        # rather than being discovered after a $0.02 refine. Classified once
        # per RC, not once per movement retry: the seed does not change inside
        # that loop.
        # One generation policy for this whole attempt (2026-09-13): every
        # component draw, beat read and prompt below uses it, and the
        # blueprint stores it for resume. Elite always resolves to legacy.
        policy = policy_for_new_plan(tier)
        seed_info, topic_shape_id = self.composer.classify_and_pick_shape(
            seed, ledger, tier, policy=policy)
        # Seedless attempts have nothing to rotate TO: the pool check below asks
        # whether the RAG store holds another content kind, but rotation draws
        # from the batch's seed provider, and with --no-seed (or an exhausted
        # provider) there is none. Measured 2026-09-01 on a parallel dry run:
        # all 12 attempts died rejected_seed_genre with no rotation possible,
        # which is a stall, not a gate.
        if not seed.doc_id:
            seed_info["saturated"] = None
        if (seed_info.get("saturated") is not None
                and not self._pool_is_single_kind(tier)):
            print(f"  [seed] genre '{seed_info['genre']}' is already "
                  f"{seed_info['saturated']:.0%} of the recent corpus - "
                  f"rotating rather than adding another")
            return RCResult(None, "", tier, "rejected_seed_genre",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            saturated_genre=seed_info["genre"],
                            notes=[f"seed genre '{seed_info['genre']}' saturated "
                                   f"at {seed_info['saturated']:.0%}"])
        elif seed_info.get("saturated") is not None:
            notes.append(
                f"seed genre '{seed_info['genre']}' is "
                f"{seed_info['saturated']:.0%} of the recent corpus, but this "
                f"tier's seed pool offers no alternative kind - shipped anyway")
            print(f"  [seed] genre '{seed_info['genre']}' saturated at "
                  f"{seed_info['saturated']:.0%}, but the '{tier}' pool is a "
                  f"single kind - gate skipped (widen TIER_SEED_GENRES to fix)")
        print(f"  [seed] {seed_info['genre']} / {seed_info['domain']} "
              f"-> topic shape {topic_shape_id}")

        for mov_attempt in range(1, max_mov + 1):
            try:
                bp = self.composer.compose(
                    tier, seed, ledger,
                    ban_families=ban_f, ban_movements=ban_m,
                    seed_info=seed_info, topic_shape_id=topic_shape_id,
                    policy=policy)
            except CompositionExhausted as e:
                return RCResult(None, "", tier, "failed_composition", notes=[str(e)],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            except BudgetExceeded as e:
                return RCResult(None, "", tier, "budget_abort", notes=[str(e)],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            self.history.record_blueprint(bp, "composed")
            if self.parallel:
                self.history.reserve_inflight(self.worker_id, bp, seed)
            # Gate A⅛ (cat-pyq-f3): the plan must stay with its seed essay.
            try:
                drifted = self._seed_fidelity_gate(bp, seed, ledger, notes, policy, ban_f, ban_m)
            except BudgetExceeded as e:
                return self._abort(bp, ledger, f"budget during seed fidelity check: {e}", notes)
            if drifted:
                return drifted
            print(f"  [BP {bp.blueprint_id}] {bp.family_id}/{bp.persona_id}/{bp.ending_id}/"
                  f"{bp.rhythm_id}/{bp.revelation_id}/{bp.distractor_profile_id}/"
                  f"{bp.topology_id} instability={bp.instability}")

            # Gate A¼: free topology clearance
            bp, topo_notes, topo_ok = self._resolve_topology(bp)
            notes.extend(topo_notes)
            if not topo_ok:
                self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
                return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                                cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                                notes=notes + ["topology precheck failed pre-render"],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))

            # Gate A½: pre-render topic-collision precheck
            collisions = self._topic_precheck(bp)
            if collisions and config.TOPIC_PRECHECK_ENFORCE:
                for i in range(1, config.TOPIC_PRECHECK_MAX_REREFINES + 1):
                    worst_s, worst_l, _t = collisions[0]
                    notes.append(f"topic precheck: collision with {worst_l} @ {worst_s:.2f} "
                                 f"— re-refine {i}/{config.TOPIC_PRECHECK_MAX_REREFINES}")
                    print(f"  [precheck] topic collides with {worst_l} @ {worst_s:.2f} "
                          f"— re-refining ({i}/{config.TOPIC_PRECHECK_MAX_REREFINES})")
                    avoid = [t or l for _s, l, t in collisions[:5]]
                    try:
                        bp = self.composer.refine_only(bp, seed, ledger, avoid_topics=avoid)
                    except BudgetExceeded as e:
                        return self._abort(bp, ledger, f"budget during re-refine: {e}", notes)
                    self.history.record_blueprint(bp, "composed")
                    # A collision re-refine is a new plan: it answers to the
                    # seed check again before its topic is trusted.
                    try:
                        drifted = self._seed_fidelity_gate(bp, seed, ledger, notes, policy, ban_f, ban_m)
                    except BudgetExceeded as e:
                        return self._abort(bp, ledger,
                                           f"budget during seed fidelity check: {e}", notes)
                    if drifted:
                        return drifted
                    collisions = self._topic_precheck(bp)
                    if not collisions:
                        break
                if collisions:
                    self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
                    return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                                    cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                                    notes=notes + [f"topic precheck: still colliding with "
                                                   f"{collisions[0][1]} @ {collisions[0][0]:.2f}"],
                                    ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            elif collisions:
                notes.append(f"topic precheck (log-only): would collide with "
                             f"{collisions[0][1]} @ {collisions[0][0]:.2f}")
                print(f"  [precheck] LOG-ONLY: topic near {collisions[0][1]} "
                      f"@ {collisions[0][0]:.2f} (not blocking)")

            # Gate A¾: planned-movement clearance (same caps as Gate B; $0)
            hits = self._movement_collisions(bp.movement_string())
            if not hits:
                break
            lev, jac, near = hits[0]
            ms = bp.movement_string()
            ban_m.add(ms)
            # Ban the colliding movement STRING, not the family. Rhythm varies a
            # family's function sequence into 3-5 distinct movement strings, so
            # one collision leaves several usable — banning the family discarded
            # them and made each collision cost a whole family. On the
            # 2026-08-10 hard run that exhausted the pool in 3 recomposes; every
            # family it barred still had 3-4 free movement strings. The family is
            # only barred once all of them are gone.
            exhausted = self.composer.family_movement_exhausted(bp.family_id, ban_m, policy)
            if exhausted:
                ban_f.add(bp.family_id)
            msg = (f"movement precheck: near {near} lev={lev:.2f} jac={jac:.2f} "
                   f"— ban movement"
                   + (f" + {bp.family_id} (no free movements left)" if exhausted else "")
                   + f", recompose {mov_attempt}/{max_mov}")
            notes.append(msg)
            print(f"  [movement] {msg}")
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            self.history.record_novelty_audit(
                bp.blueprint_id, None,
                {"movement_levenshtein": round(lev, 3),
                 "movement_bigram_jaccard": round(jac, 3), "nearest": near},
                round(1.0 - max(lev, jac), 3),
                "movement_precheck:collide",
                f"lev={lev:.2f} jac={jac:.2f} vs {near}")
            bp = None
        if bp is None:
            return RCResult(None, "", tier, "rejected_novelty",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + ["movement precheck exhausted recomposes"],
                            ban_families=sorted(ban_f), ban_movements=sorted(ban_m))

        # blueprint similarity vs shipped RCs (needed for composite scoring)
        bp_sims = self._blueprint_sims(bp)

        # ---- Stage 2 + Gate B: render + compliance, then passage novelty ----
        # The render contract is seeded with free corpus-aware divergence steering.
        # A Gate-B rejection on render-movable channels gets ONE breach-directed
        # re-render before falling back to a full recompose (which would also pay
        # to re-clear the topic/topology prechecks this blueprint already passed).
        directives = self._divergence_directives(bp, bp_sims)
        rc_id = self.history.generate_rc_id(tier)
        max_gate_b = 1 + getattr(config, "GATE_B_RENDER_RETRY", 0)
        passage = realized = pre_report = None
        for gate_b_attempt in range(1, max_gate_b + 1):
            passage, realized = None, None
            for attempt in range(1, config.MAX_RENDER_ATTEMPTS + 1):
                try:
                    candidate = self.renderer.render(bp, ledger, directives)
                    # Blind beat read first: compliance scores the passage
                    # against bp.move_plan, and must not be the thing that
                    # produced the reading (see ComplianceAuditor.move_signature).
                    cand_moves = self.auditor.move_signature(candidate, ledger, tier,
                                                             policy=policy)
                    audit = self.auditor.audit(candidate, bp, ledger, cand_moves)
                except TruncatedRender:
                    directives = ["previous attempt was cut off — tighten paragraph lengths"]
                    continue
                except BudgetExceeded as e:
                    return self._abort(bp, ledger, f"budget during render/compliance: {e}", notes)
                except ValueError as e:      # compliance JSON unparseable
                    notes.append(f"compliance parse failure attempt {attempt}: {e}")
                    continue
                if audit.f1 >= config.COMPLIANCE_F1_THRESHOLD:
                    passage, realized = candidate, audit
                    break
                directives = audit.directives[:6]
                notes.append(f"compliance F1={audit.f1} attempt {attempt}; retrying with directives")
                passage, realized = candidate, audit   # keep best-so-far
            if passage is None or realized is None:
                self.history.set_blueprint_status(bp.blueprint_id, "rejected_render")
                return RCResult(None, bp.blueprint_id, tier, "failed_render",
                                cost_usd=ledger.spent_usd, cost_lines=ledger.lines, notes=notes)
            if realized.f1 < config.COMPLIANCE_F1_THRESHOLD:
                notes.append(f"shipping best compliance F1={realized.f1} (below threshold) -> needs_review")

            for w in passage_word_report(passage)["warnings"]:
                notes.append(f"prevalidate: {w}")
            from .question_engine import texture_report
            # Same grants the renderer and auditor were given (section 5.3);
            # None keeps the legacy scan for every other plan.
            grants = None
            if policy.passage_permissions:
                from .passage_permissions import grants_for
                grants = grants_for(bp, self.registry)
            supported = None
            if policy.source_facts:
                from .source_facts import supported_claims
                supported = supported_claims(realized.fact_trace, bp.source_facts,
                                             strict=policy.strict_source_fact_audit)
                notes.extend(bp.source_fact_notes)
                for u in realized.unsupported_claims:
                    notes.append(f"unsupported factual claim ({u['support']}): {u['claim']}")
            for w in texture_report(passage, grants, supported)["warnings"]:
                notes.append(f"texture: {w}")
                print(f"  [texture] {w}")

            # What the argument actually DID, read blind, against what the
            # blueprint asked for. Reported, not gated: the planned->realised
            # agreement rate has never been measured, and gating on a number
            # nobody has seen is how the TS06/TS12 ceiling ended up worth one
            # point of a twelve-point gap. Measure first, then decide.
            sch_primary, sch_secondary = self.auditor.argument_schema(
                passage, ledger, tier, policy=policy)
            realized.argument_schema = sch_primary
            realized.argument_schema_secondary = sch_secondary
            if sch_primary:
                hit = sch_primary == bp.argument_schema_id
                notes.append(f"argument_schema planned={bp.argument_schema_id} "
                             f"realized={sch_primary}"
                             f"{'/' + sch_secondary if sch_secondary else ''}")
                print(f"  [arg-schema] planned {bp.argument_schema_id} -> "
                      f"realized {sch_primary}"
                      f"{' + ' + sch_secondary if sch_secondary else ''}"
                      f"  {'HIT' if hit else 'MISS'}")

            # realized.rhetorical_moves was filled by the blind read inside the
            # render loop above, before compliance scored the beat plan.
            pre_fp = extract_fingerprint(rc_id, bp, passage, realized,
                                         {"questions": [], "letters": [], "trap_usage": {}},
                                         embed=self.embed)
            pre_fp.move_signature = "|".join(realized.rhetorical_moves)
            self._inject_posture(pre_fp, bp, realized)
            pre_report = self.novelty.score(pre_fp, bp_sims, include_question_channels=False)
            self.history.record_novelty_audit(bp.blueprint_id, None, pre_report.channel_scores,
                                              pre_report.composite, f"passage:{pre_report.verdict}",
                                              "; ".join(pre_report.breached))
            if pre_report.verdict == "pass":
                break
            # Gate B failed. If every breach is render-movable and we have a retry
            # left, re-render with breach-specific directives; else reject cheaply.
            retry_dirs = (self._breach_directives(pre_report)
                          if gate_b_attempt < max_gate_b else [])
            if not retry_dirs:
                # Blueprint-derived (movement_*) or no retry left: ban the skeleton
                # so the batch recompose cannot re-sample the same family movement.
                bf, bm = self._movement_bans_from_breaches(bp, pre_report.breached)
                ban_f |= bf
                ban_m |= bm
                self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
                return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                                novelty_composite=pre_report.composite,
                                cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                                notes=notes + [f"passage novelty: {pre_report.breached or pre_report.composite}"],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            notes.append(f"gate B breach {pre_report.breached} — one breach-directed re-render")
            print(f"  [gate-b] {pre_report.breached} - re-rendering with directives")
            directives = retry_dirs

        # Free passage floor (cat-pyq-f3): a render can still wander off a plan
        # that passed its seed check. Rejected before the questions call, the
        # most expensive one; see config.SEED_FIDELITY_PASSAGE_FLOOR.
        if policy.seed_fidelity and self.embed and getattr(seed, "text", ""):
            from .seed_fidelity import passage_cosine
            cos = passage_cosine(seed.text, passage)
            if cos is not None:
                notes.append(f"seed fidelity: passage-seed cosine {cos:.3f} "
                             f"(floor {config.SEED_FIDELITY_PASSAGE_FLOOR})")
                if cos < config.SEED_FIDELITY_PASSAGE_FLOOR:
                    print(f"  [seed-fidelity] passage left its seed: cosine {cos:.3f} < "
                          f"{config.SEED_FIDELITY_PASSAGE_FLOOR} - rejecting before questions")
                    self.history.set_blueprint_status(bp.blueprint_id, "rejected_seed_fidelity")
                    return RCResult(None, bp.blueprint_id, tier, "rejected_seed_fidelity",
                                    cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                                    notes=notes + ["seed fidelity: rendered passage below floor"],
                                    ban_families=sorted(ban_f), ban_movements=sorted(ban_m))

        # persist the novelty-clean passage: a question failure can now resume
        # from here instead of re-paying compose/render/compliance
        self.history.record_rendered_passage(
            bp.blueprint_id, tier, passage, realized.to_json(), realized.f1,
            seed.doc_id, seed.url, seed.title, ledger.spent_usd)

        return self._questions_and_ship(bp, passage, realized, ledger, notes,
                                        seed, bp_sims, rc_id)

    def resume_questions(self, blueprint_id: str,
                         extra_guidance: str | None = None) -> RCResult:
        """Re-run stages 3-5 on a persisted, novelty-clean passage whose
        questions previously failed — without re-paying compose/render.
        Prior spend is loaded into the ledger, so total spend on the RC still
        can never exceed its tier cap. Gate B is re-run first (free) because
        the corpus may have moved since the passage was persisted."""
        row = self.history.load_rendered_passage(blueprint_id)
        if row is None:
            return RCResult(None, blueprint_id, "", "failed_resume",
                            notes=["no rendered passage stored for this blueprint"])
        if row["status"] not in ("questions_failed", "awaiting_questions"):
            return RCResult(None, blueprint_id, row["tier"], "failed_resume",
                            notes=[f"passage status is '{row['status']}', not resumable"])
        bp = Blueprint.from_json(row["blueprint_json"])
        # Resume under the policy the plan was composed with (2026-09-13). An
        # unregistered version is refused, never read as another policy.
        try:
            policy = policy_for_blueprint(bp)
        except PolicyError as e:
            return RCResult(None, blueprint_id, bp.tier, "failed_resume", notes=[str(e)])
        realized = RealizedStructure.from_json(row["realized_json"])
        passage = row["passage"]
        prior = float(row["spent_usd"] or 0.0)
        ledger = CostLedger(budget_usd=config.TIER_BUDGET_USD[bp.tier],
                            spent_usd=prior)
        seed = SeedEssay(doc_id=row["seed_doc_id"], url=row["seed_url"],
                         title=row["seed_title"])
        notes = [f"resumed questions (prior spend ${prior:.4f} counts against the cap)"]
        bp_sims = self._blueprint_sims(bp)

        rc_id = self.history.generate_rc_id(bp.tier)
        if not realized.rhetorical_moves:
            # passage persisted before the channel existed (or extraction failed
            # on the original run) — the read is sub-cent, so just redo it
            try:
                realized.rhetorical_moves = self.auditor.move_signature(
                    passage, ledger, bp.tier, policy=policy)
            except BudgetExceeded:
                realized.rhetorical_moves = []
        pre_fp = extract_fingerprint(rc_id, bp, passage, realized,
                                     {"questions": [], "letters": [], "trap_usage": {}},
                                     embed=self.embed)
        pre_fp.move_signature = "|".join(realized.rhetorical_moves)
        self._inject_posture(pre_fp, bp, realized)
        pre_report = self.novelty.score(pre_fp, bp_sims, include_question_channels=False)
        self.history.record_novelty_audit(bp.blueprint_id, None, pre_report.channel_scores,
                                          pre_report.composite, f"passage:{pre_report.verdict}",
                                          "; ".join(pre_report.breached))
        if pre_report.verdict != "pass":
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            self.history.set_passage_status(bp.blueprint_id, "abandoned",
                                            "gate B failed on resume (corpus moved)")
            return RCResult(None, bp.blueprint_id, bp.tier, "rejected_novelty",
                            novelty_composite=pre_report.composite,
                            notes=notes + [f"passage novelty on resume: "
                                           f"{pre_report.breached or pre_report.composite}"])

        # Free topology re-clearance (2026-09-14). The topology was cleared when
        # the plan was composed, but siblings may have shipped since: BP_260914_
        # 18b725c5 resumed after RC-MEDIUM-260914-0074 shipped on the same QT10,
        # paid $0.11 for questions and died at Gate C on "topology 1.00". The
        # topology is blueprint-derived and fixed before questions, so re-pick it
        # here for $0, exactly as compose does.
        old_topology = bp.topology_id
        bp, topo_notes, topo_ok = self._resolve_topology(bp)
        notes.extend(topo_notes)
        if not topo_ok:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            return RCResult(None, bp.blueprint_id, bp.tier, "rejected_novelty",
                            cost_usd=0.0, notes=notes + [
                                "topology precheck failed on resume - no questions paid; "
                                "passage left resumable"])
        if bp.topology_id != old_topology and bp.question_slots:
            # Stored slots belong to the old topology; the next questions call
            # re-resolves them under the plan's own policy.
            bp.question_slots = []
            self.history.update_blueprint_json(bp)

        return self._questions_and_ship(bp, passage, realized, ledger, notes,
                                        seed, bp_sims, rc_id,
                                        extra_guidance=extra_guidance,
                                        cost_offset=prior)

    def _questions_and_ship(self, bp: Blueprint, passage: str, realized,
                            ledger: CostLedger, notes: list[str], seed: SeedEssay,
                            bp_sims: dict[str, float], rc_id: str,
                            extra_guidance: str | None = None,
                            cost_offset: float = 0.0) -> RCResult:
        """Stages 3-5: questions, full novelty gate, solver, judge, persist.
        Entered fresh from generate_one, or via resume_questions on a passage
        loaded from rendered_passages. cost_offset: prior spend already
        reported by an earlier RCResult — subtracted from this result's
        cost_usd so batch accounting doesn't double-count (rc_sets still
        records the all-in ledger total)."""
        tier = bp.tier

        def _spent() -> float:
            return ledger.spent_usd - cost_offset

        # ---- Stage 3: questions --------------------------------------------
        # A non-legacy plan fixes its effective question slots before the first
        # questions call (2026-09-13), so retries and resumes ask the same
        # questions even if the libraries change in between. Legacy plans keep
        # resolving them from the library, as they always have.
        policy = policy_for_blueprint(bp)
        try:
            if bp.generation_policy and not bp.question_slots:
                bp.question_slots = self.qengine.effective_slots(bp)
                self.history.update_blueprint_json(bp)
            qdata = self.qengine.build(bp, passage, ledger,
                                       extra_guidance=extra_guidance)
        except BudgetExceeded as e:
            # The passage is already paid for and novelty-clean; do NOT destroy it.
            # Leave it resumable ('awaiting_questions') so a later run can finish
            # the questions on it instead of re-paying compose/render. The
            # blueprint is parked in a non-terminal 'deferred_budget' state.
            self.history.set_passage_status(bp.blueprint_id, "awaiting_questions",
                                            f"budget deferred during questions: {e}")
            self.history.set_blueprint_status(bp.blueprint_id, "deferred_budget")
            return RCResult(None, bp.blueprint_id, tier, "budget_abort",
                            cost_usd=_spent(), cost_lines=ledger.lines,
                            notes=notes + [f"budget deferred during questions "
                                           f"(passage kept resumable): {e}"])
        except QuestionEngineError as e:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_questions")
            self.history.set_passage_status(bp.blueprint_id, "questions_failed", str(e))
            return RCResult(None, bp.blueprint_id, tier, "failed_questions",
                            cost_usd=_spent(), cost_lines=ledger.lines,
                            notes=notes + [str(e)])
        # Contract plans only (the key is absent otherwise): reported, not gated.
        for w in qdata.get("contract_warnings", []):
            notes.append(f"question contract: {w}")
        # Free, strict length-bias audit (no paid rewrite). First-pass questions
        # must satisfy the rule in the question prompt; if they don't, the set
        # routes to needs_review below — never auto-approved, never a second
        # Sonnet questions call.
        length_bias = length_bias_report(qdata)
        if length_bias.get("biased"):
            print(f"  [length-bias] correct-longest "
                  f"{length_bias['correct_longest_count']}/{config.QUESTIONS_PER_SET} "
                  f"thesis_longest={length_bias['thesis_correct_longest']} "
                  f"— will not auto-approve")
        if length_bias.get("self_check_ok") is False:
            print(f"  [length-bias] self-check MISREPORTED: model claimed "
                  f"{length_bias['claimed_correct_longest']}, actual "
                  f"{length_bias['correct_longest_count']}")
        for w in length_bias["warnings"]:
            notes.append(f"option audit: {w}")

        # Free passage-length gate (500-550, same standard on every
        # tier). Computed here rather than in generate_one so the resume path
        # is covered too — resume_questions ships a passage this check has
        # never seen. Out of band never auto-approves; no re-render is paid for.
        word_report = passage_word_report(passage)
        for w in word_report["warnings"]:
            notes.append(f"passage length: {w}")

        # ---- Gate C: full novelty ------------------------------------------
        fp = extract_fingerprint(rc_id, bp, passage, realized, qdata, embed=self.embed)
        fp.move_signature = "|".join(realized.rhetorical_moves)
        # record the length-bias stats on the fingerprint so `health` can trend
        # them; _thesis_longest is keyed only when the set has a thesis slot
        fp.stylometry["_correct_longest_count"] = length_bias["correct_longest_count"]
        if length_bias["has_thesis_question"]:
            fp.stylometry["_thesis_longest"] = 1 if length_bias["thesis_correct_longest"] else 0
        self._inject_posture(fp, bp, realized)
        report = self.novelty.score(fp, bp_sims, include_question_channels=True)
        self.history.record_novelty_audit(bp.blueprint_id, rc_id, report.channel_scores,
                                          report.composite, f"full:{report.verdict}",
                                          "; ".join(report.breached))
        if report.verdict != "pass":
            return self._reject_full(bp, rc_id, passage, qdata, realized, fp, report,
                                     ledger, seed, notes, _spent, "full novelty")
        notes.extend(f"corpus flag: {f}" for f in report.corpus_flags)

        # ---- Stage 5: solver + judge (optional under budget) ----------------
        rc_text = assemble_rc_text(bp, passage, qdata)
        solver, judge = None, {"scores": {}, "average": 0.0, "verdict": "skipped"}
        solver_dispute = False
        answerability_flags: list[str] = []
        # Answerability: asked before the solver, so a question that cannot be
        # settled from the passage is named as such rather than surfacing later
        # as an unexplained dispute. Warnings only — nothing is withheld.
        try:
            from .qa_checks import answerability_warnings, check_answerability
            rows = check_answerability(passage, qdata.get("questions", []),
                                       self.llm, ledger, bp.tier, policy=policy)
            flagged = answerability_warnings(rows)
            answerability_flags = list(flagged)
            for w in flagged:
                notes.append(f"answerability: {w}")
                print(f"  [answerability] {w}")
            # Question ambiguity per policy (plan 7.5). Only non-legacy plans
            # carry it, so legacy fingerprints stay as they were.
            if bp.generation_policy and rows:
                fp.stylometry["_answerability_flags"] = len(flagged)
        except BudgetExceeded:
            notes.append("answerability skipped: budget")
        except Exception as e:
            notes.append(f"answerability check errored: {e}")

        try:
            solver = blind_solve(self.llm, ledger, bp, passage, qdata)
            solver_dispute = bool(solver.get("disputes"))
        except BudgetExceeded:
            notes.append("solver skipped: budget")
        # A dispute means two defensible answers, not necessarily a wrong key.
        # An independent cheap read says which the passage supports — and
        # "ambiguous" is the most useful verdict of the three, because it means
        # the question needs rewriting rather than re-keying.
        if solver_dispute:
            try:
                from .qa_checks import tiebreak_disputes
                for t in tiebreak_disputes(passage, qdata.get("questions", []),
                                           solver.get("disputes"), self.llm,
                                           ledger, bp.tier, policy=policy):
                    line = (f"Q{t['q']}: solver said {t['solver']}, key says "
                            f"{t['key']}, independent read supports "
                            f"{t['supported']} ({t['agrees_with']})")
                    notes.append(f"tiebreak: {line}")
                    print(f"  [tiebreak] {line}")
                    if t.get("evidence"):
                        notes.append(f"tiebreak evidence: {t['evidence']}")
            except BudgetExceeded:
                notes.append("tiebreak skipped: budget")
            except Exception as e:
                notes.append(f"tiebreak errored: {e}")

        try:
            if not solver_dispute:
                judge = judge_rc(self.llm, ledger, bp, rc_text, self.registry,
                                 length_facts=length_bias)
        except BudgetExceeded:
            notes.append("judge skipped: budget")
            judge = {"scores": {}, "average": 0.0, "verdict": "skipped_budget"}

        avg = float(judge.get("average") or 0.0)
        if solver is None:
            solver_verified, solver_unverified_reason = False, "blind solve did not run"
        elif solver.get("verdict") != "ok":
            solver_verified, solver_unverified_reason = False, "blind solve reply unusable"
        elif not solver.get("comparable", False):
            solver_verified, solver_unverified_reason = (
                False, f"blind solve answered {solver.get('answered', 0)} of "
                       f"{len(qdata.get('questions', []))} questions")
        else:
            solver_verified, solver_unverified_reason = True, ""
        from .voice_plan import review_reasons
        voice_reasons = review_reasons(bp, realized)
        notes.extend(f"voice review: {reason}" for reason in voice_reasons)
        posture_run = any(f.startswith("posture run") for f in report.corpus_flags)
        if solver_dispute:
            status = "solver_dispute"
        elif length_bias["biased"]:
            # systematic within-set length tell (correct is longest in >2/6, or the
            # thesis answer is longest) — never auto-approve; a human decides.
            status = "needs_review"
            notes.append("length_bias: routed to needs_review "
                         f"(correct-longest {length_bias['correct_longest_count']}/{config.QUESTIONS_PER_SET}, "
                         f"thesis_longest={length_bias['thesis_correct_longest']})")
        elif posture_run:
            # blueprint-consistent closing-posture run (collision with the
            # pre-posture corpus or residual library skew) — a human decides.
            status = "needs_review"
            notes.append("posture run: routed to needs_review")
        elif realized.unsupported_claims:
            # Section 6 (2026-09-13): a claim presented as real that the auditor
            # could not trace to a source-supported fact is a human decision.
            status = "needs_review"
            notes.append(f"source facts: {len(realized.unsupported_claims)} unsupported "
                         f"factual claim(s) - routed to needs_review")
        elif answerability_flags:
            # 2026-09-14 review: qa_checks has always said a flagged question "is
            # routed to review", but nothing here read the flags, so a question
            # judged unanswerable or double-keyed could ship approved.
            status = "needs_review"
            notes.append(f"answerability: {len(answerability_flags)} question(s) flagged "
                         f"- routed to needs_review")
        elif not solver_verified:
            # 2026-09-14 review: a solver reply that failed to parse, answered
            # only some questions, or was skipped for budget raised no dispute,
            # so the set could be approved with its keys never blind-checked.
            status = "needs_review"
            notes.append(f"solver: {solver_unverified_reason} - routed to needs_review")
        elif not word_report["in_band"]:
            # 500-word standard is mandatory: a passage outside the band never
            # auto-approves, whatever the judge thinks of it.
            status = "needs_review"
            notes.append(
                f"passage length: {word_report['words']} words vs required "
                f"{word_report['lo']}-{word_report['hi']} — routed to needs_review")
        elif judge.get("verdict") == "approve" and avg >= config.JUDGE_SCORE_THRESHOLD \
                and realized.f1 >= config.COMPLIANCE_F1_THRESHOLD:
            status = "approved"
        else:
            status = "needs_review"

        # ---- persist ---------------------------------------------------------
        # Parallel only: a sibling may have shipped while this worker was in
        # questions/solver/judge. Re-run the full gate under the ship lock so
        # the window this set is checked against includes every earlier ship,
        # exactly as it would have sequentially. Free; a breach costs the
        # render it already paid for, which is the price of overlap.
        with self.history.ship_lock(enabled=self.parallel):
            if self.parallel:
                late = self.novelty.score(fp, bp_sims, include_question_channels=True)
                if late.verdict != "pass":
                    self.history.record_novelty_audit(
                        bp.blueprint_id, rc_id, late.channel_scores, late.composite,
                        f"full:{late.verdict}", "late sibling: " + "; ".join(late.breached))
                    print(f"  [ship-lock] sibling shipped first: {late.breached}")
                    return self._reject_full(bp, rc_id, passage, qdata, realized, fp,
                                             late, ledger, seed, notes, _spent,
                                             "late sibling novelty")
            # Cross-client exclusivity (2026-09-12). The composer already
            # skipped every shipped combo hash, and the RAG store never hands
            # out a used seed, but both were decided before this set's render:
            # a concurrent batch can have shipped the same skeleton or seed
            # since. Under workers this check is atomic (ship lock). A
            # sequential run stays unlocked — see
            # test_ship_lock_is_only_armed_in_parallel_mode — and the
            # millisecond race left there is backstopped by ux_shipped_combo,
            # which refuses a second ship of the same skeleton outright.
            taken = []
            if self.history.combo_hash_taken(bp.combo_hash, bp.blueprint_id):
                taken.append("combo_hash_taken")
            if self.history.seed_shipped_to_other_client(seed.doc_id):
                taken.append("seed_taken_by_other_client")
            if taken:
                print(f"  [ship-lock] exclusivity: {taken}")
                report.breached = list(report.breached or []) + taken
                return self._reject_full(bp, rc_id, passage, qdata, realized, fp,
                                         report, ledger, seed, notes, _spent,
                                         "exclusivity")
            self.history.insert_rc_set(
                rc_id=rc_id, tier=tier, rc_text=rc_text, status=status, judge=judge,
                solver=solver, avg=avg, blueprint_id=bp.blueprint_id,
                compliance_f1=realized.f1, novelty_composite=report.composite,
                total_cost=ledger.spent_usd, essay_doc_id=seed.doc_id, essay_url=seed.url,
                domain=bp.topic, embedding=fp.embedding, attempts=1)
            self.history.conn.execute(
                "UPDATE rc_sets SET seed_genre = ?, topic_shape = ? WHERE rc_id = ?",
                (bp.seed_genre or "", bp.topic_shape_id or "", rc_id))
            self.history.conn.commit()
            self.history.record_voice_review(rc_id, voice_reasons)
            self.history.record_fingerprint(fp)
            self.history.mark_shipped(bp, rc_id)
            self.history.set_passage_status(bp.blueprint_id, "consumed")

        print(f"  [{rc_id}] status={status} f1={realized.f1} novelty={report.composite} "
              f"avg={avg} words={word_report['words']} "
              f"cost=${ledger.spent_usd:.4f} (budget ${ledger.budget_usd:.2f})")
        return RCResult(rc_id, bp.blueprint_id, tier, status, rc_text=rc_text,
                        average_score=avg, compliance_f1=realized.f1,
                        novelty_composite=report.composite, cost_usd=_spent(),
                        cost_lines=ledger.lines, notes=notes)

    # -------------------------------------------------------------- helpers

    def _reject_full(self, bp: Blueprint, rc_id: str, passage: str, qdata: dict,
                     realized, fp, report, ledger: CostLedger, seed: SeedEssay,
                     notes: list[str], spent_fn, label: str) -> RCResult:
        """Persist a Gate-C (full novelty) rejection. The passage is spent:
        question regen cannot fix topology/distractor channels, and a late
        sibling collision is a property of the corpus, not of the questions."""
        tier = bp.tier
        rc_text = assemble_rc_text(bp, passage, qdata)
        self.history.insert_rc_set(
            rc_id=rc_id, tier=tier, rc_text=rc_text, status="rejected_novelty",
            judge={"scores": {}, "average": 0.0, "verdict": "not_run_novelty"},
            solver=None, avg=0.0, blueprint_id=bp.blueprint_id,
            compliance_f1=realized.f1, novelty_composite=report.composite,
            total_cost=ledger.spent_usd, essay_doc_id=seed.doc_id, essay_url=seed.url,
            domain=bp.topic, embedding=fp.embedding, attempts=1)
        self.history.record_fingerprint(fp)
        self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty", rc_id)
        self.history.set_passage_status(bp.blueprint_id, "consumed")
        return RCResult(rc_id, bp.blueprint_id, tier, "rejected_novelty",
                        rc_text=rc_text,
                        novelty_composite=report.composite,
                        compliance_f1=realized.f1,
                        cost_usd=spent_fn(), cost_lines=ledger.lines,
                        notes=notes + [f"{label}: {report.breached or report.composite}"])

    def _inject_posture(self, f, bp: Blueprint, realized):
        # zero-migration carriage on the stylometry dict (see
        # _correct_longest_count in _questions_and_ship); burrows_delta only
        # reads FUNCTION_WORDS keys, so these never enter any math
        f.stylometry["_closing_posture"] = realized.closing_posture_guess
        f.stylometry["_planned_posture"] = self.registry.posture_of(bp.family_id)
        if realized.final_line_is_aphorism is not None:
            f.stylometry["_aphorism_ending"] = 1 if realized.final_line_is_aphorism else 0
        # Beat-position obedience, so the corpus can be audited on it the same
        # way _aphorism_ending made the register drift visible.
        f.stylometry["_opening_beat_ok"] = 1 if realized.opening_beat_ok else 0
        f.stylometry["_closing_beat_ok"] = 1 if realized.closing_beat_ok else 0
        f.stylometry["_middle_retention"] = realized.middle_retention
        f.stylometry["_gratuitous_moves"] = len(realized.gratuitous_moves)
        f.stylometry["_planned_schema"] = bp.argument_schema_id
        f.stylometry["_argument_schema"] = realized.argument_schema
        f.stylometry["_argument_schema_secondary"] = realized.argument_schema_secondary
        f.stylometry["_voice_plan_version"] = bp.voice_plan_version
        # Only non-legacy plans carry the key, so legacy fingerprints are
        # byte-identical to what they were before policies existed.
        if bp.generation_policy:
            f.stylometry["_generation_policy"] = bp.generation_policy
        # Planned negation, for per-policy reporting (plan 7.5). Stored slots
        # exist only on non-legacy plans, so legacy fingerprints are unchanged.
        if bp.question_slots and all("polarity" in s for s in bp.question_slots):
            neg = [s for s in bp.question_slots if s["polarity"] == "negative"]
            f.stylometry["_negated_slots"] = len(neg)
            f.stylometry["_negated_tasks"] = "|".join(sorted(s["task"] for s in neg))

    def _seed_fidelity_gate(self, bp: Blueprint, seed: SeedEssay, ledger: CostLedger,
                            notes: list[str], policy, ban_f: set | None = None,
                            ban_m: set | None = None) -> RCResult | None:
        """cat-pyq-f3 (2026-09-14): check the refined plan against its seed
        before any render money is spent; one directed re-refine on failure
        (config.SEED_FIDELITY_MAX_REREFINES), then reject so run_slot rotates
        the seed. bp is updated in place. None means go ahead. Plans under any
        other policy, and seedless attempts, pass untouched."""
        if not policy.seed_fidelity or not getattr(seed, "text", ""):
            return None
        from .seed_fidelity import check_plan
        ok, reason = check_plan(self.llm, ledger, bp, seed)
        for i in range(1, config.SEED_FIDELITY_MAX_REREFINES + 1):
            if ok:
                break
            notes.append(f"seed fidelity: plan drifted ({reason}) - re-refine "
                         f"{i}/{config.SEED_FIDELITY_MAX_REREFINES}")
            print(f"  [seed-fidelity] plan drifted: {reason} - re-refining "
                  f"({i}/{config.SEED_FIDELITY_MAX_REREFINES})")
            self.composer.refine_only(bp, seed, ledger, fidelity_failure=reason)  # in place
            self.history.record_blueprint(bp, "composed")
            ok, reason = check_plan(self.llm, ledger, bp, seed)
        if ok:
            notes.append("seed fidelity: plan keeps the seed's subject and kind")
            return None
        print(f"  [seed-fidelity] plan still off its seed: {reason} - rejecting")
        self.history.set_blueprint_status(bp.blueprint_id, "rejected_seed_fidelity")
        # Bans collected earlier in this attempt travel with the reject (2026-09-14
        # review), exactly as the novelty rejects carry them, so the slot's next
        # attempt cannot re-draw a skeleton this one already ruled out.
        return RCResult(None, bp.blueprint_id, bp.tier, "rejected_seed_fidelity",
                        cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                        notes=notes + [f"seed fidelity: plan still drifted ({reason})"],
                        ban_families=sorted(ban_f or ()), ban_movements=sorted(ban_m or ()))

    def _pool_is_single_kind(self, tier: str) -> bool:
        """Can this tier's seed pool offer any alternative content kind?

        A genre-saturation rejection assumes rotation has somewhere to go. For
        hard and elite it does not: TIER_SEED_GENRES restricts them to an
        18-magazine whitelist whose 168 unused docs are all idea_essay, so
        every seed classifies conceptual_essay and every rotation returns
        another one. Measured 2026-08-29, that deadlocked both tiers — three
        rotations each, then rejected_seed_genre, with no seed able to pass.

        Rejecting a seed for being what the pool exclusively contains is not a
        diversity lever, it is a stall, so the gate stands down and says so.
        Recomputed per call: widening the whitelist re-arms it automatically.
        """
        try:
            import RAG
            mix = RAG.unused_pool_kinds(
                genre=config.TIER_SEED_GENRES.get(tier))
        except Exception:
            return False          # cannot tell -> leave the gate armed
        return len([k for k, n in mix.items() if n > 0]) < 2

    def _abort(self, bp: Blueprint, ledger: CostLedger, why: str,
               notes: list[str]) -> RCResult:
        self.history.set_blueprint_status(bp.blueprint_id, "rejected_budget")
        return RCResult(None, bp.blueprint_id, bp.tier, "budget_abort",
                        cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                        notes=notes + [why])

    def _planned_topology_signature(self, topology_id: str) -> list[dict]:
        topo = self.registry.get("topology", topology_id)
        return [
            {"type": s["type"], "target": s.get("target", ""),
             "difficulty": float(s.get("difficulty", 0.0))}
            for s in topo.get("slots", [])
        ]

    def _topology_collisions(self, topology_id: str) -> list[tuple[float, str]]:
        """Blueprint-derived topology signature vs the RECENT corpus, worst
        first. Free (local): the signature comes from the registry, not the
        render.

        Scoped to EXCLUSION_WINDOWS["topology"], not the full fingerprint
        window, because that is the composer's own policy: _eligible() drops a
        topology only until that many sets have passed, then deliberately
        recycles it. The library has 20 topologies and the corpus is already
        larger, so recycling is mandatory — scoring it against all 100
        fingerprints made every topology collide at 1.00 and left zero clear
        options on every tier. Reuse inside the window is a composer bug and
        still gets caught; reuse outside it is the design."""
        cap = config.NOVELTY_CAPS["topology_similarity"]
        mine = self._planned_topology_signature(topology_id)
        if not mine:
            return []
        hits = []
        for other in self.history.fingerprint_window(
                config.EXCLUSION_WINDOWS["topology"]):
            if not other.topology_signature:
                continue
            sim = topology_similarity(mine, other.topology_signature)
            if sim > cap:
                hits.append((sim, other.rc_id))
        hits.sort(reverse=True)
        return hits

    def _tier_topologies(self, tier: str, policy=None) -> list[str]:
        """The plans this tier may draw. Must match the composer's bar exactly —
        this re-pick runs after the composer has chosen, so a looser rule here
        would quietly hand medium a plan the composer refused it.

        policy: the blueprint's generation policy (2026-09-13), applied first
        for the same reason; None = legacy."""
        ids = (policy or LEGACY_POLICY).eligible_ids(self.registry, "topology", tier)
        return [i for i in ids if self.composer._topology_allowed(i, tier)]

    def _pick_clear_topology(self, bp: Blueprint) -> str | None:
        ids = [i for i in self._tier_topologies(bp.tier, policy_for_blueprint(bp))
               if i != bp.topology_id]
        rng = getattr(self.composer, "rng", None) or random.Random()
        rng.shuffle(ids)
        for tid in ids:
            if not self._topology_collisions(tid):
                return tid
        return None

    def _resolve_topology(self, bp: Blueprint) -> tuple[Blueprint, list[str], bool]:
        """Free pre-render topology clearance: re-pick a colliding topology from
        the registry ($0) before any paid render. A Gate-C topology breach is
        100% blueprint-derived, so catching it here saves the whole question
        call. Returns (bp, notes, ok).

        If every allowed topology collides, fall back to the *least* colliding
        option — but only if it is actually under Gate C's cap. Proceeding above
        the cap is not "unblocking generation", it is paying for a rejection
        that was already certain: on the 2026-07-26 batch this path shipped a
        blueprint at topology 0.78 against a 0.75 cap and Gate C duly rejected
        it after the render AND the questions call had been paid for ($0.2553).
        A pre-render rejection costs the refine call alone and the batch loop
        recomposes for free."""
        notes: list[str] = []
        if not getattr(config, "TOPOLOGY_PRECHECK_ENABLED", True):
            return bp, notes, True
        hits = self._topology_collisions(bp.topology_id)
        if not hits:
            return bp, notes, True
        sim0, near0 = hits[0]
        for i in range(1, config.TOPOLOGY_PRECHECK_MAX_REPICKS + 1):
            alt = self._pick_clear_topology(bp)
            if alt is None:
                break
            notes.append(f"topology precheck: {bp.topology_id} near {near0} "
                         f"@ {sim0:.2f} — re-pick {alt}")
            print(f"  [topo] {bp.topology_id} near {near0} @ {sim0:.2f} -> {alt}")
            bp.topology_id = alt
            self.history.record_blueprint(bp, "composed")
            hits = self._topology_collisions(bp.topology_id)
            if not hits:
                return bp, notes, True
            sim0, near0 = hits[0]
        # No fully clear topology: pick the least-colliding allowed alternative.
        best_tid, best_sim, best_near = bp.topology_id, sim0, near0
        for tid in self._tier_topologies(bp.tier, policy_for_blueprint(bp)):
            th = self._topology_collisions(tid)
            if not th:
                best_tid, best_sim, best_near = tid, 0.0, ""
                break
            s, n = th[0]
            if s < best_sim:
                best_tid, best_sim, best_near = tid, s, n
        if best_tid != bp.topology_id:
            notes.append(
                f"topology precheck: no clear option — least-colliding "
                f"{bp.topology_id}->{best_tid} @ {best_sim:.2f} vs {best_near}")
            print(f"  [topo] no clear option - using least-colliding "
                  f"{bp.topology_id}->{best_tid} @ {best_sim:.2f}")
            bp.topology_id = best_tid
            self.history.record_blueprint(bp, "composed")

        # Gate C scores this exact signature against the same cap. If the best
        # we can do is still above it, the rejection is already decided — bail
        # now (cost: the refine call) instead of after render + questions.
        cap = config.NOVELTY_CAPS["topology_similarity"]
        if best_sim > cap and not getattr(config, "TOPOLOGY_GATE_ENFORCE", True):
            # 2026-09-14: Gate C no longer rejects on topology, so a shared
            # layout is no longer a certain rejection worth bailing for.
            notes.append(f"topology precheck: best available {best_tid} @ {best_sim:.2f} "
                         f"vs {best_near} - proceeding (topology is reported, not gated)")
            return bp, notes, True
        if best_sim > cap:
            notes.append(
                f"topology precheck: best available {best_tid} @ {best_sim:.2f} "
                f"is above the Gate C cap {cap} vs {best_near} — rejecting "
                f"pre-render rather than paying for a certain rejection")
            print(f"  [topo] best available @ {best_sim:.2f} > Gate C cap {cap} "
                  f"- rejecting pre-render (recompose is free)")
            return bp, notes, False

        notes.append(
            f"topology precheck: proceeding with {bp.topology_id} "
            f"@ {best_sim:.2f} vs {best_near}")
        return bp, notes, True

    def _movement_collisions(self, movement_string: str
                             ) -> list[tuple[float, float, str]]:
        """Planned (or realized) movement vs fingerprint window using the same
        NOVELTY_CAPS as Gate B. Returns [(lev_sim, jac, rc_id), ...] worst first.
        Empty = clear. Free / local."""
        if not movement_string or not getattr(config, "MOVEMENT_PRECHECK_ENABLED", True):
            return []
        from .fingerprints import UNKNOWN_MOVEMENT
        if movement_string in UNKNOWN_MOVEMENT:
            return []
        caps = config.NOVELTY_CAPS
        hits: list[tuple[float, float, str]] = []
        # Recency-scoped, not whole-corpus — see config.MOVEMENT_RECENCY_WINDOW.
        window = getattr(config, "MOVEMENT_RECENCY_WINDOW",
                         config.FINGERPRINT_WINDOW)
        for fp in self.history.fingerprint_window(window):
            if not fp.movement_string or fp.movement_string in UNKNOWN_MOVEMENT:
                continue
            lev, jac = movement_similarity(movement_string, fp.movement_string)
            if (lev > caps["movement_levenshtein"]
                    or jac > caps["movement_bigram_jaccard"]):
                hits.append((lev, jac, fp.rc_id))
        hits.sort(key=lambda t: max(t[0], t[1]), reverse=True)
        return hits

    @staticmethod
    def _movement_bans_from_breaches(bp: Blueprint,
                                     breached: list[str]) -> tuple[set[str], set[str]]:
        """If any Gate-B breach is movement-derived, ban this family + planned
        movement string for subsequent recomposes."""
        ban_f: set[str] = set()
        ban_m: set[str] = set()
        for b in breached or []:
            head = b.split()[0].rstrip(":")
            if head.startswith("movement"):
                ban_f.add(bp.family_id)
                ms = bp.movement_string()
                if ms:
                    ban_m.add(ms)
                break
        return ban_f, ban_m

    def _topic_precheck(self, bp: Blueprint) -> list[tuple[float, str, str]]:
        """Compare the refined blueprint's topic document against (a) topic
        docs of prior blueprints and (b) stored passage embeddings, using the
        free local embedder. Returns collisions [(cosine, label, topic)],
        worst first — empty when clean, disabled, or embedder unavailable.
        Every check is recorded in novelty_audits as topic_precheck:*."""
        if not (config.TOPIC_PRECHECK_ENABLED and self.embed) or not bp.topic:
            return []
        vec = embed_text(_topic_doc(bp.topic, bp.tension_system,
                                    [p.gist for p in bp.movement]))
        if vec is None:
            return []

        collisions: list[tuple[float, str, str]] = []
        # SHIPPED blueprints only. A topic that never shipped cannot be a
        # duplicate for the customer, and including rejects made every failed
        # attempt a permanent obstacle to the next one — see the note above
        # TOPIC_PRECHECK_ENABLED in config.py. Rejected topics still steer the
        # refine prompt for free through history.recent_topics().
        rows = [(bpid, bj) for bpid, _rc, _fam, bj
                in self.history.shipped_blueprint_rows(config.FINGERPRINT_WINDOW)]
        for bpid, bj in rows:
            if bpid == bp.blueprint_id:
                continue
            if bpid not in self._topic_vecs:
                try:
                    d = json.loads(bj)
                except (ValueError, TypeError):
                    self._topic_vecs[bpid] = None
                    continue
                doc = _topic_doc(d.get("topic", ""), d.get("tension_system", {}),
                                 [m.get("gist", "") for m in d.get("movement", [])])
                self._topic_vecs[bpid] = embed_text(doc) if doc.strip() else None
            other = self._topic_vecs[bpid]
            if other is None:
                continue
            c = _cosine(vec, other)
            if c >= config.TOPIC_PRECHECK_COSINE:
                try:
                    topic = json.loads(bj).get("topic", "")
                except (ValueError, TypeError):
                    topic = ""
                collisions.append((c, f"blueprint {bpid}", topic))

        # manual/legacy sets carry no blueprint topic — compare against their
        # passage embeddings at the (lower) cross-granularity threshold
        for fp in self.history.fingerprint_window(config.FINGERPRINT_WINDOW):
            if fp.embedding:
                c = _cosine(vec, fp.embedding)
                if c >= config.TOPIC_PRECHECK_PASSAGE_COSINE:
                    collisions.append((c, f"passage {fp.rc_id}", ""))

        collisions.sort(reverse=True)
        worst = collisions[0][0] if collisions else 0.0
        nearest = collisions[0][1] if collisions else ""
        self.history.record_novelty_audit(
            bp.blueprint_id, None,
            {"topic_cosine": round(worst, 4), "nearest": nearest},
            round(1.0 - worst, 4),
            f"topic_precheck:{'collide' if collisions else 'pass'}",
            "; ".join(f"{l} @ {s:.2f}" for s, l, _ in collisions[:3]))
        return collisions

    def _blueprint_sims(self, bp: Blueprint) -> dict[str, float]:
        """rc_id -> categorical blueprint similarity for shipped RCs."""
        rows = self.history.shipped_blueprint_components(config.FINGERPRINT_WINDOW)
        mine = bp.component_ids
        out = {}
        keys = ["family", "persona", "ending", "rhythm", "revelation",
                "distractor_profile", "topology"]
        for r in rows:
            other = dict(zip(keys, r[1:]))
            out[r[0]] = blueprint_categorical_similarity(mine, other)
        return out

    def _divergence_directives(self, bp: Blueprint,
                               bp_sims: dict[str, float]) -> list[str]:
        """Free prose-level steering seeded into the render contract. Pushes the
        passage's sentence rhythm and opening altitude away from the nearest
        corpus neighbours so the soft stylometry/rhythm channels diversify at the
        source. Only touches prose texture — never the blueprint-fixed thesis
        schedule or closing posture (that would fight compliance)."""
        if not getattr(config, "DIVERGENCE_DIRECTIVES_ENABLED", True):
            return []
        window = {fp.rc_id: fp
                  for fp in self.history.fingerprint_window(config.FINGERPRINT_WINDOW)}
        if not window:
            return []
        n = getattr(config, "DIVERGENCE_MAX_NEIGHBORS", 2)
        ranked = [rc for rc, _ in sorted(bp_sims.items(), key=lambda kv: kv[1],
                                         reverse=True) if rc in window]
        neighbors = [window[rc] for rc in ranked[:n]]
        if not neighbors:   # no shipped-blueprint overlap yet — use recent prose
            neighbors = list(window.values())[:n]
        means = [fp.stylometry.get("_mean_sent_len") for fp in neighbors
                 if fp.stylometry.get("_mean_sent_len")]
        dirs: list[str] = []
        if means:
            avg = sum(means) / len(means)
            dirs.append(
                f"The nearest recent passages in this corpus average about "
                f"{avg:.0f}-word sentences; deliberately differ from that profile — "
                f"mix conspicuously shorter and longer sentences so the rhythm does "
                f"not echo them.")
        dirs.append(
            "Choose a different opening altitude from the corpus norm: if the natural "
            "move is to begin on an abstract claim, open instead on a concrete "
            "particular (a case, an image), or vice versa.")
        return dirs[:3]

    # Gate-B channels a re-render can actually move (prose-level, not blueprint).
    _RENDER_MOVABLE_BREACHES = ("rhythm_cosine", "curve_similarity",
                                "embedding_cosine", "persona_leak",
                                "move_signature")

    def _breach_directives(self, report) -> list[str]:
        """Map render-movable Gate-B breaches to concrete re-render directives.
        Returns [] if ANY breach is blueprint-derived (movement_*), signalling
        that only a recompose — not a re-render — can help."""
        dirs: list[str] = []
        for b in report.breached:
            head = b.split()[0].rstrip(":")
            if head.startswith("movement"):
                return []
            if head == "rhythm_cosine":
                dirs.append("Vary the sentence-length rhythm sharply: break any regular "
                            "alternation and include at least one very short sentence early.")
            elif head == "curve_similarity":
                dirs.append("Change the LEVELS the argument's commitment passes through, "
                            "not just its cadence: start from a markedly different degree "
                            "of endorsement or resistance, and land somewhere else — "
                            "without changing which paragraph first reveals the thesis.")
            elif head == "embedding_cosine":
                dirs.append("Reframe the angle and examples away from the nearest passage's "
                            "territory: choose different illustrative cases and vocabulary.")
            elif head.startswith("move_signature"):
                dirs.append("Change the ARGUMENT'S CHOREOGRAPHY, not its wording: the "
                            "sequence of rhetorical operations matches an existing "
                            "passage too closely. In particular do not relocate the "
                            "dispute to a deeper level, and do not set up an obvious "
                            "reading in order to demolish it — build the difficulty "
                            "some other way.")
            elif head.startswith("persona_leak"):
                dirs.append("Push the prose texture away from the house voice: alter hedging "
                            "frequency and clause structure while staying in the persona.")
        seen, out = set(), []
        for d in dirs:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out[:4]


def _seed_collision(pipeline: RCPipeline, seed: SeedEssay | None) -> str | None:
    """Seed pre-screen (local embeddings, $0): returns a description of the
    nearest corpus passage when the seed's territory is already saturated,
    else None. Degrades to None when embeddings are off/unavailable."""
    if seed is None or not seed.text or not pipeline.embed \
            or not config.TOPIC_PRECHECK_ENABLED:
        return None
    vec = embed_text(" ".join(seed.text.split()[:200]))
    if vec is None:
        return None
    worst, worst_id = 0.0, None
    for fp in pipeline.history.fingerprint_window(config.FINGERPRINT_WINDOW):
        if fp.embedding:
            c = _cosine(vec, fp.embedding)
            if c > worst:
                worst, worst_id = c, fp.rc_id
    if worst >= config.SEED_PRESCREEN_COSINE:
        return f"{worst_id} @ {worst:.2f} (passage)"

    # Second channel: the SEEDS of recent sets, not their passages. Two seeds
    # can share a territory that the finished passages no longer visibly share,
    # because refine walked each one somewhere specific — see
    # config.SEED_ANCESTRY_COSINE for the case that motivated this.
    hit = _seed_ancestry_collision(pipeline, seed, vec)
    if hit:
        return hit
    return None


def _seed_ancestry_collision(pipeline: RCPipeline, seed: SeedEssay,
                             vec: list) -> str | None:
    """Compare this seed against the SEEDS of recently shipped sets. $0 — the
    seed embeddings are already in the vector store."""
    try:
        rows = pipeline.history.recent_seed_ids(config.SEED_ANCESTRY_WINDOW)
    except Exception:
        return None
    recent_ids = [(rc, doc) for rc, doc in rows if doc and doc != seed.doc_id]
    if not recent_ids:
        return None
    # Chroma returns embeddings as a NUMPY ARRAY, not a list. `x or []` and
    # `if e is None` are both wrong on one: the first raises
    # "truth value of an array with more than one element is ambiguous" and the
    # second silently misreads. That crashed the first real batch this ran in
    # (2026-08-29) — the whole extraction has to sit inside the try, and every
    # emptiness test has to be an explicit length check.
    try:
        import RAG
        store = RAG.get_db()
        # 2026-09-20: repaired/reused historical sets may share a seed. Chroma
        # rejects duplicate IDs in one get; fetch each once, compare every RC.
        got = store.get(ids=list(dict.fromkeys(d for _, d in recent_ids)),
                        include=["embeddings"]) or {}
        embs = got.get("embeddings")
        ids = got.get("ids")
        embs = [] if embs is None else list(embs)
        ids = [] if ids is None else list(ids)
        by_doc = {i: e for i, e in zip(ids, embs) if e is not None and len(e)}
        worst, worst_rc = 0.0, None
        for rc, doc in recent_ids:
            e = by_doc.get(doc)
            if e is None or not len(e):
                continue
            c = _cosine(vec, list(e))
            if c > worst:
                worst, worst_rc = c, rc
    except Exception as exc:     # store unavailable — degrade, never block a batch
        print(f"  [seed-ancestry] skipped ({type(exc).__name__}: {exc})")
        return None
    if worst >= config.SEED_ANCESTRY_COSINE:
        return f"{worst_rc} @ {worst:.2f} (shared seed territory)"
    return None


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------

def run_slot(pipeline: RCPipeline, tier: str, slot_no: int, count: int,
             seed_provider, forced_bans: set[str], *, spent, max_usd: float,
             keep) -> bool:
    """One batch slot: seed pre-screen, up to three generate_one attempts with
    accumulating family/movement bans and seed rotation on novelty rejects,
    then a questions-only retry on a paid, novelty-clean passage. Shared by
    the sequential run_batch and by each parallel worker (workers.py).

    keep(res, tier, slot_no, attempt_no) receives every RCResult in order.
    Returns True when the spending cap stopped the slot early. APIExhausted
    propagates to the caller, which decides how to stop the batch."""
    seed, on_success = (None, None)
    tried_doc_ids: set[str] = set()
    if seed_provider:
        seed, on_success = seed_provider(tier)
        if seed is None and getattr(seed_provider, "restricted", False):
            # 2026-09-14 review: a subject- or list-restricted run that has run
            # out of essays skips the slot. Running seedless would produce the
            # off-subject passage the restriction exists to prevent.
            print(f"[seeds] no matching seed left for {tier} - slot {slot_no} skipped")
            return False
        if seed is None:
            print(f"[seeds] exhausted - continuing seedless for {tier}")
        elif seed.doc_id:
            tried_doc_ids.add(seed.doc_id)
        # pre-screen: rotate seeds whose territory the corpus has
        # already covered, BEFORE paying for a render ($0 check)
        for _ in range(config.SEED_PRESCREEN_MAX_ROTATIONS):
            hit = _seed_collision(pipeline, seed)
            if hit is None:
                break
            print(f"[seeds] pre-screen: {seed.title!r} too close to "
                  f"{hit} — rotating")
            new_seed, new_cb = seed_provider(tier, exclude_ids=tried_doc_ids)
            if new_seed is None:
                break     # keep the current seed rather than starve
            seed, on_success = new_seed, new_cb
            if new_seed.doc_id:
                tried_doc_ids.add(new_seed.doc_id)
    print(f"\n=== [{tier}] {slot_no}/{count} ===")
    # retry loop for novelty rejections: resample a fresh blueprint.
    # Movement collisions accumulate family/movement bans so a
    # recompose cannot re-hit the same skeleton (seed rotation alone
    # does not change paragraph-function order).
    res = None
    ban_families: set[str] = set(forced_bans)
    ban_movements: set[str] = set()
    attempt = 0
    for attempt in range(3):
        try:
            res = pipeline.generate_one(
                tier, seed,
                ban_families=ban_families,
                ban_movements=ban_movements)
        except APIExhausted:
            raise                         # stop the batch cleanly
        except Exception as e:            # never let one RC kill the batch
            import traceback
            traceback.print_exc()
            res = RCResult(None, "", tier, "failed_error", notes=[repr(e)])
        keep(res, tier, slot_no, attempt + 1)
        ban_families.update(res.ban_families or [])
        ban_movements.update(res.ban_movements or [])
        # rejected_seed_fidelity (2026-09-14): the plan or passage left its seed;
        # a fresh seed is the retry, as for a saturated genre.
        if res.status not in ("rejected_novelty", "failed_composition",
                              "rejected_seed_genre", "rejected_seed_fidelity"):
            break
        if spent() >= max_usd:
            print(f"[batch] spending cap reached mid-retry - stopping cleanly.")
            return True
        print(f"  [retry] {res.status} - recomposing ({attempt + 1}/3)"
              + (f" bans={sorted(ban_families)}" if ban_families else ""))
        # rotate the seed too: a fresh blueprint keeps the same
        # topic anchor, so an embedding-channel collision would
        # just repeat. The untried previous seed stays unused
        # (only success marks it consumed).
        if seed_provider and seed is not None:
            # Steer the rotation away from the kinds that produce a
            # saturated genre. A uniform redraw could not clear it:
            # see config.GENRE_SOURCE_KINDS.
            avoid = config.GENRE_SOURCE_KINDS.get(
                res.saturated_genre or "", None)
            if avoid:
                print(f"  [retry] avoiding source kinds {avoid} "
                      f"(genre '{res.saturated_genre}' saturated)")
            try:
                new_seed, new_cb = seed_provider(
                    tier, exclude_ids=tried_doc_ids, avoid_kinds=avoid)
            except TypeError:     # provider predates avoid_kinds
                new_seed, new_cb = seed_provider(
                    tier, exclude_ids=tried_doc_ids)
            if new_seed is not None:
                seed, on_success = new_seed, new_cb
                if new_seed.doc_id:
                    tried_doc_ids.add(new_seed.doc_id)
                print(f"  [retry] seed rotated -> {new_seed.title!r}")
    # questions failed but the passage is paid for and novelty-clean:
    # one questions-only retry is strictly cheaper than recomposing
    if res and res.status == "failed_questions" and res.blueprint_id \
            and spent() < max_usd:
        bp_id = res.blueprint_id
        print("  [retry] questions failed - regenerating questions on the same passage")
        reason = "; ".join(res.notes)[:600]
        guidance = (
            f"A previous attempt on this exact passage failed validation: "
            f"{reason}. Correct that specific defect; keep everything else "
            f"to spec.") if reason else None
        try:
            res = pipeline.resume_questions(bp_id, extra_guidance=guidance)
        except APIExhausted:
            raise
        except Exception as e:
            import traceback
            traceback.print_exc()
            res = RCResult(None, bp_id, tier, "failed_error", notes=[repr(e)])
        keep(res, tier, slot_no, attempt + 1)
    if res and res.rc_id and on_success:
        on_success(res.rc_id)
    return False


def run_batch(pipeline: RCPipeline, tier_counts: dict[str, int],
              seed_provider=None, max_usd: float | None = None,
              only_posture: str | None = None) -> list[RCResult]:
    """seed_provider: callable -> (SeedEssay, on_success(rc_id) callback) or
    (None, None) when no seeds remain. None = seedless generation.

    max_usd: batch spending cap. No new generation attempt STARTS once
    cumulative spend reaches it, so total batch spend can overshoot it by at
    most one per-RC budget. Default: 1.25 x sum of requested tier budgets.

    only_posture: restrict every attempt to families with this closing
    posture, by seeding the existing family-ban set with all the others. For
    verifying a lever on the tier where it bites -- a change to
    refusal_suspended behaviour is otherwise invisible until chance happens
    to draw one. Uses the normal ban path, so composition, prechecks and
    fallbacks behave exactly as usual.

    For N > 1 processes see workers.run_parallel, which runs the same
    run_slot per slot."""
    if max_usd is None:
        max_usd = 1.25 * sum(config.TIER_BUDGET_USD[t] * n for t, n in tier_counts.items())
    print(f"[batch] spending cap: ${max_usd:.2f} "
          f"(per-RC caps: {config.TIER_BUDGET_USD})")
    results: list[RCResult] = []
    forced_bans: set[str] = set()
    from datetime import datetime, timezone
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if only_posture:
        reg = pipeline.composer.registry
        forced_bans = {f for f in reg.ids("family")
                       if reg.posture_of(f) != only_posture}
        keep_n = len(reg.ids("family")) - len(forced_bans)
        print(f"[batch] restricted to closing posture '{only_posture}' "
              f"({keep_n} families)")

    def spent() -> float:
        return sum(r.cost_usd for r in results)

    def _keep(res: RCResult, tier: str, slot: int, attempt_no: int) -> None:
        """Every outcome goes to the attempts table, shipped or not, so the
        cost of a rejected render outlives this process. Never fatal."""
        results.append(res)
        try:
            pipeline.history.record_attempt(batch_id, tier, slot, attempt_no, res)
        except Exception as e:                       # noqa: BLE001
            print(f"  [attempts] not recorded (non-fatal): {e}")

    try:
        for tier, count in tier_counts.items():
            for i in range(count):
                if spent() >= max_usd:
                    print(f"[batch] spending cap ${max_usd:.2f} reached "
                          f"(spent ${spent():.4f}) — stopping cleanly.")
                    summarize_batch(results, batch_id, getattr(pipeline, "llm", None))
                    return results
                stopped = run_slot(pipeline, tier, i + 1, count, seed_provider,
                                   forced_bans, spent=spent, max_usd=max_usd,
                                   keep=_keep)
                if stopped:
                    summarize_batch(results, batch_id, getattr(pipeline, "llm", None))
                    return results
    except APIExhausted as e:
        print(f"\n[STOP] API exhausted ({e}) - batch stopped cleanly; "
              f"completed work is committed. Re-run later to continue.")
    summarize_batch(results, batch_id, getattr(pipeline, "llm", None))
    return results


def summarize_batch(results: list[RCResult], batch_id: str, llm=None) -> None:
    """The batch summary and cost telemetry, shared by the sequential and
    parallel runners."""
    total = sum(r.cost_usd for r in results)
    shipped_statuses = {"approved", "needs_review", "solver_dispute"}
    shipped = [r for r in results if r.rc_id and r.status in shipped_statuses]
    print(f"\n--- Batch {batch_id} summary: {len(shipped)} shipped, "
          f"{len(results)} attempts, total ${total:.4f} ---")
    for r in results:
        reason = ""
        if r.status == "rejected_novelty":
            reason = next((n for n in r.notes if "novelty:" in n), "")
            if len(reason) > 120:
                reason = reason[:117] + "..."
        print(f"  {str(r.rc_id):16s} | {r.tier:6s} | {r.status:16s} | "
              f"f1={r.compliance_f1} novelty={r.novelty_composite} "
              f"score={r.average_score} ${r.cost_usd:.4f}"
              f"{' | ' + reason if reason else ''}")

    # ---- cost telemetry: where the money went, and yield -------------------
    # A "precheck save" is a rejection that spent almost nothing (caught at a free
    # gate before any paid render); real waste is a rejection that already paid.
    PRECHECK_SAVE_CENTS = 0.02
    shipped_spend = sum(r.cost_usd for r in shipped)
    wasted = [r for r in results if r not in shipped]
    wasted_spend = sum(r.cost_usd for r in wasted)
    precheck_saves = [r for r in wasted if r.cost_usd < PRECHECK_SAVE_CENTS]
    paid_wastes = [r for r in wasted if r.cost_usd >= PRECHECK_SAVE_CENTS]
    paid_waste_spend = sum(r.cost_usd for r in paid_wastes)
    per_shipped = (shipped_spend / len(shipped)) if shipped else 0.0
    all_in_per_shipped = (total / len(shipped)) if shipped else 0.0
    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    resumable = [r for r in results if r.status == "budget_abort"]
    print(f"--- Cost telemetry ---")
    print(f"  shipped spend        ${shipped_spend:.4f} over {len(shipped)} sets")
    print(f"  wasted spend         ${wasted_spend:.4f} "
          f"({(wasted_spend / total * 100 if total else 0):.0f}% of total) "
          f"— paid ${paid_waste_spend:.4f} in {len(paid_wastes)} attempts, "
          f"{len(precheck_saves)} free precheck saves")
    print(f"  $/shipped set        ${per_shipped:.4f} (shipped-only) | "
          f"${all_in_per_shipped:.4f} (all-in incl. waste)")
    print(f"  status counts        " + ", ".join(f"{k}={v}" for k, v in
                                                  sorted(status_counts.items())))
    if resumable:
        print(f"  resumable passages   {len(resumable)} paid but deferred "
              f"(budget): {', '.join(r.blueprint_id for r in resumable if r.blueprint_id)}")
    # Subscription usage, when the Claude Code lane served any stage. The cost
    # telemetry above is API dollars only and reads $0.00 on that lane, which
    # is true but not the whole story: the quota is finite too (2026-09-18).
    report = getattr(llm, "usage_report", None)
    if callable(report):
        shipped_n = len(shipped)
        for line in report():
            print(line)
        agg = getattr(llm, "usage", {}) or {}
        if shipped_n and agg.get("calls"):
            tok = (agg["input"] + agg["cache_write"] + agg["cache_read"]
                   + agg["output"])
            print(f"  per shipped set      {agg['calls'] / shipped_n:.1f} calls | "
                  f"{tok / shipped_n:,.0f} tokens | "
                  f"${getattr(llm, 'notional_usd', 0.0) / shipped_n:.4f} notional")
