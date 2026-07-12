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
import re
import sys

from . import config
from .history import HistoryStore
from .llm import BudgetExceeded, CostLedger, LLMClient, MockLLMClient
from .models import SeedEssay
from .novelty import kl_divergence
from .pipeline import RCPipeline, run_batch
from .registry import ComponentRegistry


# ---------------------------------------------------------------------------
# estimate
# ---------------------------------------------------------------------------

STAGES = ["refine", "render", "compliance", "questions", "solver", "judge"]
TYPICAL_OUTPUT_FRACTION = 0.6


def _stage_cost(stage: str, tier: str, worst: bool) -> float:
    model, max_tok = config.STAGE_CONFIG[stage][tier]
    rin, rout = config.MODEL_RATES[model]
    est_in = config.ESTIMATED_INPUT_TOKENS[stage]
    out_tok = max_tok if worst else int(max_tok * TYPICAL_OUTPUT_FRACTION)
    return est_in / 1e6 * rin + out_tok / 1e6 * rout


def cmd_estimate(_args) -> int:
    ok = True
    print(f"{'tier':8s} {'stage':12s} {'model':28s} {'typical':>9s} {'worst':>9s}")
    for tier in ("medium", "hard", "elite"):
        happy = 0.0
        worst_uncapped = 0.0
        for stage in STAGES:
            model, _ = config.STAGE_CONFIG[stage][tier]
            t = _stage_cost(stage, tier, worst=False)
            w = _stage_cost(stage, tier, worst=True)
            attempts = {"render": config.MAX_RENDER_ATTEMPTS,
                        "compliance": config.MAX_RENDER_ATTEMPTS,
                        "questions": config.MAX_QUESTION_ATTEMPTS,
                        "judge": config.MAX_JUDGE_ATTEMPTS}.get(stage, 1)
            happy += t
            worst_uncapped += w * attempts
            print(f"{tier:8s} {stage:12s} {model:28s} {t:>9.4f} {w:>9.4f} (x{attempts} worst)")
        budget = config.TIER_BUDGET_USD[tier]
        capped = min(worst_uncapped, budget)
        print(f"{tier:8s} {'TOTAL':12s} {'happy path':28s} {happy:>9.4f}")
        print(f"{tier:8s} {'TOTAL':12s} {'worst uncapped / enforced cap':28s} "
              f"{worst_uncapped:>9.4f} / {budget:.2f}")
        if happy > budget:
            print(f"  !! happy path ${happy:.4f} exceeds budget ${budget:.2f} — "
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
    print("SELFTEST PASSED — pipeline is runnable end-to-end; cost guard active; "
          "libraries valid.")
    return 0


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _make_seed_provider():
    try:
        from RAG import get_db, get_unused_essay, mark_essay_used  # noqa: legacy module
    except Exception as e:
        print(f"[seeds] RAG unavailable ({e}) — running seedless")
        return None
    db = get_db()

    def provider(tier: str | None = None, exclude_ids=None):
        # Hard/elite: random draw inside CAT_SEED_GENRES only (strict by default).
        # Medium: any unused genre at random. exclude_ids = batch-slot rotations.
        preferred = config.TIER_SEED_GENRES.get(tier) if tier else None
        essay = get_unused_essay(db, genre=preferred, exclude_ids=exclude_ids,
                                 randomize=True)
        strict = getattr(config, "TIER_SEED_STRICT", True)
        if essay is None and preferred is not None and not strict:
            essay = get_unused_essay(db, genre=None, exclude_ids=exclude_ids,
                                     randomize=True)
            if essay is not None:
                print(f"[seeds] preferred pool empty for '{tier}' — "
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
                         text=essay["text"], domain_hint=genre)

        def on_success(rc_id):
            mark_essay_used(db, essay["id"], rc_id)
        return seed, on_success

    return provider


def cmd_generate(args) -> int:
    tier_counts = {t: getattr(args, t) for t in ("medium", "hard", "elite")
                   if getattr(args, t) > 0}
    if not tier_counts:
        print("Nothing to generate. Use --medium/--hard/--elite N.")
        return 1

    if args.dry_run:
        llm = MockLLMClient()
        if args.db == config.DB_PATH:
            args.db = "rc_engine_dryrun.db"   # never pollute the production DB with mock RCs
        print(f"[dry-run] Using MockLLMClient — $0, no API calls. DB: {args.db}")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set.")
            return 1
        llm = LLMClient()

    history = HistoryStore(args.db)
    # dry-run passages are canned filler text — the embedding channel would
    # (correctly) reject them as duplicates, which only confuses a $0 test
    embed = not (args.no_embed or args.dry_run)
    pipe = RCPipeline(history, llm, embed=embed)
    provider = None if (args.no_seed or args.dry_run) else _make_seed_provider()
    results = run_batch(pipe, tier_counts, provider, max_usd=args.max_usd)

    if not args.no_export:
        out_dir = "exported_rc_sets_dryrun" if args.dry_run else "exported_rc_sets"
        cmd_export(argparse.Namespace(db=args.db, status=None, out=out_dir))
    if not args.dry_run:
        history.backup_to()
    history.close()
    return 0 if any(r.rc_id for r in results) else 1


# ---------------------------------------------------------------------------
# retry-questions — regenerate questions on a persisted, novelty-clean passage
# ---------------------------------------------------------------------------

def cmd_retry_questions(args) -> int:
    if args.dry_run:
        llm = MockLLMClient()
        if args.db == config.DB_PATH:
            args.db = "rc_engine_dryrun.db"
        print(f"[dry-run] Using MockLLMClient — $0, no API calls. DB: {args.db}")
    elif args.blueprint or args.all:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set.")
            return 1
        llm = LLMClient()
    else:
        llm = None                      # list mode is free — no client needed

    history = HistoryStore(args.db)
    rows = history.load_resumable_passages()

    if not args.blueprint and not args.all:
        if not rows:
            print("No resumable passages (status='questions_failed').")
        else:
            print(f"{len(rows)} resumable passage(s) — re-run with "
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
    for bp_id in targets:
        print(f"\n=== retry-questions {bp_id} ===")
        res = pipe.resume_questions(bp_id, extra_guidance=args.note)
        print(f"  -> {res.status} rc_id={res.rc_id} "
              f"new spend ${res.cost_usd:.4f}")
        for n in res.notes:
            print(f"     {n}")
        if res.rc_id:
            shipped += 1
    if shipped:
        out_dir = "exported_rc_sets_dryrun" if args.dry_run else "exported_rc_sets"
        cmd_export(argparse.Namespace(db=args.db, status=None, out=out_dir))
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


def cmd_backfill(args) -> int:
    history = HistoryStore(args.db)
    existing = {r[0] for r in history.conn.execute("SELECT rc_id FROM fingerprints")}
    n = 0

    # 1) rows already in the DB
    rows = history.conn.execute(
        """SELECT rc_id, rc_text, passage_embedding FROM rc_sets
           WHERE rc_id IS NOT NULL AND rc_text IS NOT NULL""").fetchall()
    for rc_id, rc_text, emb_json in rows:
        if rc_id in existing:
            continue
        history.record_fingerprint(_legacy_fingerprint(rc_id, rc_text, emb_json))
        existing.add(rc_id)
        n += 1

    # 2) exported .txt corpora (for DBs that were reset but whose RCs shipped)
    for d in (args.from_txt or []):
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
             AND COALESCE(source, 'engine') = 'engine'""").rowcount
    refilled = 0
    for rc_id, old in history.conn.execute(
            "SELECT rc_id, letter_sequence FROM fingerprints "
            "WHERE length(letter_sequence) < 6").fetchall():
        row = history.conn.execute(
            "SELECT rc_text FROM rc_sets WHERE rc_id = ?", (rc_id,)).fetchone()
        text = row[0] if row and row[0] else None
        if not text:
            for d in (args.from_txt or []):
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

    print(f"Backfilled {n} legacy fingerprint(s); {len(existing)} total in store. "
          f"New generations now audit against them.")
    history.close()
    return 0


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def cmd_health(args) -> int:
    reg = ComponentRegistry()
    history = HistoryStore(args.db)
    window = 100
    fam_counts = history.usage_counts_trailing("family", window)
    topo_counts = history.usage_counts_trailing("topology", window)
    fam_kl = kl_divergence(fam_counts, reg.ids("family"))
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
    lb_rate = (lb_mean / 6) if lb_mean is not None else None

    print(f"Corpus health (trailing {window} shipped):")
    print(f"  family KL vs design uniform:   {fam_kl:.3f}  (alarm > 0.15 once corpus > 100)")
    print(f"  topology KL vs design uniform: {topo_kl:.3f}")
    print(f"  answer-letter chi2 (df=3):     {chi2:.2f}  (alarm > 11.34)")
    if lb_mean is not None:
        print(f"  correct-is-longest:            {lb_mean:.2f}/6 per set "
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
        "SELECT COALESCE(source, 'engine'), COUNT(*) FROM fingerprints GROUP BY 1"))
    print(f"  fingerprints by source:        {src_counts}")
    n_fp_total = sum(src_counts.values())
    if n_fp_total < config.CURVE_CAP_MIN_CORPUS:
        print(f"  curve cap (novelty):           dormant — activates at "
              f"{config.CURVE_CAP_MIN_CORPUS} fingerprints "
              f"({n_fp_total}/{config.CURVE_CAP_MIN_CORPUS})")
    if aph_keyed:
        print(f"  aphorism endings:              {aph_true}/{aph_keyed} keyed sets "
              f"(register-rotation baseline ~12.5%)")
    history.record_health(window, fam_kl, topo_kl, [], chi2)
    history.close()
    return 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(args) -> int:
    history = HistoryStore(args.db)
    q = ("SELECT rc_id, tier, rc_text, average_score, status, created_at, "
         "compliance_f1, novelty_composite FROM rc_sets WHERE rc_text IS NOT NULL")
    params: list = []
    if args.status:
        q += " AND status = ?"
        params.append(args.status)
    rows = history.conn.execute(q, params).fetchall()
    os.makedirs(args.out, exist_ok=True)
    for rc_id, tier, rc_text, avg, status, created, f1, nov in rows:
        header = (f"RC ID: {rc_id} | Tier: {tier} | Score: {avg} | Status: {status} | "
                  f"Compliance F1: {f1} | Novelty: {nov} | Generated: {created}\n"
                  + "=" * 70 + "\n\n")
        with open(os.path.join(args.out, f"{rc_id}.txt"), "w", encoding="utf-8") as f:
            f.write(header + rc_text)
    print(f"Exported {len(rows)} set(s) to '{args.out}/'")
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


def _parse_rc_txt(text: str) -> dict:
    """Parse MANUAL_GENERATION_PROMPT.md's OUTPUT FORMAT (which the engine's
    own exports also follow). Tolerant of missing sections."""
    body = re.sub(r"^RC ID:.*?={10,}\s*", "", text, flags=re.DOTALL)

    def _section(start: str, end: str) -> str | None:
        s = body.find(start)
        if s == -1:
            return None
        s += len(start)
        e = body.find(end, s)
        return body[s:e if e != -1 else len(body)].strip()

    passage = _section("[PASSAGE]", "[QUESTIONS]")
    qblock = _section("[QUESTIONS]", "[ANSWER KEY")
    keyblock = body[body.find("[ANSWER KEY"):] if "[ANSWER KEY" in body else ""
    if passage is None:   # no markers: passage = everything before Q1
        m = re.search(r"\nQ\s*1[.)]", body)
        passage = body[:m.start()].strip() if m else body.strip()

    questions = []
    if qblock:
        for qm in re.finditer(r"(?ms)^Q(\d)[.)]\s*(.*?)(?=^Q\d[.)]|\Z)", qblock):
            parts = re.split(r"(?m)^\(([A-D])\)\s*", qm.group(2))
            options = {parts[i]: {"text": " ".join(parts[i + 1].split())}
                       for i in range(1, len(parts) - 1, 2)}
            questions.append({"q": int(qm.group(1)),
                              "stem": parts[0].strip(), "options": options})

    from .fingerprints import parse_answer_letters
    mechanisms: dict[str, int] = {}
    for _letter, mech in _MECH_LINE.findall(keyblock):
        mechanisms[mech] = mechanisms.get(mech, 0) + 1
    pm = re.search(r"Posture:\s*([a-z_]+)", keyblock)
    return {"passage": passage, "questions": questions,
            "letters": parse_answer_letters(text),
            "mechanisms": mechanisms, "posture": pm.group(1) if pm else None}


def cmd_vet(args) -> int:
    from .fingerprints import rhythm_vector, stylometry_profile, _embed
    from .models import Fingerprint
    from .novelty import NoveltyScorer
    from .question_engine import length_bias_report

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

    # -- structural + letter audits (the manual prompt's Stage-4 rules) ------
    warnings: list[str] = []
    if len(questions) != 6:
        warnings.append(f"expected 6 questions, parsed {len(questions)}")
    for q in questions:
        if len(q["options"]) != 4:
            warnings.append(f"Q{q['q']}: parsed {len(q['options'])}/4 options")
    if letters and len(letters) != len(questions):
        warnings.append(f"answer key covers {len(letters)}/{len(questions)} questions")
    if args.tier:
        lo, hi = config.TIER_PARAMS[args.tier]["passage_words"]
        if not lo - 40 <= words <= hi + 40:
            warnings.append(f"passage {words} words vs {args.tier} band {lo}-{hi}")
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
    history = HistoryStore(args.db)
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
        print("\nPASS — re-run with --ingest to add it to the corpus.")
    else:
        print("\nReview the flags above before shipping this set.")
    history.close()
    return 0 if ok or args.ingest else 1


# ---------------------------------------------------------------------------
# avoid — paste-ready AVOID line for MANUAL_GENERATION_PROMPT.md
# ---------------------------------------------------------------------------

def cmd_avoid(args) -> int:
    reg = ComponentRegistry()
    history = HistoryStore(args.db)
    rows = history.conn.execute(
        """SELECT rc_id, family_id, blueprint_json FROM blueprints
           WHERE status = 'shipped' ORDER BY created_at DESC LIMIT ?""",
        (args.n,)).fetchall()
    if not rows:
        print("No shipped engine sets in this DB yet — build the AVOID line "
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

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rc_engine", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("estimate", help="print per-tier cost table ($0)")
    sub.add_parser("selftest", help="mock end-to-end run ($0)")

    g = sub.add_parser("generate", help="generate RCs")
    g.add_argument("--medium", type=int, default=0)
    g.add_argument("--hard", type=int, default=0)
    g.add_argument("--elite", type=int, default=0)
    g.add_argument("--db", default=config.DB_PATH)
    g.add_argument("--dry-run", action="store_true", help="mock client, $0")
    g.add_argument("--no-seed", action="store_true", help="skip RAG seed essays")
    g.add_argument("--no-embed", action="store_true", help="disable embedding channel")
    g.add_argument("--no-export", action="store_true")
    g.add_argument("--max-usd", type=float, default=None,
                   help="batch spending cap (default: 1.25 x sum of requested tier budgets)")

    r = sub.add_parser("retry-questions",
                       help="regenerate questions on a persisted passage whose "
                            "questions failed (questions-stage cost only)")
    r.add_argument("--blueprint", default=None,
                   help="blueprint id (BP_...) to resume; omit to list resumable passages")
    r.add_argument("--all", action="store_true",
                   help="resume every questions_failed passage")
    r.add_argument("--note", default=None,
                   help="extra directives appended to the question prompt")
    r.add_argument("--db", default=config.DB_PATH)
    r.add_argument("--dry-run", action="store_true", help="mock client, $0")
    r.add_argument("--no-embed", action="store_true", help="disable embedding channel")

    b = sub.add_parser("backfill", help="fingerprint legacy rc_sets rows and/or exported txt ($0)")
    b.add_argument("--db", default=config.DB_PATH)
    b.add_argument("--from-txt", nargs="*", default=["exported_rc_sets", "approved_rc_sets - Copy"],
                   help="directories of exported RC .txt files to fingerprint")

    h = sub.add_parser("health", help="corpus health snapshot ($0)")
    h.add_argument("--db", default=config.DB_PATH)

    e = sub.add_parser("export", help="export rc_sets to txt")
    e.add_argument("--db", default=config.DB_PATH)
    e.add_argument("--status", default=None)
    e.add_argument("--out", default="exported_rc_sets")

    a = sub.add_parser("avoid", help="AVOID line for the manual prompt ($0)")
    a.add_argument("--db", default=config.DB_PATH)
    a.add_argument("--n", type=int, default=4,
                   help="how many recent shipped sets to include")

    v = sub.add_parser("vet", help="run the free gates on a manual RC .txt ($0)")
    v.add_argument("file", help="RC .txt in the manual prompt's output format")
    v.add_argument("--db", default=config.DB_PATH)
    v.add_argument("--id", default=None,
                   help="rc_id override (default: 'RC ID:' line, else filename)")
    v.add_argument("--tier", choices=["medium", "hard", "elite"], default=None,
                   help="also check the passage word count against this tier's band")
    v.add_argument("--ingest", action="store_true",
                   help="on pass, store the fingerprint with source='manual'")
    v.add_argument("--force", action="store_true",
                   help="ingest even with breaches/warnings")
    v.add_argument("--no-embed", action="store_true",
                   help="skip the embedding channel (faster)")

    args = p.parse_args(argv)
    return {"estimate": cmd_estimate, "selftest": cmd_selftest,
            "generate": cmd_generate, "backfill": cmd_backfill,
            "health": cmd_health, "export": cmd_export,
            "avoid": cmd_avoid, "vet": cmd_vet,
            "retry-questions": cmd_retry_questions}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
