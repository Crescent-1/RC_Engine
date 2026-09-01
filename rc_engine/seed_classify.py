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


def classify_seed(seed, llm, ledger: CostLedger | None = None,
                  tier: str = "hard") -> dict:
    """Read the seed and report its genre. Falls back to the historical
    assumption (a conceptual essay with a dispute available) so a classifier
    outage degrades to today's behaviour rather than blocking a batch."""
    text = (getattr(seed, "text", "") or "").strip()
    title = getattr(seed, "title", "") or ""
    if not text:
        return dict(FALLBACK, genre="unknown")
    model, max_tokens = config.STAGE_CONFIG["seed_classify"][tier]
    excerpt = " ".join(text.split()[:600])
    user = f"TITLE: {title}{NL}{NL}EXCERPT:{NL}{excerpt}"
    ledger = ledger or CostLedger(budget_usd=config.SEED_CLASSIFY_MAX_USD)
    try:
        raw, _ = llm.call(ledger, "seed_classify", model, max_tokens,
                          CLASSIFY_SYSTEM, user, context={"seed": seed})
        data = extract_json(raw)
    except Exception as e:
        print(f"  [seed] classification failed ({type(e).__name__}: {e}) "
              f"- treating as a conceptual essay")
        return dict(FALLBACK)
    genre = str(data.get("genre", "")).strip().lower()
    if genre not in config.SEED_GENRES:
        genre = FALLBACK["genre"]
    return {
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
    rows = history.conn.execute(
        """SELECT seed_genre FROM rc_sets
           WHERE seed_genre IS NOT NULL AND seed_genre != ''
           ORDER BY created_at DESC LIMIT ?""", (window,)).fetchall()
    if not rows:
        return {}, 0
    counts: dict[str, int] = {}
    for (g,) in rows:
        counts[g] = counts.get(g, 0) + 1
    return {g: n / len(rows) for g, n in counts.items()}, len(rows)


def genre_is_saturated(history, genre: str) -> float | None:
    """Trailing share, if this genre is over its cap and the corpus is big
    enough for a share to mean anything. None means 'go ahead'."""
    shares, n = genre_shares(history)
    if n < config.SEED_GENRE_MIN_CORPUS:
        return None
    share = shares.get(genre, 0.0)
    return share if share > config.SEED_GENRE_SATURATION else None


def eligible_topic_shapes(registry, info: dict) -> list[str]:
    """Topic shapes this seed can actually carry.

    A seed with no real dispute in it must not be handed a shape that requires
    two poles — that conversion is exactly how a technical piece became another
    'whether X or Y' essay."""
    out = []
    for tid in registry.ids("topic_shape"):
        shape = registry.get("topic_shape", tid)
        if shape.get("requires_tension") and not info.get(
                "bipolar_dispute_available", True):
            continue
        compat = shape.get("compatible_genres") or []
        if compat and info.get("genre") not in compat and info.get("genre") != "unknown":
            continue
        out.append(tid)
    if not out:      # never dead-end: fall back to the whole library
        out = list(registry.ids("topic_shape"))
    return out
