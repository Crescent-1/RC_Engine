"""Job manager: one subprocess at a time, line-buffered stdout fan-out to SSE.

Actions (generate, retry, RAG sync, backfill, ...) run as child processes of
the GUI server — `sys.executable -m rc_engine.cli ...` etc. — so the tested
CLI logic (budget caps, auto-export, DB backup, resume persistence) is reused
verbatim and heavy imports stay out of the server process. A GUI crash can
never corrupt a run: the child either finishes or the engine's built-in
resume path recovers.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "jobs_history.jsonl")
MAX_LINES = 5000        # ring cap per job
HISTORY_TAIL = 200      # lines persisted per finished job


class Job:
    def __init__(self, kind: str, argv: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.argv = argv
        self.status = "running"          # running | done | failed | killed
        self.returncode: int | None = None
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.lines: list[str] = []
        self.cond = threading.Condition()
        self._proc: subprocess.Popen | None = None
        self._killed = False

    def meta(self) -> dict:
        return {"id": self.id, "kind": self.kind, "argv": self.argv,
                "status": self.status, "returncode": self.returncode,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "n_lines": len(self.lines)}


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._current: Job | None = None

    # ------------------------------------------------------------- lifecycle

    def busy(self) -> Job | None:
        cur = self._current
        return cur if cur and cur.status == "running" else None

    def start(self, kind: str, argv: list[str]) -> Job:
        """Raises RuntimeError if a job is already running."""
        with self._lock:
            if self.busy():
                raise RuntimeError(f"a {self._current.kind} job is already running")
            job = Job(kind, argv)
            env = {**os.environ,
                   "PYTHONUNBUFFERED": "1",
                   "PYTHONIOENCODING": "utf-8"}
            job._proc = subprocess.Popen(
                argv, cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env)
            self._jobs[job.id] = job
            self._current = job
            threading.Thread(target=self._pump, args=(job,), daemon=True).start()
            return job

    def _pump(self, job: Job):
        proc = job._proc
        try:
            for line in proc.stdout:
                with job.cond:
                    job.lines.append(line.rstrip("\n"))
                    if len(job.lines) > MAX_LINES:
                        job.lines = job.lines[-MAX_LINES:]
                    job.cond.notify_all()
        finally:
            rc = proc.wait()
            with job.cond:
                job.returncode = rc
                job.finished_at = time.time()
                job.status = ("killed" if job._killed
                              else "done" if rc == 0 else "failed")
                job.cond.notify_all()
            self._persist(job)

    def kill(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status != "running":
            return False
        job._killed = True
        job._proc.terminate()  # TerminateProcess on win32
        return True

    # --------------------------------------------------------------- queries

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.started_at,
                      reverse=True)
        return [j.meta() for j in jobs[:20]]

    def stream(self, job_id: str):
        """SSE generator: replay buffered lines, then live-tail until done."""
        job = self._jobs.get(job_id)
        if job is None:
            yield _sse({"type": "error", "message": "unknown job"})
            return
        idx = 0
        while True:
            with job.cond:
                while idx >= len(job.lines) and job.status == "running":
                    job.cond.wait(timeout=15)
                chunk = job.lines[idx:]
                idx += len(chunk)
                status = job.status
                rc = job.returncode
            for line in chunk:
                yield _sse({"type": "line", "text": line})
            if status != "running" and idx >= len(job.lines):
                yield _sse({"type": "status", "status": status, "returncode": rc})
                return

    # ------------------------------------------------------------ persistence

    def _persist(self, job: Job):
        try:
            rec = job.meta()
            rec["tail"] = job.lines[-HISTORY_TAIL:]
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @staticmethod
    def last_finished() -> dict | None:
        """Most recent record from jobs_history.jsonl (survives restarts)."""
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                last = None
                for line in f:
                    if line.strip():
                        last = line
            if last:
                rec = json.loads(last)
                rec.pop("tail", None)
                return rec
        except (OSError, ValueError):
            pass
        return None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


MANAGER = JobManager()
