"""Question contracts: task, polarity and what the options must establish.

Added 2026-09-13 for section 4 of 2026-09-13-cat-pyq-implementation-plan.md.
Used ONLY by generation policies with `question_contracts=True`; legacy plans
(every elite plan, and any plan without a policy) never reach this module, so
their slots, prompts and validation stay exactly as they were.

Why a contract and not a flag. The PYQ baseline (2026-09-13-cat-pyq-baseline.md)
has 35.6% of stems negated (41.5% in 2020-24) against ~7% in shipped engine
sets. The engine's only negative form was except_scan, a special slot type. A
`negated: true` boolean cannot say what the three non-key options must
establish, and that differs by task: in a negated application question they
are new scenarios that satisfy the passage's rule; in a negated weaken question
they are facts that would weaken the argument if true. So a resolved slot
carries:

  task      the underlying task (support, application, ...)
  polarity  affirmative | negative
  contract  "affirmative" or "<task>_negative"
  marker    for negative slots, the mechanism label the three non-key options
            carry instead of a distractor mechanism (kept out of trap
            histograms, like except_scan's passage_supported always was)

Staging (plan 4.1): only the support and application negatives are RELEASED.
The strengthen, weaken, reported-view and author-endorsement negatives are
specified below so their shape is reviewable, but no policy may enable them
until each has its own semantic examples and checks. Double negation is not
supported at all.

Deterministic checks here cover structure only — marker accounting, stem
polarity, quoted spans, paragraph references, keyword-set format. Whether a key
is unique and right is semantic; that stays with answerability QA, the blind
solver and human review, and solver agreement is not verification.
"""
from __future__ import annotations

import random
import re

AFFIRMATIVE = "affirmative"
NEGATIVE = "negative"

# The underlying task of each slot type that has a negated CAT form. Types not
# listed (thesis, primary_purpose, stance, keyword_set, ...) are never negated.
TASK_OF_TYPE = {
    "detail_check": "support",
    "contextual_inference": "support",
    "except_scan": "support",
    "application": "application",
    "author_vs_reported": "reported_view",
    "strengthen": "strengthen",
    "weaken": "weaken",
    "author_would_endorse": "author_endorsement",
    # 2026-09-22 (cat-pyq-f6). consistency is where CAT puts most of its
    # negation: 10 of its 12 stems (83%) are negated, against 59% for detail
    # and 48% for inference (2026-09-13-cat-pyq-baseline.md section 2).
    # argument_evaluation is deliberately absent — the exam negates 2 of its 4
    # stems, but n=4 is too thin to write a contract against, so f6 plans it
    # affirmative only.
    "consistency": "consistency",
}

# The table in plan section 4.1. `released` gates what a policy may enable.
NEGATIVE_CONTRACTS = {
    "support": {
        "released": True,
        "marker": "passage_supported",
        "key": "fails the stated support relation for a nameable reason "
               "(scope, stance, causality, level, attribution, degree)",
        "others": "each meets the support relation: stated in the passage, or "
                  "validly inferable from it where the slot is an inference",
    },
    "application": {
        "released": True,
        "marker": "rule_satisfied",
        "key": "a new scenario that violates one condition of the rule or "
               "mechanism the passage sets out",
        "others": "each a NEW scenario (not a paraphrase of the passage) that "
                  "satisfies that rule or mechanism",
    },
    # Released 2026-09-22 for cat-pyq-f6. Consistency is NOT support, which is
    # why the baseline asks for it separately: support means the passage
    # asserts the option, consistency means the passage does not rule it out.
    # An option can be consistent with the passage and never appear in it, so
    # the "others" contract here cannot be the support one.
    "consistency": {
        "released": True,
        "marker": "passage_consistent",
        "key": "contradicts something the passage states or clearly implies, "
               "so it cannot be true alongside the passage's account",
        "others": "each can be true alongside everything the passage asserts; "
                  "they need NOT be stated in the passage, and an option the "
                  "passage never addresses belongs here, not in the key",
    },
    "reported_view": {
        "released": False,
        "marker": "position_attributed",
        "key": "fails the specified person's attributed position",
        "others": "each fits that person's position as the passage reports it",
    },
    "strengthen": {
        "released": False,
        "marker": "strengthens_if_true",
        "key": "would not strengthen the specified argument even if true",
        "others": "each would strengthen it if true; the facts need not occur "
                  "in the passage",
    },
    "weaken": {
        "released": False,
        "marker": "weakens_if_true",
        "key": "would not weaken the specified argument even if true",
        "others": "each would weaken it if true; the facts need not occur in "
                  "the passage",
    },
    "author_endorsement": {
        "released": False,
        "marker": "author_consistent",
        "key": "the view least supported by the author's stated commitments",
        "others": "each more consistent with those commitments",
    },
}

