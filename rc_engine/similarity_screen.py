"""Stage 7 — the reader's-eye similarity screen.

Every other novelty channel in this engine measures a proxy: function-word
frequencies, paragraph-length statistics, commitment curves, blueprint IDs,
rhetorical-move labels. Each of them was, at some point, confidently reporting a
healthy corpus while a human reading the passages saw the same essay over and
over — the oboist/grandmaster pair scored maximally novel on every channel the
engine had, and the four-beat arc that all 32 original families encode was
invisible to a family-KL of 0.13.

This stage does the thing none of them do: it reads the new passage next to the
ones that shipped most recently and asks whether a person would notice. It is
deliberately the LAST gate — everything else has already passed by the time it
runs — and deliberately cheap, so it can afford to look at whole passages
instead of summaries of them.

Verdicts:
    green  — ships to the normal export directory
    red    — ships to config.FLAGGED_EXPORT_DIR instead, for a human to look at
    unchecked — the screen could not run (no key, no package, no corpus yet)

`red` never deletes, blocks, or rewrites anything. It routes.
"""

from __future__ import annotations

import json

from . import config
from .llm import CostLedger, extract_json

NL = chr(10)

SCREEN_SYSTEM = """You are a quality reader for a CAT VARC reading-comprehension set.

You will be given a NEW passage and several REFERENCE passages: recent sets,
older structural neighbours, and other members of its completed batch.
Judge one thing: would an attentive reader working through these in sequence feel
they were reading the same piece again?

Judge the things a reader actually notices:
- the shape of the argument — how it opens, where it turns, how it settles
- recurring sentence formulas ("It would be easy to read this as...", "I am not
  saying X; I am saying Y", three short declaratives in a row for cadence)
- the closing gesture — a quotable maxim, a costed concession, a reopened question
- the kind of opening — a concrete scene or object, an abstract claim, a question

Do NOT judge topic overlap. Two passages about wholly different subjects can be
the same essay in shape, and that is exactly what this screen is for. Two passages
on similar subjects that argue in genuinely different shapes are fine.

CALIBRATION — read this before deciding. Some shared structure is NORMAL, not a
defect. Measured over 124 real CAT/XAT/GMAT reading-comprehension passages:

  - 77% of them open the same way (an abstract claim)
  - 81% of them close the same way (still inside the ongoing argument)
  - 91% explain a mechanism; 53% cite an authority
  - their median pairwise structural similarity is 0.35

So two passages sharing an opening kind, a closing kind, and a couple of middle
moves are as alike as two real exam passages typically are, and that is GREEN.
Reserve "red" for repetition a reader would actually notice as the same essay:
the same distinctive sequence, the same characteristic sentence formulas, the
same unusual gesture — not the ordinary furniture of expository prose.

Be strict about shape and lenient about subject.

Respond ONLY with valid JSON, no markdown fences:
{
  "verdict": "green" | "red",
  "nearest": "<rc_id of the reference passage it most resembles, or null>",
  "shared": ["<specific shared move or formula>", ...],
  "reason": "<one sentence, max 40 words>"
}
Use "red" when a reader would recognise the repetition, "green" otherwise."""


class ScreenUnavailable(RuntimeError):
    pass


def _screen_client():
    """The screen is pinned to its own provider and model, independent of the
    provider the batch ran on. The whole point is a second opinion — running it
    on the model that wrote the passage would ask the same judgement that
    produced the sameness to notice the sameness."""
    from .providers import make_client, provider_key_present

    provider = config.SIMILARITY_SCREEN["provider"]
    if not provider_key_present(provider):
        raise ScreenUnavailable(
            f"no API key for '{provider}' (set "
            f"{'/'.join(config.PROVIDER_ENV_KEYS[provider])} in .env)")
    try:
        return make_client(provider)
    except ImportError as e:
        raise ScreenUnavailable(f"{provider} client not installed ({e})") from e


