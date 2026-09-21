"""Seed fidelity (cat-pyq-f3, 2026-09-14): a passage keeps its seed essay's
subject and kind of material.

Why this exists. A client-requested "philosophy and literature only" batch on
2026-09-14 shipped a hard set seeded by a Psyche essay on Mother Teresa and
virtue as a passage about a struck clause in a will, and another seeded by a
Psyche essay on self-care as a passage about promissory-note protest. Both
carried "Inspired by" lines naming essays they had nothing to do with.

It was not an f2 accident. Measured the same day over all 134 shipped sets
(local bge-small cosine between the first 400 words of seed and passage,
scratchpad seed_fidelity_measure.py): the sets whose topic is plainly the
seed's own subject (the Hessel, Douthat, Pavese, Bajza, Carlisle and Renaissance
pedant sets) scored 0.71-0.86, while most of the corpus sat at 0.47-0.65 with
topics like "Why Am I Left-Handed?" -> shipping containers and "Ars Notoria"
-> bell-founding. The drift is designed in: refine is told to "adapt" the
essay's territory, to move "semantically distant" from recent topics, and on a
topic collision to "choose a DIFFERENT domain". Topic shapes that ask for "a
particular machine, body, market or craft" or "a single document" then invite
the refiner to invent material the essay does not concern.

Policy f3 changes the instructions (composer), checks the plan before any
render money is spent (check_plan, one cheap call), and checks the rendered
passage for free against the calibrated embedding floor (passage_cosine).
Legacy and every earlier policy keep their behaviour.
"""
from __future__ import annotations

from . import config
from .llm import extract_json

NL = chr(10)
EXCERPT_WORDS = 400

SEED_FIDELITY_SYSTEM = """You check whether a content plan for a reading-comprehension passage
stays with its SOURCE ESSAY.

The passage must be a new argument ON THE SOURCE'S OWN SUBJECT, written as the same
kind of material. It may take its own angle, question or conclusion, and it may
narrow to one part of the essay's subject. It must not copy the essay's argument,
but that is not what you are checking.

same_subject is FALSE when the plan's central subject matter is a different subject:
an essay on the ethics of virtue that becomes a passage on probate law; an essay on a
novel that becomes one on shipping logistics; an essay's abstract pattern transplanted
onto unrelated material; the source subject kept only as a passing analogy or a
framing sentence.

same_nature is FALSE when the plan changes the kind of material: literary criticism
that becomes a technical explainer, a philosophical argument that becomes a
reconstructed legal procedure, a history that becomes a present-day policy debate.
Narrowing a criticism essay to one of the works it discusses, or a philosophy essay to
one of the concepts it argues about, keeps both.

Judge from the plan as written. When in doubt, answer false.

Respond ONLY with valid JSON, no markdown fences:
{"same_subject": true|false, "same_nature": true|false,
 "source_subject": "<max 15 words>", "plan_subject": "<max 15 words>",
 "drift": "<when either flag is false: what moved, max 30 words; otherwise ''>"}"""


def anchor_from(seed, seed_info: dict | None) -> dict:
    """The seed facts f3 stores on the plan (Blueprint.seed) so refine,
    re-refine and the plan check all read the same anchor."""
    info = seed_info or {}
    return {
        "subject": str(info.get("one_line", "") or "")[:160],
        "seed_domain": str(info.get("domain", "") or ""),
        "particulars": [str(p) for p in (info.get("concrete_particulars") or [])][:6],
    }


def anchor_block(bp, seed) -> str:
    """Refine-prompt text naming what the passage must stay with."""
    anchor = bp.seed or {}
    title = getattr(seed, "title", "") or anchor.get("title") or ""
    lines = ["SOURCE FIDELITY (hard requirement; it overrides every other content "
             "instruction, including the AVOID list):",
             "  The passage is about THIS essay's subject and is the same kind of material."]
    if title or anchor.get("subject"):
        lines.append(f"  Source: \"{title}\"" + (f" - {anchor['subject']}"
                                                  if anchor.get("subject") else ""))
    kind = [f"subject domain: {anchor['seed_domain']}"] if anchor.get("seed_domain") else []
    if getattr(bp, "seed_genre", "") and bp.seed_genre != "unknown":
        kind.append(f"kind of material: {bp.seed_genre}")
    if kind:
        lines.append("  " + "; ".join(kind))
    if anchor.get("particulars"):
        lines.append("  Particulars the essay offers: " + "; ".join(anchor["particulars"]))
    lines += [
        "  Take your own angle, question or conclusion within that subject; do not "
        "reproduce the essay's own argument.",
        "  The TOPIC SHAPE decides the angle. It never licenses moving to another "
        "subject, an analogous field, or material the essay does not concern: when the "
        "shape asks for a single object, a mechanism, an episode or a measure, find "
        "it inside the essay's subject.",
    ]
    return NL.join(lines) + NL


