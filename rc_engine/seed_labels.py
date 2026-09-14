"""Seed-store labels (2026-09-14): classify every essay once, store the answer.

Until now an essay was classified at draw time, one cheap call per attempt, and
the answer lived only on the plan. So the store could not be asked for "unused
philosophy and literature essays" — the operator had to hand-build a doc-id list
(`generate --seed-ids`) — and an essay that could carry only one or two topic
shapes was discovered after it had been drawn.

`seeds classify` runs the same classifier over the store with gpt-5.6-luna
(the pinned seed_classify model), asks for every topic shape the essay's subject
can carry, and writes flat metadata beside the existing fields. The store's own
`genre` field is the PUBLICATION, so labels use `seed_*` names. Labels carry a
version; a draw uses them only when the version matches, and falls back to the
live classifier otherwise.
"""
from __future__ import annotations

import concurrent.futures
import threading
from datetime import datetime, timezone

from . import config
from .llm import BudgetExceeded, CostLedger
from .models import SeedEssay

LABEL_VERSION = "sl3"   # sl1 list, sl2 true/false: 5 test labels each, superseded
LABEL_KEYS = ("seed_genre", "seed_domain", "seed_subject", "seed_particulars",
              "seed_dispute", "seed_shapes", "seed_shapes_natural", "seed_shapes_possible",
              "seed_label_version", "seed_labeled_at")


def all_shape_ids(registry) -> list[str]:
    """Every topic shape in the library, policy-tagged ones included: a label is
    about the essay, and each draw filters by its own policy later."""
    return registry.ids("topic_shape")


def to_metadata(info: dict) -> dict:
    """Chroma metadata must be scalar: lists are joined."""
    return {
        "seed_genre": info.get("genre", ""),
        "seed_domain": info.get("domain", ""),
        "seed_subject": info.get("one_line", ""),
        "seed_particulars": " | ".join(info.get("concrete_particulars") or []),
        "seed_dispute": bool(info.get("bipolar_dispute_available", True)),
        "seed_shapes": ",".join(info.get("carriable_shapes") or []),
        "seed_shapes_natural": ",".join(info.get("natural_shapes") or []),
        "seed_shapes_possible": ",".join(info.get("possible_shapes") or []),
        "seed_label_version": LABEL_VERSION,
        "seed_labeled_at": datetime.now(timezone.utc).isoformat(),
    }


def from_metadata(meta: dict | None) -> dict | None:
    """The classifier's dict back from stored metadata; None when unlabelled or
    labelled under another version."""
    m = meta or {}
    if m.get("seed_label_version") != LABEL_VERSION or not m.get("seed_genre"):
        return None
    return {
        "genre": m["seed_genre"],
        "domain": m.get("seed_domain", ""),
        "one_line": m.get("seed_subject", ""),
        "concrete_particulars": [p for p in (m.get("seed_particulars") or "").split(" | ") if p],
        "bipolar_dispute_available": bool(m.get("seed_dispute", True)),
        "carriable_shapes": [s for s in (m.get("seed_shapes") or "").split(",") if s],
        "natural_shapes": [s for s in (m.get("seed_shapes_natural") or "").split(",") if s],
        "possible_shapes": [s for s in (m.get("seed_shapes_possible") or "").split(",") if s],
        "stored": True,
    }


def shape_count(meta: dict | None) -> int:
    return len([s for s in ((meta or {}).get("seed_shapes") or "").split(",") if s])


def pending(db, relabel: bool = False, include_used: bool = False) -> list[str]:
    got = db.get(include=["metadatas"])
    out = []
    for doc_id, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
        meta = meta or {}
        if meta.get("used") and not include_used:
            continue
        if not relabel and from_metadata(meta) is not None:
            continue
        out.append(doc_id)
    return out


