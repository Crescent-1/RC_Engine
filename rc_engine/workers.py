"""Parallel batch generation: N worker processes, one shared SQLite DB.

Why processes and not threads: every stage is a blocking HTTPS call plus
CPU-bound local scoring (stylometry, embeddings), and the SQLite connection
is per-process by design. Each worker builds its own HistoryStore, client
and RCPipeline; the parent never touches the LLM.

What keeps N concurrent renders from shipping near-duplicates of each other
(the sequential engine never had to think about this — every render saw
every earlier ship in the window):

  1. In-flight reservations (history.reserve_inflight). After compose, a
     worker registers its family, movement string and seed; every other
     worker's next compose bans those. Free, and it removes the most likely
     sibling collision — the same skeleton drawn twice — before any render.
  2. Disjoint seeds. The parent draws seeds and hands each slot its own
     small pool; a document is never in two workers at once.
  3. Ship lock + late recheck (pipeline._questions_and_ship). The full
     novelty gate is re-run under an exclusive lock immediately before the
     rc_sets insert, against a window that now includes every sibling that
     shipped during this worker's questions/solver/judge calls. The window
     is therefore exactly what it would have been sequentially, just checked
     later. A late collision is recorded as rejected_novelty like any Gate C
     breach; it has paid for its render, which is the one cost of overlap.

Cost cap: the parent stops dispatching once completed spend reaches
max_usd. Work already in flight finishes, so the overshoot is bounded by
`workers` per-RC budgets — the same shape of bound run_batch has, times N.

Windows uses the spawn start method, so the worker entry points below are
module-level and every argument they take is picklable (SeedEssay, str,
float). Output from workers is prefixed with [wPID] so interleaved logs can
be read.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone

from . import config
from .models import RCResult, SeedEssay

# ---------------------------------------------------------------- worker side

_PIPE = None          # RCPipeline, built once per worker process
_WORKER_ID = ""


class _Prefixed:
    """Line-prefixing stdout wrapper so N workers' logs stay attributable."""

    def __init__(self, stream, prefix: str):
        self._s, self._p, self._at_start = stream, prefix, True

    def write(self, text: str) -> int:
        out = []
        for chunk in text.splitlines(keepends=True):
            if self._at_start and chunk.strip():
                out.append(self._p)
            out.append(chunk)
            self._at_start = chunk.endswith("\n")
        return self._s.write("".join(out))

    def flush(self):
        self._s.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


def _worker_init(db: str, provider: str, dry_run: bool, embed: bool) -> None:
    global _PIPE, _WORKER_ID
    _WORKER_ID = f"w{os.getpid()}"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    sys.stdout = _Prefixed(sys.stdout, f"[{_WORKER_ID}] ")

    from .history import HistoryStore
    from .llm import MockLLMClient
    from .pipeline import RCPipeline

    config.set_provider(provider)
    if dry_run:
        llm = MockLLMClient()
    else:
        from .providers import RoutedClient, make_client
        llm = RoutedClient(make_client(provider))
    _PIPE = RCPipeline(HistoryStore(db), llm, embed=embed,
                       parallel=True, worker_id=_WORKER_ID)


def _worker_slot(tier: str, slot_no: int, count: int, seeds: list,
                 forced_bans: list[str], cap_usd: float) -> dict:
    """Run one batch slot to completion inside the worker. Returns plain data
    only: the RCResults, which seed each shipped rc_id consumed (the parent
    owns the seed store), and whether the API gave out."""
    from .llm import APIExhausted
    from .pipeline import run_slot

    results: list[RCResult] = []
    consumed: list[tuple[str, str]] = []
    pool = deque(seeds)

    def seed_provider(tier_: str | None = None, exclude_ids=None, avoid_kinds=None):
        while pool:
            s = pool.popleft()
            if exclude_ids and s.doc_id in exclude_ids:
                continue
            doc_id = s.doc_id
            return s, (lambda rc_id, d=doc_id: consumed.append((d, rc_id)))
        return None, None

    def keep(res: RCResult, _tier: str, _slot: int, _attempt: int) -> None:
        results.append(res)

    exhausted = False
    try:
        run_slot(_PIPE, tier, slot_no, count,
                 seed_provider if seeds else None, set(forced_bans),
                 spent=lambda: sum(r.cost_usd for r in results),
                 max_usd=cap_usd, keep=keep)
    except APIExhausted as e:
        exhausted = True
        print(f"[STOP] API exhausted in worker: {e}")
    except Exception as e:                                   # noqa: BLE001
        traceback.print_exc()
        results.append(RCResult(None, "", tier, "failed_error", notes=[repr(e)]))
    finally:
        try:
            _PIPE.history.release_inflight(_WORKER_ID)
        except Exception:                                    # noqa: BLE001
            pass
    return {"results": results, "consumed": consumed, "exhausted": exhausted}


# ---------------------------------------------------------------- parent side