def _plan_text(bp) -> str:
    ts = bp.tension_system or {}
    parts = [f"TOPIC: {bp.topic}"]
    if ts.get("content_frame"):
        parts.append(f"CONTENT FRAME: {ts['content_frame']}")
    for key in ("primary", "secondary"):
        t = ts.get(key)
        if isinstance(t, dict) and t.get("axis"):
            parts.append(f"TENSION ({key}): {t.get('axis')} - {t.get('poles')}")
    briefs = [f"  para {p.para}: {p.gist}" for p in bp.movement if p.gist]
    if briefs:
        parts.append("PARAGRAPH BRIEFS:" + NL + NL.join(briefs))
    return NL.join(parts)


def check_plan(llm, ledger, bp, seed) -> tuple[bool, str]:
    """(passed, reason). Fails closed: an unparseable reply, a missing or
    non-boolean flag, or a failed call is a failed check, because a plan that
    was never checked is exactly what shipped the probate passage.
    BudgetExceeded propagates to the caller."""
    from .llm import BudgetExceeded
    anchor = bp.seed or {}
    excerpt = " ".join((getattr(seed, "text", "") or "").split()[:EXCERPT_WORDS])
    user = NL.join([
        f"SOURCE TITLE: {getattr(seed, 'title', '') or anchor.get('title', '')}",
        f"SOURCE KIND: {bp.seed_genre or 'unknown'}",
        f"SOURCE SUMMARY: {anchor.get('subject', '')}",
        "SOURCE EXCERPT:", excerpt, "",
        "CONTENT PLAN:", _plan_text(bp)])
    model, max_tokens = config.STAGE_CONFIG["seed_fidelity"][bp.tier]
    try:
        raw, truncated = llm.call(ledger, "seed_fidelity", model, max_tokens,
                                  SEED_FIDELITY_SYSTEM, user,
                                  context={"blueprint": bp, "seed": seed})
    except BudgetExceeded:
        raise
    except Exception as e:                                   # noqa: BLE001
        return False, f"check unavailable ({type(e).__name__})"
    if truncated:
        return False, "check reply truncated"
    try:
        data = extract_json(raw)
    except (ValueError, TypeError):
        return False, "check reply unparseable"
    subject, nature = data.get("same_subject"), data.get("same_nature")
    if not isinstance(subject, bool) or not isinstance(nature, bool):
        return False, "check reply missing a boolean verdict"
    if subject and nature:
        return True, ""
    moved = [name for name, ok in (("subject", subject), ("kind of material", nature)) if not ok]
    drift = str(data.get("drift", "") or "").strip()[:200]
    src, plan = data.get("source_subject", ""), data.get("plan_subject", "")
    detail = f"source is {src!r}, plan is {plan!r}" if src or plan else ""
    return False, f"{' and '.join(moved)} moved" + (f": {drift}" if drift else "") \
        + (f" ({detail})" if detail else "")


def passage_cosine(seed_text: str, passage: str) -> float | None:
    """Free local cosine on the first 400 words of each, the measurement the
    floor was calibrated on. None when the embedder is unavailable."""
    from .fingerprints import embed_text
    if not (seed_text or "").strip() or not (passage or "").strip():
        return None
    a = embed_text(" ".join(seed_text.split()[:EXCERPT_WORDS]))
    b = embed_text(" ".join(passage.split()[:EXCERPT_WORDS]))
    if a is None or b is None:
        return None
    return sum(x * y for x, y in zip(a, b))
