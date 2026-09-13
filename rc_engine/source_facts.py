"""Source-supported facts: claims a passage may present as real, with evidence.

Added 2026-09-13 for section 6 of 2026-09-13-cat-pyq-implementation-plan.md.
Used only by policies with `source_facts=True`.

Named "source-supported", never "verified": extraction from a source proves
provenance, not truth. About 30% of CAT RC texture leans on real studies,
figures, quotations and reviewed books, and render rule 9 rightly forbids
inventing them. This module adds a narrow, checkable channel instead of
loosening that rule:

  1. the refiner proposes at most eight candidate facts, each with the exact
     supporting span from the retained seed excerpt (the same first 550 words
     refine already reads — no wider scraping), a claim, an attribution and the
     source's own qualification;
  2. `validate` keeps a candidate only if its span is found in that excerpt and
     its claim does not add numbers, drop or invert a negation, drop a hedge,
     introduce names absent from span and attribution, misplace an attribution
     or alter a quotation. These checks are STRUCTURAL. Whether a claim is
     entailed by its span, and whether the attribution is right, is semantic:
     the compliance auditor traces every factual claim in the rendered passage
     back to fact ids, and anything it cannot trace is reported;
  3. a planned beat that needs facts (NEWS_DATA_HOOK, STUDY_WALKTHROUGH,
     EXPERT_AS_SPINE, QUOTE_CLOSE) is swapped for its source-independent
     counterpart when the surviving facts cannot carry it — nothing is
     fabricated to complete a beat.

Evidence stays private: spans live on the stored blueprint (for resume) and
never in exports, logs or git. The excerpt itself is not stored; its SHA-256
digest is. A per-span word cap is a brevity rule, not a copying safeguard.
"""
from __future__ import annotations

import hashlib
import re

MAX_FACTS = 8
EXCERPT_WORDS = 550           # composer._refine_user_prompt reads exactly this much
SPAN_WORDS = (3, 40)
ATTRIBUTION_WINDOW = 300       # characters either side of the span

FACT_BEATS = {
    "NEWS_DATA_HOOK": "ABSTRACT_CLAIM_OPEN",
    "STUDY_WALKTHROUGH": "MECHANISM_EXPLAINED",
    "EXPERT_AS_SPINE": "AUTHORITY_QUOTED",
    "QUOTE_CLOSE": "BOUND_CONTINUATION",
}

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_QUOTED = re.compile(r"[\"“]([^\"”]+)[\"”]")
NEGATIONS = {"not", "no", "never", "neither", "nor", "without", "denied", "deny", "denies",
             "rejected", "rejects", "false", "unlikely", "failed", "fails", "cannot", "can't",
             "didn't", "doesn't", "isn't", "wasn't", "won't", "nothing", "none", "nobody"}
HEDGES = {"may", "might", "could", "suggest", "suggests", "suggested", "possibly", "perhaps",
          "likely", "estimated", "estimate", "estimates", "about", "around", "roughly",
          "approximately", "preliminary", "some", "claimed", "claims", "alleged", "allegedly",
          "reportedly", "appears", "appear", "according", "believed", "thought", "tentatively"}
_NOT_NAMES = {"The", "A", "An", "In", "On", "At", "Of", "For", "And", "But", "Or", "It", "This",
              "That", "These", "Those", "He", "She", "They", "We", "I", "His", "Her", "Their",
              "According", "When", "While", "After", "Before", "By", "As", "If"}


def retained_excerpt(seed_text: str | None) -> str:
    return " ".join((seed_text or "").split()[:EXCERPT_WORDS])


def digest(excerpt: str) -> str:
    return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> set[str]:
    return {w.lower().strip("'’-") for w in _WORD.findall(text or "")}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text or "")}


def _names(text: str) -> set[str]:
    """Capitalised words that are not sentence-initial function words."""
    out = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        tokens = _WORD.findall(sentence)
        for i, tok in enumerate(tokens):
            if tok[:1].isupper() and tok not in _NOT_NAMES and not (i == 0 and tok.lower() in
                                                                      _WORD_COMMON):
                out.add(tok)
    return out


_WORD_COMMON = {"the", "a", "an", "most", "many", "some", "few", "one", "two", "three", "every",
                "each", "researchers", "officials", "critics", "scientists", "studies", "data"}


def check_candidate(cand: dict, excerpt_norm: str) -> tuple[dict | None, str]:
    """(fact, "") when the candidate survives, else (None, reason)."""
    span = _norm(str(cand.get("span", "")))
    claim = _norm(str(cand.get("claim", "")))
    attribution = _norm(str(cand.get("attribution", "")))
    qualification = _norm(str(cand.get("qualification", "")))
    n_words = len(span.split())
    if not claim:
        return None, "no claim"
    if not SPAN_WORDS[0] <= n_words <= SPAN_WORDS[1]:
        return None, f"span of {n_words} words"
    start = excerpt_norm.find(span)
    if start < 0:
        return None, "span not in the retained excerpt"
    end = start + len(span)
    if not _numbers(claim) <= _numbers(span):
        return None, "claim has a figure the span does not"
    span_neg, claim_neg = bool(_words(span) & NEGATIONS), bool(_words(claim) & NEGATIONS)
    if span_neg != claim_neg:
        return None, "claim drops or inverts the span's negation"
    if _words(span) & HEDGES and not (_words(claim) & HEDGES or qualification):
        return None, "claim drops the span's qualification"
    names_ok = _names(span) | _names(attribution)
    extra = {n for n in _names(claim) if n not in names_ok and n.lower() not in _words(span)}
    if extra:
        return None, "claim introduces a name the span and attribution do not"
    if attribution:
        window = excerpt_norm[max(0, start - ATTRIBUTION_WINDOW): end + ATTRIBUTION_WINDOW]
        names = _names(attribution)
        content = {w for w in _words(attribution) if len(w) >= 4} - HEDGES
        if (any(n not in window for n in names)
                or not _numbers(attribution) <= _numbers(window)
                or (not names and content
                    and len(content & _words(window)) * 2 < len(content))):
            return None, "attribution not found near the span"
    for q in _QUOTED.findall(claim):
        if _norm(q) not in span:
            return None, "claim quotes words the span does not contain"
    return {"span": span, "claim": claim, "attribution": attribution,
            "qualification": qualification, "start": start, "end": end}, ""