def screen_passage(new_id: str, new_passage: str,
                   recent: list[tuple[str, str]],
                   ledger: CostLedger | None = None) -> dict:
    """Compare one passage against recent shipped ones.

    recent: [(rc_id, passage), ...], newest first.
    Returns {"verdict", "nearest", "shared", "reason"}; verdict is
    'unchecked' when the screen could not run.
    """
    if not recent:
        return {"verdict": "unchecked", "nearest": None, "shared": [],
                "reason": "no previously shipped passages to compare against"}
    try:
        client = _screen_client()
    except ScreenUnavailable as e:
        return {"verdict": "unchecked", "nearest": None, "shared": [],
                "reason": str(e)}

    cfg = config.SIMILARITY_SCREEN
    blocks = []
    references = recent[:cfg["compare_n"]]
    for rc_id, text in references:
        blocks.append(f"--- REFERENCE {rc_id} ---{NL}{text.strip()}")
    user = (f"NEW PASSAGE ({new_id}):{NL}{new_passage.strip()}{NL}{NL}"
            + (NL + NL).join(blocks))

    ledger = ledger or CostLedger(budget_usd=cfg["max_usd"])
    try:
        text, _ = client.call(ledger, "similarity_screen", cfg["model"],
                              cfg["max_tokens"], SCREEN_SYSTEM, user,
                              context={"passage": new_passage})
        data = extract_json(text)
    except Exception as e:
        # A screen failure must never cost a set that already passed every
        # other gate — but it must never pass silently either.
        print(f"  [screen] {new_id}: check failed ({type(e).__name__}: {e})")
        return {"verdict": "unchecked", "nearest": None, "shared": [],
                "reason": f"screen error: {e}"}

    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("green", "red"):
        verdict = "unchecked"
    nearest = data.get("nearest")
    if nearest is not None and nearest not in {r[0] for r in references}:
        verdict = "unchecked"
    shared = data.get("shared") or []
    return {
        "verdict": verdict,
        "nearest": nearest,
        "shared": [str(x) for x in shared][:6],
        "reason": str(data.get("reason", ""))[:300],
    }


def recent_passages(history, exclude: set[str], limit: int) -> list[tuple[str, str]]:
    """The last `limit` passages of this client, newest first, excluding this
    batch. Per client (2026-09-12): the screen asks whether a set reads like
    what this client already has."""
    from .cli import _parse_rc_txt

    out: list[tuple[str, str]] = []
    for rc_id, rc_text in history.recent_rc_texts():
        if rc_id in exclude:
            continue
        passage = _parse_rc_txt(rc_text)["passage"]
        if passage and len(passage.split()) > 150:
            out.append((rc_id, passage))
        if len(out) >= limit:
            break
    return out


