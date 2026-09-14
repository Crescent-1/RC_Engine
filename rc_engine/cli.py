"""Command-line interface.

  python -m rc_engine.cli estimate              # cost table per tier, $0
  python -m rc_engine.cli selftest              # full mock pipeline run, $0
  python -m rc_engine.cli generate --elite 2 --hard 1 [--no-seed] [--dry-run]
  python -m rc_engine.cli backfill              # fingerprint legacy rc_sets rows, $0
  python -m rc_engine.cli health                # corpus health snapshot, $0
  python -m rc_engine.cli export [--status approved]
  python -m rc_engine.cli avoid [--n 4]         # AVOID line for the manual prompt, $0
  python -m rc_engine.cli vet FILE [--ingest]   # free gates on a manual RC .txt, $0
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys

from . import config
from .fingerprints import move_signature_similarity
from .history import HistoryStore
from .llm import BudgetExceeded, CostLedger, LLMClient, MockLLMClient
from .models import SeedEssay
from .novelty import kl_divergence
from .pipeline import RCPipeline, run_batch
from .registry import ComponentRegistry

NL = chr(10)


# ---------------------------------------------------------------------------
# estimate
# ---------------------------------------------------------------------------

# Every stage that runs on the HAPPY path, in pipeline order. solver_tiebreak
# is deliberately absent: it fires only when the solver disputes the key, so
# counting it here would overstate the normal cost of a set. It is priced
# separately in the conditional line below.
STAGES = ["seed_classify", "refine", "render", "compliance", "move_signature",
          "questions", "answerability", "solver", "judge"]
CONDITIONAL_STAGES = ["solver_tiebreak"]
TYPICAL_OUTPUT_FRACTION = 0.6


def _effective_model(stage: str, tier: str) -> tuple[str, int]:
    """The model a stage will ACTUALLY use, honouring STAGE_MODEL_PINS and the
    same availability fallback the router applies at run time. An estimate that
    priced the unpinned model would understate a pinned run and overstate an
    unavailable one — and this table is what the budget headroom is read from."""
    model, max_tok = config.STAGE_CONFIG[stage][tier]
    pin = config.resolve_stage_pin(stage, tier)
    if pin:
        from .providers import provider_key_present
        provider, pinned_model = pin
        if provider_key_present(provider) and pinned_model in config.MODEL_RATES:
            return pinned_model, max_tok
    return model, max_tok


def _stage_cost(stage: str, tier: str, worst: bool) -> float:
    model, max_tok = _effective_model(stage, tier)
    rin, rout = config.MODEL_RATES[model]
    est_in = config.ESTIMATED_INPUT_TOKENS[stage]
    out_tok = max_tok if worst else int(max_tok * TYPICAL_OUTPUT_FRACTION)
    return est_in / 1e6 * rin + out_tok / 1e6 * rout


def cmd_estimate(_args) -> int:
    provider = getattr(_args, "provider", None) or "claude"
    config.set_provider(provider)
    if provider != "claude":
        m = config.PROVIDER_MODELS[provider]
        print(f"[provider] {provider}: big={m['big']} mid={m['mid']} small={m['small']}")
    ok = True
    print(f"{'tier':8s} {'stage':12s} {'model':28s} {'typical':>9s} {'worst':>9s}")
    for tier in ("medium", "hard", "elite"):
        happy = 0.0
        worst_uncapped = 0.0
        for stage in STAGES:
            model, _ = _effective_model(stage, tier)
            t = _stage_cost(stage, tier, worst=False)
            w = _stage_cost(stage, tier, worst=True)
            attempts = {"render": config.MAX_RENDER_ATTEMPTS,
                        "compliance": config.MAX_RENDER_ATTEMPTS,
                        "questions": config.MAX_QUESTION_ATTEMPTS,
                        "judge": config.MAX_JUDGE_ATTEMPTS}.get(stage, 1)
            happy += t
            worst_uncapped += w * attempts
            print(f"{tier:8s} {stage:12s} {model:28s} {t:>9.4f} {w:>9.4f} (x{attempts} worst)")
        for stage in CONDITIONAL_STAGES:
            model, _ = _effective_model(stage, tier)
            t = _stage_cost(stage, tier, worst=False)
            print(f"{tier:8s} {stage:12s} {model:28s} {t:>9.4f} "
                  f"{'':>9s} (only on a solver dispute)")
        budget = config.TIER_BUDGET_USD[tier]
        capped = min(worst_uncapped, budget)
        print(f"{tier:8s} {'TOTAL':12s} {'happy path':28s} {happy:>9.4f}")
        print(f"{tier:8s} {'TOTAL':12s} {'worst uncapped / enforced cap':28s} "
              f"{worst_uncapped:>9.4f} / {budget:.2f}")
        if happy > budget:
            print(f"  !! happy path ${happy:.4f} exceeds budget ${budget:.2f} - "
                  f"RCs would abort mid-generation. Fix config.")
            ok = False
        else:
            headroom = budget - happy
            print(f"  OK: happy path ${happy:.4f} <= budget ${budget:.2f} "
                  f"(headroom ${headroom:.4f} for retries; hard cap enforced pre-call)")
        print()
    print("Guarantee: CostLedger.guard() blocks any call whose worst case would "
          "push an RC past its cap — actual spend per RC can never exceed the cap.")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# selftest ($0)
# ---------------------------------------------------------------------------

class _FlakyQuestionsMock(MockLLMClient):
    """Mock whose questions stage returns invalid JSON the first N calls —
    exercises the failed_questions -> rendered_passages -> resume path."""

    def __init__(self, fail_times: int):
        super().__init__()
        self.fail_remaining = fail_times

    def _questions(self, ctx) -> str:
        if self.fail_remaining > 0:
            self.fail_remaining -= 1
            return "THIS IS NOT JSON"
        return super()._questions(ctx)


def cmd_selftest(_args) -> int:
    import tempfile
    failures = []

    print("[1/5] Component library validation...")
    try:
        reg = ComponentRegistry()
        counts = {t: len(reg.ids(t)) for t in reg.libraries}
        print(f"      OK: {counts}")
    except Exception as e:
        print(f"      FAIL: {e}")
        return 1

    print("[2/5] Cost model sanity (happy path within budget for every tier)...")
    if cmd_estimate(None) != 0:
        failures.append("estimate")

    print("[2b] Provider resolution (all providers resolve with rates, $0)...")
    try:
        for prov in config.PROVIDERS:
            config.set_provider(prov)
            for stage, tiers in config.STAGE_CONFIG.items():
                for tier, (model, _mt) in tiers.items():
                    if model not in config.MODEL_RATES:
                        failures.append(f"{prov}: {stage}/{tier} model "
                                        f"{model!r} missing from MODEL_RATES")
        if not any("MODEL_RATES" in f for f in failures):
            print(f"      OK: {', '.join(config.PROVIDERS)}")
    finally:
        config.set_provider(config.DEFAULT_PROVIDER)

    print("[3/5] Budget guard unit check...")
    ledger = CostLedger(budget_usd=0.01)
    try:
        ledger.guard("questions", 20000, config.OPUS, 3200)
        failures.append("budget guard did not trip")
        print("      FAIL: guard did not trip")
    except BudgetExceeded:
        print("      OK: guard raised BudgetExceeded before any spend")

    print("[4/5] Mock end-to-end pipeline (3 RCs, $0, temp DB)...")
    fd, tmpdb = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(tmpdb)
    try:
        history = HistoryStore(tmpdb)
        pipe = RCPipeline(history, MockLLMClient(), embed=False)
        results = run_batch(pipe, {"elite": 2, "medium": 1})
        shipped = [r for r in results if r.rc_id]
        if len(shipped) != 3:
            failures.append(f"expected 3 shipped RCs, got {len(shipped)}")
        for r in shipped:
            if r.cost_usd != 0.0:
                failures.append(f"{r.rc_id}: mock run cost != 0")
        # distinct component tuples enforced?
        combos = {row[0] for row in history.conn.execute(
            "SELECT combo_hash FROM blueprints WHERE status='shipped'")}
        if len(combos) != len(shipped):
            failures.append("duplicate combo hashes shipped")
        # fingerprints + audits recorded?
        n_fp = history.conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
        n_audit = history.conn.execute("SELECT COUNT(*) FROM novelty_audits").fetchone()[0]
        if n_fp < 3 or n_audit < 3:
            failures.append(f"missing fingerprints ({n_fp}) or audits ({n_audit})")
        # rc_text structurally complete?
        for (rc_text,) in history.conn.execute("SELECT rc_text FROM rc_sets"):
            for marker in ("[PASSAGE]", "[QUESTIONS]", "[ANSWER KEY", "Q6."):
                if marker not in rc_text:
                    failures.append(f"rc_text missing {marker}")
        history.close()
    finally:
        if os.path.exists(tmpdb):
            os.unlink(tmpdb)

    print("[5/5] Questions-fail -> resume path (flaky mock, $0, temp DB)...")
    fd, tmpdb = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(tmpdb)
    try:
        history = HistoryStore(tmpdb)
        flaky = _FlakyQuestionsMock(fail_times=config.MAX_QUESTION_ATTEMPTS)
        pipe = RCPipeline(history, flaky, embed=False)
        res = pipe.generate_one("elite")
        if res.status != "failed_questions":
            failures.append(f"flaky mock: expected failed_questions, got {res.status}")
        else:
            row = history.conn.execute(
                "SELECT status, spent_usd FROM rendered_passages WHERE blueprint_id = ?",
                (res.blueprint_id,)).fetchone()
            if not row or row[0] != "questions_failed":
                failures.append(f"flaky mock: rendered_passages status "
                                f"{row[0] if row else None!r}, expected questions_failed")
            res2 = pipe.resume_questions(res.blueprint_id)
            if res2.rc_id is None or res2.status not in ("approved", "needs_review",
                                                         "solver_dispute"):
                failures.append(f"resume: expected a shipped RC, got {res2.status}")
            row2 = history.conn.execute(
                "SELECT status FROM rendered_passages WHERE blueprint_id = ?",
                (res.blueprint_id,)).fetchone()
            if not row2 or row2[0] != "consumed":
                failures.append(f"resume: passage status "
                                f"{row2[0] if row2 else None!r}, expected consumed")
            if res2.rc_id and row:
                total = history.conn.execute(
                    "SELECT total_cost_usd FROM rc_sets WHERE rc_id = ?",
                    (res2.rc_id,)).fetchone()[0]
                if abs(total - (row[1] + res2.cost_usd)) > 1e-9:
                    failures.append(f"resume: rc_sets total ${total} != prior "
                                    f"${row[1]} + new ${res2.cost_usd}")
            if not failures:
                print(f"      OK: failed_questions persisted; resume shipped "
                      f"{res2.rc_id} ({res2.status}) without re-rendering")
        history.close()
    finally:
        if os.path.exists(tmpdb):
            os.unlink(tmpdb)

    print()
    if failures:
        print("SELFTEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELFTEST PASSED - pipeline is runnable end-to-end; cost guard active; "
          "libraries valid.")
    return 0


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _report_all_in(results, screen_usd: float) -> None:
    """Restate the batch total with the screen included.

    summarize_batch necessarily prints BEFORE the screen runs (the screen needs
    the sets to be in rc_sets), so its total cannot contain the screen. Rather
    than reorder the pipeline, the true figure is stated once here — otherwise
    the last cost number on screen is the wrong one, which is the number people
    quote."""
    if not screen_usd:
        return
    gen = sum(getattr(r, "cost_usd", 0.0) or 0.0 for r in results)
    n = sum(1 for r in results if getattr(r, "rc_id", None))
    total = gen + screen_usd
    print(f"  all-in incl. screen  ${total:.4f} "
          f"(generation ${gen:.4f} + screen ${screen_usd:.4f})"
          + (f" | ${total / n:.4f} per shipped set" if n else ""))


# Module-level so the share ceiling is a stable stream across a batch rather
# than reseeded per call.
_SEED_RNG = random.Random()


def _load_seed_ids(path: str) -> list[str]:
    """Seed doc ids from a file: a JSON list, a JSON object whose values are
    lists or {id: label} maps (grouped by subject), or one id per text line."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    ids: list[str] = []

    def walk(node):
        if isinstance(node, str):
            ids.append(node)
        elif isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k == "note":
                    continue
                if isinstance(v, str) and len(k) >= 16:     # {doc_id: label}
                    ids.append(k)
                else:
                    walk(v)
    walk(data)
    return list(dict.fromkeys(ids))