def run_parallel(history, tier_counts: dict[str, int], workers: int, *,
                 db: str, provider: str, dry_run: bool, embed: bool,
                 seed_provider=None, max_usd: float | None = None,
                 only_posture: str | None = None) -> list[RCResult]:
    """Parallel counterpart of pipeline.run_batch with the same contract:
    returns every RCResult, records every attempt, prints the same summary.
    `history` is the parent's store (attempts table + seed callbacks)."""
    from .pipeline import summarize_batch
    from .registry import ComponentRegistry

    workers = max(1, min(int(workers), config.BATCH_WORKERS_MAX))
    if max_usd is None:
        max_usd = 1.25 * sum(config.TIER_BUDGET_USD[t] * n for t, n in tier_counts.items())
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    print(f"[batch {batch_id}] {workers} workers | spending cap: ${max_usd:.2f} "
          f"(per-RC caps: {config.TIER_BUDGET_USD}); completed spend is what "
          f"the cap sees, so overshoot is bounded by {workers} per-RC budgets")

    forced_bans: list[str] = []
    if only_posture:
        reg = ComponentRegistry()
        forced_bans = sorted(f for f in reg.ids("family")
                             if reg.posture_of(f) != only_posture)
        print(f"[batch] restricted to closing posture '{only_posture}' "
              f"({len(reg.ids('family')) - len(forced_bans)} families)")

    slots: deque = deque((tier, i + 1, count)
                         for tier, count in tier_counts.items()
                         for i in range(count))
    results: list[RCResult] = []
    callbacks: dict[str, object] = {}     # seed doc_id -> on_success(rc_id)
    handed: set[str] = set()              # seeds given to any worker this batch
    history.clear_inflight()

    def spent() -> float:
        return sum(r.cost_usd for r in results)

    # Which source kinds to steer the drawn pools away from. In sequential mode
    # the retry loop passes avoid_kinds to the store at rotation time; a worker
    # cannot, because its pool is pre-drawn by the parent — so the steering has
    # to happen HERE or not at all, and before this it was not happening at all
    # (the worker's seed_provider accepted avoid_kinds and ignored it). The
    # saturated genre is knowable up front from the trailing window, so the
    # spares are drawn away from the kinds that produce it.
    avoid_kinds: list[str] | None = None
    try:
        from .seed_classify import genre_shares
        shares, n = genre_shares(history)
        if n >= config.SEED_GENRE_MIN_CORPUS:
            hot = [g for g, sh in shares.items()
                   if sh > config.SEED_GENRE_SATURATION]
            avoid_kinds = sorted({k for g in hot
                                  for k in config.GENRE_SOURCE_KINDS.get(g, [])})
            if avoid_kinds:
                print(f"[batch] drawing seed pools away from {avoid_kinds} "
                      f"(saturated: {', '.join(hot)})")
    except Exception as e:                                   # noqa: BLE001
        print(f"[batch] seed-kind steering unavailable (non-fatal): {e}")

    def draw_seeds(tier: str) -> list[SeedEssay]:
        """A private pool per slot: the primary seed plus spares for the
        rotation the slot's retry loop would otherwise ask the store for.
        Worker-side pre-screen and novelty rotation both draw from it."""
        out: list[SeedEssay] = []
        if not seed_provider:
            return out
        for _ in range(config.PARALLEL_SEEDS_PER_SLOT):
            seed, cb = seed_provider(tier, exclude_ids=handed,
                                     avoid_kinds=avoid_kinds)
            if seed is None:
                break
            if seed.doc_id:
                handed.add(seed.doc_id)
                callbacks[seed.doc_id] = cb
            out.append(seed)
        if not out:
            print(f"[seeds] exhausted - {tier} slot runs seedless")
        return out

    def record(payload: dict, tier: str, slot_no: int) -> None:
        for n, res in enumerate(payload["results"], start=1):
            results.append(res)
            try:
                history.record_attempt(batch_id, tier, slot_no, n, res)
            except Exception as e:                           # noqa: BLE001
                print(f"  [attempts] not recorded (non-fatal): {e}")
        for doc_id, rc_id in payload["consumed"]:
            cb = callbacks.get(doc_id)
            if cb:
                try:
                    cb(rc_id)
                except Exception as e:                       # noqa: BLE001
                    print(f"  [seeds] mark-used failed (non-fatal): {e}")

    stop = False
    pending: dict = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                             initargs=(db, provider, dry_run, embed)) as ex:
        while slots or pending:
            while slots and len(pending) < workers and not stop:
                if spent() >= max_usd:
                    print(f"[batch] spending cap ${max_usd:.2f} reached "
                          f"(spent ${spent():.4f}) - no new slots dispatched.")
                    stop = True
                    break
                tier, slot_no, count = slots.popleft()
                fut = ex.submit(_worker_slot, tier, slot_no, count,
                                draw_seeds(tier), forced_bans,
                                max(0.0, max_usd - spent()))
                pending[fut] = (tier, slot_no)
            if not pending:
                break
            done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                tier, slot_no = pending.pop(fut)
                try:
                    payload = fut.result()
                except Exception as e:                       # noqa: BLE001
                    traceback.print_exc()
                    payload = {"results": [RCResult(None, "", tier, "failed_error",
                                                    notes=[repr(e)])],
                               "consumed": [], "exhausted": False}
                record(payload, tier, slot_no)
                if payload["exhausted"] and not stop:
                    stop = True
                    print("\n[STOP] API exhausted - no new slots dispatched; "
                          "in-flight slots finish, completed work is committed.")
        if stop and slots:
            print(f"[batch] {len(slots)} slot(s) not started.")

    history.clear_inflight()
    summarize_batch(results, batch_id)
    return results
