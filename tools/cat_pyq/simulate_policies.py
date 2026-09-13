"""Seeded sequential mock simulations of the complete selection path, per policy.

Written 2026-09-13 for plan sections 5.2 and 7.3. A frozen-corpus replay is not
evidence of batch viability, so each run composes, renders (mock), gates and
SHIPS into its own temporary history, and every later draw sees the recency,
exclusion windows and novelty history the earlier ships created. Novelty caps
are the production values; nothing is loosened.

$0: MockLLMClient only. The mock's passages and reads are canned, so realised
prose metrics mean nothing here; what this measures is the PLANNING path —
closure categories, thesis timing, exam-form share, family/beat/component
coverage — and batch viability (yield, composition failures, novelty rejections).

    python tools/cat_pyq/simulate_policies.py --sets 40 --out report.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("RC_ENGINE_NEW_PLAN_POLICY", "")

from rc_engine import config  # noqa: E402
from rc_engine.generation_policy import get_policy  # noqa: E402
from rc_engine.history import HistoryStore  # noqa: E402
from rc_engine.llm import MockLLMClient  # noqa: E402
from rc_engine.pipeline import RCPipeline, run_batch  # noqa: E402
from rc_engine.registry import ComponentRegistry, posture_class  # noqa: E402


def closure(posture: str) -> str:
    cls = posture_class(posture)
    return "refusal" if cls == "refusal" else ("neutral" if cls == "exposition" else "committed")


def simulate(version: str, tiers: dict, seed: int) -> dict:
    config.GENERATION_POLICY_FOR_NEW_PLANS = {"medium": version, "hard": version, "elite": ""}
    reg = ComponentRegistry()
    policy = get_policy(version)
    legacy_ids = {c: set(get_policy("").eligible_ids(reg, c)) for c in reg.libraries}
    with tempfile.TemporaryDirectory() as tmp:
        history = HistoryStore(os.path.join(tmp, "sim.db"))
        pipe = RCPipeline(history, MockLLMClient(), embed=False, rng=random.Random(seed))
        results = run_batch(pipe, tiers, None, max_usd=1000.0)
        rows = history.conn.execute(
            "SELECT tier, status, blueprint_json FROM blueprints").fetchall()
        history.close()
    out = {"policy": version or "legacy", "seed": seed, "tiers": {}}
    for tier in tiers:
        attempts = [r for r in results if r.tier == tier]
        plans = [json.loads(raw) for t, s, raw in rows if t == tier]
        shipped = [json.loads(raw) for t, s, raw in rows if t == tier and s == "shipped"]
        statuses = collections.Counter(r.status for r in attempts)
        bearing = [b for b in shipped if (b.get("revelation_detail") or {}).get("timing") != "never_stated"]
        new = collections.Counter()
        for b in shipped:
            for ctype in ("family", "persona", "ending", "rhythm", "revelation", "topology"):
                if b[f"{ctype}_id"] not in legacy_ids[ctype]:
                    new[b[f"{ctype}_id"]] += 1
            if b.get("topic_shape_id") and b["topic_shape_id"] not in legacy_ids["topic_shape"]:
                new[b["topic_shape_id"]] += 1
        beats = collections.Counter(m for b in shipped for m in b.get("move_plan") or []
                                    if m not in config.RHETORICAL_MOVES)
        exam = policy.exam_derived_shapes()
        out["tiers"][tier] = {
            "attempts": len(attempts),
            "shipped": sum(1 for r in attempts if r.rc_id and r.status in config.SHIPPING_STATUSES),
            "statuses": dict(statuses),
            "composed_plans": len(plans),
            "closure_shipped": dict(collections.Counter(closure(reg.posture_of(b["family_id"]))
                                                        for b in shipped)),
            "early_thesis_share_of_bearing": (round(sum(
                1 for b in bearing if (b["revelation_detail"].get("planned_para") or 9) <= 2)
                / len(bearing), 3) if bearing else None),
            "exam_form_share": (round(sum(1 for b in shipped if reg.shape_of(b["family_id"]) in exam)
                                      / len(shipped), 3) if shipped else None),
            "distinct_families": len({b["family_id"] for b in shipped}),
            "new_components_shipped": dict(new),
            "new_beats_shipped": dict(beats),
            "negative_slots_per_set": dict(collections.Counter(
                sum(1 for s in b.get("question_slots") or [] if s.get("polarity") == "negative")
                for b in shipped)),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=40, help="sets per tier per policy")
    ap.add_argument("--policies", nargs="*", default=["", "cat-pyq-q1", "cat-pyq-s1", "cat-pyq-s2"])
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    reports = [simulate(v, {"medium": args.sets, "hard": args.sets}, args.seed)
               for v in args.policies]
    text = json.dumps(reports, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    for r in reports:
        for tier, t in r["tiers"].items():
            print(f"{r['policy']:<11} {tier:<6} shipped {t['shipped']}/{t['attempts']} "
                  f"statuses={t['statuses']} closure={t['closure_shipped']} "
                  f"early={t['early_thesis_share_of_bearing']} exam_form={t['exam_form_share']} "
                  f"families={t['distinct_families']} neg={t['negative_slots_per_set']}")
            print(f"            new components {t['new_components_shipped']}")
            print(f"            new beats {t['new_beats_shipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
