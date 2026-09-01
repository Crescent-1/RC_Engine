"""Build the static read-only demo snapshot.

Reads the production SQLite DB (read-only, never written) and emits a folder of
plain JSON that the `demo/` site consumes. The demo has no backend, no API keys
and spends nothing: everything it shows is baked here, at build time.

Redaction is on by default and deliberate. Per-set cost, token counts, model
vendor names and engine thresholds never leave this script.

Usage
-----
    python tools/build_demo_snapshot.py
    python tools/build_demo_snapshot.py --full-text RC-HARD-260726-0021
    python tools/build_demo_snapshot.py --full-text all --include-costs

By default exactly one set is published in full (the oldest approved one, which
has already been through the client's mock cycle). Every other set contributes
metadata, scores and audit channels but not its passage or answer key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.parse
from collections import Counter, defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Weights are READ from the engine, never copied. They were duplicated as
# literals here once and drifted silently — blueprint 0.20 vs 0.14, movement
# 0.18 vs 0.10 — which put wrong bars under 38 of 79 published sets while the
# headline composite (taken from the stored audit) stayed right, so the page
# disagreed with itself. Importing config is cheap and side-effect-free beyond
# reading .env into os.environ.
sys.path.insert(0, PROJECT_ROOT)
from rc_engine import config  # noqa: E402

# Fields that must never reach a public page.
COST_FIELDS = (
    "gen_cost_usd", "judge_cost_usd", "solver_cost_usd", "total_cost_usd",
    "gen_input_tokens", "gen_output_tokens", "judge_input_tokens",
    "judge_output_tokens", "solver_input_tokens", "solver_output_tokens",
)

# Ordered gates of the novelty cascade. Cheap structural checks run first so an
# expensive render is never spent on a candidate that already collides.
GATE_ORDER = [
    ("topic_precheck", "Topic pre-check",
     "Before anything is written: is this subject too close to something the corpus already covers?"),
    ("movement_precheck", "Movement pre-check",
     "Does the paragraph-function skeleton repeat a shape the corpus has already used?"),
    ("topology_precheck", "Topology pre-check",
     "Does the question-type layout duplicate an existing set's topology?"),
    ("style_peek", "Style peek",
     "A short sample of the draft is compared for voice and rhythm before the full render continues."),
    ("passage", "Passage audit",
     "The finished passage is scored against every neighbour on embedding, stylometry and cadence."),
    ("full", "Full audit",
     "Passage plus questions, scored across all nine channels and reduced to one composite."),
    ("vet", "Final vet",
     "Compliance, answer-key sanity and corpus-level hygiene before the set is cleared."),
]

# The weighted channels of the novelty composite, mirroring
# NoveltyScorer._composite exactly. The `key` of each entry is also its key in
# config.COMPOSITE_WEIGHTS — that is what channel_view() looks the weight up by,
# so a weight can never be stated in two places again.
#
# Direction matters and is easy to get wrong: every stored channel score is a
# SIMILARITY (higher = more alike), including `movement_levenshtein`, which is
# named like a distance but is produced by fingerprints.movement_similarity().
# The single exception is `distractor_jsd`, a divergence the engine folds in as
# max(0, 1 - jsd * 4). `kind` below records how each raw score becomes the
# similarity the composite actually consumes.
#
# Two further traps this list has already fallen into:
#   - `curve` must read curve_similarity, NOT curve_pearson. Both are stored,
#     both are plausible, and only the former is what _composite consumes.
#   - a channel added to the engine must be added here too, or the page simply
#     omits it: move_signature (the heaviest structural channel after
#     blueprint) was missing from every published set until 2026-09-01.
CHANNELS = [
    ("blueprint", "Blueprint overlap", "blueprint_sim", "sim",
     "How many of the seven sampled structural slots this set shares with its "
     "nearest neighbour."),
    ("movement", "Movement shape", None, "movement",
     "Similarity of the paragraph-function skeletons, taken as the worse of edit "
     "distance and shared adjacent-function pairs — so reordered but identical "
     "logic still registers."),
    ("move_signature", "Rhetorical moves", "move_signature_sim", "sim",
     "Overlap in the ordered sequence of rhetorical moves — scene-setting, "
     "concession, demolition of an easy reading. Two passages can share no "
     "wording and still run the same play."),
    ("curve", "Commitment curve", "curve_similarity", "sim_clamped",
     "Correlation of how the author's certainty rises and falls across the "
     "passage. Negative correlation is treated as fully distinct."),
    ("topology", "Question topology", "topology_similarity", "sim",
     "Overlap in the question-type layout of the set."),
    ("distractor_jsd", "Distractor mix", "distractor_jsd", "jsd",
     "Jensen–Shannon divergence between the two sets' trap-type distributions. "
     "A low divergence means the same traps are being reused."),
    ("rhythm", "Sentence rhythm", "rhythm_cosine", "sim_clamped",
     "Similarity of the z-scored sentence-length cadence vector."),
    ("stylometry", "Stylometry", "stylometry_sim", "sim",
     "Burrows's Delta over function words and punctuation — the tell a human "
     "reader experiences as voice."),
    ("embedding", "Semantic embedding", "embedding_cosine", "sim",
     "Dense-vector similarity of the passages themselves."),
]


# --------------------------------------------------------------- db plumbing

def connect(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise SystemExit(f"database not found: {path}")
    uri = "file:" + urllib.parse.quote(path.replace("\\", "/"), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def loads(blob, default=None):
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------- text parsing

PASSAGE_RE = re.compile(r"\[PASSAGE\]\s*(.*?)\s*\[QUESTIONS\]", re.S)
QUESTIONS_RE = re.compile(r"\[QUESTIONS\]\s*(.*?)\s*\[ANSWER KEY", re.S)
KEY_RE = re.compile(r"\[ANSWER KEY[^\]]*\]\s*(.*?)(?:\n\[Inspired by:|\Z)", re.S)
SOURCE_RE = re.compile(r"\[Inspired by:\s*\"(.*?)\",\s*(.*?)\]", re.S)

Q_SPLIT_RE = re.compile(r"^Q(\d+)[.)]\s*", re.M)
OPTION_RE = re.compile(r"^\(([A-D])\)\s*(.*?)(?=^\([A-D]\)|\Z)", re.S | re.M)
KEY_HEAD_RE = re.compile(r"^Q(\d+)\s*[—-]\s*Correct answer:\s*\(([A-D])\)", re.M)
KEY_LINE_RE = re.compile(r"^\s+\(([A-D])\)\s*(\S+?)\s*[—-]\s*(.*?)(?=^\s+\([A-D]\)|\Z)", re.S | re.M)


def split_questions(block: str) -> list[dict]:
    """Split the [QUESTIONS] block into stems and lettered options."""
    parts = Q_SPLIT_RE.split(block)
    out = []
    # parts == ['', '1', body, '2', body, ...]
    for i in range(1, len(parts) - 1, 2):
        num, body = int(parts[i]), parts[i + 1]
        opts = OPTION_RE.findall(body)
        stem_end = body.find("(A)")
        stem = (body[:stem_end] if stem_end != -1 else body).strip()
        out.append({
            "n": num,
            "stem": stem,
            "options": [{"letter": L, "text": t.strip()} for L, t in opts],
        })
    return out


def split_key(block: str) -> dict[int, dict]:
    """Parse the answer key into {q_number: {answer, lines:[{letter,tag,note}]}}."""
    out: dict[int, dict] = {}
    heads = list(KEY_HEAD_RE.finditer(block))
    for i, m in enumerate(heads):
        num, answer = int(m.group(1)), m.group(2)
        end = heads[i + 1].start() if i + 1 < len(heads) else len(block)
        body = block[m.end():end]
        lines = []
        for L, tag, note in KEY_LINE_RE.findall(body):
            lines.append({
                "letter": L,
                "tag": "CORRECT" if tag.upper() == "CORRECT" else tag,
                "note": " ".join(note.split()),
            })
        out[num] = {"answer": answer, "lines": lines}
    return out


def parse_rc_text(text: str) -> dict:
    """Split a stored rc_text into its four structural blocks.

    Returns {} when the text does not match the engine's output contract, so a
    malformed row degrades to metadata-only rather than breaking the build.
    """
    if not text:
        return {}
    p = PASSAGE_RE.search(text)
    q = QUESTIONS_RE.search(text)
    k = KEY_RE.search(text)
    if not (p and q and k):
        return {}

    questions = split_questions(q.group(1))
    key = split_key(k.group(1))
    if not questions or not key:
        return {}

    for item in questions:
        entry = key.get(item["n"], {})
        item["answer"] = entry.get("answer")
        item["rationale"] = entry.get("lines", [])

    src = SOURCE_RE.search(text)
    paragraphs = [b.strip() for b in p.group(1).split("\n\n") if b.strip()]
    return {
        "paragraphs": paragraphs,
        "word_count": len(p.group(1).split()),
        "questions": questions,
        "source": ({"title": src.group(1).strip(), "url": src.group(2).strip()}
                   if src else None),
    }


# ------------------------------------------------------------------ builders

def build_corpus(conn, audits: list[dict]) -> dict:
    by_status = {r["status"]: r["n"] for r in rows(
        conn, "SELECT status, COUNT(*) n FROM rc_sets GROUP BY status")}
    by_tier = {r["tier"]: r["n"] for r in rows(
        conn, "SELECT tier, COUNT(*) n FROM rc_sets GROUP BY tier")}

    tier_stats = rows(conn, """
        SELECT tier,
               COUNT(*) n,
               ROUND(AVG(average_score), 2) avg_score,
               ROUND(AVG(compliance_f1), 3) avg_compliance,
               ROUND(AVG(novelty_composite), 3) avg_novelty
        FROM rc_sets WHERE status = 'approved' GROUP BY tier""")

    usage = rows(conn, """
        SELECT component_type,
               COUNT(DISTINCT component_id) distinct_used,
               COUNT(*) draws
        FROM component_usage GROUP BY component_type ORDER BY component_type""")

    fp = {r["source"]: r["n"] for r in rows(
        conn, "SELECT source, COUNT(*) n FROM fingerprints GROUP BY source")}

    health = rows(conn, """
        SELECT window_size, family_kl, topology_kl, slot_chi2_flags,
               letter_runs_p, created_at
        FROM corpus_health ORDER BY created_at DESC LIMIT 1""")
    if health:
        health[0]["slot_chi2_flags"] = loads(health[0]["slot_chi2_flags"], [])

    span = conn.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM rc_sets").fetchone()

    return {
        "sets_total": sum(by_status.values()),
        "by_status": by_status,
        "by_tier": by_tier,
        "tier_stats": tier_stats,
        "blueprints_drawn": conn.execute(
            "SELECT COUNT(*) FROM blueprints").fetchone()[0],
        "audits_run": len(audits),
        "passages_rendered": conn.execute(
            "SELECT COUNT(*) FROM rendered_passages").fetchone()[0],
        "fingerprint_corpus": {"total": sum(fp.values()), "by_source": fp},
        "component_usage": usage,
        "health": health[0] if health else None,
        "first_set": span[0],
        "last_set": span[1],
    }


def build_funnel(audits: list[dict]) -> dict:
    """Collapse every novelty verdict into the ordered gate cascade."""
    tally: dict[str, Counter] = defaultdict(Counter)
    for a in audits:
        verdict = a["verdict"] or ""
        gate, _, outcome = verdict.partition(":")
        outcome = outcome or "unknown"
        tally[gate]["pass" if outcome == "pass" else "reject"] += 1
        tally[gate][f"reason:{outcome}"] += 1

    gates = []
    for key, label, blurb in GATE_ORDER:
        c = tally.get(key)
        if not c:
            continue
        passed, rejected = c["pass"], c["reject"]
        reasons = {k.split(":", 1)[1]: v for k, v in c.items()
                   if k.startswith("reason:") and not k.endswith(":pass")}
        gates.append({
            "key": key, "label": label, "blurb": blurb,
            "evaluated": passed + rejected,
            "passed": passed, "rejected": rejected,
            "reasons": reasons,
        })

    total_eval = sum(g["evaluated"] for g in gates)
    total_rej = sum(g["rejected"] for g in gates)
    return {
        "gates": gates,
        "total_evaluations": total_eval,
        "total_rejections": total_rej,
        "rejection_rate": round(total_rej / total_eval, 3) if total_eval else 0,
    }


def channel_view(scores: dict) -> tuple[list[dict], float | None]:
    """Turn raw channel scores into 'higher = more distinct' bars.

    Also returns the composite reconstructed from those bars, which the build
    cross-checks against the value the engine stored. A mismatch means this
    function has drifted from NoveltyScorer._composite.
    """
    out, num_, den = [], 0.0, 0.0
    for key, label, field, kind, blurb in CHANNELS:
        weight = config.COMPOSITE_WEIGHTS[key]
        if kind == "movement":
            lev = scores.get("movement_levenshtein")
            jac = scores.get("movement_bigram_jaccard")
            if lev is None and jac is None:
                continue
            raw = max(lev or 0.0, jac or 0.0)
            sim = raw
        else:
            raw = scores.get(field)
            if raw is None:
                continue
            if kind == "sim":
                sim = raw
            elif kind == "sim_clamped":
                sim = max(0.0, raw)          # engine clamps negatives to 0
            elif kind == "jsd":
                sim = max(0.0, 1.0 - raw * 4)  # divergence folded into similarity
            else:
                continue

        sim = max(0.0, min(1.0, sim))
        num_ += weight * sim
        den += weight
        out.append({
            "key": key, "label": label, "weight": weight, "blurb": blurb,
            "raw": round(raw, 3),
            "similarity": round(sim, 3),
            "distinct": round(1.0 - sim, 3),
            "contribution": round(weight * (1.0 - sim), 4),
        })

    composite = round(1.0 - (num_ / den), 3) if den else None
    return out, composite


def build_sets(conn, audits: list[dict], full_text: set[str],
               include_costs: bool
               ) -> tuple[list[dict], dict[str, dict], list[str], list[str]]:
    drift: list[str] = []
    legacy_scored: list[str] = []
    final_audit = {}
    for a in audits:
        if a["rc_id"] and (a["verdict"] or "").startswith("full:"):
            final_audit[a["rc_id"]] = a

    blueprints = {r["blueprint_id"]: r for r in rows(
        conn, "SELECT blueprint_id, blueprint_json, instability, aperture, "
              "family_id, persona_id, ending_id, rhythm_id, revelation_id, "
              "distractor_profile_id, topology_id FROM blueprints")}

    index, details = [], {}
    for r in rows(conn, "SELECT * FROM rc_sets ORDER BY created_at DESC"):
        rc_id = r["rc_id"]
        r.pop("passage_embedding", None)
        if not include_costs:
            for f in COST_FIELDS:
                r.pop(f, None)
            r.pop("provider", None)

        bp = blueprints.get(r.get("blueprint_id")) or {}
        bp_json = loads(bp.get("blueprint_json"), {}) or {}
        parsed = parse_rc_text(r.get("rc_text") or "")
        audit = final_audit.get(rc_id)
        scores = loads(audit["channel_scores"], {}) if audit else {}

        channels, rebuilt = channel_view(scores)
        # Guard against this script's channel maths drifting from the engine's.
        #
        # Only sets scored under the CURRENT channel set can reconstruct. Sets
        # audited before move_signature landed (2026-08-21) were scored by a
        # composite that did not have that channel and weighted the others
        # differently, so replaying today's weights over them must disagree —
        # that is history, not drift. Counting them as drift kept this check
        # permanently red, which is precisely why a real 0.20-vs-0.14 weight
        # error hid behind it. Legacy sets are counted separately and quietly.
        if audit and rebuilt is not None:
            stored = audit["composite"]
            if stored is not None and abs(rebuilt - stored) > 0.02:
                if "move_signature_sim" in scores:
                    drift.append(f"{rc_id}: stored {stored:.3f} vs rebuilt {rebuilt:.3f}")
                else:
                    legacy_scored.append(rc_id)

        card = {
            "rc_id": rc_id,
            "tier": r.get("tier"),
            "status": r.get("status"),
            "domain": r.get("domain"),
            "created_at": r.get("created_at"),
            "average_score": r.get("average_score"),
            "compliance_f1": r.get("compliance_f1"),
            "novelty_composite": r.get("novelty_composite"),
            "attempts": r.get("attempts"),
            "word_count": parsed.get("word_count"),
            "question_count": len(parsed.get("questions", [])),
            "topic": bp_json.get("topic"),
            "source": parsed.get("source"),
            "published": rc_id in full_text,
        }
        index.append(card)

        judge = loads(r.get("judge_json"), {}) or {}
        solver = loads(r.get("solver_json"), {}) or {}
        detail = {
            **card,
            "blueprint": {
                "blueprint_id": bp.get("blueprint_id"),
                "instability": bp.get("instability"),
                "aperture": bp.get("aperture"),
                "slots": {
                    "family": bp.get("family_id"),
                    "persona": bp.get("persona_id"),
                    "ending": bp.get("ending_id"),
                    "rhythm": bp.get("rhythm_id"),
                    "revelation": bp.get("revelation_id"),
                    "distractor_profile": bp.get("distractor_profile_id"),
                    "topology": bp.get("topology_id"),
                },
                "movement": bp_json.get("movement", []),
                "letter_plan": bp_json.get("letter_plan"),
                "tension_system": bp_json.get("tension_system"),
                "closing_register": bp_json.get("closing_register"),
            },
            "judge": {
                "scores": judge.get("scores", {}),
                "average": r.get("average_score"),
            },
            "solver": {
                "verdict": solver.get("verdict"),
                "comparable": solver.get("comparable"),
                "answers": solver.get("answers", []),
                "disputes": solver.get("disputes", []),
            },
            "novelty": {
                "composite": audit["composite"] if audit else r.get("novelty_composite"),
                "verdict": audit["verdict"] if audit else None,
                "nearest": scores.get("nearest"),
                "channels": channels,
            },
        }
        if rc_id in full_text and parsed:
            detail["passage"] = parsed["paragraphs"]
            detail["questions"] = parsed["questions"]
        details[rc_id] = detail

    return index, details, drift, legacy_scored


def pick_default_full_text(conn) -> list[str]:
    """The oldest approved set: already through the client's mock cycle, so the
    least sensitive one to reproduce in full."""
    row = conn.execute(
        "SELECT rc_id FROM rc_sets WHERE status = 'approved' "
        "ORDER BY created_at ASC LIMIT 1").fetchone()
    return [row[0]] if row else []


# ---------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(PROJECT_ROOT, "rc_pipeline.db"))
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "demo", "data"))
    ap.add_argument("--full-text", default="",
                    help="comma-separated rc_ids to publish in full, or 'all'. "
                         "Default: the oldest approved set.")
    ap.add_argument("--include-costs", action="store_true",
                    help="keep cost and token columns (NOT for a public deploy)")
    args = ap.parse_args()

    conn = connect(args.db)
    try:
        audits = rows(conn, "SELECT * FROM novelty_audits ORDER BY created_at")
        all_ids = {r[0] for r in conn.execute("SELECT rc_id FROM rc_sets")}

        if args.full_text.strip().lower() == "all":
            full_text = set(all_ids)
        elif args.full_text.strip():
            full_text = {s.strip() for s in args.full_text.split(",") if s.strip()}
            unknown = full_text - all_ids
            if unknown:
                raise SystemExit(f"unknown rc_id(s): {', '.join(sorted(unknown))}")
        else:
            full_text = set(pick_default_full_text(conn))

        corpus = build_corpus(conn, audits)
        funnel = build_funnel(audits)
        index, details, drift, legacy_scored = build_sets(
            conn, audits, full_text, args.include_costs)
    finally:
        conn.close()

    os.makedirs(args.out, exist_ok=True)
    sets_dir = os.path.join(args.out, "sets")
    os.makedirs(sets_dir, exist_ok=True)

    def dump(path: str, obj) -> int:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        return os.path.getsize(path)

    corpus["published_full_text"] = sorted(full_text)
    corpus["costs_included"] = bool(args.include_costs)

    total = 0
    total += dump(os.path.join(args.out, "corpus.json"), corpus)
    total += dump(os.path.join(args.out, "funnel.json"), funnel)
    total += dump(os.path.join(args.out, "sets.json"), index)
    for rc_id, detail in details.items():
        total += dump(os.path.join(sets_dir, f"{rc_id}.json"), detail)

    unparsed = [c["rc_id"] for c in index if not c["question_count"]]

    print(f"snapshot written to {args.out}")
    print(f"  sets            {len(index)}")
    print(f"  full text       {len(full_text)}  ({', '.join(sorted(full_text)) or 'none'})")
    print(f"  audits          {len(audits)}  ({funnel['total_rejections']} rejections)")
    print(f"  costs included  {args.include_costs}")
    print(f"  payload         {total / 1024:.0f} KB")
    if unparsed:
        print(f"  WARNING unparsed rc_text: {', '.join(unparsed)}")
    if drift:
        print(f"  WARNING composite mismatch on {len(drift)} set(s) scored under "
              f"the CURRENT channel set — the channel maths here has drifted "
              f"from NoveltyScorer._composite:")
        for d in drift[:5]:
            print(f"    {d}")
    else:
        print("  composite check  every set scored under the current channel "
              "set reconstructs within 0.02")
    if legacy_scored:
        print(f"  legacy scoring  {len(legacy_scored)} set(s) predate the "
              f"move_signature channel and cannot reconstruct under today's "
              f"weights — expected, not drift")


if __name__ == "__main__":
    main()
