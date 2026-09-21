"""Question-level records for the CAT PYQ baseline: task and polarity, labelled
independently.

Written 2026-09-13 (plan section 2.2). The first analysis used one first-match
regex list for both "what is asked" and "is it negated", so a stem such as
"least likely to support" could only ever be one of the two. Here the task
rules never look at negation and the polarity scan never looks at the task.
Every automatic label was then read against its stem by hand; disagreements
are recorded in OVERRIDES with a reason, and anything still ambiguous is kept
as `unresolved` rather than forced into a class.

    python tools/cat_pyq/question_records.py PRIVATE_DIR/pyq_parsed.json OUT.json [REVIEW.tsv]

OUT.json carries no stem or option text. REVIEW.tsv (stems included) must stay
outside the repository.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- task
# Ordered: the first rule whose pattern matches wins. None of these patterns
# may mention a negation operator; polarity is scanned separately below.
TASK_RULES = [
    ("keyword_set", r"sets? of (key)?words|keywords|sets? of (terms|concepts)|sequences? of words|"
                    r"-word sequence|captures the flow|mapping the main|encapsulates the issues"),
    ("relation_pair", r"odd pair|nature of the relationship between the items"),
    ("tone_stance", r"\btone\b|attitude|author is being|can best be described as being|"
                    r"author sees the rise|in the author.s opinion|author laments|author .*apprehensive"),
    ("strengthen", r"strengthen|complement the passage|supporting the arguments|support(s|ed)? the "
                   r"(author|argument|passage)|seen as supporting|supported by which other line|"
                   r"in accordance with the passage|consistent with the"),
    ("weaken", r"weaken|undermine|invalidate|negate the|contradict|inconsistent|call into question|"
               r"would make the reviewer|inappropriate"),
    ("application", r"scenario|hypothetical|most similar|analogous|akin to|closest (in meaning|to that)|"
                    r"comes closest|if a trader|if the author of the passage were to write|"
                    r"which of the following teams|product plans|new food brand|economically sound|"
                    r"would a chinese museum|following copies|examples? of human-centered|seen as similar|"
                    r"would be most successful|style of research|french ethnographer|"
                    r"can be seen in the marketing|behaviour demonstrate|most likely exacerbate|"
                    r"hypothetical netflix|conceptually closest|marketing firm must consider"),
    ("author_endorse", r"author .*(support|agree|approve|advise|endorse|in favour|disagree)|"
                       r"(most|least) likely to (support|agree|disagree|endorse)|would .*support|"
                       r"at a conference|we can assume that the author would|the author would like"),
    ("reported_view", r"critics would argue|critics of|differing views|disagree with each other|"
                      r"perception of|characterise dr|according to (rappaport|this book review|"
                      r"the romantics)|in dr\. thompson|views mentioned|essay for|critiques schiller|"
                      r"faults deneen|bradshaw|bregman|ehrlich and raven|jane jacobs|sahlins|"
                      r"steve jobs predicted|pinker|people who support|companies that digitally|"
                      r"scholars argue|opposed to making|in favour of making|similarity between"),
    ("purpose_of_part", r"purpose of|in order to|to illustrate|to show|refers? to .* to|"
                        r"mention(s|ed)? .* (to|in order)|uses? .* (to|in order|because)|"
                        r"why does the author|purpose|primary reason for why|provides the example|"
                        r"offered in the passage to|has been used in the passage to|"
                        r"additional complexity|main point does the author want"),
    ("meaning", r"means?\b|meaning|best (explains|expresses|captures|reflects|conveys|explicates) "
                r"(this|the (claim|sense|point|argument|meaning|larger|paradox)|what)|suggested by the "
                r"sentence|trying to communicate|best describes the word|the phrase|the word|the term|"
                r"in the sense|interpretations? of|refer(s)? to:?|is used:?$|dilemma|best explains this quote|"
                r"best describes the liberal|closest in meaning to the"),
    ("gist", r"central (idea|point|theme)|main (idea|argument|conclusion|point|objective|purpose|"
             r"concern|message|goal)|primary purpose of the passage|best (sums|describes what|summarises|"
             r"represents the essence)|gist|overall argument|essence|passage is (about|trying)|"
             r"what the passage is|author.s argument|fundamental conclusion|passage outlines|"
             r"the author is making the claim|what the passage is trying to do|author.s position about"),
    ("inference", r"infer|implied|implies|implication|deduce|conclu|valid|regarded as true|"
                  r"true about|holds? true|can be seen as|assum"),
    ("detail", r"according to|author (claims|lists|ascribes|faults|critiques|criticises|believes|says|"
               r"suggests|notes|identifies|questions|discusses|makes|mentions|gives|presents)|"
               r"the text|reason|why|because|following (is|are)|asserted|described|responsible|"
               r"all of the following|which one of the following"),
]

# Engine slot type each task most nearly corresponds to (None = no equivalent).
ENGINE_EQUIVALENT = {
    "gist": "thesis|primary_purpose", "keyword_set": None, "relation_pair": None,
    "tone_stance": "stance", "strengthen": "strengthen", "weaken": "weaken|undermine_thesis",
    "application": "application", "author_endorse": None, "reported_view": "author_vs_reported",
    "purpose_of_part": "evidence_function|structural_function|primary_purpose",
    "meaning": "phrase_in_context|contextual_inference", "inference": "contextual_inference",
    "detail": "detail_check", "consistency": None, "argument_evaluation": None,
    "unresolved": None,
}

# ---------------------------------------------------------------- polarity
OPERATORS = [
    ("except", r"\bexcept\b"),
    ("not", r"\bnot\b|n't\b"),
    ("cannot", r"\bcannot\b"),
    ("least", r"\bleast\b"),
    ("unlikely", r"\bunlikely\b"),
    ("none", r"\bnone of\b"),
    ("if_false", r"\bif false\b"),
    ("only_not", r"\bonly reason not\b"),
]
# Predicates that invert a relation. They count toward polarity only when an
# operator is also present ("not contradicting", "unlikely to disagree").
INVERTED_PREDICATES = r"\bdisagree|inconsistent|contradict|undermine|invalidate|incorrectly|false\b"


# Double and curly-double quotes may contain apostrophes ("It's", "doesn't");
# single-quoted spans may not start mid-word, so "author's" never opens one.
QUOTED = re.compile(r"“[^”]{8,}?”|\"[^\"]{8,}?\"|‘[^’]{8,}?’(?![A-Za-z])|"
                    r"(?<![A-Za-z])'[^']{8,}?['’](?![A-Za-z])")


def strip_quotes(stem: str) -> str:
    """Remove quoted passage text. A "doesn't" inside a quoted sentence, or
    "in order to" inside a quoted example, says nothing about what the
    question asks."""
    return QUOTED.sub(" ", stem)


def classify_task(stem: str) -> str:
    s = strip_quotes(stem).lower()
    for task, rx in TASK_RULES:
        if re.search(rx, s):
            return task
    return "unresolved"


def classify_polarity(stem: str) -> dict:
    s = strip_quotes(stem).lower()
    ops = [name for name, rx in OPERATORS if re.search(rx, s)]
    if "only_not" in ops and "not" in ops:
        ops.remove("not")
    inverted = bool(re.search(INVERTED_PREDICATES, s.replace("if false", "")))
    count = len(ops) + (1 if ops and inverted else 0)
    polarity = "affirmative" if count == 0 else "negated" if count == 1 else "multiple_negation"
    if not ops:
        mode = None
    elif "if_false" in ops:
        mode = "false_condition"
    elif {"except", "none"} <= set(ops) or ("except" in ops and ("not" in ops or "unlikely" in ops)):
        mode = "negated_except"
    elif "except" in ops or "only_not" in ops:
        mode = "except_scan"
    elif "least" in ops or "unlikely" in ops:
        mode = "least_degree"
    else:
        mode = "not_option"
    return {"polarity": polarity, "operators": ops, "relation_inverted": inverted and bool(ops),
            "negation_mode": mode, "content_negation": False}


# ---------------------------------------------------------------- overrides
# (pid, n_in_passage) -> corrected fields + reason. Filled from a full read of
# all 390 stems in REVIEW.tsv on 2026-09-13. Two task kinds exist only because
# the read found them: `consistency` (is a statement compatible with the text,
# often under "if false" / "not inconsistent" — distinct from strengthen/weaken,
# which bring in a new fact) and `argument_evaluation` (least depth added, most
# direct extension, where the author over-emphasises).
_AFF = {"polarity": "affirmative", "operators": [], "negation_mode": None,
        "relation_inverted": False, "content_negation": True}
_EXC = {"polarity": "negated", "operators": ["except"], "negation_mode": "except_scan",
        "relation_inverted": False, "content_negation": True}

OVERRIDES: dict[tuple[str, int], dict] = {
    # polarity: the "not" belongs to the content, not to the question
    ("17-1-1", 2): {**_EXC, "reason": "NOT is inside the asked content (reasons maps did NOT put north up); the operator is EXCEPT"},
    ("17-1-5", 2): {**_AFF, "reason": "asks why facilities are not fully used; no negated option relation"},
    ("18-1-2", 4): {**_AFF, "reason": "asks why India has not acknowledged its role; affirmative question"},
    ("19-2-1", 5): {**_EXC, "reason": "'has not always been a success' is content; operator EXCEPT"},
    ("20-1-1", 4): {**_AFF, "task": "inference", "reason": "'does not specify' is content; gap-filling inference"},
    ("20-1-2", 1): {**_AFF, "task": "application", "reason": "counterfactual condition on the mechanism; 'did not disappear' is content"},
    ("22-2-2", 4): {**_AFF, "task": "meaning", "reason": "referent of 'two characterisations'; 'not congruent' is content"},
    ("23-1-1", 4): {**_EXC, "reason": "'scholars who are not geographers' is content; operator EXCEPT"},
    ("23-2-1", 4): {**_EXC, "reason": "'have not caught on' is content; operator EXCEPT"},
    ("23-2-3", 1): {**_EXC, "reason": "'facts do not speak for themselves' is the claim under test; operator EXCEPT"},
    # task corrections
    ("17-1-1", 6): {"task": "inference", "reason": "comparative judgement across cases"},
    ("17-1-2", 3): {"task": "detail", "reason": "reported fact, no author-vs-reported contrast"},
    ("17-1-3", 5): {"task": "detail", "reason": "asks the reason given for a claim"},
    ("17-1-4", 3): {"task": "purpose_of_part", "reason": "why the author discusses three scientists"},
    ("17-2-2", 1): {"task": "gist", "reason": "purpose of the whole passage"},
    ("17-2-4", 2): {"task": "detail", "reason": "reason stated in the passage"},
    ("17-2-5", 1): {"task": "gist", "reason": "primary purpose of the whole passage"},
    ("18-1-1", 2): {"task": "meaning", "reason": "why a reported speaker uses a term"},
    ("18-1-1", 4): {"task": "reported_view", "reason": "what the reported researcher, not the author, would support"},
    ("18-1-3", 3): {"task": "meaning", "reason": "referent of 'lie'"},
    ("18-1-3", 5): {"task": "inference", "reason": "inferred evaluation of an organisation"},
    ("18-1-5", 1): {"task": "meaning", "reason": "decode what a metaphor stands for"},
    ("18-1-5", 3): {"task": "inference", "reason": "what an experiment points to"},
    ("18-2-2", 2): {"task": "purpose_of_part", "reason": "sorts passage evidence by what it supports (not new facts)"},
    ("18-2-3", 1): {"task": "application", "reason": "applies the account to an outside referent (a named Act)"},
    ("18-2-3", 4): {"task": "argument_evaluation", "reason": "which addition would add least depth"},
    ("18-2-4", 5): {"task": "detail", "reason": "which assumption the data challenged, as stated"},
    ("18-2-5", 1): {"task": "gist", "reason": "main purpose of the whole passage"},
    ("18-2-5", 2): {"task": "meaning", "reason": "what a study title suggests"},
    ("18-2-5", 4): {"task": "detail", "reason": "reason stated by the author"},
    ("19-1-1", 4): {"task": "detail", "reason": "reason stated in the passage"},
    ("19-1-1", 5): {"task": "purpose_of_part", "reason": "which item does not contribute to a claim (evidence role)"},
    ("19-1-2", 1): {"task": "argument_evaluation", "reason": "least depth added to the author's prediction"},
    ("19-1-5", 5): {"task": "consistency", "reason": "not contradicting the passage"},
    ("19-2-1", 2): {"task": "meaning", "reason": "referent of 'dilemma'"},
    ("19-2-1", 4): {"task": "meaning", "reason": "what a phrase implies"},
    ("19-2-2", 2): {"task": "meaning", "reason": "what critics mean by a term"},
    ("20-1-3", 3): {"task": "meaning", "reason": "what two words indicate"},
    ("20-1-4", 2): {"task": "consistency", "reason": "if-false support: a falsified statement agreeing with the passage"},
    ("20-2-3", 2): {"task": "consistency", "reason": "if-false support"},
    ("20-3-1", 4): {"task": "detail", "reason": "stated characteristic"},
    ("20-3-2", 3): {"task": "detail", "reason": "which view the passage expresses"},
    ("20-3-3", 2): {"task": "detail", "reason": "match a statement to its supporting line in the passage"},
    ("20-3-4", 1): {"task": "consistency", "reason": "if-false support"},
    ("21-1-3", 1): {"task": "inference", "reason": "inferred characteristic"},
    ("21-2-3", 4): {"task": "meaning", "reason": "explain a phrase ('contradictory pulls')"},
    ("21-2-4", 1): {"task": "argument_evaluation", "reason": "where the author over-emphasises"},
    ("21-3-1", 3): {"task": "meaning", "reason": "paraphrase of a quoted sentence"},
    ("21-3-3", 1): {"task": "tone_stance", "reason": "reviewer's evaluative position on the book"},
    ("21-3-3", 2): {"task": "detail", "reason": "stated facts EXCEPT"},
    ("21-3-4", 3): {"task": "consistency", "reason": "if-false support"},
    ("21-3-4", 4): {"task": "argument_evaluation", "reason": "most direct extension of the argument"},
    ("22-1-1", 2): {"task": "detail", "reason": "similarity between two described cases, not reported views"},
    ("22-1-2", 2): {"task": "consistency", "reason": "if-false contradiction"},
    ("22-1-2", 3): {"task": "inference", "reason": "not a possible implication of a quote"},
    ("22-1-3", 3): {"task": "consistency", "reason": "which statement contradicts the passage"},
    ("22-1-3", 4): {"task": "consistency", "reason": "statement consistent with the passage"},
    ("22-1-4", 2): {"task": "meaning", "reason": "claim made by a quoted statement"},
    ("22-1-4", 3): {"task": "consistency", "reason": "if false, in accordance with the passage, EXCEPT"},
    ("22-3-1", 1): {"task": "detail", "reason": "reasons for the author's apprehension EXCEPT"},
    ("22-3-3", 1): {"task": "author_endorse", "reason": "what the author implies scholars should do"},
    ("22-3-4", 2): {"task": "consistency", "reason": "does not contradict a quoted statement"},
    ("23-3-2", 4): {"task": "detail", "reason": "why the author endorses a view (stated reason)"},
    ("23-3-3", 4): {"task": "gist", "reason": "the central paradox the passage argues"},
    ("23-3-4", 3): {"task": "detail", "reason": "stated main difficulty"},
    ("24-1-1", 3): {"task": "meaning", "reason": "why a coined word is used"},
    ("24-1-2", 1): {"task": "gist", "reason": "point of the first paragraph"},
    ("24-1-3", 4): {"task": "consistency", "reason": "NOT inconsistent with the passage"},
    ("24-1-4", 4): {"task": "gist", "reason": "statement capturing the passage's argument"},
    ("24-2-1", 2): {"task": "detail", "reason": "reasons given by the author"},
    ("24-2-4", 3): {"task": "consistency", "reason": "if false, inconsistent with the passage"},
    ("24-3-1", 1): {"task": "detail", "reason": "reasons the author gives EXCEPT"},
    ("24-3-1", 4): {"task": "inference", "reason": "what contrasting reactions indicate"},
}

KNOWN_SOURCE_DEFECTS = {
    ("18-1-3", 5): "options D marker printed before option text in the PDF; options not split",
    ("22-3-2", 2): "PDF labels two options 'C'; options not split",
}


def build(parsed: dict) -> list[dict]:
    rows = []
    for p in parsed["passages"]:
        for q in p["questions"]:
            key = (p["pid"], q["n_in_passage"])
            rec = {"pid": p["pid"], "n": q["n_in_passage"], "page": q["page"],
                   "paper_qn": q.get("paper_qn"), "task": classify_task(q["stem"])}
            rec.update(classify_polarity(q["stem"]))
            rec["auto_task"], rec["auto_polarity"] = rec["task"], rec["polarity"]
            if key in OVERRIDES:
                ov = dict(OVERRIDES[key])
                rec["review_note"] = ov.pop("reason")
                rec.update(ov)
            rec["engine_equivalent"] = ENGINE_EQUIVALENT.get(rec["task"])
            if key in KNOWN_SOURCE_DEFECTS:
                rec["source_defect"] = KNOWN_SOURCE_DEFECTS[key]
            rows.append(rec)
    return rows


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    def dist(field, subset=rows):
        c = Counter(r[field] for r in subset)
        m = len(subset)
        return {k: {"n": v, "share": round(v / m, 3)} for k, v in c.most_common()}
    era = lambda r: "2017-2019" if r["pid"] < "20" else "2020-2024"
    out = {"denominator": n,
           "task": dist("task"), "polarity": dist("polarity"),
           "negation_mode": dist("negation_mode", [r for r in rows if r["negation_mode"]]),
           "by_era": {}, "negated_by_task": {}}
    for e in ("2017-2019", "2020-2024"):
        sub = [r for r in rows if era(r) == e]
        out["by_era"][e] = {"denominator": len(sub), "task": dist("task", sub), "polarity": dist("polarity", sub)}
    for t in sorted({r["task"] for r in rows}):
        sub = [r for r in rows if r["task"] == t]
        neg = sum(r["polarity"] != "affirmative" for r in sub)
        out["negated_by_task"][t] = {"denominator": len(sub), "negated": neg}
    out["unresolved"] = [f"{r['pid']}#{r['n']}" for r in rows if r["task"] == "unresolved"]
    out["overridden"] = len([r for r in rows if "review_note" in r])
    return out


def main():
    parsed = json.load(open(sys.argv[1], encoding="utf-8"))
    rows = build(parsed)
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out = {"source": parsed["source"], "created": "2026-09-13",
           "note": "task and polarity labelled independently; no PYQ text; page = PDF page (1-indexed)",
           "summary": summary(rows), "questions": rows}
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    if len(sys.argv) > 3:
        review = sys.argv[3]
        if os.path.abspath(review).startswith(repo):
            sys.exit("review file contains stems; write it outside the repository")
        stems = {(p["pid"], q["n_in_passage"]): q["stem"] for p in parsed["passages"] for q in p["questions"]}
        with open(review, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r['pid']}#{r['n']}\t{r['task']}\t{r['polarity']}\t{','.join(r['operators'])}\t"
                        f"{stems[(r['pid'], r['n'])]}\n")
    s = out["summary"]
    print("questions", s["denominator"], "| overridden", s["overridden"], "| unresolved", len(s["unresolved"]))
    print("task", {k: v["n"] for k, v in s["task"].items()})
    print("polarity", {k: v["n"] for k, v in s["polarity"].items()})
    print("negation_mode", {k: v["n"] for k, v in s["negation_mode"].items()})


if __name__ == "__main__":
    main()
