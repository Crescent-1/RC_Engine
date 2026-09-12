"""Indexes what was ACTUALLY emailed to the client, into sent_index.json.

Why this exists (2026-09-12). The shipping tracker was built on the rule that
the week folders under ..\\RC are the record of what went out (agreed 2026-09-07).
For Week 4 that rule is false, and it cost a duplicate: the client spotted
"In a converted stockroom" in Week 8 and was right -- RC-MEDIUM-260811-0027 had
already gone out on 15 Aug. It was invisible because the Week 4 email and the
Week_4_15_08 folder disagree:

    actually sent   10 files (3 elite / 3 hard / 4 medium)
    folder          12 files
    both            7

RC_MEDIUM_260811_0025 and _0027 were emailed but never filed, so the tracker
counted them as bench stock. A third file, emailed as RC_MEDIUM_260815_02,
holds a different passage from the folder's file of that name.

So the authority is the sent-mail archive: attachments downloaded out of Sent
and dropped in SENT_ARCHIVE, one folder or .zip per week. Weeks 1-3 and 5-7
reconcile exactly against the folders; only Week 4 drifted, but nothing here
assumes that -- every week is re-derived from the mail.

Run this before build_shipping_tracker.py whenever a new week is sent. Weeks
with no entry in the archive fall back to the delivery folder, which is the
right behaviour for a week that has just been staged but not yet mailed.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from difflib import SequenceMatcher

PROJ = os.path.dirname(os.path.abspath(__file__))
SENT_ARCHIVE = r"C:\Users\anshu\OneDrive\Desktop\Actual email shipped"
OUT = os.path.join(PROJ, "sent_index.json")

# Reuse the tracker's parsers. It is a script, not a module: importing it would
# rerun the whole build, so execute only its definitions.
_SRC = os.path.join(PROJ, "build_shipping_tracker.py")
_MARKER = "# ------------------------------------------------------------------ sources"
_ns = {"__file__": _SRC, "__name__": "_bst_defs"}
with open(_SRC, encoding="utf-8") as _f:
    exec(compile(_f.read().split(_MARKER)[0], _SRC, "exec"), _ns)
norm, split_passage, read_any = _ns["norm"], _ns["split_passage"], _ns["read_any"]
count_questions, load_corpus = _ns["count_questions"], _ns["load_corpus"]
EXP, MANUAL, SHIP = _ns["EXP"], _ns["MANUAL"], _ns["SHIP"]

WEEK_RE = re.compile(r"[Ww]eek[_ ]?(\d+)")


def week_key(name):
    """'week_4_15-08', 'Week_6_29_08 (1).zip' -> 4, 6. The archive names are
    whatever the mail client produced, so only the number is trusted."""
    m = WEEK_RE.search(name)
    return int(m.group(1)) if m else None


def stage_archive(dst):
    """Copy folders and expand zips into one flat staging tree: week -> dir."""
    weeks = {}
    if not os.path.isdir(SENT_ARCHIVE):
        return weeks
    for entry in sorted(os.listdir(SENT_ARCHIVE)):
        src = os.path.join(SENT_ARCHIVE, entry)
        wk = week_key(entry)
        if wk is None:
            print("  [skip] cannot read a week number from %r" % entry)
            continue
        out = os.path.join(dst, "W%02d" % wk)
        os.makedirs(out, exist_ok=True)
        if entry.lower().endswith(".zip"):
            with zipfile.ZipFile(src) as z:
                z.extractall(out)
        elif os.path.isdir(src):
            for dp, _d, fs in os.walk(src):
                rel = os.path.relpath(dp, src)
                tgt = os.path.join(out, rel) if rel != "." else out
                os.makedirs(tgt, exist_ok=True)
                for fn in fs:
                    shutil.copy2(os.path.join(dp, fn), os.path.join(tgt, fn))
        else:
            continue
        weeks[wk] = out
    return weeks


def resolve(passage, pool):
    """Delivered file -> the export/manual RC_ID it came from, by passage.
    Names cannot do this: weeks 1-4 renamed on ship, and the Week 8 revision
    edited four passages, so only a fuzzy comparison holds."""
    tgt = norm(passage).split()
    best = (0.0, None)
    for rc, variants in pool.items():
        for v in variants:
            r = SequenceMatcher(None, tgt, v, autojunk=False).ratio()
            if r > best[0]:
                best = (r, rc)
    return best


def main():
    pool = {}
    for rc, rec in load_corpus(EXP, "exported_rc_sets").items():
        pool.setdefault(rc, []).extend(norm(v).split() for v in rec["passages"].values() if v)
    for rc, rec in load_corpus(MANUAL, "manual_rc_sets/used").items():
        pool.setdefault(rc, []).extend(norm(v).split() for v in rec["passages"].values() if v)
    print("resolution pool: %d source sets" % len(pool))

    tmp = tempfile.mkdtemp(prefix="sentidx_")
    try:
        weeks = stage_archive(tmp)
        print("weeks found in the archive: %s" % sorted(weeks))
        index = {}
        for wk, root in sorted(weeks.items()):
            seen = {}
            for dp, _d, fs in os.walk(root):
                for fn in sorted(fs):
                    if not fn.lower().endswith((".txt", ".docx")) or fn.startswith("~$"):
                        continue
                    raw = read_any(os.path.join(dp, fn))
                    psg = split_passage(raw)
                    name = os.path.splitext(fn)[0]
                    # one week can carry .txt and .docx of the same set
                    prev = seen.get(name)
                    if prev is None or len(psg) > len(prev["passage"]):
                        seen[name] = {"sent_as": name, "passage": psg,
                                      "nq": count_questions(raw)}
            rows = []
            for name, rec in sorted(seen.items()):
                score, rc = resolve(rec["passage"], pool)
                rows.append({"sent_as": name,
                             "rc_id": rc if score >= 0.55 else None,
                             "match": round(score, 3),
                             "nq": rec["nq"],
                             "words": len(rec["passage"].split()),
                             "passage": rec["passage"]})
            index["W%02d" % wk] = rows
            unres = [r["sent_as"] for r in rows if not r["rc_id"]]
            print("  W%02d: %2d sets emailed%s" % (wk, len(rows),
                  ("  UNRESOLVED: " + ", ".join(unres)) if unres else ""))
        json.dump(index, open(OUT, "w", encoding="utf-8"), indent=1)
        print("\nwrote %s" % OUT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
