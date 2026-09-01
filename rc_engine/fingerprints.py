"""Structural fingerprint extraction — all deterministic and local except the
optional embedding (sentence-transformers, loaded lazily, skipped gracefully)."""

from __future__ import annotations

import math
import re
import statistics

from . import config
from .models import Blueprint, Fingerprint, RealizedStructure

# Function words + hedge markers for stylometry (Burrows' Delta basis).
FUNCTION_WORDS = [
    "the", "of", "and", "to", "a", "in", "that", "is", "it", "for", "as", "with",
    "was", "on", "are", "be", "this", "by", "not", "but", "from", "or", "which",
    "an", "at", "has", "have", "had", "its", "one", "we", "our", "their", "they",
    "what", "who", "when", "where", "how", "why", "than", "then", "so", "if",
    "because", "though", "although", "while", "yet", "however", "rather",
    "indeed", "perhaps", "may", "might", "must", "should", "would", "could",
    "partly", "largely", "merely", "only", "even", "still", "almost", "nearly",
]

# Fingerprints built from raw text (backfill, vet) have no compliance-audit
# annotation; their movement strings are sentinels, never real function tokens.
# The novelty scorer masks the movement channel when it sees one — otherwise
# two annotation-less sets would compare as movement-identical (sim 1.0).
UNKNOWN_MOVEMENT = ("LEGACY_UNKNOWN", "MANUAL_UNKNOWN")

# Answer-key line in engine exports and the manual prompt's output format:
#   "Q1 — Correct answer: (B)"  /  "Q1 - Correct answer: (C)"  /  "Q1 — Correct: (B)"
# Leading [^\w\n]{0,6} tolerates markdown bold/list chrome ("**Q1 — …").
# The \W{0,10} gap keeps stems out: prose between "Q1." and "correct" won't match.
_ANSWER_LINE = re.compile(
    r"(?im)^[^\w\n]{0,6}Q\s*(\d{1,2})\W{0,10}correct(?:\s+answer)?\W{0,10}([A-D])\b")
# Older manual exports use a markdown key: "**1. Correct: (B)**"
_ANSWER_LINE_ALT = re.compile(
    r"(?im)^\W{0,6}(\d{1,2})\W{0,4}correct\W{0,12}([A-D])\b")
# Compact keys: "Q1: B" / "Q3 — (C)" — the letter must end the line, so
# question stems ("Q1. Which of…") never match.
_ANSWER_LINE_COMPACT = re.compile(
    r"(?im)^[^\w\n]{0,6}Q\s*(\d{1,2})[ \t]*[:.\-—–][ \t]*\(?([A-D])\)?[ \t]*$")


def parse_answer_letters(text: str) -> str:
    """Extract the answer-letter sequence from an RC's answer-key block.
    Tolerant: returns '' when the text carries no recognizable key."""
    letters: dict[int, str] = {}
    for pattern in (_ANSWER_LINE, _ANSWER_LINE_ALT, _ANSWER_LINE_COMPACT):
        for qnum, letter in pattern.findall(text):
            letters.setdefault(int(qnum), letter.upper())
    return "".join(letters[k] for k in sorted(letters))


_EMBEDDER = None
_EMBED_FAILED = False


def _embed(text: str) -> list[float] | None:
    global _EMBEDDER, _EMBED_FAILED
    if _EMBED_FAILED:
        return None
    if _EMBEDDER is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDER = SentenceTransformer(config.EMBED_MODEL_NAME)
        except Exception as e:
            _EMBED_FAILED = True
            print(f"  [fingerprint] embedding model unavailable ({e}) - channel disabled")
            return None
    return [float(x) for x in _EMBEDDER.encode(text, normalize_embeddings=True)]


def embed_text(text: str) -> list[float] | None:
    """Public wrapper over the lazy local embedder ($0, no API call).
    Returns None when the model is unavailable — callers must degrade."""
    return _embed(text)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def rhythm_vector(passage: str) -> list[float]:
    paras = [p for p in passage.split("\n\n") if p.strip()]
    if not paras:
        return [0.0] * 8
    lens = [len(p.split()) for p in paras]
    sent_lens = []
    for p in paras:
        sl = [len(s.split()) for s in _sentences(p)]
        sent_lens.append(sl or [0])
    all_sents = [x for sl in sent_lens for x in sl]
    shortest_pos = lens.index(min(lens)) / max(1, len(paras) - 1) if len(paras) > 1 else 0.0
    return [
        float(len(paras)),
        statistics.pstdev(lens) if len(lens) > 1 else 0.0,
        shortest_pos,
        statistics.mean(all_sents) if all_sents else 0.0,
        statistics.pstdev(all_sents) if len(all_sents) > 1 else 0.0,
        passage.count("?") / max(1, len(all_sents)),
        (passage.count("—") + passage.count(" - ")) / max(1, len(all_sents)),
        passage.count(";") / max(1, len(all_sents)),
    ]


