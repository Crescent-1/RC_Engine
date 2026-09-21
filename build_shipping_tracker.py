"""Rebuilds RC_Shipping_Tracker.xlsx: what has gone to the institute, and what
is still on the bench. Re-run any time; it only reads its sources.

"Shipped" is the UNION of two sources: sent_index.json (what was actually
emailed, indexed by build_sent_index.py -- run that first) and the week folders
under the RC delivery root. A set in EITHER place is spoken for and never
returns to the bench; the Delivery column says which it was. Ansh chose the
union on 2026-09-12 after the Week 4 drift, so that nothing can fall between
the two records again.

The client-facing list (build_client_tracker.py) stays EMAIL-ONLY on purpose:
a staged set was never in the client's hands and must not appear there.

It used to be the week folders under the RC delivery root (agreed with Ansh
2026-09-07: "consider the folder as main source"). That was wrong, and on
2026-09-12 it cost a duplicate the client caught: Week 4's email carried 10
sets against the folder's 12, and the two it never filed came back round as
bench stock. A week with no entry in sent_index.json still falls back to its
folder, which is correct for one staged but not yet mailed.

The old RC_Tracker_new.xlsx is used
only for its RC_ID/Sent_id mapping and its remarks, both carried over; its
forward *allocations* are not trusted, because the rows it wrote on 2026-07-26
for Week_5/Week_6 were plans that the 2026-08-22 house-voice re-cut replaced.

Weeks 1-4 were delivered under renamed ids (RC_ELITE_260725_01), weeks 5+ under
the raw pipeline id, so every shipped file is matched back to its export by
PASSAGE rather than by name: the pre-delivery edits touched questions only.
"""
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

PROJ = os.path.dirname(os.path.abspath(__file__))
SHIP = os.path.abspath(os.path.join(PROJ, "..", "RC"))
EXP = os.path.join(PROJ, "exported_rc_sets")
MANUAL = os.path.join(PROJ, "manual_rc_sets", "used")
OLD_TRACKER = os.path.join(PROJ, "RC_Tracker_new.xlsx")
DB = os.path.join(PROJ, "rc_pipeline.db")
GENRES = os.path.join(PROJ, "rc_genres.json")
SENT_INDEX = os.path.join(PROJ, "sent_index.json")
OUT = os.path.join(PROJ, "RC_Shipping_Tracker.xlsx")

# This workbook is single-client by design (2026-09-12): the DB reads below
# filter to the founding client, so every row on every sheet belongs to it.
# The Client column states that rather than leaving the operator to remember
# it, and exists so a second client's workbook is a change of one constant
# rather than a re-read of the whole file.
CLIENT = "AA"

# Notes and manifests that live alongside the sets but are not sets.
SKIP_NAMES = {"_MANIFEST.txt", "_SELECTED_MANIFEST.txt", "_TRIAGE.txt"}


