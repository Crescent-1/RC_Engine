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

import random

from . import config
from .compliance import ComplianceAuditor
from .composer import (BlueprintComposer, CompositionExhausted,
                       blueprint_categorical_similarity)
from .constraints import CompatibilityRules
from .fingerprints import extract_fingerprint
from .history import HistoryStore
from .llm import APIExhausted, BudgetExceeded, CostLedger
from .models import Blueprint, RCResult, SeedEssay
from .novelty import NoveltyScorer
from .question_engine import (QuestionEngine, QuestionEngineError,
                              assemble_rc_text, length_bias_report,
                              passage_word_check)
from .quality import blind_solve, judge_rc
from .registry import ComponentRegistry
from .renderer import PassageRenderer, TruncatedRender


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

    # ------------------------------------------------------------------ main

    def generate_one(self, tier: str, seed: SeedEssay | None = None) -> RCResult:
        seed = seed or SeedEssay()
        ledger = CostLedger(budget_usd=config.TIER_BUDGET_USD[tier])
        notes: list[str] = []

        # ---- Stage 1: blueprint --------------------------------------------
        try:
            bp = self.composer.compose(tier, seed, ledger)
        except CompositionExhausted as e:
            return RCResult(None, "", tier, "failed_composition", notes=[str(e)])
        except BudgetExceeded as e:
            return RCResult(None, "", tier, "budget_abort", notes=[str(e)])
        self.history.record_blueprint(bp, "composed")
        print(f"  [BP {bp.blueprint_id}] {bp.family_id}/{bp.persona_id}/{bp.ending_id}/"
              f"{bp.rhythm_id}/{bp.revelation_id}/{bp.distractor_profile_id}/"
              f"{bp.topology_id} instability={bp.instability}")

        # blueprint similarity vs shipped RCs (needed for composite scoring)
        bp_sims = self._blueprint_sims(bp)

        # ---- Stage 2: render + compliance loop -----------------------------
        passage, realized = None, None
        directives: list[str] = []
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

        # ---- Gate B: passage-level novelty (free; before the expensive call)
        rc_id = self.history.generate_rc_id(tier)

        def _inject_posture(f):
            # zero-migration carriage on the stylometry dict (see
            # _correct_longest_count below); burrows_delta only reads
            # FUNCTION_WORDS keys, so these never enter any math
            f.stylometry["_closing_posture"] = realized.closing_posture_guess
            f.stylometry["_planned_posture"] = self.registry.posture_of(bp.family_id)
            if realized.final_line_is_aphorism is not None:
                f.stylometry["_aphorism_ending"] = 1 if realized.final_line_is_aphorism else 0

        pre_fp = extract_fingerprint(rc_id, bp, passage, realized,
                                     {"questions": [], "letters": [], "trap_usage": {}},
                                     embed=self.embed)
        _inject_posture(pre_fp)
        pre_report = self.novelty.score(pre_fp, bp_sims, include_question_channels=False)
        self.history.record_novelty_audit(bp.blueprint_id, None, pre_report.channel_scores,
                                          pre_report.composite, f"passage:{pre_report.verdict}",
                                          "; ".join(pre_report.breached))
        if pre_report.verdict != "pass":
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                            novelty_composite=pre_report.composite,
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + [f"passage novelty: {pre_report.breached or pre_report.composite}"])

        # ---- Stage 3: questions --------------------------------------------
        try:
            qdata = self.qengine.build(bp, passage, ledger)
        except BudgetExceeded as e:
            return self._abort(bp, ledger, f"budget during questions: {e}", notes)
        except QuestionEngineError as e:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_questions")
            return RCResult(None, bp.blueprint_id, tier, "failed_questions",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + [str(e)])
        length_bias = length_bias_report(qdata)
        for w in length_bias["warnings"]:
            notes.append(f"option audit: {w}")

        # ---- Gate C: full novelty ------------------------------------------
        fp = extract_fingerprint(rc_id, bp, passage, realized, qdata, embed=self.embed)
        # record the length-bias stat on the fingerprint so `health` can trend it
        fp.stylometry["_correct_longest_count"] = length_bias["correct_longest_count"]
        _inject_posture(fp)
        report = self.novelty.score(fp, bp_sims, include_question_channels=True)
        self.history.record_novelty_audit(bp.blueprint_id, rc_id, report.channel_scores,
                                          report.composite, f"full:{report.verdict}",
                                          "; ".join(report.breached))
        if report.verdict != "pass":
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                            novelty_composite=report.composite,
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
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

        print(f"  [{rc_id}] status={status} f1={realized.f1} novelty={report.composite} "
              f"avg={avg} cost=${ledger.spent_usd:.4f} (budget ${ledger.budget_usd:.2f})")
        return RCResult(rc_id, bp.blueprint_id, tier, status, rc_text=rc_text,
                        average_score=avg, compliance_f1=realized.f1,
                        novelty_composite=report.composite, cost_usd=ledger.spent_usd,
                        cost_lines=ledger.lines, notes=notes)

    # -------------------------------------------------------------- helpers

    def _abort(self, bp: Blueprint, ledger: CostLedger, why: str,
               notes: list[str]) -> RCResult:
        self.history.set_blueprint_status(bp.blueprint_id, "rejected_budget")
        return RCResult(None, bp.blueprint_id, bp.tier, "budget_abort",
                        cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                        notes=notes + [why])

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
                print(f"\n=== [{tier}] {i + 1}/{count} ===")
                # retry loop for novelty rejections: resample a fresh blueprint
                res = None
                for attempt in range(3):
                    try:
                        res = pipeline.generate_one(tier, seed)
                    except APIExhausted:
                        raise                         # stop the batch cleanly
                    except Exception as e:            # never let one RC kill the batch
                        import traceback
                        traceback.print_exc()
                        res = RCResult(None, "", tier, "failed_error", notes=[repr(e)])
                    results.append(res)
                    if res.status not in ("rejected_novelty", "failed_composition"):
                        break
                    if spent() >= max_usd:
                        print(f"[batch] spending cap reached mid-retry — stopping cleanly.")
                        return results
                    print(f"  [retry] {res.status} — recomposing ({attempt + 1}/3)")
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
                if res and res.rc_id and on_success:
                    on_success(res.rc_id)
    except APIExhausted as e:
        print(f"\n[STOP] API exhausted ({e}) — batch stopped cleanly; "
              f"completed work is committed. Re-run later to continue.")
    total = sum(r.cost_usd for r in results)
    print(f"\n--- Batch summary: {len([r for r in results if r.rc_id])} shipped, "
          f"{len(results)} attempts, total ${total:.4f} ---")
    for r in results:
        print(f"  {str(r.rc_id):16s} | {r.tier:6s} | {r.status:16s} | "
              f"f1={r.compliance_f1} novelty={r.novelty_composite} "
              f"score={r.average_score} ${r.cost_usd:.4f}")
    return results
