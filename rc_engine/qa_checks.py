"""Cheap second-opinion checks on a finished question set.

Both stages here answer the same worry from opposite ends: three of thirteen
sets shipped on 2026-08-22 came back `solver_dispute`, each on a single question
where the solver's answer was defensible and the key's was too. That is not a
solver bug — it is a question whose passage supports more than one reading.

  answerability  — asked BEFORE shipping: is each question answerable from the
                   passage alone, with exactly one defensible answer? Aimed at
                   the cause.
  solver_tiebreak — asked AFTER a dispute: read the disputed question cold and
                   say which answer the passage actually supports. Aimed at the
                   review burden.

Both are pinned to a cheap model via config.STAGE_MODEL_PINS and both degrade to
"no opinion" rather than blocking a set. Neither ever rewrites a question or
changes a key: they report, a human decides.
"""

from __future__ import annotations

from . import config
from .llm import CostLedger, extract_json

NL = chr(10)

ANSWERABILITY_SYSTEM = """You are checking reading-comprehension questions for solvability.

For each question you are given the passage and four options. Decide two things:

1. ANSWERABLE — can the question be settled using only the passage? A question
   that needs outside knowledge, or that turns on a distinction the passage never
   draws, is not answerable.
2. UNIQUE — is exactly ONE option defensible? If two options are both supportable
   on a fair reading, say so and name them. This is the common failure: a key
   that is reasonable while another option is equally reasonable.

You are NOT told which option is the intended answer. Do not try to guess it.
Judge the question as a solver would meet it.

Respond ONLY with valid JSON, no markdown fences:
{"questions": [{"q": 1, "answerable": true, "unique": true,
                "contenders": ["A"], "note": "max 25 words"}, ...]}"""

TIEBREAK_SYSTEM = """You are settling a disagreement about one reading-comprehension question.

You get the passage, the question, its four options, and two proposed answers
from different readers. You are NOT told which came from the answer key.

Decide which option the PASSAGE supports — quoting the passage's own wording
where it settles the matter. If both are genuinely defensible, say so plainly:
that verdict is more useful than a forced choice, because it means the question
needs rewriting rather than re-keying.

Respond ONLY with valid JSON, no markdown fences:
{"supported": "A" | "B" | "C" | "D" | "ambiguous",
 "evidence": "<the passage wording that settles it, max 30 words>",
 "reason": "<max 40 words>"}"""


def _fmt_options(q: dict) -> str:
    out = []
    for letter in ("A", "B", "C", "D"):
        text = ""
        opts = q.get("options")
        if isinstance(opts, dict):
            text = opts.get(letter, "")
        elif isinstance(opts, list):
            idx = "ABCD".index(letter)
            if idx < len(opts):
                o = opts[idx]
                text = o.get("text", "") if isinstance(o, dict) else str(o)
        out.append(f"  ({letter}) {text}")
    return NL.join(out)


def _system(policy, stage: str, text: str) -> str:
    """The plan's policy may append to a QA system prompt (2026-09-13: negated
    stems ask for the option that FAILS). None or legacy returns text itself."""
    return policy.system_prompt(stage, text) if policy is not None else text


def check_answerability(passage: str, questions: list[dict], llm,
                        ledger: CostLedger, tier: str = "hard",
                        policy=None) -> list[dict]:
    """Per-question answerable/unique verdicts. [] when the check cannot run."""
    if not questions:
        return []
    model, max_tokens = config.STAGE_CONFIG.get(
        "answerability", {}).get(tier, (config.PROVIDER_MODELS[
            config.ACTIVE_PROVIDER]["small"], 1600))
    blocks = []
    for i, q in enumerate(questions, start=1):
        blocks.append(f"Q{i}. {q.get('stem', '')}{NL}{_fmt_options(q)}")
    user = (f"PASSAGE:{NL}{passage.strip()}{NL}{NL}QUESTIONS:{NL}"
            + (NL + NL).join(blocks))
    try:
        text, _ = llm.call(ledger, "answerability", model, max_tokens,
                           _system(policy, "answerability", ANSWERABILITY_SYSTEM), user,
                           context={"passage": passage})
        data = extract_json(text)
    except Exception as e:
        print(f"  [answerability] check failed ({type(e).__name__}: {e})")
        return []
    rows = data.get("questions")
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "q": r.get("q"),
            "answerable": bool(r.get("answerable", True)),
            "unique": bool(r.get("unique", True)),
            "contenders": [str(x) for x in (r.get("contenders") or [])][:4],
            "note": str(r.get("note", ""))[:160],
        })
    return out