def _allowlist_seed_picker(db, seed_ids: list[str]):
    """get_unused_essay restricted to an explicit list of doc ids (2026-09-14,
    `generate --seed-ids`): an operator's subject choice — e.g. only philosophy
    and literature — which the store cannot express, since it has no subject
    field. The list overrides the tier's publication pool; used, excluded and
    avoided-kind rules still apply, with the same never-dead-end fallback."""
    import random as _random

    def pick(exclude_ids=None, avoid_kinds=None):
        got = db.get(ids=list(seed_ids), include=["documents", "metadatas"])
        cands = [{"id": i, "text": d, "metadata": m or {}}
                 for i, d, m in zip(got.get("ids") or [], got.get("documents") or [],
                                    got.get("metadatas") or [])
                 if not (m or {}).get("used") and i not in set(exclude_ids or ())]
        if avoid_kinds:
            steered = [c for c in cands if c["metadata"].get("kind") not in set(avoid_kinds)]
            cands = steered or cands
        return _random.choice(cands) if cands else None
    return pick


def _make_seed_provider(seed_ids: list[str] | None = None, subjects=None, genres=None):
    try:
        from RAG import get_db, get_unused_essay, mark_essay_used  # noqa: legacy module
    except Exception as e:
        print(f"[seeds] RAG unavailable ({e}) - running seedless")
        return None
    from .seed_labels import from_metadata, labelled_pool
    db = get_db()
    if subjects or genres:
        # 2026-09-14: pick by stored labels instead of a hand-built id list.
        pool = labelled_pool(db, subjects, genres, config.SEED_MIN_CARRIABLE_SHAPES)
        if seed_ids:
            pool = [i for i in pool if i in set(seed_ids)]
        print(f"[seeds] {len(pool)} unused labelled essays match subject={subjects or 'any'} "
              f"genre={genres or 'any'} (>= {config.SEED_MIN_CARRIABLE_SHAPES} carriable shapes)")
        if not pool:
            # 2026-09-14 review: an empty pool used to run the batch seedless,
            # i.e. off-subject. Refuse instead; the caller aborts the run.
            print("[seeds] no unused labelled essay matches - nothing to generate "
                  "(run `seeds classify` after a sync, or widen --subject/--genre)")
            return "empty"
        seed_ids = pool
    allowlisted = _allowlist_seed_picker(db, seed_ids) if seed_ids else None

    def provider(tier: str | None = None, exclude_ids=None, avoid_kinds=None):
        if allowlisted is not None:
            essay = allowlisted(exclude_ids, avoid_kinds)
            if essay is None:
                print("[seeds] --seed-ids list has no unused essay left - seedless this slot")
                return None, None
            genre = essay["metadata"].get("genre")
            print(f"[seeds] {tier or 'any'} <- [{genre}] {essay['metadata'].get('title')} (listed)")
            seed = SeedEssay(doc_id=essay["id"], url=essay["metadata"].get("url"),
                             title=essay["metadata"].get("title"),
                             text=essay["text"], domain_hint=genre,
                             labels=from_metadata(essay["metadata"]))
            return seed, (lambda rc_id, _id=essay["id"]: mark_essay_used(db, _id, rc_id))
        # Hard/elite: random draw inside the tier's pool only (strict by
        # default). Medium: any unused genre. exclude_ids = batch-slot rotations.
        preferred = config.TIER_SEED_GENRES.get(tier) if tier else None
        # Hold each capped kind to its exact share by steering BOTH ways: on a
        # winning flip restrict TO it, on a losing flip restrict AWAY. A
        # permit-only flip would multiply the flip by the kind's base rate in
        # the pool and land under the ceiling — see SEED_KIND_MAX_SHARE.
        only_kinds = None
        steer_away: list[str] = []
        for kind, cap in getattr(config, "SEED_KIND_MAX_SHARE", {}).items():
            if _SEED_RNG.random() < cap:
                only_kinds = [kind]
            else:
                steer_away.append(kind)
        avoid = sorted(set(avoid_kinds or ()) | set(steer_away)) or None
        essay = get_unused_essay(db, genre=preferred, exclude_ids=exclude_ids,
                                 randomize=True, avoid_kinds=avoid,
                                 only_kinds=only_kinds)
        strict = getattr(config, "TIER_SEED_STRICT", True)
        if essay is None and preferred is not None and not strict:
            essay = get_unused_essay(db, genre=None, exclude_ids=exclude_ids,
                                     randomize=True, avoid_kinds=avoid,
                                     only_kinds=only_kinds)
            if essay is not None:
                print(f"[seeds] preferred pool empty for '{tier}' - "
                      f"fallback any genre (TIER_SEED_STRICT=False)")
        if essay is None:
            if preferred is not None and strict:
                print(f"[seeds] no unused CAT-quality essays for '{tier}' "
                      f"(strict pool) — seedless this slot")
            return None, None

        genre = essay["metadata"].get("genre")
        print(f"[seeds] {tier or 'any'} <- [{genre}] {essay['metadata'].get('title')}")
        seed = SeedEssay(doc_id=essay["id"], url=essay["metadata"].get("url"),
                         title=essay["metadata"].get("title"),
                         text=essay["text"], domain_hint=genre,
                         labels=from_metadata(essay["metadata"]))

        def on_success(rc_id):
            mark_essay_used(db, essay["id"], rc_id)
        return seed, on_success

    # 2026-09-14 review: a restricted draw (--subject/--genre/--seed-ids) skips a
    # slot when it runs dry instead of generating seedless (run_slot, workers).
    provider.restricted = allowlisted is not None
    return provider


def _setup_provider(args) -> tuple[object | None, int]:
    """Resolve the run's provider and build its client.

    Returns (client, exit_code); client is None when the provider's API key
    is missing (exit_code carries the CLI failure). Dry-run always gets the
    $0 mock regardless of provider."""
    provider = getattr(args, "provider", "claude")
    config.set_provider(provider)
    if getattr(args, "dry_run", False):
        return MockLLMClient(), 0
    from .providers import (make_client, provider_key_present,
                            provider_key_source, verify_key)
    var = provider_key_present(provider)
    if not var:
        keys = " or ".join(config.PROVIDER_ENV_KEYS[provider])
        print(f"{keys} not set (environment or .env).")
        return None, 1
    m = config.PROVIDER_MODELS[provider]
    print(f"[provider] {provider}: big={m['big']} mid={m['mid']} small={m['small']}")
    print(f"[provider] key from {var} <- {provider_key_source(provider)}")

    # Say it loudly: a shadowed .env value means the run is about to spend
    # money on a credential the operator probably did not intend to use.
    for name in config.shadowing_conflicts():
        print(f"[provider] !! WARNING: {name} in your environment is DIFFERENT "
              f"from the value in .env, and the environment wins. .env is being "
              f"ignored for {name}.")

    # Free pre-flight: fail before the first paid call, not partway through.
    ok, detail = verify_key(provider)
    if not ok:
        print(f"[provider] !! ABORT: key check failed - {detail}")
        if config.shadowing_conflicts():
            print("[provider]    Most likely cause: the shadowing warning above. "
                  "Clear the stale variable so .env is used, or set it to the "
                  "correct key, then restart this process.")
        return None, 1
    print(f"[provider] key check: {detail}")
    # Wrap so cheap CHECKING stages can run on their own pinned model while
    # refine/render/questions stay on the batch's provider. Falls back to the
    # wrapped client whenever a pin is unusable — see providers.RoutedClient.
    from .providers import RoutedClient
    return RoutedClient(make_client(provider)), 0


# ---------------------------------------------------------------------------
# clients (2026-09-12) — one DB, a novelty window per client
# ---------------------------------------------------------------------------

# The --from-txt defaults are the founding client's delivery folders. For any
# other client they would pull the founding client's sets into a corpus that
# is meant to start empty, so other clients get no default at all.
_BACKFILL_TXT_DIRS = ["exported_rc_sets", "approved_rc_sets - Copy"]
_MOVE_AUDIT_TXT_DIRS = ["exported_rc_sets", "approved_rc_sets - Copy", "manual_rc_sets"]


def _open_store(args, db: str | None = None):
    """HistoryStore for this command's --client, or None (after saying why)
    when the client is unknown. Never silently falls back to another client."""
    from .history import UnknownClientError
    try:
        return HistoryStore(db or args.db, getattr(args, "client", None))
    except UnknownClientError as e:
        print(f"[client] {e}")
        return None


def cmd_policy_report(args) -> int:
    """$0. Plan 7.5 metrics by client, tier and generation policy. Only SELECTs;
    opening the store applies HistoryStore's usual additive migrations."""
    from .policy_report import collect, format_rows
    history = _open_store(args)
    if history is None:
        return 2
    rows = collect(history, "all" if args.all_clients else "client")
    history.close()
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print(format_rows(rows) if rows else "[policy-report] no sets or attempts")
    return 0


def _export_dir(client_id: str | None, dry_run: bool) -> str:
    """The founding client keeps the folder layout its deliveries and trackers
    already use; every other client gets its own subfolder. Nothing existing
    is moved."""
    root = "exported_rc_sets_dryrun" if dry_run else "exported_rc_sets"
    client_id = client_id or config.DEFAULT_CLIENT_ID
    if client_id == config.FOUNDING_CLIENT_ID:
        return root
    return os.path.join(root, client_id)


def _flagged_dir(client_id: str | None, out: str) -> str:
    if (client_id or config.DEFAULT_CLIENT_ID) == config.FOUNDING_CLIENT_ID:
        return config.FLAGGED_EXPORT_DIR
    return os.path.join(out, "flagged_similar")


def _txt_dirs(given: list[str] | None, client_id: str, founding_defaults: list[str]) -> list[str]:
    if given is not None:
        return given
    return list(founding_defaults) if client_id == config.FOUNDING_CLIENT_ID else []


def _apply_generation_policy(version: str) -> int:
    """Opt this run's new medium/hard plans into a registered policy (or back
    to legacy with ''). Sets the environment too, so spawned workers, which
    re-import config, compose under the same policy. Returns 0 or an exit code."""
    from .generation_policy import PolicyError, get_policy
    version = (version or "").strip()
    try:
        policy = get_policy(version)
    except PolicyError as e:
        print(f"[policy] {e}")
        return 2
    for tier in ("medium", "hard"):
        if tier not in policy.tiers:
            print(f"[policy] {version!r} does not admit {tier}")
            return 2
    os.environ["RC_ENGINE_NEW_PLAN_POLICY"] = version
    config.GENERATION_POLICY_FOR_NEW_PLANS = {
        "medium": version, "hard": version,
        "elite": config.GENERATION_POLICY_FOR_NEW_PLANS.get("elite", "")}
    return 0