CONTRACT_MARKERS = frozenset(c["marker"] for c in NEGATIVE_CONTRACTS.values())

# What a negative key may fail on. "Not mentioned" is deliberately absent: an
# option the passage never addresses fails nothing, and "not supported" is not
# "false" across question types.
FAILURE_MODES = ("scope", "stance", "causality", "level", "attribution",
                 "degree", "contradiction", "condition", "mechanism")

# Negative forms for the unreleased author-endorsement contract, specified
# separately from its affirmative forms as plan 4.2 asks. Not in any policy's
# stem pool until that contract is released under a new policy version.
STAGED_NEGATIVE_STEM_FORMS = {
    "author_would_endorse": [
        "The author is LEAST likely to agree with which one of the following views about {X}?",
        "Which one of the following practices would the author NOT endorse?",
        "All of the following are consistent with the author's position on {X}, EXCEPT:",
    ],
}


class ContractError(ValueError):
    pass


# ---- stem polarity -------------------------------------------------------------

# Case-sensitive NOT/EXCEPT: CAT prints the operator in capitals, and the
# existing affirmative library legitimately says "described but not endorsed".
_NEGATION_OPERATORS = [
    re.compile(r"\bEXCEPT\b"),
    re.compile(r"\bNOT\b"),
    re.compile(r"\bleast\b", re.I),
    re.compile(r"\bif false\b", re.I),
    re.compile(r"\bnone of\b", re.I),
]


def negation_count(stem: str) -> int:
    return sum(len(p.findall(stem or "")) for p in _NEGATION_OPERATORS)


# ---- slot resolution -------------------------------------------------------------

def authored_negative(slot: dict) -> bool:
    return slot.get("polarity") == NEGATIVE or slot["type"] == "except_scan"


def is_negative(slot: dict) -> bool:
    """Legacy slots are negative only as except_scan, exactly as before."""
    return authored_negative(slot)


def stem_key(slot: dict) -> str:
    """Stem-pool key. A legacy slot (no polarity) keys by type alone, so its
    dealing order is unchanged. except_scan's own forms are already negative."""
    if "polarity" not in slot:
        return slot["type"]
    key = slot["type"]
    if slot["polarity"] == NEGATIVE and slot["type"] != "except_scan":
        key += "/negative"
    if slot.get("variant"):
        key += "/" + slot["variant"]
    return key


def negatable(slot: dict, policy) -> bool:
    return (not authored_negative(slot)
            and TASK_OF_TYPE.get(slot["type"]) in policy.negative_tasks)


def capacity(slots: list[dict], policy) -> tuple[int, int]:
    """(authored negatives, further slots the policy could negate). Q1 is the
    set's integrator and is never negated."""
    authored = sum(1 for s in slots if authored_negative(s))
    flippable = sum(1 for s in slots[1:] if negatable(s, policy))
    return authored, flippable


def topology_supports(topology: dict, policy, tier: str | None) -> bool:
    """Can this plan carry exactly the policy's negative-slot target for the
    tier without inventing an invalid inversion? Applied as component
    eligibility, so a plan that cannot is never composed or re-picked and the
    shortfall is found before any question is bought."""
    target = policy.negative_slots_per_set.get(tier or "", 0)
    slots = topology.get("slots", [])
    authored, flippable = capacity(slots, policy)
    if any(authored_negative(s) and TASK_OF_TYPE.get(s["type"]) not in policy.negative_tasks
           for s in slots):
        return False
    return authored <= target <= authored + flippable


def resolve_slots(slots: list[dict], policy, tier: str, blueprint_id: str) -> list[dict]:
    """Annotate every slot with task/polarity/contract, negating further
    compatible slots until the tier target is met. Pre-existing negatives
    (except_scan, authored polarity) count toward it. Seeded by the blueprint
    so a plan resolves identically every time; the result is also stored on the
    blueprint before the first questions call."""
    target = policy.negative_slots_per_set.get(tier, 0)
    out = [dict(s) for s in slots]
    authored, _ = capacity(out, policy)
    candidates = [i for i, s in enumerate(out) if i > 0 and negatable(s, policy)]
    need = target - authored
    if need < 0 or need > len(candidates):
        raise ContractError(
            f"plan has {authored} negative slots and {len(candidates)} negatable "
            f"ones; cannot resolve exactly {target} for {tier}")
    flip = set(random.Random(f"{blueprint_id}:polarity").sample(candidates, need))
    variant_rng = random.Random(f"{blueprint_id}:variant")
    for i, s in enumerate(out):
        task = TASK_OF_TYPE.get(s["type"], s["type"])
        negative = authored_negative(s) or i in flip
        s["task"] = task
        s["polarity"] = NEGATIVE if negative else AFFIRMATIVE
        if negative:
            s["contract"] = f"{task}_negative"
            s["marker"] = NEGATIVE_CONTRACTS[task]["marker"]
        else:
            s["contract"] = AFFIRMATIVE
        variants = policy.slot_variants.get(s["type"])
        if variants:
            s["variant"] = variant_rng.choice(list(variants))
    return out


