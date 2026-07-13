"""Read-only SQLite access for the GUI.

The production DB lives in a OneDrive-synced folder; the GUI NEVER opens it
writable. Every helper opens a mode=ro URI connection per call and closes it
immediately — safe alongside the pipeline's short write transactions (5s busy
timeout absorbs the rare lock).
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db_path() -> str:
    p = os.environ.get("RC_ENGINE_DB", "rc_pipeline.db")
    if not os.path.isabs(p):
        p = os.path.join(PROJECT_ROOT, p)
    return p


def _connect() -> sqlite3.Connection:
    path = db_path()
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    uri = "file:" + urllib.parse.quote(path.replace("\\", "/"), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def _provider_col(conn) -> str:
    """The provider column is added by the engine's write path; a read-only
    GUI must tolerate DBs from before the migration ran."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rc_sets)")]
    return "provider" if "provider" in cols else "NULL AS provider"


def dashboard() -> dict:
    try:
        conn = _connect()
    except FileNotFoundError:
        return {"available": False, "reason": "database not found",
                "db_path": db_path()}
    try:
        out: dict = {"available": True, "db_path": db_path()}
        out["by_status"] = {r["status"]: r["n"] for r in _rows(
            conn, "SELECT status, COUNT(*) n FROM rc_sets GROUP BY status")}
        out["by_tier"] = {r["tier"]: r["n"] for r in _rows(
            conn, "SELECT tier, COUNT(*) n FROM rc_sets GROUP BY tier")}
        out["total"] = sum(out["by_status"].values())
        out["total_spend"] = conn.execute(
            "SELECT COALESCE(SUM(total_cost_usd), 0) FROM rc_sets").fetchone()[0]
        out["recent"] = _rows(conn, f"""
            SELECT rc_id, tier, status, average_score, compliance_f1,
                   novelty_composite, total_cost_usd, {_provider_col(conn)}, created_at
            FROM rc_sets ORDER BY created_at DESC LIMIT 10""")
        out["resumable"] = 0
        if _table_exists(conn, "rendered_passages"):
            out["resumable"] = conn.execute(
                "SELECT COUNT(*) FROM rendered_passages WHERE status='questions_failed'"
            ).fetchone()[0]
        out["health"] = None
        if _table_exists(conn, "corpus_health"):
            rows = _rows(conn, "SELECT * FROM corpus_health ORDER BY created_at DESC LIMIT 1")
            out["health"] = rows[0] if rows else None
        return out
    finally:
        conn.close()


def rc_list(status: str | None, tier: str | None,
            limit: int = 50, offset: int = 0) -> dict:
    conn = _connect()
    try:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if tier:
            where.append("tier = ?")
            params.append(tier)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM rc_sets {clause}", params).fetchone()[0]
        rows = _rows(conn, f"""
            SELECT rc_id, tier, status, average_score, compliance_f1,
                   novelty_composite, total_cost_usd, attempts,
                   {_provider_col(conn)}, created_at
            FROM rc_sets {clause}
            ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [limit, offset])
        return {"total": total, "rows": rows}
    finally:
        conn.close()


def rc_detail(rc_id: str) -> dict | None:
    conn = _connect()
    try:
        rows = _rows(conn, "SELECT * FROM rc_sets WHERE rc_id = ?", (rc_id,))
        if not rows:
            return None
        row = rows[0]
        row.pop("passage_embedding", None)  # bulky, useless in the UI
        return row
    finally:
        conn.close()


def resumable() -> list[dict]:
    conn = _connect()
    try:
        if not _table_exists(conn, "rendered_passages"):
            return []
        rows = _rows(conn, """
            SELECT rp.blueprint_id, rp.tier, rp.compliance_f1, rp.spent_usd,
                   rp.fail_notes, rp.created_at, rp.seed_title, b.blueprint_json
            FROM rendered_passages rp
            JOIN blueprints b ON b.blueprint_id = rp.blueprint_id
            WHERE rp.status = 'questions_failed'
            ORDER BY rp.created_at DESC""")
        for r in rows:
            try:
                r["topic"] = json.loads(r.pop("blueprint_json")).get("topic", "")
            except (ValueError, TypeError):
                r["topic"] = ""
                r.pop("blueprint_json", None)
        return rows
    finally:
        conn.close()


def health_history(limit: int = 60) -> list[dict]:
    conn = _connect()
    try:
        if not _table_exists(conn, "corpus_health"):
            return []
        rows = _rows(conn, """
            SELECT window_size, family_kl, topology_kl, slot_chi2_flags,
                   letter_runs_p, created_at
            FROM corpus_health ORDER BY created_at DESC LIMIT ?""", (limit,))
        rows.reverse()  # chronological for sparklines
        return rows
    finally:
        conn.close()
