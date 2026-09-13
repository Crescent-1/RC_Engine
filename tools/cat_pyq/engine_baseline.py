"""Engine-side baseline for the CAT PYQ comparison, per client and per tier.

Written 2026-09-13 (plan section 2.4). The first analysis compared the PYQs
against one mixed-tier `health` window and against library composition. This
script opens the production DB strictly read-only (SQLite URI mode=ro; no
HistoryStore, whose constructor runs CREATE/ALTER) and reports, separately for
each tier:

  planned  - from the stored blueprint: revelation timing and planned thesis
             paragraph, paragraph count, the family's closing posture, and
             the topology's except_scan slots
  realised - from the compliance read stored with the render
             (thesis_first_visible_para, closing_posture_guess) and from the
             shipped question stems, scanned with the SAME polarity rules used
             on the PYQs (question_records.classify_polarity)

    python tools/cat_pyq/engine_baseline.py rc_pipeline.db OUT.json [--client AA]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from question_records import classify_polarity  # noqa: E402

SHIPPING = ("approved", "needs_review", "solver_dispute")  # config.SHIPPING_STATUSES


def load_components():
    comp = os.path.join(REPO, "rc_engine", "components")
    fam = {f["id"]: f for f in json.load(open(os.path.join(comp, "families.json"), encoding="utf-8"))["items"]}
    topo = {t["id"]: t for t in json.load(open(os.path.join(comp, "topologies.json"), encoding="utf-8"))["items"]}
    rev = {r["id"]: r for r in json.load(open(os.path.join(comp, "revelations.json"), encoding="utf-8"))["items"]}
    return fam, topo, rev


def stems(rc_text: str) -> list[str]:
    """Q1..Q8 stems from a shipped set's text, first occurrence of each number
    only (answer keys and explanations repeat the numbers later)."""
    out, seen = [], set()
    for m in re.finditer(r"^Q(\d+)\.\s*(.+)$", rc_text, re.M):
        n = int(m.group(1))
        if n in seen:
            break
        seen.add(n)
        out.append(m.group(2).strip())
    return out


def share(counter: Counter, n: int) -> dict:
    return {k: {"n": v, "share": round(v / n, 3) if n else None} for k, v in counter.most_common()}


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"sets": 0}
    early = lambda p: p is not None and p <= 2
    planned_para = [r["planned_para"] for r in rows]
    real_para = [r["realised_para"] for r in rows if r["realised_para"] is not None]
    q_all = [q for r in rows for q in r["stem_polarity"]]
    return {
        "sets": n,
        "planned": {
            "revelation_timing": share(Counter(r["timing"] for r in rows), n),
            "thesis_para": share(Counter(planned_para), n),
            "thesis_para_le_2": round(sum(early(p) for p in planned_para) / n, 3),
            "paragraphs": share(Counter(r["n_paras"] for r in rows), n),
            "closing_posture": share(Counter(r["posture"] for r in rows), n),
            "refusal_posture": round(sum(r["posture"].startswith("refusal") for r in rows) / n, 3),
            "except_scan_slots_per_set": round(sum(r["except_slots"] for r in rows) / n, 2),
        },
        "realised": {
            "thesis_para_reads": len(real_para),
            "thesis_para": share(Counter(real_para), len(real_para)),
            "thesis_para_le_2": round(sum(early(p) for p in real_para) / len(real_para), 3) if real_para else None,
            "closing_posture_guess": share(Counter(r["posture_guess"] for r in rows), n),
            "stems_read": len(q_all),
            "stem_polarity": share(Counter(q_all), len(q_all)),
            "negated_or_multiple_share": round(sum(p != "affirmative" for p in q_all) / len(q_all), 3) if q_all else None,
            "negated_stems_per_set": round(sum(p != "affirmative" for p in q_all) / n, 2),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out")
    ap.add_argument("--client", default="AA")
    args = ap.parse_args()

    fam, topo, rev = load_components()
    db = pathlib.Path(args.db).resolve()
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    q = f"""
        select s.rc_id, s.tier, s.status, s.rc_text, s.created_at, b.blueprint_json, b.family_id,
               b.topology_id, b.revelation_id, r.realized_json
        from rc_sets s
        join blueprints b on b.blueprint_id = s.blueprint_id
        left join rendered_passages r on r.blueprint_id = s.blueprint_id
        where s.client_id = ? and s.status in ({','.join('?' * len(SHIPPING))})
        order by s.created_at"""
    rows_by_tier: dict[str, list] = {}
    skipped = Counter()
    for rc_id, tier, status, text, created, bpj, fam_id, topo_id, rev_id, realj in con.execute(
            q, (args.client, *SHIPPING)):
        bp = json.loads(bpj)
        real = json.loads(realj) if realj else {}
        if fam_id not in fam or topo_id not in topo:
            skipped["component_missing_from_library"] += 1
            continue
        detail = bp.get("revelation_detail") or {}
        stem_list = stems(text or "")
        rows_by_tier.setdefault(tier, []).append({
            "rc_id": rc_id, "status": status, "created_at": created,
            "timing": detail.get("timing") or rev.get(rev_id, {}).get("timing", "unknown"),
            "planned_para": detail.get("planned_para"),
            "n_paras": len(bp.get("movement") or []),
            "posture": fam[fam_id]["closing_posture"],
            "except_slots": sum(s["type"] == "except_scan" for s in topo[topo_id]["slots"]),
            "realised_para": real.get("thesis_first_visible_para"),
            "posture_guess": real.get("closing_posture_guess") or "not_read",
            "stem_polarity": [classify_polarity(s)["polarity"] for s in stem_list],
        })

    try:
        rev_hash = subprocess.check_output(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", REPO, "status", "--porcelain", "rc_engine"], text=True).strip())
    except Exception:
        rev_hash, dirty = "unknown", None
    out = {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "code_revision": rev_hash, "rc_engine_uncommitted_changes": dirty,
        "client": args.client, "statuses": list(SHIPPING),
        "window": "all shipped engine sets with a stored blueprint (no trailing cut)",
        "skipped": dict(skipped),
        "note": ("planned = stored blueprint; realised = compliance read stored with the render and "
                 "polarity of shipped stems under the PYQ scanner. Paragraph 2 counts as early on both "
                 "sides, whatever the revelation label says."),
        "by_tier": {t: summarise(rows) for t, rows in sorted(rows_by_tier.items())},
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    for t, s in out["by_tier"].items():
        p, r = s["planned"], s["realised"]
        print(f"{t}: sets={s['sets']} | planned thesis<=P2 {p['thesis_para_le_2']} refusal {p['refusal_posture']} "
              f"except/set {p['except_scan_slots_per_set']} | realised thesis<=P2 {r['thesis_para_le_2']} "
              f"(reads {r['thesis_para_reads']}) negated stems {r['negated_or_multiple_share']} "
              f"({r['negated_stems_per_set']}/set, stems {r['stems_read']})")
    print("skipped", dict(skipped))


if __name__ == "__main__":
    main()
