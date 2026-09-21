"""Planned and realised metrics by client, tier and generation policy.

Added 2026-09-13 for plan section 7.5. Every rollout decision in
2026-09-13-cat-pyq-implementation-plan.md is a comparison between a policy's
sets and legacy sets of the same tier, so this report never pools tiers or
policies. It runs SELECTs only (opening a HistoryStore still applies that
class's usual additive migrations).

What each figure is, and is not:
  - "planned" figures come from the stored blueprint and are exact;
  - "realised" figures are model reads stored at generation time (the
    compliance auditor's thesis paragraph and closing-posture label, blind
    beat and schema reads) or deterministic scans of the exported text
    (negated stems). They are evidence, not gold labels, and the compliance
    thesis read is shown the planned paragraph (compliance.py), so realised
    early-thesis visibility is biased toward the plan;
  - closure is reported as three classes — committed, neutral exposition,
    refusal — because a neutral exposition is not a refusal (plan section 1);
  - question ambiguity counts answerability flags, which exist only on sets
    generated after 2026-09-13 under a non-legacy policy.
Voice-review observations stay observational: nothing here gates a status.
"""
from __future__ import annotations

import collections
import json
import re

from . import config
from .question_contracts import negation_count

SHIPPED = ("approved", "needs_review", "solver_dispute")
_STEM = re.compile(r"^Q(\d+)\.\s+(.*)$", re.M)


def closure_class(posture: str) -> str:
    """committed | neutral | refusal | unknown."""
    if not posture:
        return "unknown"
    if posture.startswith("refusal"):
        return "refusal"
    if posture.startswith("exposition"):
        return "neutral"
    return "committed"


def _share(n: int, d: int):
    return round(n / d, 3) if d else None


def _stems(rc_text: str) -> list[str]:
    head = (rc_text or "").split("[ANSWER KEY", 1)[0]
    return [m.group(2).strip() for m in _STEM.finditer(head)]


