"""RCPipeline — orchestrator (RC_ENGINE_DEV).

Default mode = **cheap**:
  compose (free) -> refine (cheap) -> free topology/topic gates
  -> ONE fullset call (passage + questions)
  -> free novelty (soft stylometry) -> optional judge

Factory mode = production multi-stage (render/compliance/questions split).
"""

from __future__ import annotations

import json
import random

from . import config
from .compliance import ComplianceAuditor
from .composer import (BlueprintComposer, CompositionExhausted,
                       blueprint_categorical_similarity)
from .constraints import CompatibilityRules
from .fingerprints import embed_text, extract_fingerprint, topology_similarity
from .fullset import FullsetError, FullsetGenerator
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


_LENGTH_FIX_GUIDANCE = """LENGTH-BIAS REPAIR (mandatory — previous draft failed audit):
- Within EACH question, option word counts must differ by at most 8 words.
- The correct option may be strictly longest in at most 2 of 6 questions.
- On any thesis / main-point / global slot, the correct option must NOT be
  strictly longest — make at least one wrong option longer.
- Keep stems and mechanisms; rewrite option texts for length parity.
- Parallel grammar and register across the four options.
"""


class RCPipeline:
    def __init__(self, history: HistoryStore, llm, embed: bool = True,
                 rng: random.Random | None = None,
                 mode: str | None = None,
                 corpus_history: HistoryStore | None = None):
        self.registry = ComponentRegistry()
        self.history = history
        # Novelty / topic / topology reads against production corpus when set
        self.corpus = corpus_history or history
        self.llm = llm
        self.embed = embed
        self.mode = (mode or config.DEFAULT_MODE).lower()
        rules = CompatibilityRules(self.registry)
        self.composer = BlueprintComposer(self.registry, history, rules, llm, rng)
        self.renderer = PassageRenderer(self.registry, llm)
        self.auditor = ComplianceAuditor(llm, self.registry)
        self.qengine = QuestionEngine(self.registry, llm)
        self.fullset = FullsetGenerator(self.registry, llm)
        self.novelty = NoveltyScorer(self.corpus)
        self._topic_vecs: dict[str, list[float] | None] = {}   # precheck cache

    # ------------------------------------------------------------------ main

    def generate_one(self, tier: str, seed: SeedEssay | None = None) -> RCResult:
        if self.mode == "factory":
            return self._generate_one_factory(tier, seed)
        return self._generate_one_cheap(tier, seed)

    def _generate_one_cheap(self, tier: str, seed: SeedEssay | None = None) -> RCResult:
        """Cheap path: free structure clearance + one fullset call."""
        seed = seed or SeedEssay()
        ledger = CostLedger(budget_usd=config.TIER_BUDGET_USD[tier])
        notes: list[str] = [f"mode=cheap"]

        try:
            bp = self.composer.compose(tier, seed, ledger)
        except CompositionExhausted as e:
            return RCResult(None, "", tier, "failed_composition", notes=[str(e)])
        except BudgetExceeded as e:
            return RCResult(None, "", tier, "budget_abort", notes=[str(e)])
        self.history.record_blueprint(bp, "composed")
        print(f"  [BP {bp.blueprint_id}] {bp.family_id}/{bp.persona_id}/{bp.ending_id}/"
              f"{bp.rhythm_id}/{bp.revelation_id}/{bp.distractor_profile_id}/"
              f"{bp.topology_id} instability={bp.instability} [cheap]")

        # Free topology clearance before any big spend
        bp, topo_notes, topo_ok = self._resolve_topology(bp)
        notes.extend(topo_notes)
        if not topo_ok:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty")
            return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + ["topology precheck failed pre-fullset"])

        # Topic precheck (enforce, 1 re-refine)
        collisions = self._topic_precheck(bp)
        if collisions and config.TOPIC_PRECHECK_ENFORCE:
            for i in range(1, config.TOPIC_PRECHECK_MAX_REREFINES + 1):
                print(f"  [precheck] topic collides with {collisions[0][1]} "
                      f"@ {collisions[0][0]:.2f} — re-refining ({i}/"
                      f"{config.TOPIC_PRECHECK_MAX_REREFINES})")
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
                                notes=notes + [
                                    f"topic precheck: still colliding with "
                                    f"{collisions[0][1]} @ {collisions[0][0]:.2f}"])

        bp_sims = self._blueprint_sims(bp)

        # ---- ONE paid fullset call ----------------------------------------
        try:
            passage, qdata = self.fullset.generate(bp, ledger)
        except FullsetError as e:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_render")
            return RCResult(None, bp.blueprint_id, tier, "failed_render",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + [f"fullset: {e}"])
        except BudgetExceeded as e:
            return self._abort(bp, ledger, f"budget during fullset: {e}", notes)

        for w in passage_word_check(passage, bp):
            notes.append(f"prevalidate: {w}")

        # Length-bias fix: questions-only rewrite (keep passage) — Sonnet
        length_bias = length_bias_report(qdata)
        if (length_bias.get("biased") and config.CHEAP_LENGTH_FIX):
            print(f"  [length-fix] correct-longest "
                  f"{length_bias['correct_longest_count']}/6 "
                  f"thesis_longest={length_bias['thesis_correct_longest']} "
                  f"— rewriting questions only")
            try:
                qdata2 = self.qengine.build(
                    bp, passage, ledger,
                    extra_guidance=_LENGTH_FIX_GUIDANCE,
                    stage="length_fix")
                lb2 = length_bias_report(qdata2)
                if not lb2.get("biased") or (
                        lb2["correct_longest_count"]
                        < length_bias["correct_longest_count"]):
                    qdata = qdata2
                    length_bias = lb2
                    notes.append(
                        f"length-fix applied: correct-longest now "
                        f"{length_bias['correct_longest_count']}/6")
                else:
                    notes.append(
                        "length-fix did not improve bias; keeping prior Qs")
            except (BudgetExceeded, QuestionEngineError) as e:
                notes.append(f"length-fix skipped: {e}")

        for w in length_bias["warnings"]:
            notes.append(f"option audit: {w}")

        # Planned realized structure (no compliance call in cheap mode)
        realized = RealizedStructure(
            paragraph_functions=[p.function for p in bp.movement],
            matches=[True] * len(bp.movement),
            thesis_first_visible_para=bp.revelation_detail.get("planned_para"),
            commitment_curve=[0.1 * i for i in range(len(bp.movement))],
            traps_present=[t["trap_id"] for t in bp.trap_map],
            f1=1.0,
            closing_posture_guess=self.registry.posture_of(bp.family_id),
            final_line_is_aphorism=False,
        )

        rc_id = self.history.generate_rc_id(tier)
        fp = extract_fingerprint(rc_id, bp, passage, realized, qdata, embed=self.embed)
        self._inject_posture(fp, bp, realized)
        fp.stylometry["_correct_longest_count"] = length_bias["correct_longest_count"]
        if length_bias["has_thesis_question"]:
            fp.stylometry["_thesis_longest"] = 1 if length_bias["thesis_correct_longest"] else 0

        report = self.novelty.score(fp, bp_sims, include_question_channels=True)
        self.history.record_novelty_audit(
            bp.blueprint_id, rc_id, report.channel_scores, report.composite,
            f"full:{report.verdict}", "; ".join(report.breached))
        notes.extend(f"corpus flag: {f}" for f in report.corpus_flags)

        if report.verdict != "pass":
            # Hard novelty fail (embedding/topology/movement) — do not ship
            rc_text = assemble_rc_text(bp, passage, qdata)
            self.history.insert_rc_set(
                rc_id=rc_id, tier=tier, rc_text=rc_text, status="rejected_novelty",
                judge={"scores": {}, "average": 0.0, "verdict": "not_run_novelty"},
                solver=None, avg=0.0, blueprint_id=bp.blueprint_id,
                compliance_f1=1.0, novelty_composite=report.composite,
                total_cost=ledger.spent_usd, essay_doc_id=seed.doc_id,
                essay_url=seed.url, domain=bp.topic, embedding=fp.embedding,
                attempts=1)
            self.history.record_fingerprint(fp)
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_novelty", rc_id)
            return RCResult(rc_id, bp.blueprint_id, tier, "rejected_novelty",
                            rc_text=rc_text, novelty_composite=report.composite,
                            compliance_f1=1.0, cost_usd=ledger.spent_usd,
                            cost_lines=ledger.lines,
                            notes=notes + [f"novelty: {report.breached or report.composite}"])

        return self._ship_cheap(bp, passage, realized, qdata, fp, report,
                                length_bias, ledger, notes, seed, rc_id)

    def _ship_cheap(self, bp, passage, realized, qdata, fp, report, length_bias,
                    ledger, notes, seed, rc_id) -> RCResult:
        rc_text = assemble_rc_text(bp, passage, qdata)
        solver, judge = None, {"scores": {}, "average": 0.0, "verdict": "skipped"}
        solver_dispute = False

        if config.CHEAP_RUN_SOLVER:
            try:
                solver = blind_solve(self.llm, ledger, bp, passage, qdata)
                solver_dispute = bool(solver.get("disputes"))
            except BudgetExceeded:
                notes.append("solver skipped: budget")
        else:
            notes.append("solver skipped: cheap mode")

        if config.CHEAP_RUN_JUDGE and not solver_dispute:
            try:
                judge = judge_rc(self.llm, ledger, bp, rc_text, self.registry)
            except BudgetExceeded:
                notes.append("judge skipped: budget")
                judge = {"scores": {}, "average": 0.0, "verdict": "skipped_budget"}
        elif not config.CHEAP_RUN_JUDGE:
            notes.append("judge skipped: cheap mode")
            judge = {"scores": {}, "average": 8.0, "verdict": "approve"}

        avg = float(judge.get("average") or 0.0)
        soft = any(f.startswith("soft_novelty") for f in report.corpus_flags)
        posture_run = any(f.startswith("posture run") for f in report.corpus_flags)

        if solver_dispute:
            status = "solver_dispute"
        elif length_bias.get("biased"):
            status = "needs_review"
            notes.append("length_bias: needs_review")
        elif soft or posture_run:
            status = "needs_review"
            notes.append("soft novelty / posture flag → needs_review")
        elif judge.get("verdict") == "approve" and avg >= config.JUDGE_SCORE_THRESHOLD:
            status = "approved"
        else:
            status = "needs_review"

        self.history.insert_rc_set(
            rc_id=rc_id, tier=bp.tier, rc_text=rc_text, status=status, judge=judge,
            solver=solver, avg=avg, blueprint_id=bp.blueprint_id,
            compliance_f1=realized.f1, novelty_composite=report.composite,
            total_cost=ledger.spent_usd, essay_doc_id=seed.doc_id, essay_url=seed.url,
            domain=bp.topic, embedding=fp.embedding, attempts=1)
        self.history.record_fingerprint(fp)
        self.history.mark_shipped(bp, rc_id)

        print(f"  [{rc_id}] status={status} novelty={report.composite} "
              f"avg={avg} cost=${ledger.spent_usd:.4f} (budget ${ledger.budget_usd:.2f})")
        return RCResult(rc_id, bp.blueprint_id, bp.tier, status, rc_text=rc_text,
                        average_score=avg, compliance_f1=realized.f1,
                        novelty_composite=report.composite, cost_usd=ledger.spent_usd,
                        cost_lines=ledger.lines, notes=notes)

    def _generate_one_factory(self, tier: str, seed: SeedEssay | None = None) -> RCResult:
        """Production multi-stage path (opt-in via --mode factory)."""
        seed = seed or SeedEssay()
        ledger = CostLedger(budget_usd=config.TIER_BUDGET_USD[tier])
        notes: list[str] = ["mode=factory"]

        try:
            bp = self.composer.compose(tier, seed, ledger)
        except CompositionExhausted as e:
            return RCResult(None, "", tier, "failed_composition", notes=[str(e)])
        except BudgetExceeded as e:
            return RCResult(None, "", tier, "budget_abort", notes=[str(e)])
        self.history.record_blueprint(bp, "composed")
        print(f"  [BP {bp.blueprint_id}] {bp.family_id}/{bp.persona_id}/{bp.ending_id}/"
              f"{bp.rhythm_id}/{bp.revelation_id}/{bp.distractor_profile_id}/"
              f"{bp.topology_id} instability={bp.instability} [factory]")

        collisions = self._topic_precheck(bp)
        if collisions and config.TOPIC_PRECHECK_ENFORCE:
            for i in range(1, config.TOPIC_PRECHECK_MAX_REREFINES + 1):
                print(f"  [precheck] topic collides with {collisions[0][1]} "
                      f"@ {collisions[0][0]:.2f} — re-refining")
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
                                notes=notes + ["topic precheck failed"])

        bp_sims = self._blueprint_sims(bp)
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
            except ValueError as e:
                notes.append(f"compliance parse failure attempt {attempt}: {e}")
                continue
            if audit.f1 >= config.COMPLIANCE_F1_THRESHOLD:
                passage, realized = candidate, audit
                break
            directives = audit.directives[:6]
            notes.append(f"compliance F1={audit.f1} attempt {attempt}")
            passage, realized = candidate, audit
        if passage is None or realized is None:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_render")
            return RCResult(None, bp.blueprint_id, tier, "failed_render",
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines, notes=notes)

        for w in passage_word_check(passage, bp):
            notes.append(f"prevalidate: {w}")

        rc_id = self.history.generate_rc_id(tier)
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
            return RCResult(None, bp.blueprint_id, tier, "rejected_novelty",
                            novelty_composite=pre_report.composite,
                            cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                            notes=notes + [f"passage novelty: {pre_report.breached}"])

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
            # under the per-RC cap this passage can never afford questions
            self.history.set_passage_status(bp.blueprint_id, "abandoned",
                                            f"budget during questions: {e}")
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_budget")
            return RCResult(None, bp.blueprint_id, tier, "budget_abort",
                            cost_usd=_spent(), cost_lines=ledger.lines,
                            notes=notes + [f"budget during questions: {e}"])
        except QuestionEngineError as e:
            self.history.set_blueprint_status(bp.blueprint_id, "rejected_questions")
            self.history.set_passage_status(bp.blueprint_id, "questions_failed", str(e))
            return RCResult(None, bp.blueprint_id, tier, "failed_questions",
                            cost_usd=_spent(), cost_lines=ledger.lines,
                            notes=notes + [str(e)])
        length_bias = length_bias_report(qdata)
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

    def _planned_topology_signature(self, topology_id: str) -> list[dict]:
        topo = self.registry.get("topology", topology_id)
        return [
            {"type": s["type"], "target": s.get("target", ""),
             "difficulty": float(s.get("difficulty", 0.0))}
            for s in topo.get("slots", [])
        ]

    def _topology_collisions(self, topology_id: str) -> list[tuple[float, str]]:
        cap = config.NOVELTY_CAPS["topology_similarity"]
        mine = self._planned_topology_signature(topology_id)
        if not mine:
            return []
        hits = []
        stores = [self.corpus]
        if self.corpus is not self.history:
            stores.append(self.history)
        for store in stores:
            for other in store.fingerprint_window(config.FINGERPRINT_WINDOW):
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
            print(f"  [topo] {bp.topology_id} near {near0} @ {sim0:.2f} → {alt}")
            bp.topology_id = alt
            self.history.record_blueprint(bp, "composed")
            hits = self._topology_collisions(bp.topology_id)
            if not hits:
                return bp, notes, True
            sim0, near0 = hits[0]
        notes.append(f"topology precheck: still near {near0} @ {sim0:.2f}")
        return bp, notes, False

    def _abort(self, bp: Blueprint, ledger: CostLedger, why: str,
               notes: list[str]) -> RCResult:
        self.history.set_blueprint_status(bp.blueprint_id, "rejected_budget")
        return RCResult(None, bp.blueprint_id, bp.tier, "budget_abort",
                        cost_usd=ledger.spent_usd, cost_lines=ledger.lines,
                        notes=notes + [why])

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
        # Prefer production corpus for prior topics; also scan write DB
        stores = [self.corpus]
        if self.corpus is not self.history:
            stores.append(self.history)
        for store in stores:
            rows = store.conn.execute(
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

        for store in stores:
            for fp in store.fingerprint_window(config.FINGERPRINT_WINDOW):
                if fp.embedding:
                    c = _cosine(vec, fp.embedding)
                    if c >= config.TOPIC_PRECHECK_PASSAGE_COSINE:
                        collisions.append((c, f"passage {fp.rc_id}", ""))

        collisions.sort(reverse=True)
        # de-dupe labels keep worst score
        seen: set[str] = set()
        uniq = []
        for item in collisions:
            if item[1] in seen:
                continue
            seen.add(item[1])
            uniq.append(item)
        collisions = uniq
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
        out = {}
        keys = ["family", "persona", "ending", "rhythm", "revelation",
                "distractor_profile", "topology"]
        mine = bp.component_ids
        stores = [self.corpus]
        if self.corpus is not self.history:
            stores.append(self.history)
        for store in stores:
            rows = store.conn.execute(
                """SELECT rc_id, family_id, persona_id, ending_id, rhythm_id, revelation_id,
                          distractor_profile_id, topology_id
                   FROM blueprints WHERE status = 'shipped' AND rc_id IS NOT NULL
                   ORDER BY created_at DESC LIMIT ?""",
                (config.FINGERPRINT_WINDOW,)).fetchall()
            for r in rows:
                other = dict(zip(keys, r[1:]))
                out[r[0]] = blueprint_categorical_similarity(mine, other)
        return out


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
    stores = [pipeline.corpus]
    if pipeline.corpus is not pipeline.history:
        stores.append(pipeline.history)
    for store in stores:
        for fp in store.fingerprint_window(config.FINGERPRINT_WINDOW):
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
    print(f"[batch] mode={pipeline.mode} | spending cap: ${max_usd:.2f} "
          f"(per-RC caps: {config.TIER_BUDGET_USD})")
    print(f"[batch] max {getattr(config, 'MAX_SLOT_ATTEMPTS', 1)} full attempt(s)/slot")
    results: list[RCResult] = []
    max_slot = getattr(config, "MAX_SLOT_ATTEMPTS", 1)

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
                    for _ in range(config.SEED_PRESCREEN_MAX_ROTATIONS):
                        hit = _seed_collision(pipeline, seed)
                        if hit is None:
                            break
                        print(f"[seeds] pre-screen: {seed.title!r} too close to "
                              f"{hit} — rotating")
                        new_seed, new_cb = seed_provider(tier, exclude_ids=tried_doc_ids)
                        if new_seed is None:
                            break
                        seed, on_success = new_seed, new_cb
                        if new_seed.doc_id:
                            tried_doc_ids.add(new_seed.doc_id)
                print(f"\n=== [{tier}] {i + 1}/{count} ===")
                res = None
                for attempt in range(max_slot):
                    try:
                        res = pipeline.generate_one(tier, seed)
                    except APIExhausted:
                        raise
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        res = RCResult(None, "", tier, "failed_error", notes=[repr(e)])
                    results.append(res)
                    if res.status not in ("rejected_novelty", "failed_composition"):
                        break
                    if spent() >= max_usd or attempt + 1 >= max_slot:
                        break
                    print(f"  [retry] {res.status} — recomposing "
                          f"({attempt + 1}/{max_slot})")
                    if seed_provider and seed is not None:
                        new_seed, new_cb = seed_provider(tier, exclude_ids=tried_doc_ids)
                        if new_seed is not None:
                            seed, on_success = new_seed, new_cb
                            if new_seed.doc_id:
                                tried_doc_ids.add(new_seed.doc_id)
                            print(f"  [retry] seed rotated -> {new_seed.title!r}")
                if res and res.status == "failed_questions" and res.blueprint_id \
                        and spent() < max_usd and pipeline.mode == "factory":
                    bp_id = res.blueprint_id
                    print("  [retry] questions failed — regenerating on same passage")
                    try:
                        res = pipeline.resume_questions(bp_id)
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
    print(f"\n--- Batch summary: {len([r for r in results if r.rc_id and r.status in shipped_statuses])} shipped, "
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
    return results
