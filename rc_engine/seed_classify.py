"""Stage 0 — what KIND of source essay this seed is.

The last place the house voice was living. Every arc, move, stance and register
in this engine was varied over months while ~60 stored topics stayed one kind of
question: 14 opened "Whether...", 11 "Why...", and essentially all were
two-sided conceptual disputes about a social practice. Two causes, both
upstream of anything the renderer controls:

  - every RSS feed was the same genre (the idea-essay), so every seed was one;
  - the refine schema REQUIRED a tension_system with two poles, so even a
    technical seed was converted into a dispute before a word was written.

This stage reads the seed before any paid stage runs and says what it actually
is. That answer then does four things: constrains which topic shapes are
eligible, applies genre-saturation pressure the same way arc shapes get it,
rotates a seed whose genre is over-used (for a tenth of a cent, before the
$0.02 refine), and tells refine what it is looking at.
"""

from __future__ import annotations

from . import config
from .llm import CostLedger, extract_json

NL = chr(10)

CLASSIFY_SYSTEM = """You are cataloguing a source essay so a downstream writer knows what
kind of material it is.

Report what the piece IS, not what it could be turned into. A reported story about a
hospital is reportage even if it raises philosophical questions; a physics explainer is
a technical explainer even if it ends on a reflection.

GENRES (choose exactly one):
  conceptual_essay    — argues a position about how something should be understood
  narrative_history   — reconstructs events, people and periods
  technical_explainer — explains how something works, staying with the mechanism
  reportage           — reports what is happening now, from sources and scenes
  investigation       — pursues a specific question through documents and interviews
  criticism           — reads one work, artist, or body of work closely
  biography           — follows one person's life or career
  practice_account    — describes how work is actually done by practitioners
  analysis            — quantitative or institutional analysis of a situation
  legal_analysis      — reasons about law, rules, or rulings

Respond ONLY with valid JSON, no markdown fences:
{
  "genre": "<one label above>",
  "domain": "science|technology|history|arts|social|medicine|law|economics|philosophy",
  "concrete_particulars": ["<named person, place, object, date or case in the piece>", ...max 6],
  "bipolar_dispute_available": true|false,
  "one_line": "<what the piece is about, max 20 words>"
}
bipolar_dispute_available is true ONLY if the piece contains a genuine disagreement
between two positions that serious people actually hold. A topic that merely has
complications is not a dispute."""

FALLBACK = {
    "genre": "conceptual_essay",
    "domain": "social",
    "concrete_particulars": [],
    "bipolar_dispute_available": True,
    "one_line": "",
}


# 2026-09-14, revised after the first paid f3 batch. The first wording ("exists
# within the essay's subject ... When unsure, leave it out") returned one to
# three shapes per essay, TS01 in every list; six of nine plans drew TS01, four
# attempts died on novelty and all four shipped sets screened red for the same
# two-camps architecture. Subject fidelity needs the passage to stay in the
# essay's SUBJECT, not to use only material the essay itself happens to contain.
SHAPE_MENU_SYSTEM = """CARRIABLE TOPIC SHAPES: the menu below lists passage shapes. The passage
will stay on this essay's OWN subject (its field, the works, people, ideas or practice it
is about), but it does not have to reuse the essay's argument or examples. A shape is
carriable when a writer could meet it with material that belongs to that subject: a
text, episode, practice, measure, study, school, concept or dispute from the essay's
field, whether or not the essay itself mentions it. For a philosophy essay on virtue, a
famous text or case in ethics can be the object read closely, or the view a field
abandoned. For a review of a novel, the history of the form or the practice of
translation can carry an episode or a practice.

A shape is NOT carriable when meeting it would require leaving the subject for another
one (a legal procedure for a virtue-ethics essay, a machine for a literary review).

Decide EVERY shape on the menu separately, with one of three verdicts:
  "natural"  -- the essay's subject readily supplies what the shape needs; a writer
                would reach for it without strain
  "possible" -- it can be done within the subject, but the material is thin or
                the fit is a stretch
  "no"       -- meeting it would mean leaving the subject, or inventing material
                the subject does not have
Most essays have a few natural shapes, several possible ones and several noes.

Add to your JSON one verdict per menu id:
"shape_verdicts": {"TS01": "natural", "TS02": "no", "TS03": "possible", ...}

MENU:
"""
# Revised again the same day, measured on 5 real essays with luna: asked for a
# LIST it returned 2-3 shapes for 4 of 5 (a list invites naming the obvious
# few); asked true/false per id it returned 14 and 16 for two history pieces
# (TS03 "How It Works" for a fishermen history) and nothing for a third. Three
# levels let the draw prefer natural fits and fall back to possible ones.
MIN_NATURAL_SHAPES = 3


