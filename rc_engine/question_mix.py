"""Question-type mix across shipped sets vs the CAT PYQ task shares (2026-09-14).

Operator decision the same day: a set whose question layout matches a recent
set's is coincidence, not a defect, so Gate C stopped rejecting on topology
(config.TOPOLOGY_GATE_ENFORCE). What must hold instead is the distribution:
across the corpus each question task should sit near its share of the real
exam. This module measures that; `health` prints it. $0, read-only.

Exam shares: 2026-09-13-cat-pyq-baseline.md section 2, all 390 PYQ stems
(2017-2024), hand-reviewed task labels. Engine slot types map onto those tasks;
closure_reading, decoy_escape and counterfactual_structure have no exam task
and are reported as engine-only.
"""
from __future__ import annotations

import collections
import json

EXAM_TASK_SHARES = {
    "detail": 0.246, "inference": 0.159, "meaning": 0.095, "gist": 0.082,
    "purpose_of_part": 0.079, "reported_view": 0.062, "weaken": 0.062,
    "author_endorse": 0.059, "application": 0.059, "consistency": 0.031,
    "keyword_set": 0.023, "tone_stance": 0.021, "argument_evaluation": 0.010,
    "strengthen": 0.010, "relation_pair": 0.003,
}

TASK_OF_SLOT = {
    "detail_check": "detail", "except_scan": "detail",
    "contextual_inference": "inference",
    "phrase_in_context": "meaning",
    "thesis": "gist", "primary_purpose": "gist",
    "evidence_function": "purpose_of_part", "structural_function": "purpose_of_part",
    "author_vs_reported": "reported_view",
    "weaken": "weaken", "undermine_thesis": "weaken",
    "author_would_endorse": "author_endorse",
    "application": "application",
    "keyword_set": "keyword_set",
    "stance": "tone_stance",
    "strengthen": "strengthen",
}
ENGINE_ONLY = "engine_only"

# A task is flagged when its share is under half, or over double, the exam's.
# Tasks under 3% of the exam are too rare to judge on a 30-100 set window.
FLAG_RATIO = 2.0
MIN_EXAM_SHARE = 0.03
ENGINE_ONLY_MAX = 0.15


def slot_types_of(bp_json: dict, registry) -> list[str]:
    """Stored slots when the plan froze them, else the topology's own."""
    slots = bp_json.get("question_slots") or []
    if slots:
        return [s.get("type", "") for s in slots]
    try:
        return [s["type"] for s in registry.get("topology", bp_json.get("topology_id"))["slots"]]
    except Exception:                                        # noqa: BLE001
        return []


def mix(rows, registry, tier: str | None = None) -> dict:
    """rows: iterable of blueprint_json strings (newest first). Returns
    {"sets", "questions", "tasks": {task: {"n", "share", "exam", "flag"}}}."""
    counts: collections.Counter = collections.Counter()
    sets = 0
    for raw in rows:
        try:
            d = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if tier and d.get("tier") != tier:
            continue
        types = slot_types_of(d, registry)
        if not types:
            continue
        sets += 1
        for t in types:
            counts[TASK_OF_SLOT.get(t, ENGINE_ONLY)] += 1
    total = sum(counts.values())
    tasks = {}
    for task in [*EXAM_TASK_SHARES, ENGINE_ONLY]:
        n = counts.get(task, 0)
        share = n / total if total else 0.0
        exam = EXAM_TASK_SHARES.get(task)
        flag = ""
        if total and task == ENGINE_ONLY and share > ENGINE_ONLY_MAX:
            flag = f"engine-only types above {ENGINE_ONLY_MAX:.0%}"
        elif total and exam and task not in TASK_OF_SLOT.values():
            flag = "no engine type" if exam >= MIN_EXAM_SHARE else ""
        elif total and exam and exam >= MIN_EXAM_SHARE:
            if share < exam / FLAG_RATIO:
                flag = "under"
            elif share > exam * FLAG_RATIO:
                flag = "over"
        tasks[task] = {"n": n, "share": share, "exam": exam, "flag": flag}
    return {"sets": sets, "questions": total, "tasks": tasks}


def format_mix(report: dict, label: str) -> list[str]:
    lines = [f"  {label}: {report['sets']} sets, {report['questions']} questions"]
    if not report["questions"]:
        return lines + ["    (no shipped sets)"]
    lines.append(f"    {'task':20} {'engine':>7} {'exam':>6}")
    for task, r in report["tasks"].items():
        if not r["n"] and not r["exam"]:
            continue
        exam = f"{r['exam']:.1%}" if r["exam"] is not None else "-"
        mark = f"  <- {r['flag']}" if r["flag"] else ""
        lines.append(f"    {task:20} {r['share']:7.1%} {exam:>6}{mark}")
    return lines
