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
from .history import HistoryStore
from .llm import APIExhausted, BudgetExceeded, CostLedger
from .models import Blueprint, RCResult, RealizedStructure, SeedEssay
from .novelty import NoveltyScorer
from .question_engine import (QuestionEngine, QuestionEngineError,
                              assemble_rc_text, length_bias_report,
                              passage_word_check)
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
                 rng: random.Random | None = None):
        self.registry = ComponentRegistry()
        self.history = history
        self.llm = llm
        self.embed = embed
        rules = CompatibilityRules(self.registry)
        self.composer = BlueprintComposer(self.registry, history, rules, llm, rng)
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

        # ---- Stage 1 + free structural prechecks (topology / topic / movement) --
        # Movement collisions are family-level skeletons: recompose with bans
        # BEFORE render so we never pay Opus for a movement string Gate B would
        # hard-reject. Topology re-picks are free; topic collisions re-refine.
        max_mov = max(1, getattr(config, "MOVEMENT_PRECHECK_MAX_RECOMPOSES", 3)
                      if getattr(config, "MOVEMENT_PRECHECK_ENABLED", True) else 1)
        bp = None
        for mov_attempt in range(1, max_mov + 1):
            try:
                bp = self.composer.compose(
                    tier, seed, ledger,
                    ban_families=ban_f, ban_movements=ban_m)
            except CompositionExhausted as e:
                return RCResult(None, "", tier, "failed_composition", notes=[str(e)],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            except BudgetExceeded as e:
                return RCResult(None, "", tier, "budget_abort", notes=[str(e)],
                                ban_families=sorted(ban_f), ban_movements=sorted(ban_m))
            self.history.record_blueprint(bp, "composed")
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
            ban_f.add(bp.family_id)
            ban_m.add(ms)
            msg = (f"movement precheck: near {near} lev={lev:.2f} jac={jac:.2f} "
                   f"— ban {bp.family_id}, recompose {mov_attempt}/{max_mov}")
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
                    audit = self.auditor.audit(candidate, bp, ledger)
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

            for w in passage_word_check(passage, bp):
                notes.append(f"prevalidate: {w}")

            pre_fp = extract_fingerprint(rc_id, bp, passage, realized,
                                         {"questions": [], "letters": [], "trap_usage": {}},
                                         embed=self.embed)
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
            print(f"  [gate-b] {pre_report.breached} — re-rendering with directives")
            directives = retry_dirs

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
        pre_fp = extract_fingerprint(rc_id, bp, passage, realized,
                                     {"questions": [], "letters": [], "trap_usage": {}},
                                     embed=self.embed)
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
        try:
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
        # Free, strict length-bias audit (no paid rewrite). First-pass questions
        # must satisfy the rule in the question prompt; if they don't, the set
        # routes to needs_review below — never auto-approved, never a second
        # Sonnet questions call.
        length_bias = length_bias_report(qdata)
        if length_bias.get("biased"):
            print(f"  [length-bias] correct-longest "
                  f"{length_bias['correct_longest_count']}/6 "
                  f"thesis_longest={length_bias['thesis_correct_longest']} "
                  f"— will not auto-approve")
        for w in length_bias["warnings"]:
            notes.append(f"option audit: {w}")

        # ---- Gate C: full novelty ------------------------------------------
        fp = extract_fingerprint(rc_id, bp, passage, realized, qdata, embed=self.embed)
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
            # question regen can't fix a Gate-C breach (topology/distractor
            # channels derive from the blueprint) — the passage is spent
            self.history.set_passage_status(bp.blueprint_id, "consumed")
            return RCResult(rc_id, bp.blueprint_id, tier, "rejected_novelty",
                            rc_text=rc_text,
                            novelty_composite=report.composite,
                            compliance_f1=realized.f1,
                            cost_usd=_spent(), cost_lines=ledger.lines,
                            notes=notes + [f"full novelty: {report.breached or report.composite}"])
        notes.extend(f"corpus flag: {f}" for f in report.corpus_flags)

        # ---- Stage 5: solver + judge (optional under budget) ----------------
        rc_text = assemble_rc_text(bp, passage, qdata)
        solver, judge = None, {"scores": {}, "average": 0.0, "verdict": "skipped"}
        solver_dispute = False
        try:
            solver = blind_solve(self.llm, ledger, bp, passage, qdata)
            solver_dispute = bool(solver.get("disputes"))
        except BudgetExceeded:
            notes.append("solver skipped: budget")
        try:
            if not solver_dispute:
                judge = judge_rc(self.llm, ledger, bp, rc_text, self.registry)
        except BudgetExceeded:
            notes.append("judge skipped: budget")
            judge = {"scores": {}, "average": 0.0, "verdict": "skipped_budget"}

        avg = float(judge.get("average") or 0.0)
        posture_run = any(f.startswith("posture run") for f in report.corpus_flags)
        if solver_dispute:
            status = "solver_dispute"
        elif length_bias["biased"]:
            # systematic within-set length tell (correct is longest in >2/6, or the
            # thesis answer is longest) — never auto-approve; a human decides.
            status = "needs_review"
            notes.append("length_bias: routed to needs_review "
                         f"(correct-longest {length_bias['correct_longest_count']}/6, "
                         f"thesis_longest={length_bias['thesis_correct_longest']})")
        elif posture_run:
            # blueprint-consistent closing-posture run (collision with the
            # pre-posture corpus or residual library skew) — a human decides.
            status = "needs_review"
            notes.append("posture run: routed to needs_review")
        elif judge.get("verdict") == "approve" and avg >= config.JUDGE_SCORE_THRESHOLD \
                and realized.f1 >= config.COMPLIANCE_F1_THRESHOLD:
            status = "approved"
        else:
            status = "needs_review"

        # ---- persist ---------------------------------------------------------
        self.history.insert_rc_set(
            rc_id=rc_id, tier=tier, rc_text=rc_text, status=status, judge=judge,
            solver=solver, avg=avg, blueprint_id=bp.blueprint_id,
            compliance_f1=realized.f1, novelty_composite=report.composite,
            total_cost=ledger.spent_usd, essay_doc_id=seed.doc_id, essay_url=seed.url,
            domain=bp.topic, embedding=fp.embedding, attempts=1)
        self.history.record_fingerprint(fp)
        self.history.mark_shipped(bp, rc_id)
        self.history.set_passage_status(bp.blueprint_id, "consumed")

        print(f"  [{rc_id}] status={status} f1={realized.f1} novelty={report.composite} "
              f"avg={avg} cost=${ledger.spent_usd:.4f} (budget ${ledger.budget_usd:.2f})")
        return RCResult(rc_id, bp.blueprint_id, tier, status, rc_text=rc_text,
                        average_score=avg, compliance_f1=realized.f1,
                        novelty_composite=report.composite, cost_usd=_spent(),
                        cost_lines=ledger.lines, notes=notes)

    # -------------------------------------------------------------- helpers

    def _inject_posture(self, f, bp: Blueprint, realized):
        # zero-migration carriage on the stylometry dict (see
        # _correct_longest_count in _questions_and_ship); burrows_delta only
        # reads FUNCTION_WORDS keys, so these never enter any math
        f.stylometry["_closing_posture"] = realized.closing_posture_guess
        f.stylometry["_planned_posture"] = self.registry.posture_of(bp.family_id)
        if realized.final_line_is_aphorism is not None:
            f.stylometry["_aphorism_ending"] = 1 if realized.final_line_is_aphorism else 0

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
        """Blueprint-derived topology signature vs the corpus, worst first.
        Free (local): the signature comes from the registry, not the render."""
        cap = config.NOVELTY_CAPS["topology_similarity"]
        mine = self._planned_topology_signature(topology_id)
        if not mine:
            return []
        hits = []
        for other in self.history.fingerprint_window(config.FINGERPRINT_WINDOW):
            if not other.topology_signature:
                continue
            sim = topology_similarity(mine, other.topology_signature)
            if sim > cap:
                hits.append((sim, other.rc_id))
        hits.sort(reverse=True)
        return hits

    def _pick_clear_topology(self, bp: Blueprint) -> str | None:
        ids = list(self.registry.ids("topology"))
        allowed = config.TIER_PARAMS[bp.tier].get("allowed_topologies")
        if allowed:
            ids = [i for i in ids if i in allowed]
        ids = [i for i in ids if i != bp.topology_id]
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

        If every allowed topology collides (common on medium's small pool once
        a few sets ship), fall back to the *least* colliding option and proceed
        rather than burning the slot as rejected_novelty with no paid work.
        Gate C still scores topology; this only unblocks generation."""
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
        allowed = config.TIER_PARAMS[bp.tier].get("allowed_topologies")
        candidates = (allowed if allowed
                      else list(self.registry.ids("topology")))
        for tid in candidates:
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
            print(f"  [topo] no clear option — using least-colliding "
                  f"{bp.topology_id}->{best_tid} @ {best_sim:.2f}")
            bp.topology_id = best_tid
            self.history.record_blueprint(bp, "composed")
        else:
            notes.append(
                f"topology precheck: proceeding with {bp.topology_id} "
                f"@ {best_sim:.2f} vs {best_near} (no clearer alternative)")
            print(f"  [topo] proceeding with {bp.topology_id} "
                  f"@ {best_sim:.2f} (no clearer alternative)")
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
        for fp in self.history.fingerprint_window(config.FINGERPRINT_WINDOW):
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
        rows = self.history.conn.execute(
            """SELECT blueprint_id, blueprint_json FROM blueprints
               WHERE status IN ('shipped', 'composed', 'rejected_novelty',
                                'rejected_questions')
               ORDER BY created_at DESC LIMIT ?""",
            (config.FINGERPRINT_WINDOW,)).fetchall()
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
        rows = self.history.conn.execute(
            """SELECT rc_id, family_id, persona_id, ending_id, rhythm_id, revelation_id,
                      distractor_profile_id, topology_id
               FROM blueprints WHERE status = 'shipped' AND rc_id IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (config.FINGERPRINT_WINDOW,)).fetchall()
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
    _RENDER_MOVABLE_BREACHES = ("rhythm_cosine", "curve_pearson",
                                "embedding_cosine", "persona_leak")

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
            elif head == "curve_pearson":
                dirs.append("Change how the argument's commitment builds — make its "
                            "intensity rise more gradually, or in a different cadence — "
                            "without changing which paragraph first reveals the thesis.")
            elif head == "embedding_cosine":
                dirs.append("Reframe the angle and examples away from the nearest passage's "
                            "territory: choose different illustrative cases and vocabulary.")
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
        return f"{worst_id} @ {worst:.2f}"
    return None


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------