def select_references(candidate: dict, pool: list[dict], batch_ids: set[str],
                      limit: int) -> list[tuple[str, str]]:
    """Bounded, deterministic coverage of siblings, recency and old neighbours.

    The pool is a snapshot, newest first. Ranking uses blind moves/schema, not
    subject matter. Large batches get the closest siblings, not all pairs.
    Missing measurements fall back to recency. No additional model calls.
    """
    from .fingerprints import move_signature_similarity

    if limit <= 0:
        return []
    others = [r for r in pool if r['rc_id'] != candidate['rc_id']]

    def score(row):
        moves = move_signature_similarity(candidate['moves'], row['moves'])
        schema = bool(candidate['schema'] and candidate['schema'] == row['schema'])
        return moves + 0.25 * schema

    siblings = sorted((r for r in others if r['rc_id'] in batch_ids),
                      key=lambda r: (-score(r), r['rc_id']))
    prior = [r for r in others if r['rc_id'] not in batch_ids]
    chosen = siblings[:max(1, limit // 3)]
    remaining = limit - len(chosen)
    recent = prior[:(remaining + 1) // 2]
    chosen.extend(recent)
    used = {r['rc_id'] for r in chosen}
    older = [r for r in prior if r['rc_id'] not in used]
    chosen.extend(sorted(older, key=score, reverse=True)[:limit - len(chosen)])
    used = {r['rc_id'] for r in chosen}
    chosen.extend(r for r in siblings if r['rc_id'] not in used)
    return [(r['rc_id'], r['passage']) for r in chosen[:limit]]


def sibling_review_pairs(results: dict[str, dict]) -> list[tuple[str, str]]:
    """One review item per flagged sibling pair, even for reciprocal reds.

    A repeated pair is not two independently unusable passages. Reviewers can
    retain the stronger member if it otherwise meets the quality requirements.
    """
    return sorted({tuple(sorted((rc_id, res['nearest'])))
                   for rc_id, res in results.items()
                   if res.get('verdict') == 'red'
                   and isinstance(res.get('nearest'), str)
                   and res['nearest'] != rc_id and res['nearest'] in results})


def screen_batch(history, rc_ids: list[str]) -> tuple[dict[str, dict], float]:
    """Screen each set against a fixed snapshot including batch siblings.

    Returns (verdicts, spend_usd). The spend is returned, not just printed, so
    the caller can fold it into the batch total — it used to be dropped.

    Every candidate sees the same completed-batch snapshot; verdict updates do
    not change reference selection. Calls and reference counts stay bounded by
    the existing screen budget.
    """
    if not rc_ids:
        return {}, 0.0
    cfg = config.SIMILARITY_SCREEN
    from .cli import _parse_rc_txt

    pool = history.voice_reference_pool()
    for row in pool:
        row['passage'] = _parse_rc_txt(row['rc_text'])['passage']
    pool = [r for r in pool if r['passage']]
    by_id = {r['rc_id']: r for r in pool}

    ledger = CostLedger(budget_usd=cfg["max_usd"] * max(1, len(rc_ids)))
    results: dict[str, dict] = {}
    print(f"  [screen] {cfg['model']}: references from {len(pool)} client sets")
    for rc_id in rc_ids:
        row = by_id.get(rc_id)
        if not row:
            continue
        passage = row['passage']
        recent = select_references(row, pool, set(rc_ids), cfg['compare_n'])
        before = ledger.spent_usd
        res = screen_passage(rc_id, passage, recent, ledger)
        res['references'] = [ref_id for ref_id, _ in recent]
        results[rc_id] = res
        # The screen is a paid stage like any other, and until 2026-09-02 its
        # spend was printed and then dropped: outside summarize_batch, outside
        # `attempts`, outside `rc_sets`. Every $/shipped-set figure the engine
        # has ever reported was therefore low — 0.75% over this session, always
        # in the same direction. Charged per set here because the screen makes
        # one call per set, so the attribution is exact rather than averaged.
        history.conn.execute(
            "UPDATE rc_sets SET similarity_verdict = ?, similarity_note = ?, "
            "screen_cost_usd = ? WHERE rc_id = ? AND client_id = ?",
            (res["verdict"], json.dumps(res, ensure_ascii=False),
             round(ledger.spent_usd - before, 6), rc_id, history.client_id))
        mark = {"green": "GREEN", "red": "RED  ", "unchecked": "?????"}[res["verdict"]]
        print(f"    [{mark}] {rc_id}"
              + (f" ~ {res['nearest']}" if res.get("nearest") else ""))
        if res["verdict"] == "red":
            for sh in res["shared"]:
                print(f"             shared: {sh}")
            print(f"             {res['reason']}")
        elif res["verdict"] == "unchecked":
            print(f"             {res['reason']}")
    history.conn.commit()
    for left, right in sibling_review_pairs(results):
        print(f"  [screen pair] {left} / {right}: review together; retain the stronger "
              "usable set if appropriate. A mutual red is not a reason to discard both.")
    if ledger.spent_usd:
        print(f"  [screen] spend ${ledger.spent_usd:.4f}")
    return results, ledger.spent_usd