def carriable_from(natural: list[str], possible: list[str]) -> list[str]:
    """Natural fits first; possible ones join only when the natural list is
    short, so a narrow essay still gets a real choice of shapes."""
    if len(natural) >= MIN_NATURAL_SHAPES:
        return list(natural)
    return list(natural) + [p for p in possible if p not in natural]


def shape_menu(registry, shape_ids: list[str]) -> str:
    """One line per shape: id, name and the topic form it asks for."""
    lines = []
    for sid in shape_ids:
        s = registry.get("topic_shape", sid)
        lines.append(f"  {sid} {s['name']}: {s['topic_form']}")
    return NL.join(lines)


_DOMAIN_LINE = '"domain": "science|technology|history|arts|social|medicine|law|economics|philosophy",'
# Seed-store labels (2026-09-14) add literature: operators select subjects by
# domain, and "arts" lumped a review of a novel in with a gallery show.
STORE_DOMAIN_LINE = ('"domain": "science|technology|history|arts|literature|social|medicine|'
                     'law|economics|philosophy",')


def classify_seed(seed, llm, ledger: CostLedger | None = None,
                  tier: str = "hard", menu: str = "", store: bool = False) -> dict:
    """Read the seed and report its genre. Falls back to the historical
    assumption (a conceptual essay with a dispute available) so a classifier
    outage degrades to today's behaviour rather than blocking a batch.

    menu (seed-fidelity plans, 2026-09-14): a shape_menu; the reply then also
    lists the shapes the essay's own material can carry ("carriable_shapes").
    Without it the call is exactly the legacy call."""
    text = (getattr(seed, "text", "") or "").strip()
    title = getattr(seed, "title", "") or ""
    if not text:
        return dict(FALLBACK, genre="unknown")
    model, max_tokens = config.STAGE_CONFIG["seed_classify"][tier]
    excerpt = " ".join(text.split()[:600])
    user = f"TITLE: {title}{NL}{NL}EXCERPT:{NL}{excerpt}"
    ledger = ledger or CostLedger(budget_usd=config.SEED_CLASSIFY_MAX_USD)
    base = CLASSIFY_SYSTEM.replace(_DOMAIN_LINE, STORE_DOMAIN_LINE) if store else CLASSIFY_SYSTEM
    system = base + (NL + NL + SHAPE_MENU_SYSTEM + menu if menu else "")
    context = {"seed": seed, "shape_menu": menu} if menu else {"seed": seed}
    try:
        raw, _ = llm.call(ledger, "seed_classify", model, max_tokens,
                          system, user, context=context)
        data = extract_json(raw)
    except Exception as e:
        print(f"  [seed] classification failed ({type(e).__name__}: {e}) "
              f"- treating as a conceptual essay")
        return dict(FALLBACK)
    genre = str(data.get("genre", "")).strip().lower()
    if genre not in config.SEED_GENRES:
        genre = FALLBACK["genre"]
    extra = {}
    if menu:
        # Ids only. The first paid f3 batch (2026-09-14) got "TS01 The
        # Conceptual Dispute" back; kept verbatim it matched no shape, the
        # restriction silently lapsed and that essay drew TS14 and drifted.
        import re

        def ids_of(items):
            out = []
            for x in items:
                m = re.match(r"\s*(TS\d+)\b", str(x))
                if m and m.group(1) not in out:
                    out.append(m.group(1))
            return out

        verdicts = data.get("shape_verdicts")
        if isinstance(verdicts, dict):
            level = {k: str(v).strip().lower() for k, v in verdicts.items()}
            natural = ids_of(k for k, v in level.items() if v in ("natural", "true"))
            possible = ids_of(k for k, v in level.items() if v == "possible")
            extra["natural_shapes"], extra["possible_shapes"] = natural, possible
            extra["carriable_shapes"] = carriable_from(natural, possible)
            extra["shapes_reported"] = bool(level)
        else:
            listed = data.get("carriable_shapes")
            extra["carriable_shapes"] = ids_of(listed if isinstance(listed, list) else [])
            extra["shapes_reported"] = isinstance(listed, list)
    return {
        **extra,
        "genre": genre,
        "domain": str(data.get("domain", "")).strip().lower() or "social",
        "concrete_particulars": [str(x) for x in
                                 (data.get("concrete_particulars") or [])][:6],
        "bipolar_dispute_available": bool(
            data.get("bipolar_dispute_available", True)),
        "one_line": str(data.get("one_line", ""))[:160],
    }


