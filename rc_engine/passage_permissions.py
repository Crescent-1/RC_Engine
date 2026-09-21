"""Per-plan permissions: where a plan may go beyond the house render rules.

Added 2026-09-13 for section 5.3 of 2026-09-13-cat-pyq-implementation-plan.md.
Used only by policies with `passage_permissions=True`; a legacy plan never
reaches this module, so render rules 7, 8 and 11 apply to it in full.

The PYQ corpus carries prose the render contract forbids outright: closing
prescriptions (9% of passages), an explicit hypothetical case (12%), counted
kinds and reasons (16%), a scholarly introduction fixing its own scope (7 of
90). Allowing any of these globally would widen elite and put an exception in
one prompt while another still bans it. So a grant is derived from the PLAN,
once, here, and the same grants reach:

  - the renderer (system rules rewritten to defer to a PERMISSIONS block, and
    the block itself in the contract),
  - the compliance auditor (the same block, and a report of devices the
    passage used WITHOUT a grant, which become repair directives),
  - texture_report (the same grants decide which deterministic warnings fire).

"No moralizing" is never granted, and neither is fabricated scholarship.
"""
from __future__ import annotations

import re

BOUNDED_PRESCRIPTION = "bounded_prescription"
HYPOTHETICAL_CASE = "hypothetical_case"
CONTENT_ENUMERATION = "content_enumeration"
SCOPE_SETTING = "scope_setting"
REPORTED_VOICE = "reported_voice"

GRANT_TEXT = {
    BOUNDED_PRESCRIPTION:
        "the FINAL paragraph may say what should be done or which norm should change, "
        "stated plainly and bounded by what the passage has shown. No exhortation, no "
        "moral lecture, and nowhere before the final paragraph.",
    HYPOTHETICAL_CASE:
        "ONE explicitly hypothetical case (\"suppose\", \"imagine\", \"consider a...\") "
        "detailed enough to test the claim on. It is never presented as a real event, and "
        "it is the only place the reader may be addressed.",
    CONTENT_ENUMERATION:
        "the passage may announce a number of kinds, reasons, factors or stages OF ITS "
        "SUBJECT and work through them in order. Counting the subject is content; "
        "announcing the passage's own argumentative moves (\"the first objection\", "
        "\"having shown\") is still signposting and still forbidden.",
    SCOPE_SETTING:
        "the passage may say, once, what its inquiry covers and why, the way a scholarly "
        "introduction does. It may not narrate its own progress elsewhere.",
    REPORTED_VOICE:
        "a reported writer's, work's or school's position is stated in its own terms and "
        "kept audibly separate from the author's: attribute every claim of the reported "
        "position, and give the verdict in the author's own voice. The reported work or "
        "writer is described, not named, unless the contract supplies source facts that "
        "name it.",
}

# Device labels the compliance auditor reports, and the grant that permits each.
DEVICE_GRANT = {
    "prescription": BOUNDED_PRESCRIPTION,
    "reader_address": HYPOTHETICAL_CASE,
    "hypothetical": HYPOTHETICAL_CASE,
    "enumeration": CONTENT_ENUMERATION,
    "scope_statement": SCOPE_SETTING,
    "self_signposting": None,          # never granted
}

# Plan elements that carry a grant.
_BEAT_GRANTS = {
    "PRESCRIPTION_STATED": BOUNDED_PRESCRIPTION,
    "HYPOTHETICAL_CASE": HYPOTHETICAL_CASE,
    "ENUMERATED_SET": CONTENT_ENUMERATION,
    "REPORTED_POSITION": REPORTED_VOICE,
    "SPLIT_VERDICT": REPORTED_VOICE,
    # section 6 beats: planned only under source-facts policies
    "EXPERT_AS_SPINE": REPORTED_VOICE,
    "STUDY_WALKTHROUGH": REPORTED_VOICE,
    "QUOTE_CLOSE": REPORTED_VOICE,
}
_POSTURE_GRANTS = {"affirmation_endorsed": BOUNDED_PRESCRIPTION}


