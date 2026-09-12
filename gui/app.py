"""RC Engine GUI — FastAPI backend.

Reads: direct read-only SQLite (gui.db). Actions: subprocesses of the tested
CLI (gui.jobs). Long-running jobs stream stdout over SSE. Localhost only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rc_engine import config
from rc_engine.providers import provider_key_present, provider_key_source

from . import db
from .jobs import MANAGER, PROJECT_ROOT

app = FastAPI(title="RC Engine GUI")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
VET_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vet_tmp")

PY = sys.executable


def _cli(*args: str) -> list[str]:
    return [PY, "-m", "rc_engine.cli", *args]


_CLIENT_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def _client_args(client: str | None) -> list[str]:
    """--client for a CLI call (2026-09-12). The CLI rejects an unknown client
    itself; this only keeps malformed input out of argv."""
    if not client:
        return []
    if not _CLIENT_SLUG.match(client):
        raise HTTPException(400, "invalid client")
    return ["--client", client]


def _run_sync(argv: list[str], timeout: int = 120) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(argv, cwd=PROJECT_ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"command timed out after {timeout}s")
    return {"returncode": proc.returncode,
            "output": (proc.stdout or "") + (proc.stderr or "")}


def _start_job(kind: str, argv: list[str]) -> JSONResponse:
    try:
        job = MANAGER.start(kind, argv)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return JSONResponse({"job_id": job.id}, status_code=201)


# ------------------------------------------------------------------- reads

@app.get("/api/clients")
def api_clients():
    return db.clients()


@app.get("/api/dashboard")
def api_dashboard(client: str | None = None):
    data = db.dashboard(client)
    data["last_job"] = MANAGER.last_finished()
    cur = MANAGER.busy()
    data["running_job"] = cur.meta() if cur else None
    return data


@app.get("/api/rcs")
def api_rcs(status: str | None = None, tier: str | None = None,
            limit: int = 50, offset: int = 0, client: str | None = None):
    return db.rc_list(status, tier, min(limit, 200), max(offset, 0), client)


@app.get("/api/rcs/{rc_id}")
def api_rc_detail(rc_id: str):
    row = db.rc_detail(rc_id)
    if row is None:
        raise HTTPException(404, "no such RC")
    return row


@app.get("/api/resumable")
def api_resumable(client: str | None = None):
    return db.resumable(client)


@app.get("/api/health")
def api_health(client: str | None = None):
    return {"history": db.health_history(client=client)}


@app.get("/api/settings")
def api_settings():
    return {
        "providers": [
            {"name": p,
             "models": config.PROVIDER_MODELS[p],
             "env_keys": list(config.PROVIDER_ENV_KEYS[p]),
             # presence booleans ONLY — key values never leave the server
             "key_present": provider_key_present(p) is not None,
             # presence is NOT health: a revoked key looks identical to a good
             # one, which is how a stale shadowing key stayed invisible until it
             # 401'd mid-batch. Say where the key came from too.
             "key_var": provider_key_present(p),
             "key_source": provider_key_source(p)}
            for p in config.PROVIDERS
        ],
        # non-empty => the environment is silently overriding .env
        "key_conflicts": config.shadowing_conflicts(),
        "model_rates": {m: {"input": r[0], "output": r[1]}
                        for m, r in config.MODEL_RATES.items()},
        "tier_budgets": config.TIER_BUDGET_USD,
        "db_path": db.db_path(),
        "backup_dir": config.DB_BACKUP_DIR,
        "engine_version": config.ENGINE_VERSION,
    }


@app.get("/api/estimate")
def api_estimate(provider: str = "claude"):
    if provider not in config.PROVIDERS:
        raise HTTPException(400, "unknown provider")
    return _run_sync(_cli("estimate", "--provider", provider), timeout=60)


def _avoid_line(n: int, client: str | None = None) -> tuple[str, str]:
    """(avoid_line, full_avoid_output). avoid_line is the single paste-ready
    'AVOID (from my recent sets): …' line, empty if none."""
    res = _run_sync(_cli("avoid", "--n", str(max(1, min(n, 20))),
                         *_client_args(client)), timeout=60)
    line = ""
    for raw in res["output"].splitlines():
        if raw.strip().startswith("AVOID"):
            line = raw.strip()
            break
    return line, res["output"].strip()


@app.get("/api/avoid")
def api_avoid(n: int = 4, client: str | None = None):
    return _run_sync(_cli("avoid", "--n", str(max(1, min(n, 20))),
                          *_client_args(client)), timeout=60)


MANUAL_PROMPT_PATH = os.path.join(PROJECT_ROOT, "MANUAL_GENERATION_PROMPT.md")


@app.get("/api/manual-prompt")
def api_manual_prompt(n: int = 4, tier: str = "elite", client: str | None = None):
    """The full manual-generation prompt (the block between the START/END
    markers) plus a ready-to-send first message with the current AVOID line
    injected for the chosen tier."""
    if tier not in ("medium", "hard", "elite"):
        raise HTTPException(400, "unknown tier")
    try:
        text = open(MANUAL_PROMPT_PATH, encoding="utf-8").read()
    except OSError as e:
        raise HTTPException(500, f"cannot read MANUAL_GENERATION_PROMPT.md: {e}")
    lo, hi = "=== PROMPT START ===", "=== PROMPT END ==="
    start_marker = f"\n{lo}\n"
    end_marker = f"\n{hi}\n"
    i = text.find(start_marker)
    j = text.find(end_marker, i + len(start_marker))
    if i == -1 or j == -1:
        raise HTTPException(500, "prompt markers not found in the file")
    block = text[i + len(start_marker):j].strip()

    avoid_line, avoid_note = _avoid_line(n, client)
    first_message = f"TIER: {tier}"
    if avoid_line:
        first_message += "\n" + avoid_line
    full = (block
            + "\n\n--- First set message (send AFTER pasting the prompt above) ---\n\n"
            + first_message)
    return {"prompt_block": block, "avoid_line": avoid_line,
            "first_message": first_message, "full": full, "avoid_note": avoid_note}


@app.get("/api/seeds")
def api_seeds():
    probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds_probe.py")
    res = _run_sync([PY, probe], timeout=90)
    try:
        return json.loads(res["output"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"available": False, "reason": res["output"][-400:]}


@app.get("/api/tracker")
def api_tracker():
    path = os.path.join(PROJECT_ROOT, "RC_Tracker.xlsx")
    return {"exists": os.path.exists(path),
            "mtime": os.path.getmtime(path) if os.path.exists(path) else None,
            "path": path}


# ------------------------------------------------------------------- jobs

class GenerateBody(BaseModel):
    medium: int = 0
    hard: int = 0
    elite: int = 0
    provider: str = "claude"
    dry_run: bool = False
    max_usd: float | None = None
    no_seed: bool = False
    no_embed: bool = False
    workers: int = 1
    client: str | None = None


@app.post("/api/jobs/generate")
def api_generate(body: GenerateBody):
    if body.provider not in config.PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if body.medium + body.hard + body.elite <= 0:
        raise HTTPException(400, "nothing to generate")
    argv = _cli("generate", "--provider", body.provider, *_client_args(body.client))
    for tier in ("medium", "hard", "elite"):
        n = getattr(body, tier)
        if n > 0:
            argv += [f"--{tier}", str(n)]
    if body.dry_run:
        argv.append("--dry-run")
    if body.max_usd is not None:
        argv += ["--max-usd", str(body.max_usd)]
    if body.no_seed:
        argv.append("--no-seed")
    if body.no_embed:
        argv.append("--no-embed")
    if body.workers and body.workers > 1:
        argv += ["--workers", str(min(int(body.workers), config.BATCH_WORKERS_MAX))]
    return _start_job("generate", argv)


class RetryBody(BaseModel):
    blueprint: str | None = None
    all: bool = False
    note: str | None = None
    provider: str = "claude"
    dry_run: bool = False
    client: str | None = None


@app.post("/api/jobs/retry")
def api_retry(body: RetryBody):
    if body.provider not in config.PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if not body.blueprint and not body.all:
        raise HTTPException(400, "blueprint or all required")
    argv = _cli("retry-questions", "--provider", body.provider,
                *_client_args(body.client))
    if body.all:
        argv.append("--all")
    elif body.blueprint:
        argv += ["--blueprint", body.blueprint]
    if body.note:
        argv += ["--note", body.note]
    if body.dry_run:
        argv.append("--dry-run")
    return _start_job("retry", argv)


@app.post("/api/jobs/rag-sync")
def api_rag_sync():
    return _start_job("rag-sync", [PY, os.path.join(PROJECT_ROOT, "RAG.py")])


@app.post("/api/jobs/backfill")
def api_backfill(client: str | None = None):
    return _start_job("backfill", _cli("backfill", *_client_args(client)))


@app.post("/api/jobs/health-snapshot")
def api_health_snapshot(client: str | None = None):
    return _start_job("health", _cli("health", "--all", *_client_args(client)))


@app.get("/api/jobs")
def api_jobs():
    cur = MANAGER.busy()
    return {"running": cur.meta() if cur else None, "recent": MANAGER.list()}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = MANAGER.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job.meta()


@app.get("/api/jobs/{job_id}/stream")
def api_job_stream(job_id: str):
    return StreamingResponse(MANAGER.stream(job_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/kill")
def api_job_kill(job_id: str):
    if not MANAGER.kill(job_id):
        raise HTTPException(404, "no running job with that id")
    return {"ok": True}


# ------------------------------------------------------------- sync actions

class ExportBody(BaseModel):
    status: str | None = None
    client: str | None = None


@app.post("/api/export")
def api_export(body: ExportBody):
    argv = _cli("export", *_client_args(body.client))
    if body.status:
        argv += ["--status", body.status]
    return _run_sync(argv, timeout=120)


@app.post("/api/tracker/rebuild")
def api_tracker_rebuild():
    return _run_sync([PY, os.path.join(PROJECT_ROOT, "build_tracker.py")],
                     timeout=180)


@app.post("/api/vet")
async def api_vet(text: str | None = Form(None),
                  file: UploadFile | None = File(None),
                  tier: str | None = Form(None),
                  ingest: bool = Form(False),
                  force: bool = Form(False),
                  no_embed: bool = Form(True),
                  client: str | None = Form(None)):
    if MANAGER.busy():
        raise HTTPException(409, "a job is running — vet writes to the DB on "
                                 "ingest, try again when it finishes")
    content = text or ""
    if file is not None:
        content = (await file.read()).decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(400, "no RC text provided")
    os.makedirs(VET_TMP, exist_ok=True)
    tmp = os.path.join(VET_TMP, f"vet_{uuid.uuid4().hex[:8]}.txt")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        argv = _cli("vet", tmp, *_client_args(client))
        if tier in ("medium", "hard", "elite"):
            argv += ["--tier", tier]
        if ingest:
            argv.append("--ingest")
        if force:
            argv.append("--force")
        if no_embed:
            argv.append("--no-embed")
        return _run_sync(argv, timeout=600)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# static frontend LAST so /api/* wins
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
