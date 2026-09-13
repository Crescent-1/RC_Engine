"""Assemble the corrected CAT PYQ evidence baseline (plan section 2).

Written 2026-09-13. Inputs: the private parse (parse_pyq.py), the question
records (question_records.py) and the engine baseline (engine_baseline.py).
Output: one text-free JSON in the repository root.

Thesis rubric, applied identically to the PYQs here and to engine passages in
the stored compliance reads:
  kind          explicit  - the central claim is stated as a proposition
                implicit  - recoverable from the passage but never stated as one
                none      - descriptive survey or report that advances no central claim
  first_visible paragraph where a reader could first state the central claim
  fully_stated  paragraph where it is stated in full
"Early" means first_visible <= 2 on both sides, whatever a revelation label says.
Where a trustworthy 2017-21 answer key exists for a gist question, the key
anchored the claim (17-2-2, 17-2-3). One reader; see the report for limits.

    python tools/cat_pyq/build_baseline.py PRIVATE/pyq_parsed.json QREC.json ENGINE.json OUT.json
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter

# pid: (kind, first_visible, fully_stated)
RUBRIC = {
    "17-1-1": ("explicit", 2, 2), "17-1-2": ("explicit", 3, 5), "17-1-3": ("explicit", 3, 5),
    "17-1-4": ("implicit", 2, 3), "17-1-5": ("explicit", 1, 1), "17-2-1": ("explicit", 1, 1),
    "17-2-2": ("explicit", 3, 5), "17-2-3": ("explicit", 2, 5), "17-2-4": ("explicit", 1, 1),
    "17-2-5": ("explicit", 1, 2), "18-1-1": ("explicit", 2, 2), "18-1-2": ("explicit", 1, 3),
    "18-1-3": ("explicit", 1, 2), "18-1-4": ("explicit", 3, 5), "18-1-5": ("explicit", 2, 2),
    "18-2-1": ("explicit", 1, 1), "18-2-2": ("explicit", 4, 5), "18-2-3": ("explicit", 1, 2),
    "18-2-4": ("explicit", 2, 2), "18-2-5": ("explicit", 2, 5), "19-1-1": ("explicit", 1, 2),
    "19-1-2": ("explicit", 2, 3), "19-1-3": ("explicit", 1, 2), "19-1-4": ("explicit", 1, 1),
    "19-1-5": ("none", None, None), "19-2-1": ("explicit", 3, 3), "19-2-2": ("none", None, None),
    "19-2-3": ("explicit", 1, 1), "19-2-4": ("explicit", 3, 5), "19-2-5": ("explicit", 1, 2),
    "20-1-1": ("none", None, None), "20-1-2": ("explicit", 4, 5), "20-1-3": ("explicit", 1, 1),
    "20-1-4": ("explicit", 1, 4), "20-2-1": ("explicit", 1, 1), "20-2-2": ("implicit", 2, 5),
    "20-2-3": ("explicit", 1, 1), "20-2-4": ("none", None, None), "20-3-1": ("none", None, None),
    "20-3-2": ("explicit", 4, 6), "20-3-3": ("explicit", 1, 1), "20-3-4": ("explicit", 1, 1),
    "21-1-1": ("explicit", 1, 5), "21-1-2": ("explicit", 1, 1), "21-1-3": ("explicit", 1, 3),
    "21-1-4": ("explicit", 1, 3), "21-2-1": ("implicit", 3, 3), "21-2-2": ("explicit", 4, 5),
    "21-2-3": ("explicit", 1, 1), "21-2-4": ("explicit", 1, 2), "21-3-1": ("explicit", 1, 2),
    "21-3-2": ("explicit", 1, 1), "21-3-3": ("explicit", 1, 4), "21-3-4": ("explicit", 2, 2),
    "22-1-1": ("explicit", 1, 4), "22-1-2": ("explicit", 1, 3), "22-1-3": ("explicit", 1, 3),
    "22-1-4": ("none", None, None), "22-2-1": ("none", None, None), "22-2-2": ("explicit", 1, 2),
    "22-2-3": ("explicit", 1, 2), "22-2-4": ("explicit", 1, 2), "22-3-1": ("explicit", 1, 1),
    "22-3-2": ("explicit", 1, 4), "22-3-3": ("explicit", 1, 2), "22-3-4": ("explicit", 1, 4),
    "23-1-1": ("explicit", 1, 3), "23-1-2": ("explicit", 1, 2), "23-1-3": ("explicit", 3, 4),
    "23-1-4": ("explicit", 1, 3), "23-2-1": ("explicit", 4, 5), "23-2-2": ("explicit", 2, 4),
    "23-2-3": ("explicit", 1, 3), "23-2-4": ("explicit", 5, 5), "23-3-1": ("explicit", 1, 1),
    "23-3-2": ("explicit", 3, 6), "23-3-3": ("explicit", 3, 4), "23-3-4": ("explicit", 3, 3),
    "24-1-1": ("implicit", 3, 5), "24-1-2": ("explicit", 1, 5), "24-1-3": ("explicit", 1, 5),
    "24-1-4": ("explicit", 2, 5), "24-2-1": ("explicit", 3, 8), "24-2-2": ("explicit", 3, 5),
    "24-2-3": ("explicit", 1, 1), "24-2-4": ("none", None, None), "24-3-1": ("explicit", 1, 2),
    "24-3-2": ("explicit", 4, 5), "24-3-3": ("explicit", 2, 3), "24-3-4": ("explicit", 1, 1),
}


def dist(values) -> dict:
    c = Counter(values)
    n = sum(c.values())
    return {str(k): {"n": v, "share": round(v / n, 3)} for k, v in sorted(c.items(), key=lambda kv: str(kv[0]))}


def main():
    parsed = json.load(open(sys.argv[1], encoding="utf-8"))
    qrec = json.load(open(sys.argv[2], encoding="utf-8"))
    engine = json.load(open(sys.argv[3], encoding="utf-8"))
    assert set(RUBRIC) == {p["pid"] for p in parsed["passages"]}, "rubric must cover exactly the 90 passages"

    passages = []
    for p in parsed["passages"]:
        kind, fv, fs = RUBRIC[p["pid"]]
        n = len(p["paragraphs"])
        passages.append({
            "pid": p["pid"], "year": p["year"], "slot": p["slot"], "pages": p["pages"],
            "words": p["words"], "paragraphs": n,
            "para_words": [len(x.split()) for x in p["paragraphs"]],
            "questions": len(p["questions"]),
            "thesis_kind": kind, "thesis_first_visible": fv, "thesis_fully_stated": fs,
            "thesis_first_visible_relative": round(fv / n, 2) if fv else None,
        })

    bearing = [x for x in passages if x["thesis_kind"] != "none"]
    era = lambda x: "2017-2019" if x["year"] <= 2019 else "2020-2024"
    per_year = {}
    for y in sorted({x["year"] for x in passages}):
        ps = [x for x in passages if x["year"] == y]
        per_year[y] = {"passages": len(ps), "questions": sum(x["questions"] for x in ps),
                       "questions_per_passage": round(sum(x["questions"] for x in ps) / len(ps), 2),
                       "median_words": statistics.median(x["words"] for x in ps),
                       "median_paragraphs": statistics.median(x["paragraphs"] for x in ps)}

    summary = {
        "passages": len(passages), "questions": sum(x["questions"] for x in passages),
        "per_year": per_year,
        "thesis_kind": dist(x["thesis_kind"] for x in passages),
        "thesis_first_visible_among_bearing": dist(x["thesis_first_visible"] for x in bearing),
        "thesis_first_visible_le_2": {
            "all_passages_denominator": len(passages),
            "share_of_all": round(sum(x["thesis_first_visible"] is not None and x["thesis_first_visible"] <= 2
                                      for x in passages) / len(passages), 3),
            "thesis_bearing_denominator": len(bearing),
            "share_of_bearing": round(sum(x["thesis_first_visible"] <= 2 for x in bearing) / len(bearing), 3),
            "by_era_share_of_bearing": {
                e: round(sum(x["thesis_first_visible"] <= 2 for x in bearing if era(x) == e)
                         / len([x for x in bearing if era(x) == e]), 3)
                for e in ("2017-2019", "2020-2024")},
        },
        "paragraph_count": dist(x["paragraphs"] for x in passages),
    }
    out = {
        "title": "CAT RC PYQ 2017-2024 evidence baseline (corrected)",
        "created": "2026-09-13",
        "supersedes_numbers_in": ["2026-09-13-cat-pyq-engine-analysis.md", "2026-09-13-cat-pyq-findings-handoff.md",
                                  "2026-09-13-cat-pyq-labels.json"],
        "source": parsed["source"], "text_included": False,
        "rubric": __doc__.split("Thesis rubric")[1].split("python tools")[0].strip(),
        "pyq": {"summary": summary, "questions_summary": qrec["summary"],
                "passages": passages, "questions": qrec["questions"]},
        "engine": engine,
    }
    with open(sys.argv[4], "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: summary[k] for k in ("passages", "questions", "thesis_kind", "thesis_first_visible_le_2")},
                     indent=1))
    print("per year", {y: (v["questions"], v["questions_per_passage"]) for y, v in per_year.items()})


if __name__ == "__main__":
    main()