def validate(candidates, seed) -> tuple[list[dict], list[str]]:
    """Validated facts (ids SF1..) and rejection reasons (no source text)."""
    excerpt = retained_excerpt(getattr(seed, "text", "") or "")
    if not excerpt or not isinstance(candidates, list):
        return [], (["no retained seed excerpt"] if not excerpt else [])
    excerpt_norm = _norm(excerpt)
    ex_digest = digest(excerpt)
    facts, reasons, seen = [], [], set()
    for cand in candidates[:MAX_FACTS]:
        if not isinstance(cand, dict):
            reasons.append("malformed candidate")
            continue
        fact, why = check_candidate(cand, excerpt_norm)
        if fact is None:
            reasons.append(why)
            continue
        if fact["span"] in seen:
            continue
        seen.add(fact["span"])
        fact.update(id=f"SF{len(facts) + 1}", source_url=getattr(seed, "url", "") or "",
                    doc_id=getattr(seed, "doc_id", "") or "", excerpt_digest=ex_digest)
        facts.append(fact)
    if len(candidates) > MAX_FACTS:
        reasons.append(f"{len(candidates) - MAX_FACTS} candidates beyond the limit of {MAX_FACTS}")
    return facts, reasons


def beat_supported(beat: str, facts: list[dict]) -> bool:
    attributed = [f for f in facts if f.get("attribution")]
    if beat == "NEWS_DATA_HOOK":
        return any(_numbers(f["claim"]) or _numbers(f["span"]) for f in facts)
    if beat == "STUDY_WALKTHROUGH":
        return bool(attributed)
    if beat == "EXPERT_AS_SPINE":
        return len(attributed) >= 2
    if beat == "QUOTE_CLOSE":
        return any(_QUOTED.search(f["span"]) for f in attributed)
    return True


def replace_unsupported_beats(move_plan: list[str], facts: list[dict],
                              forbidden: set[str]) -> tuple[list[str], list[str]]:
    """Swap fact beats the facts cannot carry for source-independent ones; a
    middle replacement that would repeat a beat or break the stance is dropped."""
    plan, notes = list(move_plan), []
    for i, beat in enumerate(list(plan)):
        if beat not in FACT_BEATS or beat_supported(beat, facts):
            continue
        sub = FACT_BEATS[beat]
        interior = 0 < i < len(plan) - 1
        if interior and (sub in plan or sub in forbidden):
            plan[i] = None
            notes.append(f"{beat} dropped (no supporting facts)")
        else:
            plan[i] = sub
            notes.append(f"{beat} -> {sub} (no supporting facts)")
    return [m for m in plan if m], notes


def facts_block(facts: list[dict]) -> str:
    if not facts:
        return ("SOURCE-SUPPORTED FACTS: none survived validation. Nothing in this passage may "
                "be presented as a real study, figure, quotation, named person or dated event "
                "beyond what rule 9 already allows.")
    lines = []
    for f in facts:
        line = f"  {f['id']}: {f['claim']}"
        if f.get("attribution"):
            line += f" [attribution: {f['attribution']}]"
        if f.get("qualification"):
            line += f" [qualification: {f['qualification']}]"
        if _QUOTED.search(f["span"]):
            line += f" [exact source wording: {f['span']}]"
        lines.append(line)
    return ("SOURCE-SUPPORTED FACTS (the only real-world studies, figures, quotations, named "
            "people or works this passage may present as real beyond rule 9's well-known "
            "references; paraphrase freely, keep each attribution and qualification, and copy "
            "quotations exactly):\n" + "\n".join(lines))


def unsupported(trace, facts: list[dict]) -> list[dict]:
    """Trace entries the auditor could not support. `common_knowledge` is rule 9's
    real-reference allowance and is not flagged."""
    known = {f["id"] for f in facts}
    out = []
    for t in trace or []:
        if not isinstance(t, dict):
            continue
        support = str(t.get("support", "")).strip().lower()
        ids = [str(x) for x in (t.get("fact_ids") or [])]
        if support == "common_knowledge":
            continue
        if support == "source_fact" and ids and set(ids) <= known and t.get("attribution_ok", True):
            continue
        out.append({"claim": str(t.get("claim", ""))[:200], "fact_ids": ids,
                    "support": support or "unsupported"})
    return out


def supported_claims(trace, facts: list[dict]) -> list[str]:
    """Claim texts traced to known facts with a correct attribution: the only
    passage text that may silence a fabricated-scholarship warning."""
    known = {f["id"] for f in facts}
    return [str(t.get("claim", "")) for t in trace or []
            if isinstance(t, dict) and str(t.get("support", "")).lower() == "source_fact"
            and t.get("fact_ids") and set(map(str, t["fact_ids"])) <= known
            and t.get("attribution_ok", True) is True]