def answerability_warnings(rows: list[dict]) -> list[str]:
    """Human-facing lines for the set's notes. Warnings only — a flagged
    question still ships; it is routed to review, not withheld."""
    warnings = []
    for r in rows:
        if not r["answerable"]:
            warnings.append(
                f"Q{r['q']}: not answerable from the passage alone"
                + (f" - {r['note']}" if r["note"] else ""))
        elif not r["unique"]:
            names = ", ".join(r["contenders"]) or "more than one option"
            warnings.append(
                f"Q{r['q']}: {names} both defensible"
                + (f" - {r['note']}" if r["note"] else ""))
    return warnings


def tiebreak(passage: str, question: dict, solver_answer: str, key_answer: str,
             llm, ledger: CostLedger, tier: str = "hard", policy=None) -> dict:
    """Independent read of one disputed question.

    The two candidates are presented WITHOUT saying which is the key, so the
    check cannot simply defer to authority — the failure it exists to catch is
    a key that is merely reasonable rather than right.
    """
    model, max_tokens = config.STAGE_CONFIG.get(
        "solver_tiebreak", {}).get(tier, (config.PROVIDER_MODELS[
            config.ACTIVE_PROVIDER]["small"], 900))
    first, second = sorted([str(solver_answer), str(key_answer)])
    user = (f"PASSAGE:{NL}{passage.strip()}{NL}{NL}"
            f"QUESTION: {question.get('stem', '')}{NL}{_fmt_options(question)}{NL}{NL}"
            f"One reader answered ({first}). Another answered ({second}).")
    try:
        text, _ = llm.call(ledger, "solver_tiebreak", model, max_tokens,
                           _system(policy, "solver_tiebreak", TIEBREAK_SYSTEM), user,
                           context={"passage": passage})
        data = extract_json(text)
    except Exception as e:
        print(f"  [tiebreak] failed ({type(e).__name__}: {e})")
        return {"supported": "unchecked", "evidence": "", "reason": str(e)[:120]}
    supported = str(data.get("supported", "")).strip().upper()
    if supported not in ("A", "B", "C", "D", "AMBIGUOUS"):
        supported = "unchecked"
    return {
        "supported": supported.lower() if supported == "AMBIGUOUS" else supported,
        "evidence": str(data.get("evidence", ""))[:200],
        "reason": str(data.get("reason", ""))[:240],
    }


def tiebreak_disputes(passage: str, questions: list[dict], disputes: list[dict],
                      llm, ledger: CostLedger, tier: str = "hard",
                      policy=None) -> list[dict]:
    """Run the tiebreak over every dispute the solver raised."""
    out = []
    for d in disputes or []:
        qno = d.get("q")
        if not isinstance(qno, int) or qno < 1 or qno > len(questions):
            continue
        res = tiebreak(passage, questions[qno - 1], d.get("solver", ""),
                       d.get("key", ""), llm, ledger, tier, policy=policy)
        res["q"] = qno
        res["solver"] = d.get("solver")
        res["key"] = d.get("key")
        agrees_with = ("key" if res["supported"] == str(d.get("key", "")).upper()
                       else "solver" if res["supported"] == str(d.get("solver", "")).upper()
                       else res["supported"])
        res["agrees_with"] = agrees_with
        out.append(res)
    return out
