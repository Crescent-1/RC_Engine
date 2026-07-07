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
#   "Q1 — Correct answer: (B)"   /   "Q1 - Correct answer: (C)"
_ANSWER_LINE = re.compile(
    r"(?im)^\s*Q\s*(\d)\W{0,10}correct\s+answer\W{0,10}([A-D])\b")
# Older manual exports use a markdown key: "**1. Correct: (B)**"
_ANSWER_LINE_ALT = re.compile(
    r"(?im)^\W{0,6}(\d)\W{0,4}correct\W{0,12}([A-D])\b")


def parse_answer_letters(text: str) -> str:
    """Extract the answer-letter sequence from an RC's answer-key block.
    Tolerant: returns '' when the text carries no recognizable key."""
    letters: dict[int, str] = {}
    for pattern in (_ANSWER_LINE, _ANSWER_LINE_ALT):
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
            print(f"  [fingerprint] embedding model unavailable ({e}) — channel disabled")
            return None
    return [float(x) for x in _EMBEDDER.encode(text, normalize_embeddings=True)]


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
