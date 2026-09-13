"""SQLite persistence: blueprints, component usage, fingerprints, novelty
audits, corpus health — plus a legacy-compatible rc_sets table so the
existing export tooling keeps working on the same database file."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config
from .generation_policy import known_argument_schema_ids
from .models import Blueprint, Fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _movement_of(bp) -> str:
    """Blueprint.movement_string is a method; test doubles use an attribute."""
    mv = getattr(bp, "movement_string", "")
    return (mv() if callable(mv) else mv) or ""


class UnknownClientError(ValueError):
    """--client named a client the DB has never heard of."""


# Tables whose rows belong to exactly one client (2026-09-12). component_usage
# and novelty_audits are not listed: they hang off a blueprint or rc_id and
# take the client through that join.
CLIENT_SCOPED_TABLES = ("rc_sets", "blueprints", "fingerprints", "rendered_passages",
                        "attempts", "inflight", "corpus_health")

# A slug becomes a folder name under exported_rc_sets/, so it has to be a safe
# one on Windows too.
_CLIENT_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}


class HistoryStore:
    def __init__(self, db_path: str = config.DB_PATH, client_id: str | None = None):
        self._db_path = db_path
        self.conn = sqlite3.connect(db_path)
        # Wait on a locked DB instead of failing at once: the GUI opens it
        # read-only, backups use the online-backup API, and a second generate
        # process must queue behind the writer rather than die mid-ship.
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._init_tables()
        # Every corpus read below is scoped to this client; the few that are
        # deliberately global (combo hashes, rc ids, the ship lock) say so.
        #
        # An unknown client is an error, never an empty corpus. An empty
        # window auto-passes novelty at composite 1.0 (novelty.py), so a typo
        # in --client would otherwise ship sets checked against nothing.
        self.client_id = client_id or config.DEFAULT_CLIENT_ID
        if not self.client_exists(self.client_id):
            known = ", ".join(c["client_id"] for c in self.list_clients())
            self.conn.close()
            raise UnknownClientError(
                f"unknown client '{self.client_id}' (known: {known}). "
                f"Add it with: python -m rc_engine.cli client add {self.client_id}")

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
        # The similarity screen is a paid stage whose spend used to be printed
        # and then dropped, so every $/shipped-set figure was low.
        self._ensure_column("rc_sets", "screen_cost_usd", "REAL DEFAULT 0")
        self._ensure_column("rc_sets", "similarity_verdict", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "similarity_note", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "voice_review_status", "TEXT DEFAULT ''")
        self._ensure_column("rc_sets", "voice_review_json", "TEXT DEFAULT '[]'")
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
                components TEXT,
                created_at TEXT NOT NULL
            )""")
        # existing DBs predate `components`
        self._ensure_column("inflight", "components", "TEXT")

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

        # ---- clients (2026-09-12) --------------------------------------------
        # Until this date the DB held one client's work and every novelty lever
        # read all of it. A second client needs a fresh window, but the playbook
        # sells structural exclusivity, so a few things stay global — see the
        # "global" notes on shipped_combo_hashes, generate_rc_id and ship_lock.
        #
        # The ADD COLUMN default is what migrates an existing DB: SQLite fills
        # every existing row with it in one statement, so all pre-2026-09-12
        # work belongs to the founding client with no UPDATE pass. The default
        # is FOUNDING_CLIENT_ID and must never change — it is a migration
        # constant, not a preference. Writers always pass client_id explicitly.
        c.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                display_name TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )""")
        c.execute("INSERT OR IGNORE INTO clients (client_id, display_name, active, created_at) "
                  "VALUES (?, ?, 1, ?)",
                  (config.FOUNDING_CLIENT_ID, "Founding client", _now()))
        for table in CLIENT_SCOPED_TABLES:
            self._ensure_column(table, "client_id",
                                f"TEXT NOT NULL DEFAULT '{config.FOUNDING_CLIENT_ID}'")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bp_client "
                  "ON blueprints(client_id, status, created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fp_client "
                  "ON fingerprints(client_id, created_at)")
        # Structural exclusivity as an actual constraint: one shipped blueprint
        # per combo hash, across every client. Checked 2026-09-12 against the
        # production DB before adding it: 116 shipped, 0 duplicate hashes.
        # A DB that already holds duplicates (an old dry-run DB, say) keeps
        # working without the index; `health --all` reports the duplicates.
        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_shipped_combo "
                      "ON blueprints(combo_hash) WHERE status = 'shipped'")
        except sqlite3.IntegrityError:
            print("[history] WARNING: shipped combo hashes are not unique in this DB; "
                  "the exclusivity index was not created (see `health --all`)")
        c.commit()

    def _ensure_column(self, table: str, column: str, decl: str):
        cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # --------------------------------------------------------------- clients

    def _scope(self, scope: str, col: str = "client_id") -> tuple[str, tuple]:
        """SQL predicate for 'client' (this client), 'others' (every other
        client: the global house-voice pressure) or 'all' (audits)."""
        if scope == "client":
            return f"{col} = ?", (self.client_id,)
        if scope == "others":
            return f"{col} != ?", (self.client_id,)
        if scope == "all":
            return "1 = 1", ()
        raise ValueError(f"unknown scope {scope!r}")

    def client_exists(self, client_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM clients WHERE client_id = ?",
                                 (client_id,)).fetchone() is not None

    def add_client(self, client_id: str, display_name: str = "") -> None:
        """Register a client. Slugs are case-insensitively unique because they
        become folder names, and Windows folders ignore case."""
        if not _CLIENT_SLUG.match(client_id or "") \
                or client_id.lower() in _WINDOWS_RESERVED:
            raise ValueError(f"'{client_id}' is not a valid client slug "
                             "(letters, digits, - and _, max 32, not a Windows device name)")
        clash = self.conn.execute(
            "SELECT client_id FROM clients WHERE lower(client_id) = lower(?)",
            (client_id,)).fetchone()
        if clash:
            raise ValueError(f"client '{clash[0]}' already exists")
        self.conn.execute(
            "INSERT INTO clients (client_id, display_name, active, created_at) "
            "VALUES (?, ?, 1, ?)", (client_id, display_name or client_id, _now()))
        self.conn.commit()

    def list_clients(self) -> list[dict]:
        """Every client with its shipped/total set counts and last activity."""
        shipping = tuple(config.SHIPPING_STATUSES)
        marks = ",".join("?" * len(shipping))
        rows = self.conn.execute(
            f"""SELECT c.client_id, c.display_name, c.active, c.created_at,
                       COUNT(r.rc_id),
                       COALESCE(SUM(CASE WHEN r.status IN ({marks}) THEN 1 ELSE 0 END), 0),
                       MAX(r.created_at)
                FROM clients c LEFT JOIN rc_sets r ON r.client_id = c.client_id
                GROUP BY c.client_id ORDER BY c.created_at""", shipping).fetchall()
        keys = ["client_id", "display_name", "active", "created_at",
                "sets", "shipped", "last_set_at"]
        return [dict(zip(keys, r)) for r in rows]

    def exclusivity_audit(self) -> dict:
        """What `health --all` certifies: no argument skeleton and no seed essay
        shipped to more than one client. Both lists must be empty."""
        shipping = tuple(config.SHIPPING_STATUSES)
        marks = ",".join("?" * len(shipping))
        combos = self.conn.execute(
            """SELECT combo_hash, GROUP_CONCAT(DISTINCT client_id)
               FROM blueprints WHERE status = 'shipped'
               GROUP BY combo_hash HAVING COUNT(DISTINCT client_id) > 1""").fetchall()
        seeds = self.conn.execute(
            f"""SELECT essay_doc_id, GROUP_CONCAT(DISTINCT client_id)
                FROM rc_sets
                WHERE status IN ({marks}) AND essay_doc_id IS NOT NULL AND essay_doc_id != ''
                GROUP BY essay_doc_id HAVING COUNT(DISTINCT client_id) > 1""",
            shipping).fetchall()
        dup_combo = self.conn.execute(
            """SELECT COUNT(*) FROM (SELECT combo_hash FROM blueprints
               WHERE status = 'shipped' GROUP BY combo_hash HAVING COUNT(*) > 1)""").fetchone()[0]
        index = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ux_shipped_combo'"
        ).fetchone() is not None
        return {"shared_combo_hashes": combos, "shared_seeds": seeds,
                "duplicate_shipped_combo_hashes": dup_combo, "unique_index": index}

    # ------------------------------------------------------------ blueprints

    def record_blueprint(self, bp: Blueprint, status: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO blueprints
               (blueprint_id, rc_id, tier, family_id, persona_id, ending_id, rhythm_id,
                revelation_id, distractor_profile_id, topology_id, instability, aperture,
                combo_hash, pair_hashes, blueprint_json, status, created_at, client_id)
               VALUES (?,
                       (SELECT rc_id FROM blueprints WHERE blueprint_id = ?),
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bp.blueprint_id, bp.blueprint_id, bp.tier, bp.family_id, bp.persona_id,
             bp.ending_id, bp.rhythm_id, bp.revelation_id, bp.distractor_profile_id,
             bp.topology_id, bp.instability, bp.aperture, bp.combo_hash,
             json.dumps(bp.pair_hashes), bp.to_json(), status, _now(), self.client_id))
        self.conn.commit()

    def update_blueprint_json(self, bp: Blueprint):
        """Rewrite a stored plan's JSON in place (2026-09-13), leaving status,
        created_at and rc_id alone. Used to persist resolved question slots,
        which are not a component and do not move combo_hash. Scoped to this
        client, like load_rendered_passage."""
        self.conn.execute(
            "UPDATE blueprints SET blueprint_json = ? WHERE blueprint_id = ? AND client_id = ?",
            (bp.to_json(), bp.blueprint_id, self.client_id))
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
        used = dict(bp.component_ids)
        # topic_shape and argument_schema are Blueprint fields but NOT members
        # of component_ids, because that property feeds combo_hash. They still
        # need usage rows or their recency machinery is dead.
        #
        # It WAS dead for topic_shape, from the day it was added until
        # 2026-09-05: nothing ever inserted a topic_shape row, so
        # usage_counts_trailing("topic_shape", 30) returned {} on every call,
        # every decay weight was 0.5**0 = 1.0, and the "inverse-frequency" draw
        # in classify_and_pick_shape was a uniform random pick. A 20k-draw
        # simulation that day put TS06+TS12 at 14.82% against a 14.3% uniform
        # expectation — the signature of no damping at all.
        if bp.topic_shape_id:
            used["topic_shape"] = bp.topic_shape_id
        if bp.argument_schema_id:
            used["argument_schema"] = bp.argument_schema_id
        for ctype, cid in used.items():
            self.conn.execute(
                """INSERT INTO component_usage (component_type, component_id, blueprint_id, shipped, used_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (ctype, cid, bp.blueprint_id, _now()))
        self.conn.commit()

    def recent_shipped_blueprints(self, limit: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT family_id, persona_id, ending_id, rhythm_id, revelation_id,
                      distractor_profile_id, topology_id, combo_hash, pair_hashes
               FROM blueprints WHERE status = 'shipped' AND client_id = ?
               ORDER BY created_at DESC LIMIT ?""", (self.client_id, limit)).fetchall()
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
                WHERE status IN ({placeholders}) AND client_id = ?
                ORDER BY created_at DESC LIMIT ?""",
            (*statuses, self.client_id, limit * 3)).fetchall()
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
               WHERE cu.component_type = ? AND b.status = 'shipped' AND b.client_id = ?
               ORDER BY b.created_at DESC""", (ctype, self.client_id)).fetchall()
        shipped_times = [r[0] for r in self.conn.execute(
            "SELECT created_at FROM blueprints WHERE status = 'shipped' AND client_id = ? "
            "ORDER BY created_at DESC", (self.client_id,))]
        pos_of_time = {t: i for i, t in enumerate(shipped_times)}
        out: dict[str, int] = {}
        for cid, t in rows:
            if cid not in out:
                out[cid] = pos_of_time.get(t, len(shipped_times))
        return out

    def usage_counts_trailing(self, ctype: str, window: int = 100,
                              scope: str = "client") -> dict[str, int]:
        where, params = self._scope(scope, "client_id")
        rows = self.conn.execute(
            f"""SELECT cu.component_id, COUNT(*)
                FROM component_usage cu JOIN blueprints b ON b.blueprint_id = cu.blueprint_id
                WHERE cu.component_type = ? AND b.status = 'shipped'
                  AND b.blueprint_id IN (
                      SELECT blueprint_id FROM blueprints
                      WHERE status = 'shipped' AND {where}
                      ORDER BY created_at DESC LIMIT ?)
                GROUP BY cu.component_id""", (ctype, *params, window)).fetchall()
        return dict(rows)

    def usage_counts_other_clients(self, ctype: str, window: int) -> dict[str, int]:
        """Trailing usage across every OTHER client's shipped sets, pooled. The
        global house-voice pressure in composer.py; empty while one client
        exists, which is what keeps that layer an exact no-op for it."""
        return self.usage_counts_trailing(ctype, window, scope="others")

    def shipped_combo_hashes(self) -> set[str]:
        """GLOBAL on purpose: an argument skeleton shipped to any client is
        taken for every client. This is the structural exclusivity the
        playbook sells; ux_shipped_combo enforces the same rule in SQL."""
        return {r[0] for r in self.conn.execute(
            "SELECT combo_hash FROM blueprints WHERE status = 'shipped'")}

    def combo_hash_taken(self, combo_hash: str, blueprint_id: str) -> bool:
        """Has another blueprint (any client) already shipped this skeleton?
        Checked again at ship time, because a concurrent batch for another
        client can ship it after this blueprint was composed."""
        return self.conn.execute(
            "SELECT 1 FROM blueprints WHERE status = 'shipped' AND combo_hash = ? "
            "AND blueprint_id != ?", (combo_hash, blueprint_id)).fetchone() is not None

    def seed_shipped_to_other_client(self, essay_doc_id: str | None) -> bool:
        """Seed essays are exclusive across clients. The RAG `used` flag already
        stops a second draw, but two clients' batches running at the same time
        can hold the same unused essay. Same-client reuse is left to the
        existing seed gates, so the founding client's behaviour is unchanged."""
        if not essay_doc_id:
            return False
        shipping = tuple(config.SHIPPING_STATUSES)
        marks = ",".join("?" * len(shipping))
        return self.conn.execute(
            f"SELECT 1 FROM rc_sets WHERE essay_doc_id = ? AND client_id != ? "
            f"AND status IN ({marks})",
            (essay_doc_id, self.client_id, *shipping)).fetchone() is not None

    def shipped_blueprint_rows(self, limit: int) -> list[tuple]:
        """(blueprint_id, rc_id, family_id, blueprint_json) of this client's
        most recent shipped blueprints — topic precheck and `avoid`."""
        return self.conn.execute(
            """SELECT blueprint_id, rc_id, family_id, blueprint_json FROM blueprints
               WHERE status = 'shipped' AND client_id = ?
               ORDER BY created_at DESC LIMIT ?""", (self.client_id, limit)).fetchall()

    def shipped_blueprint_components(self, limit: int) -> list[tuple]:
        """(rc_id, family, persona, ending, rhythm, revelation, distractor_profile,
        topology) for this client's recent shipped RCs — blueprint similarity."""
        return self.conn.execute(
            """SELECT rc_id, family_id, persona_id, ending_id, rhythm_id, revelation_id,
                      distractor_profile_id, topology_id
               FROM blueprints WHERE status = 'shipped' AND rc_id IS NOT NULL
                 AND client_id = ?
               ORDER BY created_at DESC LIMIT ?""", (self.client_id, limit)).fetchall()

    def recent_seed_ids(self, limit: int) -> list[tuple[str, str]]:
        """(rc_id, essay_doc_id) of this client's most recent seeded sets."""
        return self.conn.execute(
            """SELECT rc_id, essay_doc_id FROM rc_sets
               WHERE essay_doc_id IS NOT NULL AND essay_doc_id != '' AND client_id = ?
               ORDER BY created_at DESC LIMIT ?""", (self.client_id, limit)).fetchall()

    def recent_seed_genres(self, limit: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            """SELECT seed_genre FROM rc_sets
               WHERE seed_genre IS NOT NULL AND seed_genre != '' AND client_id = ?
               ORDER BY created_at DESC LIMIT ?""", (self.client_id, limit))]

    def recent_rc_texts(self):
        """(rc_id, rc_text) for this client, newest first — the similarity screen."""
        return self.conn.execute(
            """SELECT rc_id, rc_text FROM rc_sets
               WHERE rc_text IS NOT NULL AND client_id = ?
               ORDER BY created_at DESC""", (self.client_id,))

    def argument_schema_counts(self, window: int, scope: str = "client") -> dict[str, int]:
        """Realized primary schemas of recent ships, scoped explicitly.

        Plans are not evidence of what readers received. Missing/invalid reads
        occupy a window position but never get replaced with the planned label.
        """
        predicate, params = self._scope(scope, "b.client_id")
        rows = self.conn.execute(
            f"""SELECT rp.realized_json FROM blueprints b
                LEFT JOIN rendered_passages rp ON rp.blueprint_id = b.blueprint_id
                    AND rp.client_id = b.client_id
                WHERE b.status = 'shipped' AND {predicate}
                ORDER BY b.created_at DESC, b.rowid DESC LIMIT ?""",
            (*params, window))
        counts: dict[str, int] = {}
        for (raw,) in rows:
            try:
                schema = json.loads(raw or "{}").get("argument_schema")
            except (ValueError, AttributeError):
                continue
            # Any registered policy's schema counts (2026-09-13): a policy
            # schema occupies window positions like a legacy one.
            if isinstance(schema, str) and schema in known_argument_schema_ids():
                counts[schema] = counts.get(schema, 0) + 1
        return counts

    def voice_health(self, window: int) -> dict[str, dict]:
        """Plan obedience for this client's recent ships, split by plan version.

        Unknown measurements have separate denominators; legacy plans do not
        get attributed to the new planner. These are model reads, not gold labels.
        """
        rows = self.conn.execute(
            """SELECT b.blueprint_json, rp.realized_json, r.voice_review_status
               FROM blueprints b
               LEFT JOIN rendered_passages rp ON rp.blueprint_id = b.blueprint_id
                   AND rp.client_id = b.client_id
               LEFT JOIN rc_sets r ON r.rc_id = b.rc_id AND r.client_id = b.client_id
               WHERE b.client_id = ? AND b.status = 'shipped'
               ORDER BY b.created_at DESC, b.rowid DESC LIMIT ?""",
            (self.client_id, window))
        cohorts = {}
        for bp_raw, read_raw, voice_status in rows:
            try:
                bp, read = json.loads(bp_raw or '{}'), json.loads(read_raw or '{}')
                if not isinstance(bp, dict) or not isinstance(read, dict):
                    continue
            except ValueError:
                continue
            version = bp.get('voice_plan_version') or 'legacy'
            c = cohorts.setdefault(version, dict(ships=0, schema_planned=0,
                schema_measured=0, primary_matches=0, either_matches=0,
                moves_planned=0, moves_measured=0, opening_matches=0,
                closing_matches=0, middle_matches=0, voice_observed=0, voice_flagged=0))
            c['ships'] += 1
            c['voice_observed'] += voice_status in ('review', 'clear')
            c['voice_flagged'] += voice_status == 'review'
            planned = bp.get('argument_schema_id')
            if planned:
                c['schema_planned'] += 1
                measured = read.get('argument_schema')
                if isinstance(measured, str) and measured in known_argument_schema_ids():
                    c['schema_measured'] += 1
                    c['primary_matches'] += measured == planned
                    c['either_matches'] += planned in (measured, read.get('argument_schema_secondary'))
            if bp.get('move_plan'):
                c['moves_planned'] += 1
                if read.get('rhetorical_moves'):
                    c['moves_measured'] += 1
                    for name, key in [('opening_matches', 'opening_beat_ok'),
                                      ('closing_matches', 'closing_beat_ok'),
                                      ('middle_matches', 'middle_beats_ok')]:
                        c[name] += read.get(key) is True
        return cohorts

    def voice_reference_pool(self) -> list[dict]:
        """All shipped texts for this client, with blind structural labels.

        Retrieval scans the corpus locally; only a bounded shortlist is sent
        to the reader screen. Include review/dispute rows because they can be
        batch siblings requiring a human decision, not just approved examples.
        """
        statuses = tuple(config.SHIPPING_STATUSES)
        marks = ','.join('?' for _ in statuses)
        rows = self.conn.execute(
            f"""SELECT r.rc_id, r.rc_text, rp.realized_json
                FROM rc_sets r LEFT JOIN rendered_passages rp
                  ON rp.blueprint_id = r.blueprint_id AND rp.client_id = r.client_id
                WHERE r.client_id = ? AND r.status IN ({marks})
                  AND r.rc_text IS NOT NULL
                ORDER BY r.created_at DESC, r.rowid DESC""",
            (self.client_id, *statuses))
        out = []
        for rc_id, rc_text, raw in rows:
            try:
                realized = json.loads(raw or '{}')
                if not isinstance(realized, dict):
                    realized = {}
            except ValueError:
                realized = {}
            out.append({'rc_id': rc_id, 'rc_text': rc_text,
                        'moves': realized.get('rhetorical_moves') or [],
                        'schema': realized.get('argument_schema') or ''})
        return out

    def record_voice_review(self, rc_id: str, reasons: list[str]):
        """Observe voice deviations without changing this client's ship status.

        2026-09-13: the user's replay flagged 30/30 historical ships. Until a
        real pilot calibrates these signals, they are telemetry, not a gate.
        Existing compliance, novelty and question-quality checks still apply.
        """
        self.conn.execute(
            """UPDATE rc_sets SET voice_review_status = ?, voice_review_json = ?
               WHERE rc_id = ? AND client_id = ?""",
            ("review" if reasons else "clear", json.dumps(reasons, ensure_ascii=False),
             rc_id, self.client_id))
        self.conn.commit()

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
                created_at, client_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (blueprint_id, tier, passage, realized_json, compliance_f1,
             seed_doc_id, seed_url, seed_title, spent_usd, status, _now(),
             self.client_id))
        self.conn.commit()

    def set_passage_status(self, blueprint_id: str, status: str,
                           fail_notes: str | None = None):
        self.conn.execute(
            "UPDATE rendered_passages SET status = ?, fail_notes = ? WHERE blueprint_id = ?",
            (status, fail_notes, blueprint_id))
        self.conn.commit()

    def load_rendered_passage(self, blueprint_id: str) -> dict | None:
        # Scoped: resuming another client's passage under this client would
        # ship it into the wrong corpus and the wrong export folder.
        row = self.conn.execute(
            """SELECT rp.blueprint_id, rp.tier, rp.passage, rp.realized_json,
                      rp.compliance_f1, rp.seed_doc_id, rp.seed_url, rp.seed_title,
                      rp.spent_usd, rp.status, rp.fail_notes, rp.created_at,
                      b.blueprint_json
               FROM rendered_passages rp
               JOIN blueprints b ON b.blueprint_id = rp.blueprint_id
               WHERE rp.blueprint_id = ? AND rp.client_id = ?""",
            (blueprint_id, self.client_id)).fetchone()
        return self._passage_row_to_dict(row) if row else None

    def load_resumable_passages(self, status: str = "questions_failed") -> list[dict]:
        rows = self.conn.execute(
            """SELECT rp.blueprint_id, rp.tier, rp.passage, rp.realized_json,
                      rp.compliance_f1, rp.seed_doc_id, rp.seed_url, rp.seed_title,
                      rp.spent_usd, rp.status, rp.fail_notes, rp.created_at,
                      b.blueprint_json
               FROM rendered_passages rp
               JOIN blueprints b ON b.blueprint_id = rp.blueprint_id
               WHERE rp.status = ? AND rp.client_id = ?
               ORDER BY rp.created_at DESC""", (status, self.client_id)).fetchall()
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
                stylometry, embedding, source, move_signature, created_at, client_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp.rc_id, fp.blueprint_id, fp.persona_id, fp.movement_string,
             json.dumps(fp.commitment_curve), json.dumps(fp.rhythm_vector),
             json.dumps(fp.topology_signature), json.dumps(fp.trap_histogram),
             fp.letter_sequence, json.dumps(fp.stylometry),
             json.dumps(fp.embedding) if fp.embedding else None, fp.source,
             fp.move_signature, _now(), self.client_id))
        self.conn.commit()

    def fingerprint_window(self, limit: int,
                           include_quarantined: bool = False,
                           scope: str = "client") -> list[Fingerprint]:
        """Novelty baseline. Quarantined rows are excluded by default: a corpus
        that holds many sets sharing one rhetorical grammar makes the gates
        defend a monoculture — new renders get scored against duplicates of the
        same thing. Quarantine keeps one representative and hides the rest from
        this window ONLY; the rows, the rc_sets and the exported files are
        untouched. Pass include_quarantined=True for audits and reporting.

        Scoped to this client (2026-09-12): a new client's window starts empty,
        exactly as the founding client's did in July. scope='others' is the
        pooled window of every other client, for the global house-voice term."""
        excluded = tuple(config.NOVELTY_WINDOW_EXCLUDE_STATUSES)
        scope_sql, scope_params = self._scope(scope)
        clauses, params = [scope_sql], list(scope_params)
        if not include_quarantined:
            clauses.append("quarantined = 0")
            if excluded:
                # Also hide sets that are not going to ship (solver_dispute) or
                # were themselves rejected as duplicates — see the config note.
                marks = ",".join("?" * len(excluded))
                clauses.append("rc_id NOT IN "
                               f"(SELECT rc_id FROM rc_sets WHERE status IN ({marks}))")
                params.extend(excluded)
        rows = self.conn.execute(
            """SELECT rc_id, blueprint_id, persona_id, movement_string, commitment_curve,
                      rhythm_vector, topology_signature, trap_histogram, letter_sequence,
                      stylometry, embedding, source, move_signature
               FROM fingerprints WHERE """ + " AND ".join(clauses) +
            """ ORDER BY created_at DESC LIMIT ?""", (*params, limit)).fetchall()
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

    def fingerprint_window_other_clients(self, limit: int) -> list[Fingerprint]:
        return self.fingerprint_window(limit, scope="others")

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
        """Register everything a live worker holds, so siblings avoid it.

        `components` carries the WHOLE component set, not just the family:
        every one of the nine ctypes in config.EXCLUSION_WINDOWS is a recency
        constraint a sequential run enforces for free, and a parallel run
        cannot see until the sibling ships. Measured 2026-09-05: two workers
        both drew topology QT08 (window 12, so sequentially impossible), and
        because topology is only novelty-checked with the question channels —
        after questions — the collision stayed invisible until $0.18 of
        questions, solver and judge had been bought. The reservation covered
        family, movement and seed but not topology.
        """
        import json as _json
        try:
            comps = _json.dumps(bp.component_ids)
        except Exception:                                    # noqa: BLE001
            comps = "{}"
        self.conn.execute(
            """INSERT OR REPLACE INTO inflight
               (worker_id, family_id, movement_string, seed_doc_id, topic,
                components, created_at, client_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (worker_id, bp.family_id, _movement_of(bp),
             getattr(seed, "doc_id", None), bp.topic or "", comps, _now(),
             self.client_id))
        self.conn.commit()

    def inflight_components(self, exclude_worker: str = "") -> dict:
        """{ctype: {component_id, ...}} held by other live workers of this
        client right now. Recency is a per-client lever, so another client's
        batch running alongside is not a sibling."""
        import json as _json
        from datetime import datetime
        cutoff = time.time() - 60 * config.INFLIGHT_STALE_MIN
        out: dict[str, set] = {}
        try:
            rows = self.conn.execute(
                "SELECT worker_id, components, created_at FROM inflight "
                "WHERE client_id = ?", (self.client_id,)).fetchall()
        except Exception:                                    # noqa: BLE001
            return out
        for wid, comps, created in rows:
            if wid == exclude_worker or not comps:
                continue
            try:
                if datetime.fromisoformat(created).timestamp() < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
            try:
                for ctype, cid in (_json.loads(comps) or {}).items():
                    if cid:
                        out.setdefault(ctype, set()).add(cid)
            except Exception:                                # noqa: BLE001
                continue
        return out

    def release_inflight(self, worker_id: str) -> None:
        self.conn.execute("DELETE FROM inflight WHERE worker_id = ?", (worker_id,))
        self.conn.commit()

    def clear_inflight(self) -> None:
        # Scoped: an unscoped DELETE would wipe the live reservations of another
        # client's batch running at the same time.
        self.conn.execute("DELETE FROM inflight WHERE client_id = ?", (self.client_id,))
        self.conn.commit()

    def inflight_bans(self, exclude_worker: str = "") -> dict:
        """Families, movement strings and seeds other live workers of this
        client hold."""
        cutoff = time.time() - 60 * config.INFLIGHT_STALE_MIN
        out = {"families": set(), "movements": set(), "seeds": set()}
        for wid, fam, mov, seed, created in self.conn.execute(
                "SELECT worker_id, family_id, movement_string, seed_doc_id, "
                "created_at FROM inflight WHERE client_id = ?", (self.client_id,)):
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
        # GLOBAL on purpose: keyed on the DB, not the client, so the ship-time
        # exclusivity check (combo hash, seed) is atomic across every client's
        # concurrent batches.
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
                    WHERE quarantined = 0 AND client_id = ? AND rc_id IN
                          (SELECT rc_id FROM rc_sets WHERE status IN ({marks}))""",
                (self.client_id, *excluded)).fetchone()[0]
        quarantined = self.conn.execute(
            "SELECT COUNT(*) FROM fingerprints WHERE quarantined = 1 AND client_id = ?",
            (self.client_id,)).fetchone()[0]
        return {"live": len(live), "mix": mix,
                "hidden_by_status": hidden_by_status, "quarantined": quarantined}

    def record_attempt(self, batch_id: str, tier: str, slot: int,
                       attempt_no: int, res) -> None:
        reason = "; ".join(res.notes or [])[:400]
        self.conn.execute(
            """INSERT INTO attempts
               (batch_id, tier, slot, attempt_no, rc_id, blueprint_id, status,
                cost_usd, novelty_composite, compliance_f1, reason, created_at,
                client_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (batch_id, tier, slot, attempt_no, res.rc_id, res.blueprint_id or None,
             res.status, float(res.cost_usd or 0.0), res.novelty_composite,
             res.compliance_f1, reason, _now(), self.client_id))
        self.conn.commit()

    def attempt_summary(self, last_batches: int = 5,
                        paid_floor_usd: float = 0.02) -> list[dict]:
        """Per-batch yield, newest first: attempts, shipped, rejections that
        had already paid for a render (cost >= paid_floor_usd) versus free
        precheck saves, and the dollars behind each. This is the number to
        watch when a gate or threshold changes."""
        shipped = ("approved", "needs_review", "solver_dispute")
        batches = [r[0] for r in self.conn.execute(
            """SELECT batch_id FROM attempts WHERE client_id = ? GROUP BY batch_id
               ORDER BY MIN(created_at) DESC LIMIT ?""", (self.client_id, last_batches))]
        out = []
        for b in batches:
            rows = self.conn.execute(
                """SELECT status, cost_usd, rc_id, created_at FROM attempts
                   WHERE batch_id = ? AND client_id = ?""", (b, self.client_id)).fetchall()
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

        Format: RC-{TIER}-{YYMMDD}-{seq:04d}, e.g. RC-ELITE-260706-0142.

        GLOBAL on purpose (2026-09-12): one sequence for every client, so an
        rc_id names one set in the whole DB and export filenames never collide
        between clients."""
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
                engine_version, provider, client_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rc_id, tier, rc_text, json.dumps(judge, ensure_ascii=False), avg, status,
             essay_doc_id, essay_url, total_cost, attempts, _now(),
             json.dumps(solver, ensure_ascii=False) if solver else None, domain,
             json.dumps(embedding) if embedding else None,
             blueprint_id, compliance_f1, novelty_composite, config.ENGINE_VERSION,
             config.ACTIVE_PROVIDER, self.client_id))
        self.conn.commit()

    def letter_sequences_trailing(self, limit: int = 20) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT letter_sequence FROM fingerprints WHERE client_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (self.client_id, limit))]

    def record_health(self, window: int, family_kl: float, topology_kl: float,
                      slot_flags: list, letter_runs_p: float):
        self.conn.execute(
            """INSERT INTO corpus_health
               (window_size, family_kl, topology_kl, slot_chi2_flags, probe_accuracy,
                letter_runs_p, created_at, client_id)
               VALUES (?, ?, ?, ?, NULL, ?, ?, ?)""",
            (window, family_kl, topology_kl, json.dumps(slot_flags), letter_runs_p, _now(),
             self.client_id))
        self.conn.commit()