def run_batch(pipeline: RCPipeline, tier_counts: dict[str, int],
              seed_provider=None, max_usd: float | None = None) -> list[RCResult]:
    """seed_provider: callable -> (SeedEssay, on_success(rc_id) callback) or
    (None, None) when no seeds remain. None = seedless generation.

    max_usd: batch spending cap. No new generation attempt STARTS once
    cumulative spend reaches it, so total batch spend can overshoot it by at
    most one per-RC budget. Default: 1.25 x sum of requested tier budgets."""
    if max_usd is None:
        max_usd = 1.25 * sum(config.TIER_BUDGET_USD[t] * n for t, n in tier_counts.items())
    print(f"[batch] spending cap: ${max_usd:.2f} "
          f"(per-RC caps: {config.TIER_BUDGET_USD})")
    results: list[RCResult] = []

    def spent() -> float:
        return sum(r.cost_usd for r in results)

    try:
        for tier, count in tier_counts.items():
            for i in range(count):
                if spent() >= max_usd:
                    print(f"[batch] spending cap ${max_usd:.2f} reached "
                          f"(spent ${spent():.4f}) — stopping cleanly.")
                    return results
                seed, on_success = (None, None)
                tried_doc_ids: set[str] = set()
                if seed_provider:
                    seed, on_success = seed_provider(tier)
                    if seed is None:
                        print(f"[seeds] exhausted — continuing seedless for {tier}")
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
                print(f"\n=== [{tier}] {i + 1}/{count} ===")
                # retry loop for novelty rejections: resample a fresh blueprint.
                # Movement collisions accumulate family/movement bans so a
                # recompose cannot re-hit the same skeleton (seed rotation alone
                # does not change paragraph-function order).
                res = None
                ban_families: set[str] = set()
                ban_movements: set[str] = set()
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
                    results.append(res)
                    ban_families.update(res.ban_families or [])
                    ban_movements.update(res.ban_movements or [])
                    if res.status not in ("rejected_novelty", "failed_composition"):
                        break
                    if spent() >= max_usd:
                        print(f"[batch] spending cap reached mid-retry — stopping cleanly.")
                        return results
                    print(f"  [retry] {res.status} — recomposing ({attempt + 1}/3)"
                          + (f" bans={sorted(ban_families)}" if ban_families else ""))
                    # rotate the seed too: a fresh blueprint keeps the same
                    # topic anchor, so an embedding-channel collision would
                    # just repeat. The untried previous seed stays unused
                    # (only success marks it consumed).
                    if seed_provider and seed is not None:
                        new_seed, new_cb = seed_provider(tier, exclude_ids=tried_doc_ids)
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
                    print("  [retry] questions failed — regenerating questions on the same passage")
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
                    results.append(res)
                if res and res.rc_id and on_success:
                    on_success(res.rc_id)
    except APIExhausted as e:
        print(f"\n[STOP] API exhausted ({e}) — batch stopped cleanly; "
              f"completed work is committed. Re-run later to continue.")
    total = sum(r.cost_usd for r in results)
    shipped_statuses = {"approved", "needs_review", "solver_dispute"}
    shipped = [r for r in results if r.rc_id and r.status in shipped_statuses]
    print(f"\n--- Batch summary: {len(shipped)} shipped, "
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
    return results