def grants_for(bp, registry) -> list[str]:
    """Sorted grant ids for this plan: from planned beats, the family's own
    `permits` field, and the closing posture."""
    out = {_BEAT_GRANTS[m] for m in (bp.move_plan or []) if m in _BEAT_GRANTS}
    try:
        family = registry.get("family", bp.family_id)
    except Exception:                                            # noqa: BLE001
        family = {}
    out |= set(family.get("permits") or [])
    posture = family.get("closing_posture", "")
    if posture in _POSTURE_GRANTS:
        out.add(_POSTURE_GRANTS[posture])
    return sorted(g for g in out if g in GRANT_TEXT)


def permissions_block(grants: list[str]) -> str:
    if not grants:
        return ("PERMISSIONS FOR THIS PASSAGE: none. Rules 7, 8 and 11 apply in full: no "
                "prescriptions, no reader address or hypothetical case, no enumeration "
                "announcements, no statement of scope.")
    lines = "\n".join(f"  - {g}: {GRANT_TEXT[g]}" for g in grants)
    return ("PERMISSIONS FOR THIS PASSAGE (exactly these, nothing more; every other "
            "prohibition in rules 7, 8 and 11 stands):\n" + lines)


def unpermitted(devices, grants: list[str]) -> list[str]:
    """Devices the auditor found that no grant covers, in reported order."""
    have = set(grants)
    out = []
    for d in devices or []:
        d = str(d).strip().lower()
        if d not in DEVICE_GRANT or d in out:
            continue
        grant = DEVICE_GRANT[d]
        if grant is None or grant not in have:
            out.append(d)
    return out


# ---- deterministic texture checks ------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_HYPOTHETICAL = re.compile(r"\b(?:suppose|imagine|picture a|consider an? )\b", re.I)
_READER = re.compile(r"\b(?:you|your|yourself)\b", re.I)
_PRESCRIPTION = re.compile(
    r"\b(?:should|ought to|must (?:be|now|instead|stop|start)|needs? to be|"
    r"it is time to|we must|policymakers must)\b", re.I)
_ENUMERATION = re.compile(
    r"\b(?:two|three|four|five|six|several) (?:kinds|types|sorts|forms|reasons|factors|"
    r"stages|channels|ways|varieties|classes)\b", re.I)
_SCOPE = re.compile(r"\b(?:in this|the present) (?:essay|inquiry|study|book|chapter|account)\b",
                    re.I)


def texture_findings(passage: str, grants: list[str]) -> list[str]:
    """Warnings for devices used without a grant (contract plans only)."""
    have = set(grants)
    paras = [p for p in re.split(r"\n\s*\n", passage or "") if p.strip()]
    warnings = []
    sentences = [s for s in _SENTENCE.split(passage or "") if s.strip()]
    hypo = [s for s in sentences if _HYPOTHETICAL.search(s)]
    allowed_hypo = hypo[:1] if HYPOTHETICAL_CASE in have else []
    for s in hypo:
        if s not in allowed_hypo:
            warnings.append(f"unpermitted hypothetical case - {_HYPOTHETICAL.search(s).group(0)!r}")
    for s in sentences:
        m = _READER.search(s)
        if m and s not in allowed_hypo:
            warnings.append(f"unpermitted reader address - {m.group(0)!r}")
            break
    final = paras[-1] if paras else ""
    for i, p in enumerate(paras):
        m = _PRESCRIPTION.search(p)
        if not m:
            continue
        if BOUNDED_PRESCRIPTION in have and p is final:
            continue
        where = "before the final paragraph" if BOUNDED_PRESCRIPTION in have else "not granted"
        warnings.append(f"unpermitted prescription ({where}) - {m.group(0)!r}")
        break
    m = _ENUMERATION.search(passage or "")
    if m and CONTENT_ENUMERATION not in have:
        warnings.append(f"unpermitted enumeration announcement - {m.group(0)!r}")
    m = _SCOPE.search(passage or "")
    if m and SCOPE_SETTING not in have:
        warnings.append(f"unpermitted scope statement - {m.group(0)!r}")
    return warnings