def classify_store(db, llm, registry, doc_ids: list[str], max_usd: float,
                   workers: int = 6, log=print) -> dict:
    """Classify doc_ids and write labels as each one returns (resumable: a
    rerun skips what is already labelled). Stops starting new calls once
    max_usd is reached. Returns {"labelled", "failed", "spent_usd"}."""
    from .seed_classify import classify_seed, shape_menu
    menu = shape_menu(registry, all_shape_ids(registry))
    lock = threading.Lock()
    state = {"labelled": 0, "failed": 0, "spent_usd": 0.0, "stopped": False}

    def work(doc_id):
        with lock:
            if state["stopped"]:
                return doc_id, None, None, 0.0
        got = db.get(ids=[doc_id], include=["documents", "metadatas"])
        if not got.get("ids"):
            return doc_id, None, None, 0.0
        meta = (got["metadatas"] or [{}])[0] or {}
        seed = SeedEssay(doc_id=doc_id, title=meta.get("title"), url=meta.get("url"),
                         text=(got["documents"] or [""])[0])
        ledger = CostLedger(budget_usd=config.SEED_CLASSIFY_MAX_USD)
        try:
            info = classify_seed(seed, llm, ledger, "hard", menu=menu, store=True)
        except BudgetExceeded:
            return doc_id, meta, None, ledger.spent_usd
        # classify_seed degrades to FALLBACK on any failure; never store that.
        # A reply without shape verdicts is not a label either; a rerun retries it.
        ok = (bool(info.get("one_line")) and info.get("genre") != "unknown"
              and bool(info.get("shapes_reported")))
        return doc_id, meta, (info if ok else None), ledger.spent_usd

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, d) for d in doc_ids]
        for fut in concurrent.futures.as_completed(futures):
            doc_id, meta, info, spent = fut.result()
            with lock:
                state["spent_usd"] += spent
                if state["spent_usd"] >= max_usd and not state["stopped"]:
                    state["stopped"] = True
                    log(f"[seeds] spending cap ${max_usd:.2f} reached - no new calls")
            if meta is None:
                continue
            if info is None:
                state["failed"] += 1
                continue
            db._collection.update(ids=[doc_id], metadatas=[{**meta, **to_metadata(info)}])
            state["labelled"] += 1
            done = state["labelled"] + state["failed"]
            if done % 25 == 0:
                log(f"[seeds] {done}/{len(doc_ids)} done, ${state['spent_usd']:.3f}")
    return {k: state[k] for k in ("labelled", "failed", "spent_usd")}


def labelled_pool(db, subjects=None, genres=None, min_shapes: int = 0) -> list[str]:
    """Unused, labelled doc ids matching the subject/genre filters."""
    subjects = {s.strip().lower() for s in (subjects or []) if s.strip()}
    genres = {g.strip().lower() for g in (genres or []) if g.strip()}
    got = db.get(include=["metadatas"])
    out = []
    for doc_id, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
        meta = meta or {}
        if meta.get("used") or from_metadata(meta) is None:
            continue
        if subjects and (meta.get("seed_domain") or "").lower() not in subjects:
            continue
        if genres and (meta.get("seed_genre") or "").lower() not in genres:
            continue
        if shape_count(meta) < min_shapes:
            continue
        out.append(doc_id)
    return out


def report(db) -> list[str]:
    import collections
    got = db.get(include=["metadatas"])
    metas = [m or {} for m in got.get("metadatas") or []]
    unused = [m for m in metas if not m.get("used")]
    labelled = [m for m in unused if from_metadata(m) is not None]
    lines = [f"[seeds] store {len(metas)} essays, {len(unused)} unused, "
             f"{len(labelled)} unused labelled ({LABEL_VERSION})"]
    by = collections.Counter((m["seed_domain"], m["seed_genre"]) for m in labelled)
    domains = collections.Counter(m["seed_domain"] for m in labelled)
    for domain, n in domains.most_common():
        parts = ", ".join(f"{g} {c}" for (d, g), c in by.most_common() if d == domain)
        lines.append(f"  {domain:12} {n:4}  ({parts})")
    shapes = collections.Counter(min(shape_count(m), 6) for m in labelled)
    lines.append("  carriable shapes per essay: "
                 + ", ".join(f"{k if k < 6 else '6+'}: {shapes[k]}" for k in sorted(shapes)))
    return lines
