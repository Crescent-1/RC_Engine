"""Parse the CAT RC PYQ 2017-2024 compilation into passages and questions.

Written 2026-09-13 for the evidence baseline in
`2026-09-13-cat-pyq-implementation-plan.md` section 2. It replaces the
session-scratch pipeline behind the first analysis, which dropped page numbers
and let 2IIM's navigation strip ("Q1 Q4 Q5 Q2 Q3") inflate question counts.

The PDF is marked for personal study use. This script writes passage and
question TEXT only to the private output directory you pass, which must be
outside the repository. Derived, text-free records are produced separately by
`question_records.py`.

    python tools/cat_pyq/parse_pyq.py "C:/Users/anshu/Downloads/CAT RC PYQ 2017-2024.pdf" OUT_DIR
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys

# (year, slot, first_page, last_page) — 1-indexed pages, from the PDF's own
# contents page.
SLOTS = [
    (2017, 1, 2, 25), (2017, 2, 26, 49), (2018, 1, 50, 75), (2018, 2, 76, 104),
    (2019, 1, 105, 133), (2019, 2, 134, 162), (2020, 1, 163, 184), (2020, 2, 185, 205),
    (2020, 3, 206, 226), (2021, 1, 227, 247), (2021, 2, 248, 269), (2021, 3, 270, 290),
    (2022, 1, 291, 315), (2022, 2, 316, 340), (2022, 3, 341, 365), (2023, 1, 366, 390),
    (2023, 2, 391, 415), (2023, 3, 416, 440), (2024, 1, 441, 465), (2024, 2, 466, 490),
    (2024, 3, 491, 515),
]

BOILER = re.compile("|".join([
    r"^online\.2IIM\.com", r"^For more CAT Level", r"^CAT\s+20\d\d Question Paper",
    r"^Click", r"^To Download", r"^Download the free", r"^Original CAT 20\d\d",
    r"^CAT 20\d\d Slot\s*-\s*\d", r"^Explanation\s*Video Solution", r"^Video Solution",
    r"^Explanation$", r"^- (Rajesh|Bharathwaj|Jatin)", r"^40 hrs of free",
    r"^questions from 2IIM", r"^Questions\s*$", r"^Question\s*$", r"^Answer\s*$",
    r"^Passage\s*$", r"^Q\d(\s+Q?\d)+\s*$", r"^Click here", r"^Comprehension\s*$",
    r"^\d+\s*$", r"^Set \d+\s*$", r"^CAT 20\d\d – Verbal", r"^Text Solutions",
    r"^CAT Syllabus", r"^Access ALL Original",
]))
INTRO = re.compile(r"^(Read the passage and answer|The passage below is accompanied|"
                   r"passage, choose the best|choose the best answer|each question|question\.$|"
                   r"Based on the passage, choose|Answer the question based on|Verbal Ability|"
                   r"Verbal CAT|CAT 20\d\d .*Verbal)", re.I)
TERMINAL = re.compile(r"[.?!\"'”’)\]…:]\s*$")


def slot_of(page: int):
    for y, s, a, b in SLOTS:
        if a <= page <= b:
            return y, s
    return None


def page_lines(doc) -> list[tuple[int, str]]:
    """(page, logical line) pairs with boilerplate removed. A short line or a
    vertical gap closes a line, so paragraphs survive as separate lines."""
    out = []
    for pno in range(1, len(doc)):
        d = doc[pno].get_text("dict")
        lines = []
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if t:
                    x0, y0, x1, y1 = ln["bbox"]
                    lines.append([x0, y0, x1, y1, t])
        lines.sort(key=lambda r: (round(r[1]), r[0]))
        merged = []
        for r in lines:
            if merged and abs(merged[-1][1] - r[1]) < 2.5:
                merged[-1][2] = max(merged[-1][2], r[2])
                merged[-1][4] += " " + r[4]
            else:
                merged.append(r)
        body = [r for r in merged if not BOILER.search(r[4])]
        if not body:
            continue
        right = max(r[2] for r in body)
        lh = statistics.median([r[3] - r[1] for r in body])
        buf, prev = "", None
        for r in body:
            if prev is not None and (r[1] - prev[3]) > 0.9 * lh and buf:
                out.append((pno + 1, buf)); buf = ""
            if buf.endswith("-") and not buf.endswith(" -"):
                buf = buf[:-1] + r[4]
            else:
                buf = (buf + " " + r[4]).strip()
            if r[2] < right - 60:
                out.append((pno + 1, buf)); buf = ""
            prev = r
        if buf:
            out.append((pno + 1, buf))
    return out


def merge_paragraphs(lines: list[str]) -> list[str]:
    paras = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if paras and not TERMINAL.search(paras[-1]):
            paras[-1] += " " + ln
        else:
            paras.append(ln)
    return paras


def split_options(text: str):
    """stem, [A, B, C, D] — options located in order so 'U.S.' cannot split."""
    pos, start = [], 0
    for letter in "ABCD":
        m = re.search(r"(?:^|\s)" + letter + r"[\.\)]\s+", text[start:])
        if not m:
            return re.sub(r"\s+", " ", text).strip(), []
        pos.append((start + m.start(), start + m.end()))
        start += m.end()
    stem = re.sub(r"\s+", " ", text[:pos[0][0]]).strip()
    opts = [re.sub(r"\s+", " ", text[pos[k][1]:(pos[k + 1][0] if k < 3 else len(text))]).strip()
            for k in range(4)]
    return stem, opts


def parse(pdf_path: str) -> dict:
    import pymupdf  # local: the pure helpers above are unit-tested without it
    doc = pymupdf.open(pdf_path)
    lines = page_lines(doc)
    passages: list[dict] = []
    keys: dict[tuple, list[str]] = {}

    def new_passage(y, s, title, page):
        p = {"year": y, "slot": s, "title": title, "pages": [page], "_lines": [],
             "_qtext": [], "_qpages": [], "keys": []}
        passages.append(p)
        return p

    # ---- 2017-2021: "Passage N: title" / "Passage N: Questions" / solutions
    cur, mode, sol_n = None, None, None
    for page, t in lines:
        ys = slot_of(page)
        if not ys or ys[0] > 2021:
            continue
        y, s = ys
        m = re.match(r"^Passage\s*(\d+)\s*:\s*(.*)$", t)
        if m:
            n, rest = int(m.group(1)), m.group(2).strip()
            if re.search(r"solution", rest, re.I):
                mode = "sol" if re.search(r"detailed", rest, re.I) else "skip"
                sol_n = (y, s, n)
            elif re.match(r"^Questions?\b", rest):
                mode = "q"
            elif rest == "" and cur is not None and cur["year"] == y and cur["slot"] == s:
                mode = "q"      # 2017 S2 P5 carries a bare "Passage 5:" header
            else:
                cur = new_passage(y, s, rest, page); cur["idx"] = n; mode = "p"
            continue
        if INTRO.match(t):
            continue
        if mode == "p":
            if re.match(r"^Q\s?1\s?\.", t):
                mode = "q"
            else:
                cur["_lines"].append(t)
                if page not in cur["pages"]:
                    cur["pages"].append(page)
                continue
        if mode == "q" and cur is not None:
            cur["_qtext"].append((page, t))
        elif mode == "sol":
            k = re.match(r"^Option\s*:?\s*\(?([ABCD])\)?\b", t)
            if k:
                keys.setdefault(sol_n, []).append(k.group(1))

    # ---- 2022-2024: prose pages, then one "Qn N" page per question
    cur, mode, fresh, last_page = None, None, False, 0
    for page, t in lines:
        ys = slot_of(page)
        if not ys or ys[0] < 2022:
            continue
        y, s = ys
        if page != last_page:
            fresh, last_page = True, page
        # The instruction line must not consume the new-page flag: most
        # passages open with it, and the prose after it would otherwise be
        # read as the tail of the previous question.
        if INTRO.match(t):
            continue
        first = fresh
        fresh = False
        if re.match(r"^Qn\s*\d+", t):
            mode = "q"
            cur["_qtext"].append((page, "@@Q" + re.sub(r"\D", "", t)))
            continue
        if mode == "q" and first and not re.match(r"^[A-D][\.\)]\s", t):
            mode = None
        if mode == "q":
            cur["_qtext"].append((page, t))
            continue
        if cur is None or mode is None or cur["year"] != y or cur["slot"] != s:
            cur = new_passage(y, s, "", page); mode = "p"
        cur["_lines"].append(t)
        if page not in cur["pages"]:
            cur["pages"].append(page)

    # ---- assemble
    counter: dict[tuple, int] = {}
    for p in passages:
        k = (p["year"], p["slot"])
        counter[k] = counter.get(k, 0) + 1
        p.setdefault("idx", counter[k])
        p["pid"] = f"{str(p['year'])[2:]}-{p['slot']}-{p['idx']}"
        p["paragraphs"] = merge_paragraphs(p.pop("_lines"))
        qs = []
        if p["year"] <= 2021:
            # Question starts must run 1, 2, 3 in order and be followed by
            # stem text. The period is optional (2018 S2 P2 prints "Q4 Which",
            # 2021 S2 P1 prints "Q1 The") but the next token may not be
            # another "Q<n>", which is what the navigation strip looks like.
            joined, spans = "", []
            for page, t in p["_qtext"]:
                spans.append((len(joined), page))
                joined += " " + t
            starts, want = [], 1
            for m in re.finditer(r"(?<![A-Za-z0-9])Q\s?(\d{1,2})\s?(?:\.+\s*|\s+)(?=[A-Z\"“'‘])(?!Q\s?\d)",
                                 joined):
                if int(m.group(1)) == want:
                    starts.append(m); want += 1
            for i, m in enumerate(starts):
                end = starts[i + 1].start() if i + 1 < len(starts) else len(joined)
                body = joined[m.end():end]
                body = re.split(r"\s(?:Click to see|Click here|Passage Q\d|Detailed explanation)", body)[0]
                stem, opts = split_options(body)
                page = max(pg for off, pg in spans if off <= m.start())
                qs.append({"n_in_passage": i + 1, "page": page, "stem": stem, "options": opts})
            # 2IIM repeats solution pages, so "Option X" lines over-count. Keep
            # a key list only when it lines up one-to-one with the questions.
            ks = keys.get((p["year"], p["slot"], p["idx"]), [])
            p["keys"] = ks if len(ks) == len(qs) else []
        else:
            blocks, curb = [], None
            for page, t in p["_qtext"]:
                if t.startswith("@@Q"):
                    curb = {"qn": int(t[3:]), "page": page, "text": ""}; blocks.append(curb)
                elif curb is not None:
                    curb["text"] += " " + t
            for i, b in enumerate(blocks):
                key = re.search(r"Correct Answer:\s*([ABCD])", b["text"])
                body = re.sub(r"Correct Answer:.*$", "", b["text"])
                stem, opts = split_options(body)
                qs.append({"n_in_passage": i + 1, "paper_qn": b["qn"], "page": b["page"],
                           "stem": stem, "options": opts, "key": key.group(1) if key else None})
        p["questions"] = qs
        p.pop("_qtext"); p.pop("_qpages")
        p["words"] = sum(len(re.findall(r"[A-Za-z][A-Za-z’'\-]*", x)) for x in p["paragraphs"])
    return {"source": os.path.basename(pdf_path), "passages": passages}


def main():
    pdf, out_dir = sys.argv[1], sys.argv[2]
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if os.path.abspath(out_dir).startswith(repo):
        sys.exit("refusing to write PYQ text inside the repository; pass a private directory")
    os.makedirs(out_dir, exist_ok=True)
    data = parse(pdf)
    path = os.path.join(out_dir, "pyq_parsed.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    by_year: dict[int, list] = {}
    for p in data["passages"]:
        by_year.setdefault(p["year"], []).append(p)
    print(f"{len(data['passages'])} passages -> {path}")
    for y in sorted(by_year):
        ps = by_year[y]
        print(y, "passages", len(ps), "questions", sum(len(p["questions"]) for p in ps),
              "| per passage:", " ".join(f"{p['pid']}:{len(p['questions'])}" for p in ps))


if __name__ == "__main__":
    main()
