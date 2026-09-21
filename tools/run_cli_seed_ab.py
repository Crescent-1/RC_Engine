"""Run one controlled real RC generation lane for a fixed-seed CLI A/B test."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _clone_db(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    baseline = src.execute("SELECT COALESCE(MAX(rowid), 0) FROM rc_sets").fetchone()[0]
    dest = sqlite3.connect(destination)
    with dest:
        src.backup(dest)
    dest.close()
    src.close()
    return int(baseline)


def _export_new(db_path: Path, out: Path, lane: str, baseline: int, seed: dict) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = list(con.execute(
        "SELECT * FROM rc_sets WHERE rowid > ? AND rc_text IS NOT NULL ORDER BY rowid",
        (baseline,)))
    con.close()
    exported = []
    for row in rows:
        header = (
            f"A/B lane: {lane} | Seed ID: {seed['id']} | Seed: {seed['title']}\n"
            f"Seed URL: {seed['url']}\n"
            f"RC ID: {row['rc_id']} | Tier: {row['tier']} | Score: {row['average_score']} | "
            f"Status: {row['status']} | Compliance F1: {row['compliance_f1']} | "
            f"Novelty: {row['novelty_composite']} | Screen: {row['similarity_verdict']} | "
            f"Generated: {row['created_at']}\n" + "=" * 70 + "\n\n")
        path = out / f"{lane}-{row['rc_id']}.txt"
        path.write_text(header + row["rc_text"], encoding="utf-8")
        exported.append({
            "rc_id": row["rc_id"], "tier": row["tier"], "status": row["status"],
            "average_score": row["average_score"], "compliance_f1": row["compliance_f1"],
            "novelty_composite": row["novelty_composite"],
            "similarity_verdict": row["similarity_verdict"], "file": str(path.resolve()),
        })
    return exported


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", choices=("claude", "openai"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-db", default="rc_pipeline.db")
    parser.add_argument("--rng-seed", type=int, default=20260921)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    seed = json.loads((out / "seed.json").read_text(encoding="utf-8"))
    db_path = out / "state" / f"{args.lane}.db"
    baseline_path = out / "state" / "baseline.json"
    if baseline_path.exists():
        baseline = int(json.loads(baseline_path.read_text())["max_rc_rowid"])
    else:
        # Both lane DBs are created before either generation starts.
        baseline = _clone_db(Path(args.source_db).resolve(), out / "state" / "claude.db")
        other = _clone_db(Path(args.source_db).resolve(), out / "state" / "openai.db")
        if other != baseline:
            raise RuntimeError("A/B database snapshots have different baselines")
        baseline_path.write_text(json.dumps({
            "max_rc_rowid": baseline,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source_db": str(Path(args.source_db).resolve()),
            "rng_seed": args.rng_seed,
        }, indent=2), encoding="utf-8")

    # Configure before importing the engine.
    os.environ.update(
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
        RC_ENGINE_CODEX_TIMEOUT_S="1800", RC_ENGINE_CLAUDE_CODE_TIMEOUT_S="1800")
    from rc_engine import cli, codex_cli
    from rc_engine.history import HistoryStore
    from rc_engine.pipeline import RCPipeline as RealPipeline
    import RAG

    # A/B artifacts are not shipped corpus. Keep the shared seed unused and
    # compare both lanes against independent copies of the same baseline.
    RAG.mark_essay_used = lambda db, doc_id, rc_id: True

    class ControlledPipeline(RealPipeline):
        def __init__(self, history, llm, embed=True, rng=None, **kwargs):
            super().__init__(history, llm, embed=embed,
                             rng=random.Random(args.rng_seed), **kwargs)

    cli.RCPipeline = ControlledPipeline
    backup_dir = out / "backups" / args.lane
    original_backup = HistoryStore.backup_to
    HistoryStore.backup_to = lambda self, *a, **kw: original_backup(
        self, str(backup_dir), keep=1000)

    calls_dir = out / "calls" / args.lane
    calls_dir.mkdir(parents=True, exist_ok=True)
    if args.lane == "openai":
        original_run = codex_cli.run_process
        counter = {"n": 0}

        def capture(argv, *run_args, **run_kwargs):
            result = original_run(argv, *run_args, **run_kwargs)
            counter["n"] += 1
            stem = calls_dir / f"{counter['n']:02d}"
            stem.with_suffix(".events.jsonl").write_text(result.stdout or "", encoding="utf-8")
            stem.with_suffix(".stderr.txt").write_text(result.stderr or "", encoding="utf-8")
            meta = Path(run_kwargs["cwd"]) / "metadata.json"
            if meta.exists():
                stem.with_suffix(".metadata.json").write_text(
                    meta.read_text(encoding="utf-8"), encoding="utf-8")
            return result

        codex_cli.run_process = capture
    else:
        from rc_engine.claude_code import ClaudeCodeClient
        original_subprocess = ClaudeCodeClient._subprocess
        counter = {"n": 0}

        def capture(self, argv, turn, timeout):
            result = original_subprocess(self, argv, turn, timeout)
            counter["n"] += 1
            stem = calls_dir / f"{counter['n']:02d}"
            stem.with_suffix(".response.json").write_text(result.stdout or "", encoding="utf-8")
            stem.with_suffix(".stderr.txt").write_text(result.stderr or "", encoding="utf-8")
            return result

        ClaudeCodeClient._subprocess = capture

    lane_args = (["--claude-code", "--claude-code-effort", "low"]
                 if args.lane == "claude"
                 else ["--codex-cli", "--codex-effort", "low"])
    argv = ["generate", "--hard", "1", "--db", str(db_path),
            "--seed-ids", str(out / "seed-ids.json"), "--require-seed",
            "--generation-policy", "cat-pyq-f4", "--no-export", *lane_args]
    log_path = out / f"{args.lane}.log"
    code = 1
    with (log_path.open("w", encoding="utf-8", buffering=1) as log,
          redirect_stdout(log), redirect_stderr(log)):
        print(json.dumps({"lane": args.lane, "seed": seed, "rng_seed": args.rng_seed,
                          "policy": "cat-pyq-f4", "effort": "low"}, ensure_ascii=False))
        try:
            code = cli.main(argv)
        finally:
            exported = _export_new(db_path, out, args.lane, baseline, seed)
            result = {"lane": args.lane, "exit_code": code, "seed": seed,
                      "rng_seed": args.rng_seed, "policy": "cat-pyq-f4",
                      "effort": "low", "exported": exported,
                      "finished_utc": datetime.now(timezone.utc).isoformat()}
            (out / f"{args.lane}-result.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