# ------------------------------------------------------------------ parsing
def norm(s):
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'),
                 ("”", '"'), ("—", " "), ("–", " "),
                 ("…", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


# Six generations of exporter/deliverable format have to be read here, so the
# passage is located structurally rather than by any one marker: it is
# everything between the metadata header and the first question stem.
_MARKER = re.compile(
    r"^\s*(?:#+\s*)?(?:\*\*)?\[?\s*(?:PASSAGE|QUESTIONS?(?:\s*1\s*-\s*6)?"
    r"|ANSWER\s*KEY|ANSWERS|READING\s+COMPREHENSION[^\n]*)\s*\]?(?:\*\*)?:?\s*$",
    re.I)
_RULE = re.compile(r"^\s*(?:[-=*_]{3,})\s*$")
_CHATTER = re.compile(r"^\s*(?:Here(?:'s| is) the complete|RC (?:ID|Set)\s*[#:])", re.I)
# Q1 stems seen in the corpus: "Q1.", "1.", "**Q1.**", "**1.", "Q1 - Central Thesis".
_Q1 = re.compile(r"^\s*\*{0,2}(?:Q\s*)?1\s*(?:[.)]|—|–|:)", re.I)
_QSTEM = re.compile(r"^\s*\*{0,2}(?:Q\s*)?(\d{1,2})\s*(?:[.)]|—|–|:)", re.M)
_QHEAD = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?\[?\s*QUESTIONS?", re.M | re.I)


def count_questions(text):
    """How many stems the set carries. The product moved from 6Q to 8Q at
    Week_4 (2026-08-15), so this is what decides whether a bench set is
    deliverable as-is or needs two more questions written."""
    m = _QHEAD.search(text)
    body = text[m.end():] if m else text
    seen = sorted({int(x) for x in _QSTEM.findall(body) if 1 <= int(x) <= 12})
    n = 0
    for i, v in enumerate(seen, start=1):
        if v != i:
            break
        n = v
    return n


def split_passage(text):
    out, started = [], False
    for ln in text.replace("\r\n", "\n").split("\n"):
        if _Q1.match(ln):
            break
        if _MARKER.match(ln) or _RULE.match(ln) or _CHATTER.match(ln):
            continue
        if ln.lstrip().startswith("#"):
            continue
        if not started and not ln.strip():
            continue
        started = True
        out.append(ln)
    return "\n".join(out).strip()


def read_any(p):
    if p.lower().endswith(".docx"):
        return "\n".join(par.text for par in Document(p).paragraphs)
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def sim(a, b):
    """Word-level ratio. autojunk MUST stay off: on a 500-word passage the
    heuristic treats every common word as junk and collapses the score to ~0.
    Measured 2026-09-07: the Anthropocene pair scores 0.92 here, 0.01 with it on."""
    return SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def canon(rc):
    """RC-HARD-260706-0003 and RC_HARD_260706_0003 name the same set."""
    return re.sub(r"[-_]", "-", (rc or "")).upper().strip()


HDR_RE = re.compile(r"(Tier|Score|Status|Compliance F1|Novelty|Generated):\s*([^|\n]+)")


def tier_from(*texts):
    """Manual sets carry their tier only in a filename suffix (..._medium.txt)
    or in the delivered name (RC_MEDIUM_260815_01); the DB never sees them."""
    for t in texts:
        low = (t or "").lower()
        for tier in ("elite", "hard", "medium"):
            if tier in low:
                return tier
    return ""


def load_corpus(root, source):
    """rc_id -> record, keeping every exported variant of the same set.
    Variant paths are stored project-root-relative so the two corpora (exports
    and the manual folder) stay distinguishable in one column."""
    recs = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            if not fn.lower().endswith(".txt") or fn in SKIP_NAMES or fn.startswith("~$"):
                continue
            p = os.path.join(dirpath, fn)
            txt = read_any(p)
            head = txt.split("\n", 1)[0]
            m = re.match(r"RC ID:\s*([A-Za-z0-9_\-]+)", head)
            rc = m.group(1) if m else re.sub(r"_(elite|hard|medium)$", "",
                                             os.path.splitext(fn)[0], flags=re.I)
            meta = dict(HDR_RE.findall(head))
            psg = split_passage(txt)
            rel = source + "/" + os.path.relpath(p, root).replace("\\", "/")
            r = recs.setdefault(rc, {"rc_id": rc, "source": source,
                                     "variants": [], "passages": {}})
            r["variants"].append(rel)
            r["passages"][rel] = psg
            r.setdefault("nq", {})[rel] = count_questions(txt)
            if "tier" not in r or "/" not in rel:      # the root export is canonical
                tier = ((meta.get("Tier") or "").strip().lower()
                        or tier_from(rc, os.path.splitext(fn)[0]))
                r.update(tier=tier,
                         hdr_status=(meta.get("Status") or "").strip(),
                         hdr_score=(meta.get("Score") or "").strip(),
                         hdr_f1=(meta.get("Compliance F1") or "").strip(),
                         hdr_novelty=(meta.get("Novelty") or "").strip(),
                         generated=(meta.get("Generated") or "").strip()[:10],
                         words=len(psg.split()))
    for r in recs.values():
        r["variants"].sort()
    return recs


def variant_rank(path, nq=None):
    """Which file to hand over when one set was exported several times. Question
    count dominates: the 2026-08-14 8Q expansion of RC-MEDIUM-260810-0022/0024
    lives in a dated subfolder, and ranking folders first would hand over the
    superseded 6Q root export instead. Then a v2 revision beats the first cut,
    and a novelty-flagged copy is the last resort."""
    segs = path.lower().split("/")[1:]                # drop the corpus prefix
    score = 1000 * (nq or 0)
    if any(s == "v2" or s.endswith("-v2") for s in segs):
        score += 100
    if len(segs) == 1:
        score += 50                                   # canonical root export
    if "try_2" in segs:
        score -= 20
    if "flagged_similar" in segs:
        score -= 40
    return score


WEEK_DATE = re.compile(r"^Week_(\d+)_(\d{2})_(\d{2})$")


def week_date(wk):
    m = WEEK_DATE.match(wk)
    return "2026-%s-%s" % (m.group(3), m.group(2)) if m else ""


# ------------------------------------------------------------------ sources
exported = load_corpus(EXP, "exported_rc_sets")
manual = load_corpus(MANUAL, "manual_rc_sets/used")
pool = dict(exported)
for rc, rec in manual.items():
    pool.setdefault(rc, rec)

def scan_week_folder(wk):
    """The week folder's own contents: sent_id -> {passage, nq, paths}."""
    out = {}
    for dirpath, _dirs, files in os.walk(os.path.join(SHIP, wk)):
        for fn in sorted(files):
            if not fn.lower().endswith((".txt", ".docx")) or fn.startswith("~$"):
                continue
            p = os.path.join(dirpath, fn)
            sent = os.path.splitext(fn)[0]
            raw = read_any(p)
            psg = split_passage(raw)
            r = out.setdefault(sent, {"passage": psg, "nq": count_questions(raw),
                                      "paths": []})
            r["nq"] = max(r["nq"], count_questions(raw))
            r["paths"].append(os.path.relpath(p, SHIP).replace("\\", "/"))
            if len(psg) > len(r["passage"]):          # .txt and .docx of one set
                r["passage"] = psg
    for r in out.values():
        r["paths"].sort()
    return out


# What actually went out. sent_index.json (written by build_sent_index.py from
# the downloaded Sent attachments) is the authority; a week folder is only the
# fallback for a week staged but not yet emailed.
#
# The folders were the authority until 2026-09-12, when the client spotted
# "In a converted stockroom" repeating in Week 8 and was right. Week 4's email
# carried 10 sets, the folder holds 12, and only 7 are common: two emailed sets
# were never filed, so the tracker had been offering them as bench stock.
# Weeks 1-3 and 5-7 reconcile exactly, but nothing below assumes that.
sent_index = {}
if os.path.exists(SENT_INDEX):
    sent_index = json.load(open(SENT_INDEX, encoding="utf-8"))

week_dirs = {}
for _wk in sorted(os.listdir(SHIP)):
    # directories only: a mailed week also leaves a Week_8_12_09.zip beside its
    # folder, and sorted() puts the zip second, so it silently won and the whole
    # week vanished from the tracker (2026-09-12).
    _m = re.match(r"Week_(\d+)_", _wk)
    if _m and os.path.isdir(os.path.join(SHIP, _wk)):
        week_dirs[int(_m.group(1))] = _wk

shipped_files = {}
reconcile_rows = []
for num in sorted(set(week_dirs) | {int(k[1:]) for k in sent_index}):
    wk = week_dirs.get(num, "Week_%d_unfiled" % num)
    folder = scan_week_folder(wk) if num in week_dirs else {}
    rows = sent_index.get("W%02d" % num)

    def put(sent_id, rec):
        """Week 4 emailed one passage and staged another under the SAME name
        (RC_MEDIUM_260815_02), so a collision here is real data, not a bug."""
        key = (wk, sent_id)
        if key in shipped_files:
            key = (wk, sent_id + " [staged]")
        shipped_files[key] = rec

    if rows is None:
        # not emailed yet (or no archive for it): the folder is all there is
        for sent, r in sorted(folder.items()):
            put(sent, {"week": wk, "sent_id": sent, "paths": r["paths"],
                       "passage": r["passage"], "nq": r["nq"],
                       "delivery": "staged, not yet emailed"})
        continue

    # UNION of the mail and the folder (Ansh, 2026-09-12: "take union of both
    # ... so this doesn't happen in the future"). A set present in EITHER place
    # counts as spoken for, so the bench can never offer it again. The Delivery
    # column says which, so a staged-only set can still be reused deliberately.
    matched_folder = set()
    for row in rows:
        # a folder file whose passage matches is the same set, whatever it is named
        hit = max(((sim(norm(row["passage"]), norm(v["passage"])), k)
                   for k, v in folder.items()), default=(0.0, None))
        ok = hit[0] >= 0.90
        if ok:
            matched_folder.add(hit[1])
        put(row["sent_as"], {
            "week": wk, "sent_id": row["sent_as"],
            "paths": folder[hit[1]]["paths"] if ok else [],
            "passage": row["passage"], "nq": row["nq"],
            "delivery": "emailed" if ok else "emailed, never filed in the folder",
        })
        if not ok:
            reconcile_rows.append({"Week": wk, "Issue": "emailed, not in the folder",
                                   "Sent_as": row["sent_as"],
                                   "RC_ID": row["rc_id"] or "(unresolved)",
                                   "Detail": "closest folder file %s at %.2f"
                                             % (hit[1] or "-", hit[0])})
    for k, v in sorted(folder.items()):
        if k in matched_folder:
            continue
        put(k, {"week": wk, "sent_id": k, "paths": v["paths"],
                "passage": v["passage"], "nq": v["nq"],
                "delivery": "staged, never emailed"})
        reconcile_rows.append({"Week": wk, "Issue": "in the folder, never emailed",
                               "Sent_as": k, "RC_ID": "",
                               "Detail": "counted as spoken for; reuse only deliberately"})

# Live DB status beats the snapshot frozen into an export file's header.
db = {}
if os.path.exists(DB):
    conn = sqlite3.connect(DB)
    cols = ("rc_id", "tier", "status", "score", "f1", "novelty", "created", "domain")
    # Founding client only (2026-09-12): the "Available" sheet must never offer
    # another client's sets as shippable to this one. No client_id column means
    # the engine has not migrated the DB yet, and every row is the founding
    # client's.
    _rc_cols = [r[1] for r in conn.execute("PRAGMA table_info(rc_sets)")]
    has_client = "client_id" in _rc_cols
    # 2026-09-21: the similarity screen already stores its verdict per set, so
    # the tracker reads it rather than re-running a paid screen. An older DB
    # predates these columns; those rows simply show no flag.
    has_screen = "similarity_verdict" in _rc_cols
    extra = ((", similarity_verdict, similarity_note" if has_screen else "")
             + (", client_id" if has_client else ""))
    if has_screen:
        cols += ("verdict", "note")
    if has_client:
        cols += ("client",)
    for row in conn.execute("""SELECT rc_id, tier, status, average_score, compliance_f1,
                                      novelty_composite, created_at, domain"""
                            + extra + " FROM rc_sets"
                            + (" WHERE client_id = '%s'" % CLIENT if has_client else "")):
        db[row[0]] = dict(zip(cols, row))
    conn.close()

def screen_cells(meta):
    """(Flag, Flag_Against, Flag_Remark) from the stored similarity screen.

    2026-09-21. The screen is the last gate before a set leaves the building:
    GREEN means its argument moves are as alike as two real exam passages
    normally are, RED means a reviewer should look before it ships again.
    Only RED carries the against/remark pair, because that is the only case
    the operator has to act on — a green nearest-neighbour is noise in a
    tracker column and would bury the six rows that matter.

    A set generated before the screen existed, or one it could not reach, has
    no verdict at all; that reads as blank rather than as a pass.
    """
    verdict = (meta.get("verdict") or "").strip().lower()
    if verdict not in ("red", "green"):
        return "", "", ""
    if verdict == "green":
        return "GREEN", "", ""
    try:
        note = json.loads(meta.get("note") or "{}")
    except (ValueError, TypeError):
        note = {}
    against = note.get("nearest") or ""
    # The model's own sentence on WHY, with the shared moves behind it. Both
    # are already in the note; neither is recomputed here.
    reason = (note.get("reason") or "").strip()
    shared = [s for s in (note.get("shared") or []) if s]
    if shared:
        reason = (reason + "  Shared: " + "; ".join(shared)).strip()
    return "RED", against, reason


# Subject-matter genre, assigned by reading each passage (see rc_genres.json).
# Nothing in the engine carries this: domain is a topic line, families are
# rhetorical arcs, TIER_SEED_GENRES lists seed publications.
genre_map = {}
if os.path.exists(GENRES):
    genre_map = json.load(open(GENRES, encoding="utf-8")).get("genres", {})
genre_by_canon = {canon(k): v for k, v in genre_map.items()}

old_rows, sent2rc, remarks, blocked = [], {}, {}, {}
if os.path.exists(OLD_TRACKER):
    ows = load_workbook(OLD_TRACKER)["RC Tracker"]
    ohdr = [c.value for c in ows[1]]
    for row in ows.iter_rows(min_row=2, values_only=True):
        d = {h: ("" if v is None else str(v).strip()) for h, v in zip(ohdr, row)}
        old_rows.append(d)
        if d.get("Sent_id") and d.get("RC_ID"):
            sent2rc[d["Sent_id"]] = d["RC_ID"]
        if d.get("Remarks_user"):
            remarks[canon(d["RC_ID"])] = d["Remarks_user"]
            if d.get("Sent_id"):
                remarks.setdefault(canon(d["Sent_id"]), d["Remarks_user"])
        # A row Ansh marked not-sent is a verdict, not a gap: these are the
        # length-bias failures and the truncated legacy files from 2026-07-08.
        # Their export headers still say "approved" from before that audit, so
        # without this the bench would offer them back as ready to ship.
        if d.get("is_sent") != "Y":
            for key in (d.get("RC_ID"), d.get("Sent_id")):
                if key:
                    blocked.setdefault(canon(key), d.get("Remarks_user", ""))

# ----------------------------------------------------------------- matching
key_index = defaultdict(set)
for rc, rec in pool.items():
    for v in rec["passages"].values():
        if v:
            key_index[norm(v)[:300]].add(rc)

shipped = []
for (wk, sent), s in sorted(shipped_files.items(),
                            key=lambda kv: (week_date(kv[0][0]), kv[0][1])):
    tgt = norm(s["passage"])
    hit = key_index.get(tgt[:300])
    if hit:
        rc, method = sorted(hit)[0], "passage exact"
    else:
        score, rc = max(((sim(tgt, norm(v)), k) for k, rec in pool.items()
                         for v in rec["passages"].values() if v), default=(0.0, ""))
        method = "passage fuzzy %.2f" % score if score >= 0.55 else "UNMATCHED"
        if score < 0.55:
            rc = ""
    src = pool.get(rc, {})
    meta = db.get(rc, {})
    tracked = sent2rc.get(sent, "")
    note = []
    if tracked and canon(tracked) != canon(rc):
        note.append("old tracker filed this as %s" % tracked)
    if method.startswith("passage fuzzy"):
        note.append("passage edited after export")
    variants = sorted(src.get("variants", []),
                      key=lambda v: variant_rank(v, src.get("nq", {}).get(v)),
                      reverse=True)
    _flag = screen_cells(meta)
    shipped.append({
        "Week": wk,
        "Send_Date": week_date(wk),
        "Sent_id": sent,
        "Qs": s["nq"],
        # an emailed set with no export resolves to no RC_ID; key it by the
        # delivered name instead so it is not left blank (RC_MEDIUM_260815_02)
        "Genre": genre_by_canon.get(canon(rc)) or genre_by_canon.get(canon(sent), ""),
        "RC_ID": rc,
        # the delivered name is authoritative for tier: it is how the set was sold
        "Tier": ((meta.get("tier") or "").lower() or tier_from(sent, src.get("tier", ""))),
        "Origin": ("Pipeline" if rc in db else
                   "Manual" if "MANUAL" in rc.upper() else
                   "Legacy" if rc else ""),
        "Status": meta.get("status") or src.get("hdr_status", ""),
        "Score": meta.get("score") or src.get("hdr_score", ""),
        "Flag": _flag[0], "Flag_Against": _flag[1], "Flag_Remark": _flag[2],
        "Client": meta.get("client") or CLIENT,
        "Match": method,
        "Export_File": variants[0] if variants else "",
        "Delivered_Files": " | ".join(s["paths"]),
        "Old_Tracker_ID": tracked,
        "Delivery": s.get("delivery", "emailed"),
        "Notes": "; ".join(note) or remarks.get(canon(rc), "")[:200],
    })

shipped_ids = {canon(r["RC_ID"]) for r in shipped if r["RC_ID"]}
shipped_ids |= {canon(r["Old_Tracker_ID"]) for r in shipped if r["Old_Tracker_ID"]}

available = []
for rc, rec in sorted(exported.items()):
    if canon(rc) in shipped_ids:
        continue
    meta = db.get(rc, {})
    # legacy/manual sets never went through the judge, so they have no status
    status = meta.get("status") or rec.get("hdr_status", "") or "unrated"
    variants = sorted(rec["variants"],
                      key=lambda v: variant_rank(v, rec["nq"].get(v)),
                      reverse=True)
    only_flagged = all("flagged_similar" in v.split("/") for v in rec["variants"])
    reject = blocked.get(canon(rc))
    note = []
    if reject is not None:
        note.append("BLOCKED - you marked this not-sent: " + (reject[:160] or "no reason recorded"))
    if rc not in db:
        note.append("legacy/manual export, not in the engine DB")
    if only_flagged:
        note.append("only ever exported into flagged_similar (novelty-flagged)")
    if len(variants) > 1:
        note.append("%d exported variants; preferred one listed first" % len(variants))
    if remarks.get(canon(rc)) and reject is None:
        note.append(remarks[canon(rc)][:200])
    nq = rec["nq"].get(variants[0], 0) if variants else 0
    _flag = screen_cells(meta)
    available.append({
        "RC_ID": rc,
        "Genre": genre_by_canon.get(canon(rc), ""),
        "Qs": nq,
        "To_8Q": "" if nq >= 8 else ("+%d questions" % (8 - nq) if nq else "unknown"),
        "Tier": (meta.get("tier") or "").lower() or tier_from(rec.get("tier", ""), rc,
                                                              variants[0] if variants else ""),
        "Status": "blocked" if reject is not None else status,
        "Ship_Ready": ("Y" if status == "approved" and not only_flagged
                       and reject is None else "N"),
        "Score": meta.get("score") or rec.get("hdr_score", ""),
        "Compliance_F1": meta.get("f1") or rec.get("hdr_f1", ""),
        "Novelty": meta.get("novelty") or rec.get("hdr_novelty", ""),
        "Flag": _flag[0], "Flag_Against": _flag[1], "Flag_Remark": _flag[2],
        "Client": meta.get("client") or CLIENT,
        "Generated": (meta.get("created") or "")[:10] or rec.get("generated", ""),
        "Words": rec.get("words", ""),
        "Best_File": variants[0] if variants else "",
        "All_Variants": " | ".join(variants),
        "Full_Path": os.path.join(PROJ, variants[0].replace("/", os.sep)) if variants else "",
        "Notes": "; ".join(note),
    })

# Old tracker rows with no live delivered file: the Week_5/Week_6 plan that the
# 2026-08-22 re-cut replaced, plus the legacy sets it recorded as broken.
live_sent = {canon(s["Sent_id"]) for s in shipped}
reconcile = []
for d in old_rows:
    if d.get("Sent_id") and canon(d["Sent_id"]) in live_sent:
        continue
    rc = d.get("RC_ID", "")
    if d.get("is_sent") == "Y":
        where = ("returned to the available bench" if canon(rc) not in shipped_ids
                 else "the set itself shipped under another id")
        resolution = "no file in the live week folder; " + where
    else:
        resolution = "was already marked not-sent; still not sent"
    reconcile.append({
        "Old_RC_ID": rc,
        "Old_Sent_id": d.get("Sent_id", ""),
        "Old_Level": d.get("Level", ""),
        "Old_is_sent": d.get("is_sent", ""),
        "Old_send_period": d.get("send_period", ""),
        "Resolution": resolution,
        "Old_Remarks": d.get("Remarks_user", "")[:400],
    })

# ------------------------------------------------------------------ writing
HDR_FILL = PatternFill("solid", start_color="1F4E78")
HDR_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
BODY = Font(name="Arial", size=10)
FILLS = {"approved": PatternFill("solid", start_color="C6EFCE"),
         "needs_review": PatternFill("solid", start_color="FFEB9C"),
         "solver_dispute": PatternFill("solid", start_color="FFC7CE"),
         "rejected_novelty": PatternFill("solid", start_color="F2F2F2"),
         "blocked": PatternFill("solid", start_color="FFC7CE"),
         "unrated": PatternFill("solid", start_color="F2F2F2")}
YES = PatternFill("solid", start_color="C6EFCE")
# The similarity screen's own two states. Deliberately louder than the status
# fills: a RED set is the one thing on this sheet that must not ship unread.
VERDICT_FILL = {"RED": PatternFill("solid", start_color="FFC7CE"),
                "GREEN": PatternFill("solid", start_color="C6EFCE")}


def sheet(wb, title, rows, cols, widths, status_col=None, flag_col=None,
          verdict_col=None, first=False):
    ws = wb.active if first else wb.create_sheet(title)
    ws.title = title
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    for i in range(1, len(cols) + 1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2, max_row=len(rows) + 1):
        for c in row:
            c.font = BODY
        if status_col:
            c = row[cols.index(status_col)]
            if c.value in FILLS:
                c.fill = FILLS[c.value]
        if flag_col:
            c = row[cols.index(flag_col)]
            if str(c.value).upper() == "Y":
                c.fill = YES
        if verdict_col:
            c = row[cols.index(verdict_col)]
            if c.value in VERDICT_FILL:
                c.fill = VERDICT_FILL[c.value]
                c.alignment = Alignment(horizontal="center")
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"
    last = ws.cell(row=1, column=len(cols)).column_letter
    ws.auto_filter.ref = "A1:%s%d" % (last, len(rows) + 1)
    return ws


wb = Workbook()
sheet(wb, "Shipped", shipped,
      ["Week", "Send_Date", "Sent_id", "Qs", "RC_ID", "Tier", "Genre", "Origin",
       "Client", "Status", "Score", "Flag", "Flag_Against", "Flag_Remark",
       "Match", "Delivery", "Export_File", "Delivered_Files",
       "Old_Tracker_ID", "Notes"],
      [15, 12, 24, 5, 24, 8, 26, 10, 8, 15, 7, 7, 24, 80,
       18, 34, 44, 60, 22, 46],
      status_col="Status", verdict_col="Flag", first=True)

# Most useful first: what you can send today, then the best of the review queue.
STATUS_ORDER = {"approved": 0, "needs_review": 1, "solver_dispute": 2,
                "rejected_novelty": 3, "unrated": 4, "blocked": 5}


def bench_key(a):
    try:
        score = -float(a["Score"])
    except (TypeError, ValueError):
        score = 0.0
    return (a["Ship_Ready"] != "Y", STATUS_ORDER.get(a["Status"], 9),
            a["Tier"], score, a["RC_ID"])


available.sort(key=bench_key)

sheet(wb, "Available", available,
      ["RC_ID", "Tier", "Genre", "Client", "Status", "Ship_Ready", "Qs", "To_8Q",
       "Score", "Compliance_F1", "Novelty", "Flag", "Flag_Against",
       "Flag_Remark", "Generated", "Words", "Best_File",
       "Full_Path", "All_Variants", "Notes"],
      [24, 8, 26, 8, 16, 11, 5, 14, 7, 13, 9, 7, 24, 80, 11, 7, 46, 74, 70, 46],
      status_col="Status", flag_col="Ship_Ready", verdict_col="Flag")

weeks = []
for wk in sorted({s["Week"] for s in shipped}, key=week_date):
    rows = [s for s in shipped if s["Week"] == wk]
    tiers = Counter(s["Tier"] for s in rows)
    origins = Counter(s["Origin"] for s in rows)
    weeks.append({
        "Week": wk, "Send_Date": week_date(wk), "Sets": len(rows),
        "Elite": tiers["elite"], "Hard": tiers["hard"], "Medium": tiers["medium"],
        "Pipeline": origins["Pipeline"], "Manual": origins["Manual"],
        "Legacy": origins["Legacy"],
        "Naming": ("renamed (RC_TIER_YYMMDD_NN)" if rows[0]["Sent_id"].count("_") >= 3
                   else "pipeline id"),
    })
sheet(wb, "By Week", weeks,
      ["Week", "Send_Date", "Sets", "Elite", "Hard", "Medium", "Pipeline", "Manual",
       "Legacy", "Naming"],
      [15, 12, 7, 7, 7, 8, 10, 8, 8, 30])

# Genre mix: what has gone out against what is left, so a thin bucket on the
# bench is visible before it becomes a repetitive week.
gseen = sorted({r["Genre"] for r in shipped + available if r["Genre"]})
gmix = []
for g in gseen:
    sh = [r for r in shipped if r["Genre"] == g]
    bn = [a for a in available if a["Genre"] == g]
    ready = [a for a in bn if a["Ship_Ready"] == "Y"]
    gmix.append({
        "Genre": g, "Shipped": len(sh), "On_Bench": len(bn), "Bench_Ready": len(ready),
        "Bench_Elite": sum(1 for a in bn if a["Tier"] == "elite"),
        "Bench_Hard": sum(1 for a in bn if a["Tier"] == "hard"),
        "Bench_Medium": sum(1 for a in bn if a["Tier"] == "medium"),
        "Share_Shipped": round(100.0 * len(sh) / max(len(shipped), 1), 1),
    })
gmix.sort(key=lambda r: (-r["Shipped"], r["Genre"]))
gmix.append({"Genre": "TOTAL", "Shipped": sum(r["Shipped"] for r in gmix),
             "On_Bench": sum(r["On_Bench"] for r in gmix),
             "Bench_Ready": sum(r["Bench_Ready"] for r in gmix),
             "Bench_Elite": sum(r["Bench_Elite"] for r in gmix),
             "Bench_Hard": sum(r["Bench_Hard"] for r in gmix),
             "Bench_Medium": sum(r["Bench_Medium"] for r in gmix), "Share_Shipped": ""})
sheet(wb, "Genre Mix", gmix,
      ["Genre", "Shipped", "On_Bench", "Bench_Ready", "Bench_Elite", "Bench_Hard",
       "Bench_Medium", "Share_Shipped"],
      [28, 9, 10, 12, 12, 11, 13, 14])

# Where the delivery folders disagree with the mail. Empty is the healthy state.
sheet(wb, "Folder vs Sent", reconcile_rows,
      ["Week", "Issue", "Sent_as", "RC_ID", "Detail"],
      [16, 30, 26, 24, 52])

sheet(wb, "Reconciliation", reconcile,
      ["Old_RC_ID", "Old_Sent_id", "Old_Level", "Old_is_sent", "Old_send_period",
       "Resolution", "Old_Remarks"],
      [24, 24, 8, 11, 16, 62, 70])

ws = wb.create_sheet("Summary")
ws["A1"] = "RC Shipping Tracker"
ws["A1"].font = Font(name="Arial", bold=True, size=13)
ws["A2"] = ("Shipped = the live week folders under " + SHIP + ". Each delivered file is "
            "matched back to its export by passage, because only questions were edited "
            "before delivery.")
ws["A2"].font = Font(name="Arial", size=9, italic=True)
av = Counter(a["Status"] for a in available)
ready = sum(1 for a in available if a["Ship_Ready"] == "Y")
lines = [
    ("Weeks delivered", len(weeks)),
    ("Sets shipped", len(shipped)),
    ("  matched exactly by passage", sum(1 for s in shipped if s["Match"] == "passage exact")),
    ("  matched fuzzily (passage edited)",
     sum(1 for s in shipped if s["Match"].startswith("passage fuzzy"))),
    ("  UNMATCHED to any export", sum(1 for s in shipped if not s["RC_ID"])),
    ("", ""),
    ("Exported sets on the bench (not shipped)", len(available)),
    ("  approved", av.get("approved", 0)),
    ("    of which ready to ship", ready),
    ("    of which exist only as a flagged_similar copy",
     av.get("approved", 0) - ready),
    ("  needs_review", av.get("needs_review", 0)),
    ("  solver_dispute", av.get("solver_dispute", 0)),
    ("  rejected_novelty", av.get("rejected_novelty", 0)),
    ("  blocked (you marked not-sent earlier)", av.get("blocked", 0)),
    ("  unrated legacy/manual", av.get("unrated", 0)),
    ("", ""),
    ("Bench already at 8Q (deliverable as-is)",
     sum(1 for a in available if a["Qs"] >= 8)),
    ("Bench still at 6Q (needs +2 questions)",
     sum(1 for a in available if 0 < a["Qs"] < 8)),
    ("  of those, approved and otherwise ready",
     sum(1 for a in available if 0 < a["Qs"] < 8 and a["Ship_Ready"] == "Y")),
    ("", ""),
    ("Bench: elite", sum(1 for a in available if a["Tier"] == "elite")),
    ("Bench: hard", sum(1 for a in available if a["Tier"] == "hard")),
    ("Bench: medium", sum(1 for a in available if a["Tier"] == "medium")),
    ("", ""),
    ("Weeks of runway at 10/week (approved only)", round(ready / 10.0, 1)),
    ("Weeks of runway at 10/week (approved + needs_review)",
     round((ready + av.get("needs_review", 0)) / 10.0, 1)),
    ("", ""),
    # The similarity screen, read back from the DB rather than re-run. A RED
    # bench set is the one that costs money to discover late: it looks
    # shippable on every other column.
    ("Bench flagged RED by the similarity screen",
     sum(1 for a in available if a.get("Flag") == "RED")),
    ("  of those, otherwise ready to ship",
     sum(1 for a in available if a.get("Flag") == "RED" and a["Ship_Ready"] == "Y")),
    ("Bench passed GREEN", sum(1 for a in available if a.get("Flag") == "GREEN")),
    ("Bench never screened (predates the screen)",
     sum(1 for a in available if not a.get("Flag"))),
    ("Already-shipped sets that were RED",
     sum(1 for r in shipped if r.get("Flag") == "RED")),
    ("", ""),
    ("Old tracker rows with no delivered file", len(reconcile)),
    ("Folder-vs-mail discrepancies", len(reconcile_rows)),
    ("  emailed", sum(1 for r in shipped if r["Delivery"] == "emailed")),
    ("  emailed, never filed", sum(1 for r in shipped
                                   if r["Delivery"] == "emailed, never filed in the folder")),
    ("  staged, never emailed", sum(1 for r in shipped
                                    if r["Delivery"] == "staged, never emailed")),
    ("  staged, not yet emailed", sum(1 for r in shipped
                                      if r["Delivery"] == "staged, not yet emailed")),
]
for i, (label, val) in enumerate(lines, start=4):
    ws.cell(row=i, column=1, value=label).font = BODY
    if val != "":
        ws.cell(row=i, column=2, value=val).font = Font(name="Arial", size=10, bold=True)
ws.column_dimensions["A"].width = 50
ws.column_dimensions["B"].width = 12

wb.save(OUT)
print("Saved %s" % OUT)
print("  shipped %d across %d weeks | bench %d (%d approved) | %d old rows reconciled"
      % (len(shipped), len(weeks), len(available), ready, len(reconcile)))
nogenre = [r["RC_ID"] for r in shipped + available if r["RC_ID"] and not r["Genre"]]
if nogenre:
    print("  %d set(s) missing a genre in rc_genres.json: %s"
          % (len(nogenre), sorted(set(nogenre))))
unmatched = [s for s in shipped if not s["RC_ID"]]
if unmatched:
    print("  WARNING unmatched shipped sets:",
          [(s["Week"], s["Sent_id"]) for s in unmatched])