def _apply_elite_policy(version: str) -> int:
    """2026-09-14: opt this run's new elite plans into a legacy-based policy
    (legacy-sf1). Anything else is refused, not silently read as legacy."""
    from .generation_policy import PolicyError, get_policy
    version = (version or "").strip()
    try:
        policy = get_policy(version)
    except PolicyError as e:
        print(f"[policy] {e}")
        return 2
    if version and not (policy.legacy_base and "elite" in policy.tiers):
        print(f"[policy] {version!r} is not a legacy-based policy; elite may only take one")
        return 2
    os.environ["RC_ENGINE_ELITE_PLAN_POLICY"] = version
    config.GENERATION_POLICY_FOR_NEW_PLANS = {**config.GENERATION_POLICY_FOR_NEW_PLANS,
                                              "elite": version}
    return 0


def cmd_generate(args) -> int:
    tier_counts = {t: getattr(args, t) for t in ("medium", "hard", "elite")
                   if getattr(args, t) > 0}
    if not tier_counts:
        print("Nothing to generate. Use --medium/--hard/--elite N.")
        return 1

    llm, err = _setup_provider(args)
    if llm is None:
        return err
    if args.dry_run:
        if args.db == config.DB_PATH:
            args.db = "rc_engine_dryrun.db"   # never pollute the production DB with mock RCs
        print(f"[dry-run] Using MockLLMClient - $0, no API calls. DB: {args.db}")
    if getattr(args, "generation_policy", None) is not None:
        err = _apply_generation_policy(args.generation_policy)
        if err:
            return err
    if getattr(args, "elite_policy", None) is not None:
        err = _apply_elite_policy(args.elite_policy)
        if err:
            return err
    print("[policy] new plans: " + ", ".join(
        f"{t}={config.GENERATION_POLICY_FOR_NEW_PLANS.get(t) or 'legacy'}"
        for t in tier_counts))

    history = _open_store(args)
    if history is None:
        return 2
    print(f"[client] {history.client_id} - novelty window and exports are this "
          f"client's; skeletons and seed essays are exclusive across clients")
    # dry-run passages are canned filler text — the embedding channel would
    # (correctly) reject them as duplicates, which only confuses a $0 test
    embed = not (args.no_embed or args.dry_run)
    pipe = RCPipeline(history, llm, embed=embed)
    seed_ids = None
    if getattr(args, "seed_ids", None):
        seed_ids = _load_seed_ids(args.seed_ids)
        print(f"[seeds] restricted to {len(seed_ids)} listed seed essays ({args.seed_ids})")
    subjects = [x for x in (getattr(args, "subject", None) or "").split(",") if x.strip()]
    genres = [x for x in (getattr(args, "genre", None) or "").split(",") if x.strip()]
    provider = None if (args.no_seed or args.dry_run) else _make_seed_provider(
        seed_ids, subjects=subjects, genres=genres)
    if provider == "empty":
        history.close()
        return 1
    workers = max(1, min(int(getattr(args, "workers", 1) or 1), config.BATCH_WORKERS_MAX))
    if workers > 1:
        # The parent's client is only used for the key check above; workers
        # build their own. The parent's history records attempts and owns the
        # seed store (mark-used callbacks run here, never in a worker).
        from .workers import run_parallel
        results = run_parallel(history, tier_counts, workers,
                               db=args.db, provider=args.provider,
                               dry_run=bool(args.dry_run), embed=embed,
                               seed_provider=provider, max_usd=args.max_usd,
                               only_posture=getattr(args, "only_posture", None),
                               client_id=history.client_id)
    else:
        results = run_batch(pipe, tier_counts, provider, max_usd=args.max_usd,
                            only_posture=getattr(args, "only_posture", None))

    # The similarity screen runs after generation and before export, so a set
    # that reads like the last ten lands in a different folder rather than
    # quietly joining the batch. See rc_engine/similarity_screen.py.
    # "has an rc_id" is not "shipped": a set rejected at the parallel ship lock
    # has both an id and an rc_sets row. Screening those spends money on work
    # that will never be exported and writes a verdict onto a dead row.
    shipped_ids = [r.rc_id for r in results
                   if r.rc_id and r.status in config.SHIPPING_STATUSES]
    if shipped_ids and not args.dry_run and not args.no_screen:
        from .similarity_screen import screen_batch
        _, screen_usd = screen_batch(history, shipped_ids)
        _report_all_in(results, screen_usd)

    if not args.no_export:
        out_dir = _export_dir(history.client_id, args.dry_run)
        cmd_export(argparse.Namespace(db=args.db, status=None, out=out_dir,
                                      client=history.client_id))
    if not args.dry_run:
        history.backup_to()
    history.close()
    return 0 if any(r.rc_id for r in results) else 1


# ---------------------------------------------------------------------------
# retry-questions — regenerate questions on a persisted, novelty-clean passage
# ---------------------------------------------------------------------------

def cmd_retry_questions(args) -> int:
    if args.dry_run or args.blueprint or args.all:
        llm, err = _setup_provider(args)
        if llm is None:
            return err
        if args.dry_run:
            if args.db == config.DB_PATH:
                args.db = "rc_engine_dryrun.db"
            print(f"[dry-run] Using MockLLMClient - $0, no API calls. DB: {args.db}")
    else:
        config.set_provider(getattr(args, "provider", "claude"))
        llm = None                      # list mode is free — no client needed

    history = _open_store(args)
    if history is None:
        return 2
    rows = history.load_resumable_passages()

    if not args.blueprint and not args.all:
        if not rows:
            print("No resumable passages (status='questions_failed').")
        else:
            print(f"{len(rows)} resumable passage(s) - re-run with "
                  f"--blueprint BP_ID or --all:")
            for r in rows:
                try:
                    topic = json.loads(r["blueprint_json"]).get("topic", "")
                except (ValueError, TypeError):
                    topic = ""
                print(f"  {r['blueprint_id']} | {r['tier']:6s} | "
                      f"spent ${r['spent_usd']:.4f} | {r['created_at'][:16]} | "
                      f"{topic[:60]}")
                if r["fail_notes"]:
                    print(f"      failed: {r['fail_notes'][:110]}")
        history.close()
        return 0

    targets = [r["blueprint_id"] for r in rows] if args.all else [args.blueprint]
    if not targets:
        print("Nothing to resume.")
        history.close()
        return 0
    pipe = RCPipeline(history, llm, embed=not (args.no_embed or args.dry_run))
    shipped = 0
    shipped_ids: list[str] = []
    # 2026-09-14: `results` was never defined here, so every real resume that
    # shipped crashed in _report_all_in after the screen and skipped the export.
    results = []
    for bp_id in targets:
        print(f"\n=== retry-questions {bp_id} ===")
        res = pipe.resume_questions(bp_id, extra_guidance=args.note)
        results.append(res)
        print(f"  -> {res.status} rc_id={res.rc_id} "
              f"new spend ${res.cost_usd:.4f}")
        for n in res.notes:
            print(f"     {n}")
        if res.rc_id and res.status in config.SHIPPING_STATUSES:
            shipped += 1
            shipped_ids.append(res.rc_id)
    if shipped_ids:
        if not args.dry_run and not getattr(args, "no_screen", False):
            from .similarity_screen import screen_batch
            _, screen_usd = screen_batch(history, shipped_ids)
            _report_all_in(results, screen_usd)
        out_dir = _export_dir(history.client_id, args.dry_run)
        cmd_export(argparse.Namespace(db=args.db, status=None, out=out_dir,
                                      client=history.client_id))
    history.close()
    return 0 if shipped else 1


# ---------------------------------------------------------------------------
# backfill — local-only fingerprints for legacy rc_sets rows
# ---------------------------------------------------------------------------

def _legacy_fingerprint(rc_id: str, rc_text: str, emb_json: str | None,
                        source: str = "legacy"):
    from .fingerprints import (parse_answer_letters, rhythm_vector,
                               stylometry_profile, _embed)
    from .models import Fingerprint

    m = re.search(r"\nQ\s*1\b", rc_text)
    passage = rc_text[:m.start()] if m else rc_text
    passage = re.sub(r"\[PASSAGE\]", "", passage)
    # strip export header ("RC ID: ... ====== ")
    passage = re.sub(r"^RC ID:.*?={10,}\s*", "", passage, flags=re.DOTALL).strip()
    embedding = json.loads(emb_json) if emb_json else _embed(passage)
    return Fingerprint(
        rc_id=rc_id, blueprint_id="", persona_id="",
        movement_string="LEGACY_UNKNOWN",
        commitment_curve=[0.0, 0.0, 0.0],
        rhythm_vector=rhythm_vector(passage),
        topology_signature=[], trap_histogram={},
        letter_sequence=parse_answer_letters(rc_text),
        stylometry=stylometry_profile(passage),
        embedding=embedding,
        source=source)


def _passage_sources(history, dirs: list[str]) -> dict:
    """rc_id -> passage text, from the DB first then the exported .txt corpora.
    Only ~half the fingerprint rows have rc_text in rc_sets (the legacy/manual
    ones were themselves backfilled from txt), so both sources are needed to
    cover the corpus."""
    out: dict[str, str] = {}
    for rc_id, rc_text in history.conn.execute(
            """SELECT rc_id, rc_text FROM rc_sets
               WHERE rc_id IS NOT NULL AND rc_text IS NOT NULL"""):
        out[rc_id] = _parse_rc_txt(rc_text)["passage"]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith(".txt"):
                continue
            with open(os.path.join(d, fname), encoding="utf-8",
                      errors="replace") as f:
                text = f.read()
            m = re.search(r"RC ID:\s*(\S+)", text)
            rc_id = m.group(1) if m else os.path.splitext(fname)[0]
            passage = _parse_rc_txt(text)["passage"]
            # DB text wins only if it actually parsed to something usable
            if passage and len(passage.split()) > 150 and not out.get(rc_id):
                out[rc_id] = passage
    return out