def stylometry_profile(passage: str) -> dict:
    words = re.findall(r"[a-z']+", passage.lower())
    total = max(1, len(words))
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    profile = {w: counts.get(w, 0) / total for w in FUNCTION_WORDS}
    sents = _sentences(passage)
    slens = [len(s.split()) for s in sents] or [0]
    profile["_mean_sent_len"] = statistics.mean(slens)
    profile["_std_sent_len"] = statistics.pstdev(slens) if len(slens) > 1 else 0.0
    return profile


def extract_fingerprint(rc_id: str, bp: Blueprint, passage: str,
                        realized: RealizedStructure, qdata: dict,
                        embed: bool = True) -> Fingerprint:
    topo_sig = [{"type": q["slot_type"], "target": "", "difficulty": 0.0}
                for q in qdata["questions"]]
    # enrich with planned slot data where available
    return Fingerprint(
        rc_id=rc_id,
        blueprint_id=bp.blueprint_id,
        persona_id=bp.persona_id,
        movement_string=realized.movement_string() or bp.movement_string(),
        commitment_curve=realized.commitment_curve,
        rhythm_vector=rhythm_vector(passage),
        topology_signature=topo_sig,
        trap_histogram=qdata.get("trap_usage", {}),
        letter_sequence="".join(qdata.get("letters", [])),
        stylometry=stylometry_profile(passage),
        embedding=_embed(passage) if embed else None,
    )


# ---------------------------------------------------------------------------
# Distance primitives (pure python; corpus sizes here don't need numpy)
# ---------------------------------------------------------------------------

def levenshtein(a: list, b: list) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def movement_similarity(ms_a: str, ms_b: str) -> tuple[float, float]:
    """Returns (levenshtein_similarity, transition_bigram_jaccard)."""
    a, b = ms_a.split("|"), ms_b.split("|")
    dist = levenshtein(a, b)
    lev_sim = 1.0 - dist / max(len(a), len(b), 1)
    big_a = {(a[i], a[i + 1]) for i in range(len(a) - 1)}
    big_b = {(b[i], b[i + 1]) for i in range(len(b) - 1)}
    union = big_a | big_b
    jac = len(big_a & big_b) / len(union) if union else 0.0
    return lev_sim, jac


def _lcs_len(a: list, b: list) -> int:
    """Longest common subsequence length — order-preserving but gap-tolerant."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1]


def move_signature_similarity(a: list[str], b: list[str],
                              freq: dict[str, int] | None = None,
                              corpus_n: int = 0) -> float:
    """Similarity of two blind rhetorical-move signatures, in [0, 1].

    Deliberately NOT movement_similarity(). That function is exact-order
    Levenshtein plus adjacent-bigram Jaccard, and on the pair this channel was
    built to catch — RC-ELITE-260712-0028 vs RC_E_0706_1 — it returned
    lev=0.23 / jac=0.00 even though the two passages share six moves including
    every distinctive one. Two essays can run the same argumentative grammar
    while interleaving it differently and at different lengths; adjacency is
    the wrong unit.

    Two terms instead:
      overlap — rarity-weighted set overlap (weighted Jaccard). A shared
                INSTANCE_SURVEY means little if 80% of the corpus does it; a
                shared BOTHSIDES_REFUSED means a lot if 10% does. Without corpus
                frequencies every move weighs 1.0 (plain Jaccard).
      order   — LCS over the sequences, normalised by the shorter one. Same
                moves in the same order is a stronger match than the same moves
                shuffled.

    Weighted 0.7 / 0.3: sharing the distinctive moves at all is the primary
    signal; running them in the same order sharpens it.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)

    def weight(move: str) -> float:
        # inverse document frequency, floored so a universal move still counts
        # for something and a unique one cannot dominate on its own
        if not freq or corpus_n <= 0:
            return 1.0
        share = freq.get(move, 1) / corpus_n
        return max(0.25, min(2.0, 1.0 / max(share, 0.05) ** 0.5))

    inter = sum(weight(m) for m in sa & sb)
    union = sum(weight(m) for m in sa | sb)
    overlap = inter / union if union else 0.0
    order = _lcs_len(a, b) / max(1, min(len(a), len(b)))
    return round(0.7 * overlap + 0.3 * order, 4)


def pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