# ---- deterministic checks on generated questions -----------------------------------

_QUOTE_PAIRS = [re.compile(r"“([^”]+)”"),        # “...”
                re.compile(r"‘(.+?)’(?=[\s.,;:?!)—-]|$)"),  # ‘...’
                re.compile(r'"([^"]+)"')]
_SINGLE_OPEN = re.compile(r"(?:^|(?<=[\s(—:-]))'")


def _norm(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def _span_found(span: str, passage: str) -> bool:
    parts = [p.strip(" .,;:!?\"'-") for p in re.split(r"\.\.\.|…", span)]
    parts = [_norm(p) for p in parts if p.strip(" .,;:!?\"'-")]
    if not parts:
        return True
    hay = _norm(passage)
    pos = 0
    for p in parts:
        at = hay.find(p, pos)
        if at < 0 and p[:1].isalpha():          # sentence-initial capital
            alt = p[0].swapcase() + p[1:]
            at = hay.find(alt, pos)
        if at < 0:
            return False
        pos = at + len(p)
    return True


def quoted_spans(stem: str) -> list[list[str]]:
    """Candidate readings of each quotation in a stem. A single-quoted span can
    contain apostrophes, so every possible closing quote is a candidate."""
    stem = stem or ""
    out = [[m.group(1)] for pat in _QUOTE_PAIRS for m in pat.finditer(stem)]
    for m in _SINGLE_OPEN.finditer(stem):
        start = m.end()
        cands = [stem[start:j] for j in range(start + 1, len(stem))
                 if stem[j] == "'" and (j + 1 == len(stem) or not stem[j + 1].isalnum())]
        cands = [c for c in cands if len(c.split()) >= 1 and c.strip()]
        if cands:
            out.append(cands)
    return out


def missing_quotes(stem: str, passage: str) -> list[str]:
    missing = []
    for cands in quoted_spans(stem):
        if not any(_span_found(c, passage) for c in cands):
            missing.append(cands[0])
    return missing


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def paragraph_count(passage: str) -> int:
    blocks = [b for b in re.split(r"\n\s*\n", (passage or "").strip()) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b for b in (passage or "").splitlines() if b.strip()]
    return max(1, len(blocks))


def bad_paragraph_refs(stem: str, passage: str) -> list[int]:
    n = paragraph_count(passage)
    refs = [int(x) for x in re.findall(r"\bparagraph\s+(\d+)", stem or "", re.I)]
    refs += [_ORDINALS[w.lower()] for w in
             re.findall(r"\b(" + "|".join(_ORDINALS) + r")\s+paragraph\b", stem or "", re.I)]
    return [r for r in refs if not 1 <= r <= n]


_SEQUENCE_SPLIT = re.compile(r"\s*(?:→|->)\s*")
_KEYWORD_SPLIT = re.compile(r"\s*[,;]\s*")
KEYWORD_ITEMS = (4, 5)
KEYWORD_ITEM_WORDS = {"keywords": 4, "sequence": 6}


def keyword_items(text: str, variant: str) -> list[str]:
    body = (text or "").strip().rstrip(".")
    if variant == "sequence":
        parts = _SEQUENCE_SPLIT.split(body)
    else:
        if _SEQUENCE_SPLIT.search(body):
            return []
        parts = _KEYWORD_SPLIT.split(body)
    return [p.strip() for p in parts if p.strip()]


def keyword_set_problems(options: list[str], variant: str) -> list[str]:
    problems = []
    lists = [keyword_items(t, variant) for t in options]
    lo, hi = KEYWORD_ITEMS
    limit = KEYWORD_ITEM_WORDS.get(variant, 4)
    for n, items in enumerate(lists, start=1):
        if not lo <= len(items) <= hi:
            problems.append(f"option {n} has {len(items)} {variant} items, needs {lo}-{hi}")
        long = [i for i in items if len(i.split()) > limit]
        if long:
            problems.append(f"option {n} item {long[0]!r} exceeds {limit} words")
    if len({len(items) for items in lists}) > 1:
        problems.append("options do not all list the same number of items")
    keyed = [tuple(i.lower() for i in items) if variant == "sequence"
             else tuple(sorted(i.lower() for i in items)) for items in lists]
    if len(set(keyed)) < len(keyed):
        problems.append("two options list the same items")
    return problems