def genre_shares(history, window: int | None = None) -> tuple[dict, int]:
    """Trailing share of each seed genre across recently shipped sets."""
    window = window or config.SEED_GENRE_WINDOW
    # This client's sets only (2026-09-12): genre saturation is a per-client lever.
    genres = history.recent_seed_genres(window)
    if not genres:
        return {}, 0
    counts: dict[str, int] = {}
    for g in genres:
        counts[g] = counts.get(g, 0) + 1
    return {g: n / len(genres) for g, n in counts.items()}, len(genres)


def genre_is_saturated(history, genre: str) -> float | None:
    """Trailing share, if this genre is over its cap and the corpus is big
    enough for a share to mean anything. None means 'go ahead'."""
    shares, n = genre_shares(history)
    if n < config.SEED_GENRE_MIN_CORPUS:
        return None
    share = shares.get(genre, 0.0)
    return share if share > config.SEED_GENRE_SATURATION else None


def eligible_topic_shapes(registry, info: dict, policy=None) -> list[str]:
    """Topic shapes this seed can actually carry.

    A seed with no real dispute in it must not be handed a shape that requires
    two poles — that conversion is exactly how a technical piece became another
    'whether X or Y' essay.

    policy: the generation policy of the plan being composed (2026-09-13);
    shapes tagged for another policy are never offered, even by the fallback."""
    from .generation_policy import LEGACY_POLICY
    shape_ids = (policy or LEGACY_POLICY).eligible_ids(registry, "topic_shape")
    out = []
    for tid in shape_ids:
        shape = registry.get("topic_shape", tid)
        if shape.get("requires_tension") and not info.get(
                "bipolar_dispute_available", True):
            continue
        compat = shape.get("compatible_genres") or []
        if compat and info.get("genre") not in compat and info.get("genre") != "unknown":
            continue
        out.append(tid)
    if not out:      # never dead-end: fall back to the policy's whole library
        out = list(shape_ids)
    # Seed fidelity (2026-09-14): a shape the essay's own material cannot supply
    # is how a virtue essay was handed "One Object, Read Closely" and came back
    # as a struck clause in a will. Restrict to the classifier's carriable
    # shapes; if none of them survive the filters above, the carriable list
    # itself (the dispute rule still applies) beats a shape that forces drift.
    carriable = info.get("carriable_shapes")
    if policy is not None and policy.seed_fidelity and carriable:
        narrowed = [t for t in out if t in carriable]
        if not narrowed:
            narrowed = [t for t in shape_ids if t in carriable
                        and not (registry.get("topic_shape", t).get("requires_tension")
                                 and not info.get("bipolar_dispute_available", True))]
        if narrowed:
            out = narrowed
    return out