def cmd_move_audit(args) -> int:
    """Extract the blind rhetorical-move signature for every fingerprint that
    lacks one, then report how much of the corpus shares a grammar. $0 for rows
    already extracted; sub-cent per new row."""
    from .compliance import ComplianceAuditor
    from .llm import CostLedger, LLMClient, MockLLMClient
    from .registry import ComponentRegistry

    config.set_provider(getattr(args, "provider", None) or "claude")
    history = _open_store(args)
    if history is None:
        return 2
    cid = history.client_id
    rows = history.conn.execute(
        """SELECT rc_id, move_signature FROM fingerprints WHERE client_id = ?
           ORDER BY created_at ASC""", (cid,)).fetchall()
    if getattr(args, "reextract", False):
        # The move vocabulary is versioned by meaning, not by name: narrowing a
        # label (LEVEL_RELOCATION, 2026-08-22) makes every stored signature a
        # mix of old and new definitions, and saturation figures computed across
        # that mix are not comparable. Clear and re-read rather than top up.
        history.conn.execute("UPDATE fingerprints SET move_signature = '' "
                             "WHERE client_id = ?", (cid,))
        history.conn.commit()
        rows = [(r[0], "") for r in rows]
        print("[move-audit] --reextract: cleared stored signatures")
    todo = [r[0] for r in rows if not (r[1] or "").strip()]
    print(f"[move-audit] {len(rows)} fingerprints, {len(todo)} without a signature")

    if todo and not args.report_only:
        passages = _passage_sources(
            history, _txt_dirs(args.from_txt, cid, _MOVE_AUDIT_TXT_DIRS))
        llm = MockLLMClient() if args.dry_run else LLMClient()
        auditor = ComplianceAuditor(llm, ComponentRegistry())
        ledger = CostLedger(budget_usd=args.max_usd)
        # Each set is re-read with the closed vocabulary of the policy its plan
        # was composed under (2026-09-13). A legacy re-read of a policy set would
        # erase the beats only that policy can name. Sets with no stored plan
        # (manual, legacy imports) read with the legacy vocabulary as before.
        from .generation_policy import PolicyError, get_policy
        versions = history.policy_versions_by_rc_id()
        done = missing = skipped = 0
        for rc_id in todo:
            passage = passages.get(rc_id)
            if not passage or len(passage.split()) < 150:
                missing += 1
                continue
            try:
                policy = get_policy(versions.get(rc_id, ""))
            except PolicyError as e:
                print(f"  [{rc_id}] skipped: {e}")
                skipped += 1
                continue
            try:
                moves = auditor.move_signature(passage, ledger, "hard", policy=policy)
            except Exception as e:
                print(f"  [{rc_id}] extraction failed: {e}")
                break
            if not moves:
                continue
            history.conn.execute(
                "UPDATE fingerprints SET move_signature=? WHERE rc_id=?",
                ("|".join(moves), rc_id))
            done += 1
        history.conn.commit()
        print(f"[move-audit] extracted {done}, no passage found for {missing}, "
              f"unknown policy {skipped}, spend ${ledger.spent_usd:.4f}")

    # ---- report -----------------------------------------------------------
    sigs = {r[0]: (r[1] or "").split("|")
            for r in history.conn.execute(
                """SELECT rc_id, move_signature FROM fingerprints
                   WHERE move_signature IS NOT NULL AND move_signature != ''
                     AND client_id = ?""", (cid,))}
    if not sigs:
        print("[move-audit] no signatures on record yet")
        history.close()
        return 1

    print(f"{NL}--- move frequency across {len(sigs)} sets ---")
    freq: dict[str, int] = {}
    for moves in sigs.values():
        for m in set(moves):
            freq[m] = freq.get(m, 0) + 1
    for m, n in sorted(freq.items(), key=lambda kv: -kv[1]):
        share = n / len(sigs)
        bar = "#" * int(share * 40)
        print(f"  {m:26s} {n:3d}/{len(sigs)} {share:5.0%} {bar}")

    unused = [m for m in config.RHETORICAL_MOVES if m not in freq]
    if unused:
        print(f"{NL}  never used: {', '.join(unused)}")

    print(f"{NL}--- nearest pairs (rarity-weighted overlap) ---")
    pairs = []
    ids = sorted(sigs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim = move_signature_similarity(sigs[ids[i]], sigs[ids[j]], freq, len(sigs))
            pairs.append((sim, ids[i], ids[j]))
    pairs.sort(reverse=True)
    for sim, a, b in pairs[:args.top]:
        print(f"  {sim:.2f}  {a}  ~  {b}")
    vals = [p[0] for p in pairs]
    vals.sort()
    def pct(q):
        return vals[min(len(vals) - 1, int(len(vals) * q))]
    print(f"{NL}  distribution: p50={pct(0.50):.2f} p90={pct(0.90):.2f} "
          f"p95={pct(0.95):.2f} p99={pct(0.99):.2f} max={vals[-1]:.2f}")
    print(f"  current cap: {config.MOVE_SIGNATURE_CAPS['move_signature_sim']:.2f} "
          f"-> would reject {sum(1 for v in vals if v > config.MOVE_SIGNATURE_CAPS['move_signature_sim'])}"
          f"/{len(vals)} pairs")

    if args.quarantine:
        n = _quarantine_redundant(history, sigs, freq,
                                  config.MOVE_SIGNATURE_CAPS["move_signature_sim"])
        print(f"{NL}[move-audit] quarantined {n} set(s) from the novelty baseline "
              f"(rows kept, exports untouched)")
    history.close()
    return 0


def _quarantine_redundant(history, sigs: dict, freq: dict, cap: float) -> int:
    """Keep the EARLIEST member of each over-similar cluster in the novelty
    window and hide the rest. Nothing is deleted; `quarantined` only filters
    HistoryStore.fingerprint_window."""
    order = [r[0] for r in history.conn.execute(
        "SELECT rc_id FROM fingerprints WHERE client_id = ? ORDER BY created_at ASC",
        (history.client_id,)) if r[0] in sigs]
    kept: list[str] = []
    drop: list[str] = []
    for rc_id in order:
        if any(move_signature_similarity(sigs[rc_id], sigs[k], freq, len(sigs)) > cap
               for k in kept):
            drop.append(rc_id)
        else:
            kept.append(rc_id)
    for rc_id in drop:
        history.conn.execute(
            "UPDATE fingerprints SET quarantined=1 WHERE rc_id=?", (rc_id,))
    history.conn.commit()
    return len(drop)


def cmd_backfill(args) -> int:
    history = _open_store(args)
    if history is None:
        return 2
    cid = history.client_id
    dirs = _txt_dirs(args.from_txt, cid, _BACKFILL_TXT_DIRS)
    # GLOBAL on purpose: rc_id is the fingerprint's primary key, so a file whose
    # id another client already holds must be skipped, not re-recorded (which
    # would move that fingerprint into this client's corpus).
    existing = {r[0] for r in history.conn.execute("SELECT rc_id FROM fingerprints")}
    n = 0

    # 1) rows already in the DB
    rows = history.conn.execute(
        """SELECT rc_id, rc_text, passage_embedding FROM rc_sets
           WHERE rc_id IS NOT NULL AND rc_text IS NOT NULL AND client_id = ?""",
        (cid,)).fetchall()
    for rc_id, rc_text, emb_json in rows:
        if rc_id in existing:
            continue
        history.record_fingerprint(_legacy_fingerprint(rc_id, rc_text, emb_json))
        existing.add(rc_id)
        n += 1

    # 2) exported .txt corpora (for DBs that were reset but whose RCs shipped)
    for d in dirs:
        if not os.path.isdir(d):
            print(f"[backfill] skipping missing dir: {d}")
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith(".txt"):
                continue
            path = os.path.join(d, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            m = re.search(r"RC ID:\s*(\S+)", text)
            rc_id = m.group(1) if m else os.path.splitext(fname)[0]
            if rc_id in existing or len(text.split()) < 200:
                continue
            history.record_fingerprint(_legacy_fingerprint(rc_id, text, None))
            existing.add(rc_id)
            n += 1

    # 3) maintenance on existing rows (idempotent): retag blueprint-less
    #    fingerprints as 'legacy' and fill letter sequences the old parser missed
    from .fingerprints import parse_answer_letters
    retagged = history.conn.execute(
        """UPDATE fingerprints SET source='legacy'
           WHERE (blueprint_id IS NULL OR blueprint_id='')
             AND COALESCE(source, 'engine') = 'engine' AND client_id = ?""",
        (cid,)).rowcount
    refilled = 0
    for rc_id, old in history.conn.execute(
            "SELECT rc_id, letter_sequence FROM fingerprints "
            "WHERE length(letter_sequence) < 6 AND client_id = ?", (cid,)).fetchall():
        row = history.conn.execute(
            "SELECT rc_text FROM rc_sets WHERE rc_id = ?", (rc_id,)).fetchone()
        text = row[0] if row and row[0] else None
        if not text:
            for d in dirs:
                p = os.path.join(d, f"{rc_id}.txt")
                if os.path.isfile(p):
                    with open(p, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    break
        letters = parse_answer_letters(text) if text else ""
        if len(letters) > len(old):
            history.conn.execute(
                "UPDATE fingerprints SET letter_sequence = ? WHERE rc_id = ?",
                (letters, rc_id))
            refilled += 1
    history.conn.commit()
    if retagged or refilled:
        print(f"[backfill] maintenance: {retagged} fingerprint(s) retagged 'legacy', "
              f"{refilled} empty letter sequence(s) filled")

    print(f"Backfilled {n} legacy fingerprint(s) for client {cid}; {len(existing)} "
          f"total in store. New generations for {cid} now audit against them.")
    history.close()
    return 0


# ---------------------------------------------------------------------------
# topo-report
# ---------------------------------------------------------------------------

def cmd_topo_report(args) -> int:
    """Read-only audit of the question blueprint library: which plans a tier may
    draw, how hard they are once the tier's scaling is applied, and whether any
    slot type has recaptured a position. No DB, no API."""
    import collections

    from .composer import BlueprintComposer
    from .question_engine import QuestionEngine

    reg = ComponentRegistry()
    composer = BlueprintComposer.__new__(BlueprintComposer)
    composer.registry = reg
    tiers = [args.tier] if args.tier else ["medium", "hard", "elite"]
    all_ids = list(reg.ids("topology"))

    n_slots = config.QUESTIONS_PER_SET
    print(f"library: {len(all_ids)} topologies x {n_slots} slots, "
          f"{len(reg.slot_type_definitions)} slot types")
    for i in range(n_slots):
        c = collections.Counter(reg.get("topology", t)["slots"][i]["type"]
                                for t in all_ids)
        top, n = c.most_common(1)[0]
        pin = "  <- pinned" if i == 0 else ""
        print(f"  Q{i+1} most common: {top} ({n}/{len(all_ids)}){pin}")

    # Corpus-level type mix, which is what the CAT weightings are tuned against.
    total = collections.Counter(s["type"] for t in all_ids
                                for s in reg.get("topology", t)["slots"])
    denom = sum(total.values())
    print(f"\n  type mix across the library ({denom} slots):")
    for stype, n in total.most_common():
        print(f"    {stype:26} {n:3}  {n / denom * 100:5.1f}%  "
              f"({sum(1 for t in all_ids if any(s['type'] == stype for s in reg.get('topology', t)['slots']))}/{len(all_ids)} topologies)")

    window = config.EXCLUSION_WINDOWS["topology"]
    for tier in tiers:
        pool = [t for t in all_ids if composer._topology_allowed(t, tier)]
        barred = [t for t in all_ids if t not in pool]
        scaled = [QuestionEngine._scale_slots(reg.get("topology", t)["slots"], tier)
                  for t in pool]
        mean = sum(s["difficulty"] for p in scaled for s in p) / (n_slots * len(scaled))
        raw = sum(s["difficulty"] for t in pool
                  for s in reg.get("topology", t)["slots"]) / (n_slots * len(pool))
        spans = sum(1 for p in scaled for s in p if s["target"] == "span")
        print(f"\n[{tier}] pool {len(pool)}/{len(all_ids)} "
              f"(exclusion window {window} -> {len(pool) - window} always available)")
        print(f"  barred: {', '.join(barred) or 'none'}")
        print(f"  mean slot difficulty: {raw:.3f} raw -> {mean:.3f} after tier scaling")
        print(f"  cross-paragraph slots: {spans} of {n_slots * len(pool)}")
        for i in (0, n_slots - 1):
            c = collections.Counter(reg.get("topology", t)["slots"][i]["type"]
                                    for t in pool)
            print(f"  Q{i+1}: {c.most_common(4)}")
    return 0


# ---------------------------------------------------------------------------
# seeds — classify the seed store once, report coverage (2026-09-14)
# ---------------------------------------------------------------------------

def cmd_seeds(args) -> int:
    try:
        from RAG import get_db  # noqa: legacy module
    except Exception as e:
        print(f"[seeds] RAG unavailable ({e})")
        return 2
    from . import seed_labels
    db = get_db()
    if args.action == "report":
        for line in seed_labels.report(db):
            print(line)
        return 0
    todo = seed_labels.pending(db, relabel=args.relabel)
    if args.limit:
        todo = todo[:args.limit]
    config.set_provider(args.provider)
    from .llm import CostLedger  # noqa: F401  (pricing below uses config rates)
    model = config.resolve_stage_pin("seed_classify", "hard") or (
        args.provider, config.STAGE_CONFIG["seed_classify"]["hard"][0])
    rate_in, rate_out = config.MODEL_RATES.get(model[1], (0.0, 0.0))
    # ~2,300 input tokens (600-word excerpt + 16-shape menu), ~450 output incl. reasoning
    est = len(todo) * (2300 * rate_in + 450 * rate_out) / 1e6
    print(f"[seeds] {len(todo)} unused essays to label with {model[1]} "
          f"(estimated ${est:.2f}; cap ${args.max_usd:.2f})")
    if args.estimate or not todo:
        return 0
    if args.dry_run:
        llm = MockLLMClient()
        todo = todo[:3]
        print("[seeds] dry run: mock classifier on 3 essays, nothing written")

        class _NoWrite:
            def __init__(self, inner):
                self._inner, self._collection = inner, self

            def get(self, *a, **k):
                return self._inner.get(*a, **k)

            def update(self, *a, **k):
                pass
        db = _NoWrite(db)
    else:
        llm, err = _setup_provider(argparse.Namespace(provider=args.provider, dry_run=False))
        if llm is None:
            return err
    result = seed_labels.classify_store(db, llm, ComponentRegistry(), todo,
                                        max_usd=args.max_usd, workers=args.workers)
    print(f"[seeds] labelled {result['labelled']}, failed {result['failed']}, "
          f"spent ${result['spent_usd']:.4f}")
    if not args.dry_run:
        for line in seed_labels.report(get_db()):
            print(line)
    return 0


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def cmd_health(args) -> int:
    reg = ComponentRegistry()
    history = _open_store(args)
    if history is None:
        return 2
    cid = history.client_id
    window = 100
    fam_counts = history.usage_counts_trailing("family", window)
    topo_counts = history.usage_counts_trailing("topology", window)
    fam_kl = kl_divergence(fam_counts, reg.ids("family"))
    # Shape KL is the honest version of family KL. Family KL sat at ~0.13 for
    # months while every shipped passage ran the same four-beat arc, because it
    # measures how evenly 46 IDs rotate — and 32 of those IDs name one shape.
    shape_counts: dict[str, int] = {}
    for fid, cnt in fam_counts.items():
        try:
            shape = reg.shape_of(fid)
        except Exception:
            continue
        shape_counts[shape] = shape_counts.get(shape, 0) + cnt
    shape_kl = kl_divergence(shape_counts, sorted(reg.shapes()))
    topo_kl = kl_divergence(topo_counts, reg.ids("topology"))

    seqs = history.letter_sequences_trailing(20)
    counts = {c: 0 for c in "ABCD"}
    total = 0
    for s in seqs:
        for c in s:
            if c in counts:
                counts[c] += 1
                total += 1
    chi2 = 0.0
    if total:
        expected = total / 4
        chi2 = sum((counts[c] - expected) ** 2 / expected for c in "ABCD")

    # length-bias trend: how often the correct option is the strictly longest,
    # averaged over the corpus. ~1.5/6 (0.25) is chance; a rising trend toward
    # "always" is the tell to watch.
    lb_vals = []
    posture_counts: dict[str, int] = {}
    aph_keyed, aph_true = 0, 0
    th_keyed, th_true = 0, 0
    for fp in history.fingerprint_window(window):
        v = fp.stylometry.get("_correct_longest_count")
        if isinstance(v, (int, float)):
            lb_vals.append(v)
        p = fp.stylometry.get("_closing_posture") or "unknown"
        posture_counts[p] = posture_counts.get(p, 0) + 1
        a = fp.stylometry.get("_aphorism_ending")
        if a is not None:
            aph_keyed += 1
            aph_true += 1 if a else 0
        t = fp.stylometry.get("_thesis_longest")
        if t is not None:
            th_keyed += 1
            th_true += 1 if t else 0
    lb_mean = sum(lb_vals) / len(lb_vals) if lb_vals else None
    # Denominator is the current set size. Sets shipped before the 6 -> 8 move
    # carry 6 questions, so while the trailing window still mixes both the rate
    # reads slightly low for those; it self-corrects as the window rolls over.
    lb_rate = (lb_mean / config.QUESTIONS_PER_SET) if lb_mean is not None else None

    print(f"Corpus health for client {cid} (trailing {window} shipped):")
    print(f"  family KL vs design uniform:   {fam_kl:.3f}  (alarm > 0.15 once corpus > 100)")
    print(f"  topology KL vs design uniform: {topo_kl:.3f}")
    # 2026-09-14: the question-type MIX replaces per-pair topology rejection
    # (config.TOPOLOGY_GATE_ENFORCE); see rc_engine/question_mix.py.
    from .question_mix import format_mix, mix
    bp_rows = [bj for _b, _r, _f, bj in history.shipped_blueprint_rows(window)]
    print(f"\n  question-task mix vs CAT PYQ (last {window} shipped; flag = under half / over double):")
    for line in format_mix(mix(bp_rows, reg), "all tiers"):
        print(line)
    for tier in ("medium", "hard", "elite"):
        r = mix(bp_rows, reg, tier)
        flags = [f"{t} {v['share']:.0%} vs {v['exam']:.0%} ({v['flag']})"
                 for t, v in r["tasks"].items() if v["flag"] and v["exam"]]
        eo = r["tasks"]["engine_only"]
        print(f"  {tier}: {r['sets']} sets; engine-only types {eo['share']:.0%}"
              + (f"; flagged: {', '.join(flags)}" if flags else "; no task flagged"))
    print(f"  ARC-SHAPE KL vs design uniform: {shape_kl:.3f}  "
          f"(the family-level number that actually tracks how a passage reads)")
    if shape_counts:
        total_shapes = sum(shape_counts.values())
        for shape, n in sorted(shape_counts.items(), key=lambda kv: -kv[1]):
            share = n / total_shapes
            fams = len(reg.shapes().get(shape, []))
            mark = "  <-- the legacy arc" if shape == "staged_turn_settled" else ""
            print(f"    {shape:26s} {n:3d} sets {share:5.0%}  "
                  f"({fams} famil{'y' if fams == 1 else 'ies'}){mark}")
        unused = [sh for sh in reg.shapes() if sh not in shape_counts]
        if unused:
            print(f"    never shipped: {', '.join(sorted(unused))}")
    print(f"  answer-letter chi2 (df=3):     {chi2:.2f}  (alarm > 11.34)")
    if lb_mean is not None:
        print(f"  correct-is-longest:            {lb_mean:.2f}/{config.QUESTIONS_PER_SET} per set "
              f"({lb_rate:.0%} of questions)  (chance ~25%; alarm > 45%, "
              f"n={len(lb_vals)})")
    else:
        print(f"  correct-is-longest:            no engine-generated sets yet "
              f"(legacy fingerprints don't carry this stat)")
    if th_keyed:
        print(f"  thesis-longest:                {th_true}/{th_keyed} keyed sets "
              f"(budget: at most {config.THESIS_LONGEST_MAX} in "
              f"{config.THESIS_LONGEST_WINDOW})")
    print(f"  family usage: {dict(sorted(fam_counts.items()))}")
    print(f"  closing postures (realized): {dict(sorted(posture_counts.items()))}")
    src_counts = dict(history.conn.execute(
        "SELECT COALESCE(source, 'engine'), COUNT(*) FROM fingerprints "
        "WHERE client_id = ? GROUP BY 1", (cid,)))
    print(f"  fingerprints by source:        {src_counts}")
    n_fp_total = sum(src_counts.values())
    if n_fp_total < config.CURVE_CAP_MIN_CORPUS:
        print(f"  curve cap (novelty):           dormant - activates at "
              f"{config.CURVE_CAP_MIN_CORPUS} fingerprints "
              f"({n_fp_total}/{config.CURVE_CAP_MIN_CORPUS})")
    if aph_keyed:
        print(f"  aphorism endings:              {aph_true}/{aph_keyed} keyed sets "
              f"(register-rotation baseline ~12.5%)")
    # ---- move saturation: the corpus-level house-voice metric ---------------
    # A move in nearly every passage is the house voice by definition, and it is
    # invisible to every pairwise channel. See config.MOVE_SATURATION_BAN.
    msigs = [w.move_signature.split("|")
             for w in history.fingerprint_window(window) if w.move_signature]
    if len(msigs) >= 8:
        mfreq: dict[str, int] = {}
        for moves in msigs:
            for m in set(moves):
                mfreq[m] = mfreq.get(m, 0) + 1
        hot = [(m, n / len(msigs)) for m, n in mfreq.items()
               if n / len(msigs) > config.MOVE_SATURATION_WARN]
        hot.sort(key=lambda kv: -kv[1])
        print(f"  move saturation ({len(msigs)} keyed sets, ban > "
              f"{config.MOVE_SATURATION_BAN:.0%}, warn > {config.MOVE_SATURATION_WARN:.0%}):")
        if hot:
            for m, share in hot:
                mark = "BAN " if share > config.MOVE_SATURATION_BAN else "warn"
                print(f"    [{mark}] {m:26s} {share:5.0%}")
        else:
            print("    none above the warn line")
        cold = [m for m in config.RHETORICAL_MOVES if mfreq.get(m, 0) / len(msigs) < 0.10]
        if cold:
            print(f"    under-used (<10%): {', '.join(cold)}")

    for version, v in history.voice_health(window).items():
        print(f"  voice plan {version}: {v['ships']} ships (blind model reads)")
        print(f"    observational voice flags {v['voice_flagged']}/{v['voice_observed']} "
              f"checked; {v['ships'] - v['voice_observed']} unreviewed "
              "(voice observations do not change approval status)")
        print(f"    schema measured {v['schema_measured']}/{v['schema_planned']} planned; "
              f"primary matches {v['primary_matches']}/{v['schema_measured']}, "
              f"primary or secondary {v['either_matches']}/{v['schema_measured']}")
        print(f"    moves measured {v['moves_measured']}/{v['moves_planned']} planned; "
              f"opening/closing/body pass {v['opening_matches']}/"
              f"{v['closing_matches']}/{v['middle_matches']} of {v['moves_measured']}")

    # ---- seed genre + topic shape ------------------------------------------
    # The last layer the house voice was hiding in: every feed was one genre and
    # the refine schema made every topic bipolar, so 14 of ~60 stored topics
    # opened "Whether..." and 11 "Why...". These two lines are how you see
    # whether the widened feeds and the topic-shape library are actually landing.
    for label, col in (("seed genres", "seed_genre"), ("topic shapes", "topic_shape")):
        rows = history.conn.execute(
            f"""SELECT {col}, COUNT(*) FROM rc_sets
                WHERE {col} IS NOT NULL AND {col} != '' AND client_id = ?
                GROUP BY 1 ORDER BY 2 DESC""", (cid,)).fetchall()
        if rows:
            total = sum(n for _, n in rows)
            top = ", ".join(f"{k} {n}" for k, n in rows[:6])
            print(f"  {label:30s} {total} keyed | {top}")
        else:
            print(f"  {label:30s} none recorded yet")

    # ---- difficulty by arc shape -------------------------------------------
    # The guardrail on the exam-derived families (2026-08-25). They were capped
    # at 50%/35%/0% by tier on the concern that expository forms might read
    # easier than the literary ones. That concern is testable rather than
    # arguable: if exam-form sets score materially below literary-form sets at
    # the same tier, the cap was right and should tighten. If they score the
    # same, the difficulty lives in the levers that are independent of arc
    # shape — late thesis, trap map, instability, question scaling — as
    # designed, and the cap can loosen.
    #
    # Needs roughly 10 sets per group before the means mean anything.
    rows = history.conn.execute(
        """SELECT r.tier, b.blueprint_json, r.average_score
           FROM rc_sets r JOIN blueprints b ON b.blueprint_id = r.blueprint_id
           WHERE r.average_score > 0 AND r.client_id = ?""", (cid,)).fetchall()
    if rows:
        import json as _json
        buckets: dict = {}
        for tier, bpj, score in rows:
            try:
                fid = _json.loads(bpj).get("family_id")
                shape = reg.shape_of(fid)
            except Exception:
                continue
            group = ("exam-derived" if shape in config.EXAM_DERIVED_SHAPES
                     else "legacy arc" if shape == "staged_turn_settled"
                     else "arc-shape")
            buckets.setdefault((tier, group), []).append(float(score))
        if buckets:
            print("  judge score by arc-shape group (guardrail on the "
                  "exam-derived families):")
            for tier in ("medium", "hard", "elite"):
                parts = []
                for group in ("legacy arc", "arc-shape", "exam-derived"):
                    v = buckets.get((tier, group))
                    if v:
                        parts.append(f"{group} {sum(v)/len(v):.1f} (n={len(v)})")
                if parts:
                    print(f"    {tier:7s} " + " | ".join(parts))
            thin = [k for k, v in buckets.items()
                    if k[1] == "exam-derived" and len(v) < 10]
            if thin or not any(k[1] == "exam-derived" for k in buckets):
                print("    (exam-derived groups still under n=10 — not yet "
                      "decisive)")

    # ---- what the novelty gates are scoring against ------------------------
    # The window is the baseline every render is judged for novelty against.
    # If it fills with sets that will never ship, the gates defend ghosts.
    comp = history.window_composition(window)
    mix = ", ".join(f"{k} {v}" for k, v in
                    sorted(comp["mix"].items(), key=lambda kv: -kv[1]))
    print(f"  novelty window                 {comp['live']} live | {mix}")
    print(f"    hidden: {comp['hidden_by_status']} by status "
          f"{list(config.NOVELTY_WINDOW_EXCLUDE_STATUSES)}, "
          f"{comp['quarantined']} quarantined")

    # ---- batch yield: paid waste per batch ----------------------------------
    # A paid reject is a render that was already bought before a gate refused
    # it. This is the number a threshold or steering change has to move.
    batches = history.attempt_summary(5)
    if batches:
        print("  recent batches (attempts table):")
        for b in batches:
            yield_pct = (b["shipped"] / b["attempts"] * 100) if b["attempts"] else 0
            print(f"    {b['batch_id']}  {b['shipped']}/{b['attempts']} shipped "
                  f"({yield_pct:.0f}%) | paid rejects {b['paid_rejects']} "
                  f"(${b['paid_waste']:.2f}) | free {b['free_rejects']} | "
                  f"spend ${b['spend']:.2f}")
    else:
        print("  recent batches                 none recorded yet "
              "(attempts table fills from the next generate run)")

    if getattr(args, "all", False):
        _print_cross_client(history)

    history.record_health(window, fam_kl, topo_kl, [], chi2)
    history.close()
    return 0


def _print_cross_client(history) -> None:
    """`health --all`: every client, the exclusivity certificate, and the global
    house-voice pressure this client's draws currently feel."""
    print(f"{NL}Cross-client view ({history._db_path}):")
    for c in history.list_clients():
        mark = "  <- this report" if c["client_id"] == history.client_id else ""
        print(f"  {c['client_id']:12s} {c['shipped']:4d} shipped / {c['sets']:4d} sets | "
              f"last {(c['last_set_at'] or 'never')[:16]} | {c['display_name']}{mark}")
    audit = history.exclusivity_audit()
    ok = not audit["shared_combo_hashes"] and not audit["shared_seeds"]
    print(f"  exclusivity: {'OK' if ok else 'BREACHED'} - argument skeletons shared "
          f"across clients: {len(audit['shared_combo_hashes'])}, seed essays shared "
          f"across clients: {len(audit['shared_seeds'])}")
    for h, clients in audit["shared_combo_hashes"][:10]:
        print(f"    skeleton {h[:16]} -> {clients}")
    for d, clients in audit["shared_seeds"][:10]:
        print(f"    seed {d} -> {clients}")
    print(f"  unique index ux_shipped_combo: "
          f"{'present' if audit['unique_index'] else 'MISSING'} "
          f"(duplicate shipped combo hashes in DB: {audit['duplicate_shipped_combo_hashes']})")

    fams = history.usage_counts_other_clients("family", config.GLOBAL_USAGE_WINDOW)
    sigs = [w.move_signature.split("|")
            for w in history.fingerprint_window_other_clients(config.GLOBAL_MOVE_WINDOW)
            if w.move_signature]
    if not fams and not sigs:
        print(f"  global house-voice pressure on {history.client_id}: inactive "
              f"(no other client has shipped)")
        return
    print(f"  global house-voice pressure on {history.client_id} "
          f"(other clients pooled; decay {config.GLOBAL_DECAY_LAMBDA}, "
          f"move power {config.GLOBAL_MOVE_RARITY_POWER}):")
    if fams:
        top = sorted(fams.items(), key=lambda kv: -kv[1])[:8]
        print(f"    family use, trailing {config.GLOBAL_USAGE_WINDOW}: {dict(top)}")
    if sigs:
        mfreq: dict[str, int] = {}
        for moves in sigs:
            for m in set(moves):
                mfreq[m] = mfreq.get(m, 0) + 1
        hot = sorted(((m, n / len(sigs)) for m, n in mfreq.items()
                      if n / len(sigs) > config.MOVE_SATURATION_WARN), key=lambda kv: -kv[1])
        print(f"    moves above {config.MOVE_SATURATION_WARN:.0%} across {len(sigs)} "
              f"keyed sets: " + (", ".join(f"{m} {s:.0%}" for m, s in hot) or "none"))


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def _move_superseded(path: str, dest_root: str) -> int:
    """Move one superseded export out of the client folders (2026-09-14). Keeps
    the folder it came from as a subfolder and never overwrites an earlier move."""
    import shutil
    from datetime import datetime as _dt
    sub = os.path.basename(os.path.dirname(os.path.abspath(path)))
    target_dir = os.path.join(dest_root, sub)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(path))
    if os.path.exists(target):
        stem, ext = os.path.splitext(target)
        target = f"{stem}.{_dt.now().strftime('%Y%m%d-%H%M%S')}{ext}"
    shutil.move(path, target)
    return 1


def cmd_export(args) -> int:
    history = _open_store(args)
    if history is None:
        return 2
    # Only this client's sets: a set shipped to one client is never exported
    # into another client's folder.
    q = ("SELECT rc_id, tier, rc_text, average_score, status, created_at, "
         "compliance_f1, novelty_composite, "
         "COALESCE(similarity_verdict, '') FROM rc_sets "
         "WHERE rc_text IS NOT NULL AND client_id = ?")
    params: list = [history.client_id]
    if args.status:
        q += " AND status = ?"
        params.append(args.status)
    else:
        # 2026-09-14 review: with no --status every row with text was written,
        # including rejected_novelty sets (_reject_full stores their text), and
        # two had reached the client folders. The default is shipped sets only;
        # `--status rejected_novelty` still exports rejects on request.
        q += f" AND status IN ({','.join('?' * len(config.SHIPPING_STATUSES))})"
        params.extend(config.SHIPPING_STATUSES)
    rows = history.conn.execute(q, params).fetchall()
    out = getattr(args, "out", None) or _export_dir(history.client_id, False)
    os.makedirs(out, exist_ok=True)
    flagged_dir = getattr(args, "flagged_out", None) or _flagged_dir(history.client_id, out)
    superseded = getattr(args, "superseded_out", None) or os.path.join(
        config.EXPORT_SUPERSEDED_DIR, history.client_id)
    n_ok = n_red = n_moved = 0
    for rc_id, tier, rc_text, avg, status, created, f1, nov, verdict in rows:
        # A red verdict routes the file; it never changes the set's status or
        # withholds it. The reviewer decides what a flagged set is worth.
        red = (verdict == "red")
        dest = flagged_dir if red else out
        os.makedirs(dest, exist_ok=True)
        screen_line = f" | Screen: {verdict}" if verdict else ""
        header = (f"RC ID: {rc_id} | Tier: {tier} | Score: {avg} | Status: {status} | "
                  f"Compliance F1: {f1} | Novelty: {nov}{screen_line} | "
                  f"Generated: {created}\n" + "=" * 70 + "\n\n")
        with open(os.path.join(dest, f"{rc_id}.txt"), "w", encoding="utf-8") as f:
            f.write(header + rc_text)
        # The same set in the OTHER folder is a stale copy from before its
        # verdict changed. Move it aside (never delete) so a reviewer never
        # sees one set twice with contradicting screen headers.
        other = os.path.join(out if red else flagged_dir, f"{rc_id}.txt")
        if (os.path.abspath(other) != os.path.abspath(os.path.join(dest, f"{rc_id}.txt"))
                and os.path.isfile(other)):
            n_moved += _move_superseded(other, superseded)
        n_red += red
        n_ok += (not red)
    print(f"Exported {n_ok} set(s) for client {history.client_id} to '{out}/'")
    if n_moved:
        print(f"Moved {n_moved} superseded copy/copies to '{superseded}/' "
              f"(same set, other folder, older screen verdict)")
    if n_red:
        print(f"Exported {n_red} similarity-flagged set(s) to '{flagged_dir}/' "
              f"- these read like recent sets and want a human look")
    history.close()
    return 0


# ---------------------------------------------------------------------------
# vet — free gates for a manually generated RC (.txt); --ingest to sync it
# ---------------------------------------------------------------------------

_MECH_LINE = re.compile(r"(?m)^\s*\(([A-D])\)\s*([a-z][a-z_]{2,40})\s*[—\-–:]")

# Manual sets carry no slot types; the thesis question is identified by stem
# so the thesis-specific length rule and its 1-in-3 corpus budget apply.
_THESIS_STEM = re.compile(
    r"(?i)central\s+(?:thesis|claim|argument|idea|point)"
    r"|main\s+(?:point|idea|argument|claim|thesis)"
    r"|primary\s+(?:purpose|argument|claim|thesis)"
    r"|passage'?s\s+thesis|overall\s+argument|principal\s+claim")


# Formatting noise stripped before structural parsing: chat/markdown uploads
# wrap stems and key lines in ** and separate sections with horizontal rules.
_HR_LINE = re.compile(r"(?m)^[ \t]*(?:-{3,}|_{3,}|\*{3,})[ \t]*$")

# Question stem: "Q1." / "Q1)" / "Q1:" / "Question 1." (group 1), or a bare
# numbered line "1." / "1)" (group 2 — only trusted when options follow).
_QSTEM = re.compile(
    r"(?m)^[ \t]*(?:Q(?:uestion)?[ \t]*\.?[ \t]*(\d{1,2})[ \t]*[.):—–-]"
    r"|(\d{1,2})[ \t]*[.)])[ \t]*")

# Option line: "(A)", "A)", "A.", "[A]", "A:" — either case.
_OPT_SPLIT = re.compile(r"(?m)^[ \t]*[\(\[]?([A-Da-d])[\)\].:][ \t]+")

# Leading chat-export chrome before the passage: "# CAT-Style RC", "Domain: …".
_TITLE_LINE = re.compile(r"^(?:#[^\n]*|(?:Domain|Tier|Topic)[ \t]*:[^\n]*)\n+")


def _normalize_rc_text(text: str) -> str:
    text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = _HR_LINE.sub("", text)
    return text.replace("**", "")


def _section_heading(body: str, word: str) -> re.Match | None:
    """A section heading in any of the shapes uploads arrive in:
    "[QUESTIONS]" (engine format), "## Questions" (markdown), "Questions:"."""
    return re.search(
        rf"(?im)^[ \t]*(?:\[[ \t]*{word}[^\]\n]*\]?"
        rf"|#{{1,6}}[ \t]*{word}\b[^\n]*"
        rf"|{word}[ \t]*:)[ \t]*$", body)


def _scan_questions(qtext: str, validate: bool) -> tuple[list[dict], int | None]:
    """Question blocks in qtext; (questions, offset of the first stem).
    With validate=True a stem only counts when >=3 option lines follow it,
    so numbered lines in prose are not mistaken for questions."""
    stems = list(_QSTEM.finditer(qtext))
    out: list[dict] = []
    first: int | None = None
    for i, sm in enumerate(stems):
        end = stems[i + 1].start() if i + 1 < len(stems) else len(qtext)
        parts = _OPT_SPLIT.split(qtext[sm.end():end])
        if validate and (len(parts) - 1) // 2 < 3:
            continue
        if first is None:
            first = sm.start()
        options = {parts[j].upper(): {"text": " ".join(parts[j + 1].split())}
                   for j in range(1, len(parts) - 1, 2)}
        out.append({"q": int(sm.group(1) or sm.group(2)),
                    "stem": parts[0].strip(), "options": options})
    return out, first


def _parse_rc_txt(text: str) -> dict:
    """Parse an RC set in MANUAL_GENERATION_PROMPT.md's OUTPUT FORMAT (which
    the engine's own exports also follow) OR the markdown shape chat uploads
    arrive in (## headings, bold stems, A)/A. options). Tolerant of missing
    sections; 'notes' reports how the file was read."""
    text = _normalize_rc_text(text)
    body = re.sub(r"^RC ID:.*?={10,}\s*", "", text, flags=re.DOTALL)
    notes: list[str] = []

    heads = {name: _section_heading(body, word)
             for name, word in (("passage", "passage"),
                                ("questions", r"questions?"),
                                ("key", r"answer[ \t]*keys?"))}
    key_start = heads["key"].start() if heads["key"] else len(body)

    questions: list[dict] = []
    first_stem: int | None = None
    if heads["questions"]:
        questions, off = _scan_questions(
            body[heads["questions"].end():key_start], validate=False)
        if heads["questions"].group(0).lstrip().startswith("#"):
            notes.append("markdown-style section headings")
    if not questions:
        # no usable Questions section — scan everything before the answer key
        questions, first_stem = _scan_questions(body[:key_start], validate=True)
        if questions:
            notes.append(f"{len(questions)} question(s) found by fallback scan"
                         + ("" if heads["questions"] else
                            " (no Questions heading present)"))

    if heads["questions"]:
        p_end = heads["questions"].start()
    elif first_stem is not None:
        p_end = first_stem
    elif heads["key"]:
        p_end = key_start
    else:
        p_end = len(body)
    p_start = heads["passage"].end() if heads["passage"] else 0
    passage = body[p_start:min(p_end, len(body))].strip() if p_start < p_end \
        else body[p_start:].strip()
    if not heads["passage"]:
        while (tm := _TITLE_LINE.match(passage)):
            passage = passage[tm.end():].lstrip()

    keyblock = body[key_start:] if heads["key"] else ""

    from .fingerprints import parse_answer_letters
    from .question_contracts import CONTRACT_MARKERS
    mechanisms: dict[str, int] = {}
    for _letter, mech in _MECH_LINE.findall(keyblock):
        # passage_supported marks the true statements in an EXCEPT question, not
        # a distractor mechanism — counting it would make manual and engine sets
        # produce incomparable trap histograms. 2026-09-13: the same for every
        # negative-contract marker (rule_satisfied, ...), which includes it.
        if mech in CONTRACT_MARKERS:
            continue
        mechanisms[mech] = mechanisms.get(mech, 0) + 1
    pm = re.search(r"Posture:\s*([a-z_]+)", keyblock)
    return {"passage": passage, "questions": questions,
            "letters": parse_answer_letters(text),
            "mechanisms": mechanisms, "posture": pm.group(1) if pm else None,
            "notes": notes}


def cmd_vet(args) -> int:
    from .fingerprints import rhythm_vector, stylometry_profile, _embed
    from .models import Fingerprint
    from .novelty import NoveltyScorer
    from .question_engine import length_bias_report, passage_word_report

    if not os.path.isfile(args.file):
        print(f"File not found: {args.file}")
        return 1
    with open(args.file, encoding="utf-8", errors="replace") as f:
        text = f.read()
    parsed = _parse_rc_txt(text)
    passage, questions, letters = parsed["passage"], parsed["questions"], parsed["letters"]

    m = re.search(r"RC ID:\s*(\S+)", text)
    rc_id = args.id or (m.group(1) if m
                        else os.path.splitext(os.path.basename(args.file))[0])
    words = len(passage.split())
    print(f"[vet] {rc_id}: {words}-word passage, {len(questions)} question(s), "
          f"key '{letters or '?'}', {sum(parsed['mechanisms'].values())} named mechanism(s)")
    for note in parsed["notes"]:
        print(f"[vet] parse: {note}")

    # -- structural + letter audits (the manual prompt's Stage-4 rules) ------
    warnings: list[str] = []
    if len(questions) != config.QUESTIONS_PER_SET:
        warnings.append(f"expected {config.QUESTIONS_PER_SET} questions, "
                        f"parsed {len(questions)}")
        if not questions:
            warnings.append("no question stems recognized — stems must start "
                            "a line as 'Q1.'/'Q1)'/'1.' with options on their "
                            "own lines as '(A)'/'A)'/'A.'")
    for q in questions:
        if len(q["options"]) != 4:
            warnings.append(f"Q{q['q']}: parsed {len(q['options'])}/4 options")
    if letters and len(letters) != len(questions):
        warnings.append(f"answer key covers {len(letters)}/{len(questions)} questions")
    # Passage length is one house standard, not a tier parameter — checked on
    # every vetted set, --tier or not, using the same band the engine enforces
    # (these used to disagree: engine +/-60 vs vet +/-40).
    warnings += passage_word_report(passage)["warnings"]
    if letters:
        for c in "ABCD":
            if letters.count(c) > 3:
                warnings.append(f"letter {c} correct {letters.count(c)}x (max 3)")
        for i in range(len(letters) - 2):
            if letters[i] == letters[i + 1] == letters[i + 2]:
                warnings.append(f"letter {letters[i]} correct 3x in a row")
                break
    lb = None
    if (letters and len(letters) == len(questions)
            and all(len(q["options"]) == 4 for q in questions)):
        for q, letter in zip(questions, letters):
            q["correct"] = letter
        for q in questions:
            if _THESIS_STEM.search(q["stem"]):
                q["slot_type"] = "thesis"
                break
        lb = length_bias_report({"questions": questions})
        warnings += [f"length bias: {w}" for w in lb["warnings"]]

    # -- novelty vs corpus (channels available without a compliance audit) ---
    history = _open_store(args)
    if history is None:
        return 2
    fp = Fingerprint(
        rc_id=rc_id, blueprint_id="", persona_id="",
        movement_string="MANUAL_UNKNOWN", commitment_curve=[0.0, 0.0, 0.0],
        rhythm_vector=rhythm_vector(passage), topology_signature=[],
        trap_histogram=parsed["mechanisms"], letter_sequence=letters,
        stylometry=stylometry_profile(passage),
        embedding=None if args.no_embed else _embed(passage),
        source="manual")
    if parsed["posture"]:
        fp.stylometry["_closing_posture"] = parsed["posture"]
    if lb is not None:
        fp.stylometry["_correct_longest_count"] = lb["correct_longest_count"]
        if lb["has_thesis_question"]:
            fp.stylometry["_thesis_longest"] = 1 if lb["thesis_correct_longest"] else 0
    report = NoveltyScorer(history).score(fp, {},
                                          include_question_channels=bool(questions))

    print(f"\n  novelty:  {report.verdict}  (composite {report.composite}, "
          f"nearest {report.channel_scores.get('nearest')})")
    for b in report.breached:
        print(f"    BREACH  {b}")
    for fl in report.corpus_flags:
        print(f"    corpus  {fl}")
    if warnings:
        for w in warnings:
            print(f"    WARN    {w}")
    else:
        print("  audits:   clean")

    ok = report.verdict == "pass" and not warnings
    if args.ingest:
        if not ok and not args.force:
            print("\nNOT ingested (see flags above). Fix the set or re-run with --force.")
            history.close()
            return 1
        replaced = history.conn.execute(
            "SELECT 1 FROM fingerprints WHERE rc_id = ?", (rc_id,)).fetchone()
        history.record_fingerprint(fp)
        history.record_novelty_audit("manual", rc_id, report.channel_scores,
                                     report.composite, f"vet:{report.verdict}",
                                     "; ".join(report.breached))
        print(f"\nIngested {'(replaced) ' if replaced else ''}{rc_id} as "
              f"source='manual' — future generations now audit against it.")
        history.backup_to()
    elif ok:
        print("\nPASS - re-run with --ingest to add it to the corpus.")
    else:
        print("\nReview the flags above before shipping this set.")
    history.close()
    return 0 if ok or args.ingest else 1


# ---------------------------------------------------------------------------
# avoid — paste-ready AVOID line for MANUAL_GENERATION_PROMPT.md
# ---------------------------------------------------------------------------

def cmd_avoid(args) -> int:
    reg = ComponentRegistry()
    history = _open_store(args)
    if history is None:
        return 2
    rows = [(rc_id, fam, bpj) for _bp, rc_id, fam, bpj
            in history.shipped_blueprint_rows(args.n)]
    if not rows:
        print("No shipped engine sets in this DB yet - build the AVOID line "
              "from RC_Tracker.xlsx instead.")
        history.close()
        return 0

    # realized closing postures live on the fingerprints; planned posture
    # (from the family) is the fallback for sets fingerprinted without one
    realized_posture = {}
    for fp in history.fingerprint_window(args.n * 3):
        p = fp.stylometry.get("_closing_posture")
        if p:
            realized_posture[fp.rc_id] = p

    families, postures, topics = [], [], []
    for rc_id, family_id, bp_json in rows:
        try:
            families.append(reg.get("family", family_id)["name"])
        except KeyError:
            families.append(family_id)
        postures.append(realized_posture.get(rc_id) or reg.posture_of(family_id))
        try:
            topic = json.loads(bp_json).get("topic", "") if bp_json else ""
        except (ValueError, TypeError):
            topic = ""
        if topic:
            topics.append(topic)

    def _dedupe(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        return [x for x in xs if x and not (x in seen or seen.add(x))]

    posture_counts: dict[str, int] = {}
    for p in postures:
        posture_counts[p] = posture_counts.get(p, 0) + 1
    posture_str = ", ".join(f"{p} x{c}" if c > 1 else p
                            for p, c in posture_counts.items())

    print(f"[avoid] last {len(rows)} shipped engine set(s). Manual sets are NOT "
          f"included — add them from RC_Tracker.xlsx.\n")
    print(f"AVOID (from my recent sets): {', '.join(_dedupe(families))} families; "
          f"postures: {posture_str}; "
          f"topics: {', '.join(_dedupe(topics)) or 'n/a'}")
    history.close()
    return 0


# ---------------------------------------------------------------------------
# client — add / list
# ---------------------------------------------------------------------------

def cmd_client(args) -> int:
    """Clients share one DB. A new client starts with an empty novelty window;
    argument skeletons, seed essays and rc ids stay exclusive across all."""
    # Opened as the founding client, which always exists, so this works even
    # when RC_ENGINE_CLIENT names a client that has not been added yet.
    history = HistoryStore(args.db, config.FOUNDING_CLIENT_ID)
    try:
        if args.client_cmd == "add":
            try:
                history.add_client(args.slug, args.name)
            except ValueError as e:
                print(f"[client] {e}")
                return 2
            print(f"Added client '{args.slug}' to {args.db}. Its novelty window is empty; "
                  f"exports go to '{_export_dir(args.slug, False)}/'.")
            print(f"Try it at $0 first:  python -m rc_engine.cli generate --dry-run "
                  f"--client {args.slug} --hard 2   (dry-run uses rc_engine_dryrun.db, "
                  f"so add the client there too)")
            return 0
        rows = history.list_clients()
        print(f"{'client':12s} {'shipped':>7s} {'sets':>5s}  {'last set':16s}  name")
        for c in rows:
            default = "  (default)" if c["client_id"] == config.DEFAULT_CLIENT_ID else ""
            print(f"{c['client_id']:12s} {c['shipped']:7d} {c['sets']:5d}  "
                  f"{(c['last_set_at'] or 'never')[:16]:16s}  {c['display_name']}{default}")
        return 0
    finally:
        history.close()


# ---------------------------------------------------------------------------

def _make_stdout_unicode_safe() -> None:
    """Never let a print() kill a paid batch.

    Seed titles come from live RSS and routinely carry curly quotes, en dashes
    and combining accents. On Windows the console defaults to cp1252, which
    cannot encode them, so `print(title)` raises UnicodeEncodeError — and on
    2026-08-10 that aborted a whole `generate --hard 1` run from inside the seed
    provider, before any RC existed. Degrading one character to '?' is always
    preferable to losing the batch.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # already wrapped, or not reconfigurable — printing still works


def main(argv=None) -> int:
    _make_stdout_unicode_safe()
    p = argparse.ArgumentParser(prog="rc_engine", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def _client_opt(sp):
        sp.add_argument("--client", default=None,
                        help=f"client slug (default {config.DEFAULT_CLIENT_ID}; "
                             f"see `client list`)")

    est = sub.add_parser("estimate", help="print per-tier cost table ($0)")
    est.add_argument("--provider", choices=list(config.PROVIDERS), default="claude",
                     help="price the cost table for this provider's models")
    sub.add_parser("selftest", help="mock end-to-end run ($0)")

    g = sub.add_parser("generate", help="generate RCs")
    g.add_argument("--provider", choices=list(config.PROVIDERS), default="claude",
                   help="LLM provider for the whole run (default: claude)")
    g.add_argument("--medium", type=int, default=0)
    g.add_argument("--hard", type=int, default=0)
    g.add_argument("--elite", type=int, default=0)
    g.add_argument("--db", default=config.DB_PATH)
    g.add_argument("--dry-run", action="store_true", help="mock client, $0")
    g.add_argument("--no-seed", action="store_true", help="skip RAG seed essays")
    g.add_argument("--seed-ids", default=None, metavar="FILE",
                   help="draw seeds only from these doc ids (JSON list/map or one id per "
                        "line) — e.g. a subject-restricted batch; overrides tier seed pools")
    g.add_argument("--subject", default=None, metavar="LIST",
                   help="draw only unused essays whose stored label domain is in this "
                        "comma list, e.g. philosophy,literature (run `seeds classify` first)")
    g.add_argument("--genre", default=None, metavar="LIST",
                   help="draw only unused essays whose stored label genre is in this "
                        "comma list, e.g. criticism,conceptual_essay")
    g.add_argument("--no-embed", action="store_true", help="disable embedding channel")
    g.add_argument("--no-export", action="store_true")
    g.add_argument("--no-screen", action="store_true",
                   help="skip the pre-export similarity screen")
    g.add_argument("--max-usd", type=float, default=None,
                   help="batch spending cap (default: 1.25 x sum of requested tier budgets)")
    g.add_argument("--only-posture", default=None,
                   help="restrict every attempt to families with this closing "
                        "posture (verification lever; uses the normal family-ban path)")
    g.add_argument("--workers", type=int, default=config.BATCH_WORKERS_DEFAULT,
                   help=f"parallel worker processes, 1-{config.BATCH_WORKERS_MAX} "
                        f"(default {config.BATCH_WORKERS_DEFAULT}); see rc_engine/workers.py")
    g.add_argument("--generation-policy", default=None, metavar="VERSION",
                   help="compose NEW medium/hard plans under this generation policy "
                        "(e.g. cat-pyq-q1); elite always stays legacy; '' forces legacy. "
                        "Default: config.GENERATION_POLICY_FOR_NEW_PLANS")
    g.add_argument("--elite-policy", default=None, metavar="VERSION",
                   help="compose NEW elite plans under a legacy-based policy, e.g. "
                        "legacy-sf1 (legacy engine + seed fidelity). Default: legacy")
    _client_opt(g)

    pr = sub.add_parser("policy-report",
                        help="$0: planned and realised metrics by client, tier and "
                             "generation policy (read-only)")
    pr.add_argument("--db", default=config.DB_PATH)
    pr.add_argument("--all-clients", action="store_true",
                    help="every client, one row per client/tier/policy")
    pr.add_argument("--json", action="store_true", help="print JSON instead of text")
    _client_opt(pr)

    r = sub.add_parser("retry-questions",
                       help="regenerate questions on a persisted passage whose "
                            "questions failed (questions-stage cost only)")
    r.add_argument("--provider", choices=list(config.PROVIDERS), default="claude",
                   help="LLM provider for the retry (default: claude)")
    r.add_argument("--blueprint", default=None,
                   help="blueprint id (BP_...) to resume; omit to list resumable passages")
    r.add_argument("--all", action="store_true",
                   help="resume every questions_failed passage")
    r.add_argument("--note", default=None,
                   help="extra directives appended to the question prompt")
    r.add_argument("--db", default=config.DB_PATH)
    r.add_argument("--dry-run", action="store_true", help="mock client, $0")
    r.add_argument("--no-embed", action="store_true", help="disable embedding channel")
    r.add_argument("--no-screen", action="store_true",
                   help="skip the pre-export similarity screen")
    _client_opt(r)

    ma = sub.add_parser("move-audit",
                        help="extract blind rhetorical-move signatures and report "
                             "how much of the corpus shares a grammar")
    ma.add_argument("--db", default=config.DB_PATH)
    ma.add_argument("--provider", choices=list(config.PROVIDERS), default="claude")
    ma.add_argument("--from-txt", nargs="*", default=None,
                    help="dirs to source passages from for rows with no rc_text "
                         f"(founding client default: {_MOVE_AUDIT_TXT_DIRS}; "
                         "other clients: none)")
    ma.add_argument("--reextract", action="store_true",
                    help="clear every stored signature and read them all again "
                         "(needed after the move vocabulary changes meaning)")
    ma.add_argument("--report-only", action="store_true",
                    help="skip extraction, report on signatures already stored ($0)")
    ma.add_argument("--dry-run", action="store_true", help="mock client, $0")
    ma.add_argument("--max-usd", type=float, default=1.00,
                    help="spend cap for the extraction pass")
    ma.add_argument("--top", type=int, default=15,
                    help="how many nearest pairs to print")
    ma.add_argument("--quarantine", action="store_true",
                    help="exclude redundant sets from the novelty baseline "
                         "(keeps one per cluster; deletes nothing)")
    _client_opt(ma)

    b = sub.add_parser("backfill", help="fingerprint legacy rc_sets rows and/or exported txt ($0)")
    b.add_argument("--db", default=config.DB_PATH)
    b.add_argument("--from-txt", nargs="*", default=None,
                   help="directories of exported RC .txt files to fingerprint "
                        f"(founding client default: {_BACKFILL_TXT_DIRS}; other clients: none)")
    _client_opt(b)

    sd = sub.add_parser("seeds", help="seed-store labels: classify essays once (cheap "
                                      "model) and report subject/genre coverage")
    sd.add_argument("action", choices=["classify", "report"])
    sd.add_argument("--provider", choices=list(config.PROVIDERS), default="openai",
                    help="provider whose small model labels (default openai: gpt-5.6-luna)")
    sd.add_argument("--limit", type=int, default=None, help="label at most N essays")
    sd.add_argument("--max-usd", type=float, default=3.0, help="stop starting calls at this spend")
    sd.add_argument("--workers", type=int, default=6, help="parallel classifier calls")
    sd.add_argument("--relabel", action="store_true", help="label again even if already labelled")
    sd.add_argument("--estimate", action="store_true", help="count and price only, no calls ($0)")
    sd.add_argument("--dry-run", action="store_true", help="mock classifier, writes nothing ($0)")

    h = sub.add_parser("health", help="corpus health snapshot ($0)")
    h.add_argument("--db", default=config.DB_PATH)
    h.add_argument("--all", action="store_true",
                   help="append the cross-client view: every client, the exclusivity "
                        "audit, and the global house-voice pressure")
    _client_opt(h)

    tr = sub.add_parser("topo-report",
                        help="question blueprint library audit: tier pools, "
                             "scaled difficulty, positional balance ($0)")
    tr.add_argument("--tier", default=None, choices=["medium", "hard", "elite"])

    e = sub.add_parser("export", help="export rc_sets to txt")
    e.add_argument("--db", default=config.DB_PATH)
    e.add_argument("--status", default=None)
    e.add_argument("--out", default=None,
                   help="default: exported_rc_sets for the founding client, "
                        "exported_rc_sets/<client> for any other")
    e.add_argument("--flagged-out", default=None,
                   help=f"where similarity-flagged sets go "
                        f"(default {config.FLAGGED_EXPORT_DIR}, or <out>/flagged_similar "
                        f"for other clients)")
    _client_opt(e)

    a = sub.add_parser("avoid", help="AVOID line for the manual prompt ($0)")
    a.add_argument("--db", default=config.DB_PATH)
    a.add_argument("--n", type=int, default=4,
                   help="how many recent shipped sets to include")
    _client_opt(a)

    v = sub.add_parser("vet", help="run the free gates on a manual RC .txt ($0)")
    v.add_argument("file", help="RC .txt in the manual prompt's output format")
    v.add_argument("--db", default=config.DB_PATH)
    v.add_argument("--id", default=None,
                   help="rc_id override (default: 'RC ID:' line, else filename)")
    v.add_argument("--tier", choices=["medium", "hard", "elite"], default=None,
                   help="accepted but no longer used: passage length is one "
                        "500-word standard across all tiers and is now checked "
                        "on every vetted set (kept so existing commands and the "
                        "GUI keep working)")
    v.add_argument("--ingest", action="store_true",
                   help="on pass, store the fingerprint with source='manual'")
    v.add_argument("--force", action="store_true",
                   help="ingest even with breaches/warnings")
    v.add_argument("--no-embed", action="store_true",
                   help="skip the embedding channel (faster)")
    _client_opt(v)

    cl = sub.add_parser("client", help="add or list clients ($0)")
    cl_sub = cl.add_subparsers(dest="client_cmd", required=True)
    cl_add = cl_sub.add_parser("add", help="register a client (starts with an empty "
                                           "novelty window)")
    cl_add.add_argument("slug", help="short id, e.g. AA; becomes the export subfolder")
    cl_add.add_argument("--name", default="", help="display name")
    cl_add.add_argument("--db", default=config.DB_PATH)
    cl_list = cl_sub.add_parser("list", help="clients with shipped counts")
    cl_list.add_argument("--db", default=config.DB_PATH)

    args = p.parse_args(argv)
    return {"estimate": cmd_estimate, "selftest": cmd_selftest,
            "generate": cmd_generate, "backfill": cmd_backfill,
            "health": cmd_health, "export": cmd_export,
            "avoid": cmd_avoid, "vet": cmd_vet, "topo-report": cmd_topo_report,
            "retry-questions": cmd_retry_questions,
            "move-audit": cmd_move_audit, "client": cmd_client,
            "policy-report": cmd_policy_report, "seeds": cmd_seeds}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