def collect(history, scope: str = "client") -> list[dict]:
    """One row per (client, tier, policy)."""
    predicate, params = history._scope(scope, "b.client_id")
    groups: dict[tuple, dict] = collections.defaultdict(lambda: {
        "sets": 0, "statuses": collections.Counter(),
        "planned_thesis_bearing": 0, "planned_early_thesis": 0,
        "realised_thesis_read": 0, "realised_early_thesis": 0,
        "planned_closure": collections.Counter(), "realised_closure": collections.Counter(),
        "families": collections.Counter(), "beats": collections.Counter(),
        "schema_planned": 0, "schema_primary_match": 0,
        "negated_slots_planned": collections.Counter(), "questions": 0,
        "negated_stems": 0, "multiple_negation_stems": 0,
        "answerability_flag_sets": 0, "answerability_flags": 0, "answerability_measured": 0,
    })
    postures = _posture_lookup()
    rows = history.conn.execute(
        f"""SELECT b.client_id, b.tier, b.family_id, b.blueprint_json, rp.realized_json,
                   r.status, r.rc_text, f.stylometry
            FROM blueprints b
            JOIN rc_sets r ON r.rc_id = b.rc_id AND r.client_id = b.client_id
            LEFT JOIN rendered_passages rp ON rp.blueprint_id = b.blueprint_id
                AND rp.client_id = b.client_id
            LEFT JOIN fingerprints f ON f.rc_id = b.rc_id
            WHERE b.status = 'shipped' AND {predicate}""", params).fetchall()
    for client, tier, family, bp_raw, read_raw, status, rc_text, stylo_raw in rows:
        bp = _loads(bp_raw)
        read = _loads(read_raw)
        stylo = _loads(stylo_raw)
        g = groups[(client, tier, bp.get("generation_policy") or "")]
        g["sets"] += 1
        g["statuses"][status] += 1
        g["families"][family] += 1
        plan = bp.get("move_plan") or []
        g["beats"].update(plan)
        detail = bp.get("revelation_detail") or {}
        if detail.get("timing") != "never_stated":
            g["planned_thesis_bearing"] += 1
            g["planned_early_thesis"] += int((detail.get("planned_para") or 99) <= 2)
            para = read.get("thesis_first_visible_para")
            if isinstance(para, int):
                g["realised_thesis_read"] += 1
                g["realised_early_thesis"] += int(para <= 2)
        g["planned_closure"][closure_class(bp.get("closing_posture") or postures.get(family, ""))] += 1
        g["realised_closure"][closure_class(read.get("closing_posture_guess", ""))] += 1
        if bp.get("argument_schema_id"):
            g["schema_planned"] += 1
            g["schema_primary_match"] += int(read.get("argument_schema") == bp["argument_schema_id"])
        for s in bp.get("question_slots") or []:
            if s.get("polarity") == "negative":
                g["negated_slots_planned"][s.get("task", s.get("type"))] += 1
        stems = _stems(rc_text)
        g["questions"] += len(stems)
        counts = [negation_count(s) for s in stems]
        g["negated_stems"] += sum(1 for c in counts if c >= 1)
        g["multiple_negation_stems"] += sum(1 for c in counts if c >= 2)
        if "_answerability_flags" in stylo:
            g["answerability_measured"] += 1
            flags = int(stylo["_answerability_flags"] or 0)
            g["answerability_flags"] += flags
            g["answerability_flag_sets"] += int(flags > 0)

    attempts = collections.defaultdict(lambda: {"attempts": 0, "cost_usd": 0.0,
                                                "statuses": collections.Counter()})
    a_pred, a_params = history._scope(scope, "client_id")
    for client, tier, policy, status, cost in history.conn.execute(
            f"""SELECT client_id, tier, COALESCE(generation_policy, ''), status, cost_usd
                FROM attempts WHERE {a_pred}""", a_params):
        a = attempts[(client, tier, policy)]
        a["attempts"] += 1
        a["cost_usd"] += float(cost or 0.0)
        a["statuses"][status] += 1

    out = []
    for key in sorted(set(groups) | set(attempts)):
        client, tier, policy = key
        g, a = groups[key], attempts[key]
        shipped_attempts = sum(a["statuses"][s] for s in SHIPPED)
        out.append({
            "client": client, "tier": tier, "policy": policy or "legacy",
            "sets": g["sets"], "set_statuses": dict(g["statuses"]),
            "attempts": a["attempts"], "attempt_statuses": dict(a["statuses"]),
            "yield": _share(shipped_attempts, a["attempts"]),
            "composition_failures": a["statuses"]["failed_composition"],
            "novelty_rejections": a["statuses"]["rejected_novelty"],
            "question_failures": a["statuses"]["failed_questions"],
            "solver_disputes": g["statuses"]["solver_dispute"],
            "cost_usd": round(a["cost_usd"], 4),
            "cost_per_shipped_usd": (round(a["cost_usd"] / shipped_attempts, 4)
                                     if shipped_attempts else None),
            "early_thesis": {
                "planned_share": _share(g["planned_early_thesis"], g["planned_thesis_bearing"]),
                "planned_denominator": g["planned_thesis_bearing"],
                "realised_share": _share(g["realised_early_thesis"], g["realised_thesis_read"]),
                "realised_denominator": g["realised_thesis_read"],
            },
            "closure_planned": dict(g["planned_closure"]),
            "closure_realised": dict(g["realised_closure"]),
            "schema_primary_match": _share(g["schema_primary_match"], g["schema_planned"]),
            "families_used": len(g["families"]),
            "beats_used": len(g["beats"]),
            "beats_outside_legacy_vocabulary": sorted(
                b for b in g["beats"] if b not in config.RHETORICAL_MOVES),
            "negation": {
                "planned_by_task": dict(g["negated_slots_planned"]),
                "questions": g["questions"],
                "negated_stem_share": _share(g["negated_stems"], g["questions"]),
                "multiple_negation_stems": g["multiple_negation_stems"],
            },
            "answerability": {
                "sets_measured": g["answerability_measured"],
                "sets_flagged": g["answerability_flag_sets"],
                "flags": g["answerability_flags"],
            },
        })
    return out


def format_rows(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        et, neg = r["early_thesis"], r["negation"]
        lines.append(
            f"{r['client']} {r['tier']:<6} {r['policy']:<12} sets={r['sets']:<3} "
            f"attempts={r['attempts']:<3} yield={r['yield']} "
            f"comp_fail={r['composition_failures']} novelty_rej={r['novelty_rejections']} "
            f"q_fail={r['question_failures']} disputes={r['solver_disputes']} "
            f"cost=${r['cost_usd']} (${r['cost_per_shipped_usd']}/shipped)")
        lines.append(
            f"    early thesis planned {et['planned_share']} (n={et['planned_denominator']}) "
            f"realised read {et['realised_share']} (n={et['realised_denominator']}) | "
            f"closure planned {r['closure_planned']} realised {r['closure_realised']}")
        lines.append(
            f"    negated stems {neg['negated_stem_share']} of {neg['questions']} "
            f"(multiple {neg['multiple_negation_stems']}), planned by task {neg['planned_by_task']} | "
            f"schema match {r['schema_primary_match']} | families {r['families_used']} "
            f"beats {r['beats_used']} new beats {r['beats_outside_legacy_vocabulary']} | "
            f"answerability flagged {r['answerability']['sets_flagged']}/"
            f"{r['answerability']['sets_measured']}")
    return "\n".join(lines)


def _loads(raw) -> dict:
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def _posture_lookup() -> dict:
    try:
        from .registry import ComponentRegistry
        reg = ComponentRegistry()
        return {fid: reg.posture_of(fid) for fid in reg.ids("family")}
    except Exception:                                            # noqa: BLE001
        return {}
