"""SQLite persistence: blueprints, component usage, fingerprints, novelty
audits, corpus health — plus a legacy-compatible rc_sets table so the
existing export tooling keeps working on the same database file."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config
from .models import Blueprint, Fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _movement_of(bp) -> str:
    """Blueprint.movement_string is a method; test doubles use an attribute."""
    mv = getattr(bp, "movement_string", "")
    return (mv() if callable(mv) else mv) or ""


class HistoryStore:
    def __init__(self, db_path: str = config.DB_PATH):
        self._db_path = db_path
        self.conn = sqlite3.connect(db_path)
        # Wait on a locked DB instead of failing at once: the GUI opens it
        # read-only, backups use the online-backup API, and a second generate
        # process must queue behind the writer rather than die mid-ship.
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._init_tables()

    def close(self):
        self.conn.close()

    def backup_to(self, dest_dir: str = config.DB_BACKUP_DIR,
                  keep: int = config.DB_BACKUP_KEEP) -> str | None:
        """Copy the DB to a non-synced local folder via SQLite's online backup
        API (safe against a live/locked DB, unlike a file copy). Keeps the
        newest `keep` backups. Never fatal — returns the path or None."""
        try:
            check = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                print(f"[backup] WARNING: integrity_check reported: {check}")
            os.makedirs(dest_dir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            dest = os.path.join(dest_dir, f"rc_pipeline-{stamp}.db")
            target = sqlite3.connect(dest)
            with target:
                self.conn.backup(target)
            target.close()
            backups = sorted(f for f in os.listdir(dest_dir)
                             if f.startswith("rc_pipeline-") and f.endswith(".db"))
            for old in backups[:-keep]:
                os.remove(os.path.join(dest_dir, old))
            print(f"[backup] DB -> {dest} (integrity: {check}; keeping last {keep})")
            return dest
        except Exception as e:
            print(f"[backup] failed (non-fatal): {e}")
            return None

    # ------------------------------------------------------------------ init

    def _init_tables(self):
        c = self.conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS rc_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rc_id TEXT UNIQUE, tier TEXT, rc_text TEXT, judge_json TEXT,
                average_score REAL, status TEXT, essay_doc_id TEXT, essay_url TEXT,
                gen_input_tokens INTEGER, gen_output_tokens INTEGER,
                judge_input_tokens INTEGER, judge_output_tokens INTEGER,
                gen_cost_usd REAL, judge_cost_usd REAL, total_cost_usd REAL,
                attempts INTEGER, created_at TEXT
            )""")
        for col, decl in [
            ("solver_json", "TEXT"), ("solver_input_tokens", "INTEGER"),
            ("solver_output_tokens", "INTEGER"), ("solver_cost_usd", "REAL"),
            ("domain", "TEXT"), ("passage_embedding", "TEXT"),
            ("blueprint_id", "TEXT"), ("compliance_f1", "REAL"),
            ("novelty_composite", "REAL"), ("engine_version", "TEXT"),
            ("provider", "TEXT"),
        ]:
            self._ensure_column("rc_sets", col, decl)

        c.execute("""
            CREATE TABLE IF NOT EXISTS blueprints (
                blueprint_id TEXT PRIMARY KEY,
                rc_id TEXT, tier TEXT NOT NULL,
                family_id TEXT NOT NULL, persona_id TEXT NOT NULL,
                ending_id TEXT NOT NULL, rhythm_id TEXT NOT NULL,
                revelation_id TEXT NOT NULL, distractor_profile_id TEXT NOT NULL,
                topology_id TEXT NOT NULL,
                instability REAL, aperture TEXT,
                combo_hash TEXT NOT NULL, pair_hashes TEXT NOT NULL,
                blueprint_json TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bp_status ON blueprints(status, created_at)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS rendered_passages (
                blueprint_id TEXT PRIMARY KEY,
                tier TEXT NOT NULL,
                passage TEXT NOT NULL,
                realized_json TEXT NOT NULL,
                compliance_f1 REAL,
                seed_doc_id TEXT, seed_url TEXT, seed_title TEXT,
                spent_usd REAL NOT NULL,
                status TEXT NOT NULL,
                fail_notes TEXT,
                created_at TEXT NOT NULL
            )""")
        c.execute("""CREATE INDEX IF NOT EXISTS idx_rp_status
                     ON rendered_passages(status, created_at)""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS component_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component_type TEXT NOT NULL, component_id TEXT NOT NULL,
                blueprint_id TEXT NOT NULL, shipped INTEGER NOT NULL DEFAULT 0,
                used_at TEXT NOT NULL
            )""")
        c.execute("""CREATE INDEX IF NOT EXISTS idx_cu_lookup
                     ON component_usage(component_type, component_id, used_at)""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS id_counters (
                tier TEXT PRIMARY KEY,
                next_seq INTEGER NOT NULL
            )""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                rc_id TEXT PRIMARY KEY,
                blueprint_id TEXT, persona_id TEXT,
                movement_string TEXT NOT NULL,
                commitment_curve TEXT NOT NULL,
                rhythm_vector TEXT NOT NULL,
                topology_signature TEXT NOT NULL,
                trap_histogram TEXT NOT NULL,
                letter_sequence TEXT NOT NULL,
                stylometry TEXT NOT NULL,
                embedding TEXT,
                created_at TEXT NOT NULL
            )""")
        # provenance tag: engine | legacy (backfilled) | manual (vet --ingest)
        self._ensure_column("fingerprints", "source", "TEXT DEFAULT 'engine'")
        self._ensure_column("rc_sets", "seed_genre", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "topic_shape", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "similarity_verdict", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "similarity_note", "TEXT DEFAULT ''")
        self._ensure_column("fingerprints", "move_signature", "TEXT DEFAULT ''")
        # Excluded from the novelty baseline, never deleted. See fingerprint_window.
        self._ensure_column("fingerprints", "quarantined", "INTEGER DEFAULT 0")

        # Every generate_one outcome inside run_batch, shipped or not, with what
        # it cost. rc_sets only ever held the shipped ones, so the price of a
        # rejected render lived in the process's memory and vanished with it —
        # there was no way to tell whether a gate change had cut paid waste.
        c.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                tier TEXT NOT NULL,
                slot INTEGER NOT NULL,
                attempt_no INTEGER NOT NULL,
                rc_id TEXT, blueprint_id TEXT,
                status TEXT NOT NULL,
                cost_usd REAL NOT NULL,
                novelty_composite REAL, compliance_f1 REAL,
                reason TEXT,
                created_at TEXT NOT NULL
            )""")

        # What each parallel worker is rendering RIGHT NOW, so siblings can
        # ban its skeleton before they compose. One row per worker, replaced
        # on every compose, released when the slot ends. Rows older than
        # INFLIGHT_STALE_MIN are a crashed worker's and are ignored.
        c.execute("""
            CREATE TABLE IF NOT EXISTS inflight (
                worker_id TEXT PRIMARY KEY,
                family_id TEXT, movement_string TEXT,
                seed_doc_id TEXT, topic TEXT,
                created_at TEXT NOT NULL
            )""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS novelty_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rc_id TEXT, blueprint_id TEXT NOT NULL,
                channel_scores TEXT NOT NULL, composite REAL NOT NULL,
                verdict TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
            )""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS corpus_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window_size INTEGER NOT NULL,
                family_kl REAL, topology_kl REAL,
                slot_chi2_flags TEXT, probe_accuracy REAL, letter_runs_p REAL,
                created_at TEXT NOT NULL
            )""")
        c.commit()

    def _ensure_column(self, table: str, column: str, decl: str):
        cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ------------------------------------------------------------ blueprints

    def record_blueprint(self, bp: Blueprint, status: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO blueprints
               (blueprint_id, rc_id, tier, family_id, persona_id, ending_id, rhythm_id,
                revelation_id, distractor_profile_id, topology_id, instability, aperture,
                combo_hash, pair_hashes, blueprint_json, status, created_at)
               VALUES (?,
                       (SELECT rc_id FROM blueprints WHERE blueprint_id = ?),
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bp.blueprint_id, bp.blueprint_id, bp.tier, bp.family_id, bp.persona_id,
             bp.ending_id, bp.rhythm_id, bp.revelation_id, bp.distractor_profile_id,
             bp.topology_id, bp.instability, bp.aperture, bp.combo_hash,
             json.dumps(bp.pair_hashes), bp.to_json(), status, _now()))
        self.conn.commit()

    def set_blueprint_status(self, blueprint_id: str, status: str, rc_id: str | None = None):
        if rc_id:
            self.conn.execute("UPDATE blueprints SET status = ?, rc_id = ? WHERE blueprint_id = ?",
                              (status, rc_id, blueprint_id))
        else:
            self.conn.execute("UPDATE blueprints SET status = ? WHERE blueprint_id = ?",
                              (status, blueprint_id))
        self.conn.commit()

    def mark_shipped(self, bp: Blueprint, rc_id: str):
        self.set_blueprint_status(bp.blueprint_id, "shipped", rc_id)
        for ctype, cid in bp.component_ids.items():
            self.conn.execute(
                """INSERT INTO component_usage (component_type, component_id, blueprint_id, shipped, used_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (ctype, cid, bp.blueprint_id, _now()))
        self.conn.commit()

    def recent_shipped_blueprints(self, limit: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT family_id, persona_id, ending_id, rhythm_id, revelation_id,
                      distractor_profile_id, topology_id, combo_hash, pair_hashes
               FROM blueprints WHERE status = 'shipped'
               ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
        keys = ["family", "persona", "ending", "rhythm", "revelation",
                "distractor_profile", "topology"]
        out = []
        for r in rows:
            d = dict(zip(keys, r[:7]))
            d["combo_hash"] = r[7]
            d["pair_hashes"] = json.loads(r[8]) if r[8] else {}
            out.append(d)
        return out

    def recent_topics(self, limit: int = 12,
                      statuses: tuple[str, ...] = ("shipped", "composed",
                                                   "rejected_novelty",
                                                   "rejected_questions")) -> list[str]:
        """Distinct topics of recent blueprints — shipped AND rejected, because
        a topic that just collided on the embedding channel is exactly what the
        next refine call must steer away from."""
        placeholders = ",".join("?" * len(statuses))
        rows = self.conn.execute(
            f"""SELECT blueprint_json FROM blueprints
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC LIMIT ?""",
            (*statuses, limit * 3)).fetchall()
        out: list[str] = []
        seen: set[str] = set()
        for (bj,) in rows:
            try:
                t = (json.loads(bj).get("topic") or "").strip()
            except (ValueError, TypeError):
                continue
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
            if len(out) >= limit:
                break
        return out

    def component_positions(self, ctype: str) -> dict[str, int]:
        """For each component id: how many shipped RCs ago it was last used
        (0 = most recent shipped RC). Used for exclusion windows."""
        rows = self.conn.execute(
            """SELECT cu.component_id, b.created_at
               FROM component_usage cu JOIN blueprints b ON b.blueprint_id = cu.blueprint_id
               WHERE cu.component_type = ? AND b.status = 'shipped'
               ORDER BY b.created_at DESC""", (ctype,)).fetchall()
        shipped_times = [r[0] for r in self.conn.execute(
            "SELECT created_at FROM blueprints WHERE status = 'shipped' ORDER BY created_at DESC")]
        pos_of_time = {t: i for i, t in enumerate(shipped_times)}
        out: dict[str, int] = {}
        for cid, t in rows:
            if cid not in out:
                out[cid] = pos_of_time.get(t, len(shipped_times))
        return out

    def usage_counts_trailing(self, ctype: str, window: int = 100) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT cu.component_id, COUNT(*)
               FROM component_usage cu JOIN blueprints b ON b.blueprint_id = cu.blueprint_id
               WHERE cu.component_type = ? AND b.status = 'shipped'
                 AND b.blueprint_id IN (
                     SELECT blueprint_id FROM blueprints WHERE status = 'shipped'
                     ORDER BY created_at DESC LIMIT ?)
               GROUP BY cu.component_id""", (ctype, window)).fetchall()
        return dict(rows)

    def shipped_combo_hashes(self) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT combo_hash FROM blueprints WHERE status = 'shipped'")}

    # ------------------------------------------------------ rendered passages

    def record_rendered_passage(self, blueprint_id: str, tier: str, passage: str,
                                realized_json: str, compliance_f1: float,
                                seed_doc_id: str | None, seed_url: str | None,
                                seed_title: str | None, spent_usd: float,
                                status: str = "awaiting_questions"):
        self.conn.execute(
            """INSERT OR REPLACE INTO rendered_passages
               (blueprint_id, tier, passage, realized_json, compliance_f1,
                seed_doc_id, seed_url, seed_title, spent_usd, status, fail_notes,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (blueprint_id, tier, passage, realized_json, compliance_f1,
             seed_doc_id, seed_url, seed_title, spent_usd, status, _now()))
        self.conn.commit()

    def set_passage_status(self, blueprint_id: str, status: str,
                           fail_notes: str | None = None):
        self.conn.execute(
            "UPDATE rendered_passages SET status = ?, fail_notes = ? WHERE blueprint_id = ?",
            (status, fail_notes, blueprint_id))
        self.conn.commit()

    def load_rendered_passage(self, blueprint_id: str) -> dict | None:
        row = self.conn.execute(
            """SELECT rp.blueprint_id, rp.tier, rp.passage, rp.realized_json,
                      rp.compliance_f1, rp.seed_doc_id, rp.seed_url, rp.seed_title,
                      rp.spent_usd, rp.status, rp.fail_notes, rp.created_at,
                      b.blueprint_json
               FROM rendered_passages rp
               JOIN blueprints b ON b.blueprint_id = rp.blueprint_id
               WHERE rp.blueprint_id = ?""", (blueprint_id,)).fetchone()
        return self._passage_row_to_dict(row) if row else None

    def load_resumable_passages(self, status: str = "questions_failed") -> list[dict]:
        rows = self.conn.execute(
            """SELECT rp.blueprint_id, rp.tier, rp.passage, rp.realized_json,
                      rp.compliance_f1, rp.seed_doc_id, rp.seed_url, rp.seed_title,
                      rp.spent_usd, rp.status, rp.fail_notes, rp.created_at,
                      b.blueprint_json
               FROM rendered_passages rp
               JOIN blueprints b ON b.blueprint_id = rp.blueprint_id
               WHERE rp.status = ?
               ORDER BY rp.created_at DESC""", (status,)).fetchall()
        return [self._passage_row_to_dict(r) for r in rows]

    @staticmethod
    def _passage_row_to_dict(row) -> dict:
        keys = ["blueprint_id", "tier", "passage", "realized_json", "compliance_f1",
                "seed_doc_id", "seed_url", "seed_title", "spent_usd", "status",
                "fail_notes", "created_at", "blueprint_json"]
        return dict(zip(keys, row))

    # ----------------------------------------------------------- fingerprints

    def record_fingerprint(self, fp: Fingerprint):
        self.conn.execute(
            """INSERT OR REPLACE INTO fingerprints
               (rc_id, blueprint_id, persona_id, movement_string, commitment_curve,
                rhythm_vector, topology_signature, trap_histogram, letter_sequence,
                stylometry, embedding, source, move_signature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp.rc_id, fp.blueprint_id, fp.persona_id, fp.movement_string,
             json.dumps(fp.commitment_curve), json.dumps(fp.rhythm_vector),
             json.dumps(fp.topology_signature), json.dumps(fp.trap_histogram),
             fp.letter_sequence, json.dumps(fp.stylometry),
             json.dumps(fp.embedding) if fp.embedding else None, fp.source,
             fp.move_signature, _now()))
        self.conn.commit()

    def fingerprint_window(self, limit: int,
                           include_quarantined: bool = False) -> list[Fingerprint]:
        """Novelty baseline. Quarantined rows are excluded by default: a corpus
        that holds many sets sharing one rhetorical grammar makes the gates
        defend a monoculture — new renders get scored against duplicates of the
        same thing. Quarantine keeps one representative and hides the rest from
        this window ONLY; the rows, the rc_sets and the exported files are
        untouched. Pass include_quarantined=True for audits and reporting."""
        excluded = tuple(config.NOVELTY_WINDOW_EXCLUDE_STATUSES)
        if include_quarantined:
            where, params = "", (limit,)
        elif excluded:
            # Also hide sets that are not going to ship (solver_dispute) or
            # were themselves rejected as duplicates — see the config note.
            marks = ",".join("?" * len(excluded))
            where = (" WHERE quarantined = 0 AND rc_id NOT IN "
                     f"(SELECT rc_id FROM rc_sets WHERE status IN ({marks}))")
            params = (*excluded, limit)
        else:
            where, params = " WHERE quarantined = 0", (limit,)
        rows = self.conn.execute(
            """SELECT rc_id, blueprint_id, persona_id, movement_string, commitment_curve,
                      rhythm_vector, topology_signature, trap_histogram, letter_sequence,
                      stylometry, embedding, source, move_signature
               FROM fingerprints""" + where +
            """ ORDER BY created_at DESC LIMIT ?""", params).fetchall()
        out = []
        for r in rows:
            out.append(Fingerprint(
                rc_id=r[0], blueprint_id=r[1] or "", persona_id=r[2] or "",
                movement_string=r[3], commitment_curve=json.loads(r[4]),
                rhythm_vector=json.loads(r[5]), topology_signature=json.loads(r[6]),
                trap_histogram=json.loads(r[7]), letter_sequence=r[8],
                stylometry=json.loads(r[9]),
                embedding=json.loads(r[10]) if r[10] else None,
                source=r[11] or "engine",
                move_signature=r[12] or ""))
        return out

    # -------------------------------------------------------------- rc & audit

    def record_novelty_audit(self, blueprint_id: str, rc_id: str | None,
                             channel_scores: dict, composite: float,
                             verdict: str, details: str = ""):
        self.conn.execute(
            """INSERT INTO novelty_audits
               (rc_id, blueprint_id, channel_scores, composite, verdict, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rc_id, blueprint_id, json.dumps(channel_scores), composite, verdict, details, _now()))
        self.conn.commit()

    # ------------------------------------------------------ parallel workers

    def reserve_inflight(self, worker_id: str, bp, seed=None) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO inflight
               (worker_id, family_id, movement_string, seed_doc_id, topic, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (worker_id, bp.family_id, _movement_of(bp),
             getattr(seed, "doc_id", None), bp.topic or "", _now()))
        self.conn.commit()

    def release_inflight(self, worker_id: str) -> None:
        self.conn.execute("DELETE FROM inflight WHERE worker_id = ?", (worker_id,))
        self.conn.commit()

    def clear_inflight(self) -> None:
        self.conn.execute("DELETE FROM inflight")
        self.conn.commit()

    def inflight_bans(self, exclude_worker: str = "") -> dict:
        """Families, movement strings and seeds other live workers hold."""
        cutoff = time.time() - 60 * config.INFLIGHT_STALE_MIN
        out = {"families": set(), "movements": set(), "seeds": set()}
        for wid, fam, mov, seed, created in self.conn.execute(
                "SELECT worker_id, family_id, movement_string, seed_doc_id, "
                "created_at FROM inflight"):
            if wid == exclude_worker:
                continue
            try:
                from datetime import datetime
                age_ok = datetime.fromisoformat(created).timestamp() >= cutoff
            except (ValueError, TypeError):
                age_ok = True
            if not age_ok:
                continue
            if fam:
                out["families"].add(fam)
            if mov:
                out["movements"].add(mov)
            if seed:
                out["seeds"].add(seed)
        return out

    def _ship_lock_path(self) -> str:
        key = hashlib.sha1(os.path.abspath(self._db_path).encode()).hexdigest()[:12]
        # local temp dir, never the synced project folder
        return os.path.join(tempfile.gettempdir(), f"rc_engine-{key}.ship.lock")

    @contextmanager
    def ship_lock(self, enabled: bool = True):
        """Exclusive section for 'final novelty recheck + insert'. A lock file
        created with O_EXCL is atomic on Windows and POSIX alike. A stale
        file (dead worker) is broken after SHIP_LOCK_STALE_S; after
        SHIP_LOCK_WAIT_S the caller ships unlocked with a warning rather than
        hang a paid batch on a lock nobody will release."""
        if not enabled:
            yield
            return
        path = self._ship_lock_path()
        deadline = time.time() + config.SHIP_LOCK_WAIT_S
        held = False
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                held = True
                break
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(path)
                except OSError:
                    continue            # vanished between the two calls
                if age > config.SHIP_LOCK_STALE_S:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    print("  [ship-lock] !! held for too long - shipping unlocked")
                    break
                time.sleep(0.2)
        try:
            yield
        finally:
            if held:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def window_composition(self, limit: int) -> dict:
        """What the novelty gates are actually scoring against: rc_sets status
        of every row in the live window, plus how many rows the status rule
        and quarantine are hiding. Rows with no rc_sets row are legacy/manual
        backfill that shipped before the engine kept a row for them."""
        live = [fp.rc_id for fp in self.fingerprint_window(limit)]
        status = dict(self.conn.execute(
            "SELECT rc_id, status FROM rc_sets").fetchall())
        mix: dict[str, int] = {}
        for rc_id in live:
            k = status.get(rc_id, "no_rc_row")
            mix[k] = mix.get(k, 0) + 1
        excluded = tuple(config.NOVELTY_WINDOW_EXCLUDE_STATUSES)
        hidden_by_status = 0
        if excluded:
            marks = ",".join("?" * len(excluded))
            hidden_by_status = self.conn.execute(
                f"""SELECT COUNT(*) FROM fingerprints
                    WHERE quarantined = 0 AND rc_id IN
                          (SELECT rc_id FROM rc_sets WHERE status IN ({marks}))""",
                excluded).fetchone()[0]
        quarantined = self.conn.execute(
            "SELECT COUNT(*) FROM fingerprints WHERE quarantined = 1").fetchone()[0]
        return {"live": len(live), "mix": mix,
                "hidden_by_status": hidden_by_status, "quarantined": quarantined}

    def record_attempt(self, batch_id: str, tier: str, slot: int,
                       attempt_no: int, res) -> None:
        reason = "; ".join(res.notes or [])[:400]
        self.conn.execute(
            """INSERT INTO attempts
               (batch_id, tier, slot, attempt_no, rc_id, blueprint_id, status,
                cost_usd, novelty_composite, compliance_f1, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (batch_id, tier, slot, attempt_no, res.rc_id, res.blueprint_id or None,
             res.status, float(res.cost_usd or 0.0), res.novelty_composite,
             res.compliance_f1, reason, _now()))
        self.conn.commit()

    def attempt_summary(self, last_batches: int = 5,
                        paid_floor_usd: float = 0.02) -> list[dict]:
        """Per-batch yield, newest first: attempts, shipped, rejections that
        had already paid for a render (cost >= paid_floor_usd) versus free
        precheck saves, and the dollars behind each. This is the number to
        watch when a gate or threshold changes."""
        shipped = ("approved", "needs_review", "solver_dispute")
        batches = [r[0] for r in self.conn.execute(
            """SELECT batch_id FROM attempts GROUP BY batch_id
               ORDER BY MIN(created_at) DESC LIMIT ?""", (last_batches,))]
        out = []
        for b in batches:
            rows = self.conn.execute(
                """SELECT status, cost_usd, rc_id, created_at FROM attempts
                   WHERE batch_id = ?""", (b,)).fetchall()
            n_ship = sum(1 for s, _, rc, _ in rows if rc and s in shipped)
            wasted = [(s, c) for s, c, rc, _ in rows if not (rc and s in shipped)]
            paid = [(s, c) for s, c in wasted if c >= paid_floor_usd]
            out.append({
                "batch_id": b, "started": min(r[3] for r in rows)[:16],
                "attempts": len(rows), "shipped": n_ship,
                "paid_rejects": len(paid), "free_rejects": len(wasted) - len(paid),
                "spend": round(sum(c for _, c, _, _ in rows), 4),
                "paid_waste": round(sum(c for _, c in paid), 4),
            })
        return out

    def generate_rc_id(self, tier: str) -> str:
        """Atomic, collision-free: claims the next sequence number for this
        tier in a single INSERT..ON CONFLICT statement, so concurrent callers
        (e.g. parallel workers) can never observe or claim the same number —
        unlike the old COUNT(*)-based approach it replaces. The sequence is a
        running total per tier across all time, not reset daily; a gap (e.g.
        seq 41 never shipping because its RC hit budget_abort) is expected and
        harmless — uniqueness is the guarantee, not contiguity.

        Format: RC-{TIER}-{YYMMDD}-{seq:04d}, e.g. RC-ELITE-260706-0142."""
        date_str = datetime.now(timezone.utc).strftime("%y%m%d")
        self.conn.execute(
            "INSERT INTO id_counters (tier, next_seq) VALUES (?, 1) "
            "ON CONFLICT(tier) DO UPDATE SET next_seq = next_seq + 1",
            (tier,))
        seq = self.conn.execute(
            "SELECT next_seq FROM id_counters WHERE tier = ?", (tier,)).fetchone()[0]
        self.conn.commit()
        return f"RC-{tier.upper()}-{date_str}-{seq:04d}"

    def insert_rc_set(self, rc_id: str, tier: str, rc_text: str, status: str,
                      judge: dict, solver: dict | None, avg: float,
                      blueprint_id: str, compliance_f1: float, novelty_composite: float,
                      total_cost: float, essay_doc_id: str | None, essay_url: str | None,
                      domain: str | None, embedding: list | None, attempts: int):
        self.conn.execute(
            """INSERT INTO rc_sets
               (rc_id, tier, rc_text, judge_json, average_score, status,
                essay_doc_id, essay_url, gen_input_tokens, gen_output_tokens,
                judge_input_tokens, judge_output_tokens, gen_cost_usd, judge_cost_usd,
                total_cost_usd, attempts, created_at, solver_json, domain,
                passage_embedding, blueprint_id, compliance_f1, novelty_composite,
                engine_version, provider)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rc_id, tier, rc_text, json.dumps(judge, ensure_ascii=False), avg, status,
             essay_doc_id, essay_url, total_cost, attempts, _now(),
             json.dumps(solver, ensure_ascii=False) if solver else None, domain,
             json.dumps(embedding) if embedding else None,
             blueprint_id, compliance_f1, novelty_composite, config.ENGINE_VERSION,
             config.ACTIVE_PROVIDER))
        self.conn.commit()

    def letter_sequences_trailing(self, limit: int = 20) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT letter_sequence FROM fingerprints ORDER BY created_at DESC LIMIT ?",
            (limit,))]

    def record_health(self, window: int, family_kl: float, topology_kl: float,
                      slot_flags: list, letter_runs_p: float):
        self.conn.execute(
            """INSERT INTO corpus_health
               (window_size, family_kl, topology_kl, slot_chi2_flags, probe_accuracy,
                letter_runs_p, created_at)
               VALUES (?, ?, ?, ?, NULL, ?, ?)""",
            (window, family_kl, topology_kl, json.dumps(slot_flags), letter_runs_p, _now()))
        self.conn.commit()
