"""Small process/usage helpers shared by subscription CLI clients (2026-09-20)."""
from __future__ import annotations

import os
import signal
import subprocess


def subscription_env() -> dict[str, str]:
    """Keep saved CLI login locations, never inherit API billing overrides.

    config loads .env into the parent process. Passing that environment to
    headless Claude selected API billing while its ledger booked zero dollars.
    Only the child is sanitized; API clients in the parent retain their keys.
    """
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(("ANTHROPIC_", "OPENAI_",
                                         "CLAUDE_CODE_USE_", "AWS_", "AZURE_"))
            and k.upper() not in {"CODEX_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                                  "GOOGLE_APPLICATION_CREDENTIALS"}}


def run_process(argv, turn, timeout, *, cwd, env):
    """Run a native binary; cancel its process tree on timeout/interruption."""
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
               if os.name == "nt" else {"start_new_session": True})
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          cwd=cwd, env=env, **options) as proc:
        try:
            stdout, stderr = proc.communicate(turn, timeout=timeout)
        except BaseException:
            # Windows subprocess.kill() alone can leave the CLI's children
            # consuming quota. PID is from our own Popen, never user input.
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=15)
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, subprocess.SubprocessError):
                # A child may already have exited, or taskkill may fail. Keep
                # the original timeout/interruption as the caller's error.
                pass
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate()
            raise
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def usage_snapshot(client) -> dict:
    if not getattr(client, "usage", None):
        return {}
    return {"usage": dict(client.usage),
            "by_stage": {k: dict(v) for k, v in client.by_stage.items()},
            "notional_usd": client.notional_usd,
            "label": getattr(client, "usage_label", "Claude Code")}


def usage_delta(before: dict, after: dict) -> dict:
    """Workers return slot deltas, not repeated lifetime totals."""
    if not after:
        return {}
    return {"label": after["label"],
            "usage": {k: v - before.get("usage", {}).get(k, 0)
                      for k, v in after["usage"].items()},
            "by_stage": {s: {k: v - before.get("by_stage", {}).get(s, {}).get(k, 0)
                              for k, v in d.items()}
                         for s, d in after["by_stage"].items()},
            "notional_usd": after["notional_usd"] - before.get("notional_usd", 0)}
