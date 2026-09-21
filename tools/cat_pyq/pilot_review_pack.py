"""Blinded human-review pack for a generation-policy pilot (plan section 7).

Written 2026-09-13. The pilot the plan describes is qualitative: pilot sets are
read alongside existing sets of the same tiers with their origin hidden. For each
set the reviewer checks thesis visibility, usable source detail and repeated
house voice; for each negated question, whether the key is unique and the three
other options establish the stated relation. Mock success is never a substitute.

Reads the DB read-only (SQLite mode=ro), writes only to --out, which must be
outside the repository (sets are client material):

  sets/S01.txt ...        one set per file, shuffled, RC ids and source lines removed
  review_sheet.csv        one row per set and per negated question, blank verdicts
  KEY_do_not_open.json    set -> rc_id, tier, policy (open only after review)

    python tools/cat_pyq/pilot_review_pack.py --db rc_pipeline.db --policy cat-pyq-f1 \
        --baseline 10 --out C:/Users/<you>/rc_data/pilot_review
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

SHIPPED = ("approved", "needs_review", "solver_dispute")
_STEM = re.compile(r"^Q(\d+)\.\s+(.*)$", re.M)


def _connect(db: str) -> sqlite3.Connection:
    path = os.path.abspath(db).replace("\\", "/")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def pick_sets(conn, client: str, policy: str, baseline: int, tiers, rng) -> list[dict]:
    rows = conn.execute(
        """SELECT r.rc_id, r.tier, r.rc_text, b.blueprint_json, r.created_at
           FROM rc_sets r JOIN blueprints b ON b.rc_id = r.rc_id AND b.client_id = r.client_id
           WHERE r.client_id = ? AND r.status IN (?, ?, ?)
           ORDER BY r.created_at DESC""", (client, *SHIPPED)).fetchall()
    pilot, legacy = [], {t: [] for t in tiers}
    for rc_id, tier, rc_text, bp_raw, created in rows:
        if tier not in tiers:
            continue
        version = json.loads(bp_raw or "{}").get("generation_policy") or ""
        entry = {"rc_id": rc_id, "tier": tier, "policy": version or "legacy", "rc_text": rc_text}
        if version == policy:
            pilot.append(entry)
        elif version == "":
            legacy[tier].append(entry)
    chosen = list(pilot)
    for tier in tiers:
        n_pilot = sum(1 for p in pilot if p["tier"] == tier)
        chosen += legacy[tier][:baseline if baseline else n_pilot]
    rng.shuffle(chosen)
    return chosen


def blind(rc_text: str) -> str:
    text = re.sub(r"\bRC[-_][A-Z]+[-_]\d{6}[-_]\d+\b", "[set]", rc_text or "")
    return "\n".join(l for l in text.splitlines() if not l.startswith("[Inspired by:")).strip() + "\n"


def negated_questions(rc_text: str) -> list[int]:
    from rc_engine.question_contracts import negation_count
    head = (rc_text or "").split("[ANSWER KEY", 1)[0]
    return [int(m.group(1)) for m in _STEM.finditer(head) if negation_count(m.group(2)) >= 1]


def build(db: str, out: str, policy: str, client: str, baseline: int, seed: int,
          tiers=("medium", "hard")) -> dict:
    out = os.path.abspath(out)
    if os.path.commonpath([out, ROOT]) == ROOT:
        raise SystemExit("refusing to write a review pack inside the repository")
    rng = random.Random(seed)
    conn = _connect(db)
    try:
        sets = pick_sets(conn, client, policy, baseline, tiers, rng)
    finally:
        conn.close()
    os.makedirs(os.path.join(out, "sets"), exist_ok=True)
    key, sheet = {}, []
    for n, s in enumerate(sets, start=1):
        sid = f"S{n:02d}"
        with open(os.path.join(out, "sets", f"{sid}.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(blind(s["rc_text"]))
        key[sid] = {"rc_id": s["rc_id"], "tier": s["tier"], "policy": s["policy"]}
        sheet.append({"set": sid, "question": "", "check": "thesis first visible (paragraph)", "verdict": "", "note": ""})
        sheet.append({"set": sid, "question": "", "check": "usable source detail (yes/no)", "verdict": "", "note": ""})
        sheet.append({"set": sid, "question": "", "check": "repeated house voice (yes/no)", "verdict": "", "note": ""})
        for q in negated_questions(s["rc_text"]):
            sheet.append({"set": sid, "question": f"Q{q}", "check": "negated: key unique (yes/no)", "verdict": "", "note": ""})
            sheet.append({"set": sid, "question": f"Q{q}", "check": "negated: other three meet the relation (yes/no)", "verdict": "", "note": ""})
    with open(os.path.join(out, "review_sheet.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["set", "question", "check", "verdict", "note"])
        w.writeheader()
        w.writerows(sheet)
    with open(os.path.join(out, "KEY_do_not_open.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    return {"sets": len(sets), "pilot": sum(1 for v in key.values() if v["policy"] == policy),
            "rows": len(sheet), "out": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--client", default="AA")
    ap.add_argument("--baseline", type=int, default=0,
                    help="legacy sets per tier to mix in (default: as many as the pilot has)")
    ap.add_argument("--seed", type=int, default=20260913)
    args = ap.parse_args(argv)
    print(build(args.db, args.out, args.policy, args.client, args.baseline, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