# Commitment values live in [-1, 1], so the largest possible per-paragraph gap
# is 2.0 — the divisor that turns mean absolute deviation into a [0,1] similarity.
CURVE_VALUE_RANGE = 2.0
# Curves are 3-5 points (one per paragraph). Both sides are resampled onto this
# many points so a 4-paragraph and a 5-paragraph passage are comparable end to
# end; pearson() truncated to the shorter curve instead, which silently dropped
# the closing paragraph — the most informative point in the arc.
CURVE_GRID = 5


def _resample_curve(c: list[float], n: int = CURVE_GRID) -> list[float]:
    """Linear-interpolate a commitment curve onto an n-point grid."""
    if len(c) == n:
        return list(c)
    if len(c) == 1:
        return [c[0]] * n
    out = []
    for k in range(n):
        pos = k * (len(c) - 1) / (n - 1)
        lo = int(pos)
        hi = min(lo + 1, len(c) - 1)
        frac = pos - lo
        out.append(c[lo] * (1 - frac) + c[hi] * frac)
    return out


def curve_similarity(a: list[float], b: list[float]) -> float:
    """Level-aware commitment-curve similarity. 1.0 = same arc at the same
    commitment levels; 0.0 = maximally opposed.

    This replaces pearson() as the curve NOVELTY channel. Pearson is invariant
    to location and scale, so it scores only "do these rise together" and
    ignores where they sit. On 4-point curves that made it useless as a
    duplicate detector: [-0.8, 0.4, 0.7, 1.0] and [0.3, 0.7, 0.8, 0.9] score a
    perfect 1.000 under pearson despite being opposite passages (one author
    opens hostile and is won over, the other opens warm and warms further).
    Because the engine deliberately builds toward a late thesis, most curves
    rise monotonically — so pearson flagged the corpus's most common and most
    desirable shape, rejecting ~29% of valid renders once the gate activated.
    Mean absolute deviation keeps the levels and scores that same pair 0.805.
    """
    if not a or not b:
        return 0.0
    ra, rb = _resample_curve(a), _resample_curve(b)
    mad = sum(abs(x - y) for x, y in zip(ra, rb)) / len(ra)
    return max(0.0, 1.0 - mad / CURVE_VALUE_RANGE)


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a, b = a[:n], b[:n]
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def zscored_cosine(a: list[float], b: list[float], means: list[float],
                   stds: list[float]) -> float:
    za = [(x - m) / s if s else 0.0 for x, m, s in zip(a, means, stds)]
    zb = [(x - m) / s if s else 0.0 for x, m, s in zip(b, means, stds)]
    return cosine(za, zb)


def jensen_shannon(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    sp, sq = sum(p.values()) or 1, sum(q.values()) or 1
    pv = {k: p.get(k, 0) / sp for k in keys}
    qv = {k: q.get(k, 0) / sq for k in keys}

    def kl(x, y):
        return sum(x[k] * math.log2(x[k] / y[k]) for k in keys if x[k] > 0 and y[k] > 0)

    m = {k: (pv[k] + qv[k]) / 2 for k in keys}
    return 0.5 * kl(pv, m) + 0.5 * kl(qv, m)


def topology_similarity(sig_a: list[dict], sig_b: list[dict]) -> float:
    """JSD on type distribution (inverted to similarity) blended with order
    edit distance on the type sequence."""
    hist_a: dict[str, int] = {}
    hist_b: dict[str, int] = {}
    for s in sig_a:
        hist_a[s["type"]] = hist_a.get(s["type"], 0) + 1
    for s in sig_b:
        hist_b[s["type"]] = hist_b.get(s["type"], 0) + 1
    jsd = jensen_shannon(hist_a, hist_b)          # 0 identical .. 1 disjoint
    seq_a = [s["type"] for s in sig_a]
    seq_b = [s["type"] for s in sig_b]
    order_sim = 1.0 - levenshtein(seq_a, seq_b) / max(len(seq_a), len(seq_b), 1)
    return 0.5 * (1.0 - jsd) + 0.5 * order_sim


def burrows_delta(p1: dict, p2: dict, corpus: list[dict]) -> float:
    """Simplified Burrows' Delta over the function-word profile. Needs a
    corpus (window) to z-score against; returns a large value when the
    corpus is too small to standardize (i.e., 'no evidence of same author')."""
    if len(corpus) < 5:
        return 99.0
    words = FUNCTION_WORDS
    means, stds = {}, {}
    for w in words:
        vals = [c.get(w, 0.0) for c in corpus]
        means[w] = statistics.mean(vals)
        stds[w] = statistics.pstdev(vals)
    diffs = []
    for w in words:
        s = stds[w]
        if s == 0:
            continue
        z1 = (p1.get(w, 0.0) - means[w]) / s
        z2 = (p2.get(w, 0.0) - means[w]) / s
        diffs.append(abs(z1 - z2))
    return statistics.mean(diffs) if diffs else 99.0
