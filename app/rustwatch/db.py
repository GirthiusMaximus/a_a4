"""SQLite. One file, one schema, no migration tool.

`finding.dedupe_key` is unique on purpose: a re-scan must not re-open a flag a person already
cleared, which is the failure mode that turns a review queue into noise nobody trusts.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS rotation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  digest TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT,
  item_count INTEGER DEFAULT 0,
  source TEXT
);
CREATE TABLE IF NOT EXISTS skin (
  id TEXT PRIMARY KEY,
  name TEXT,
  item_shortname TEXT,
  store_tags TEXT,
  tradable INTEGER,
  icon_url TEXT,
  price_cents INTEGER,
  price_source TEXT,
  price_seen_at TEXT,
  first_seen_rotation INTEGER REFERENCES rotation(id),
  last_seen_rotation INTEGER REFERENCES rotation(id),
  files_status TEXT DEFAULT 'pending',
  files_path TEXT,
  scan_status TEXT DEFAULT 'unscanned',
  analyzed_at TEXT,
  group_count INTEGER DEFAULT 0,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS texture (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skin_id TEXT NOT NULL REFERENCES skin(id) ON DELETE CASCADE,
  group_index INTEGER,
  slot TEXT,
  path TEXT,
  width INTEGER, height INTEGER, mode TEXT,
  md5 TEXT, dhash TEXT,
  seam_ratio REAL, blank INTEGER DEFAULT 0, cut_fraction REAL DEFAULT 0,
  unique_colors INTEGER, is_power_of_two INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS finding (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skin_id TEXT NOT NULL REFERENCES skin(id) ON DELETE CASCADE,
  code TEXT, severity TEXT, title TEXT, detail TEXT,
  texture_path TEXT, crop_path TEXT,
  sources TEXT,
  needs_human INTEGER DEFAULT 1,
  created_at TEXT NOT NULL,
  dedupe_key TEXT UNIQUE,
  status TEXT DEFAULT 'open',
  decided_by TEXT, decided_at TEXT, decision_note TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT, kind TEXT, payload TEXT,
  state TEXT DEFAULT 'pending',
  error TEXT,
  created_at TEXT NOT NULL, sent_at TEXT,
  rotation_id INTEGER, skin_id TEXT, finding_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_finding_open ON finding(status, severity, created_at);
CREATE INDEX IF NOT EXISTS idx_skin_rotation ON skin(first_seen_rotation);
CREATE INDEX IF NOT EXISTS idx_texture_skin ON texture(skin_id);
"""

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Additive columns only. A volume from an earlier build keeps its data; nothing is rewritten."""
        have = {row[1] for row in self._conn.execute("PRAGMA table_info(outbox)")}
        if "finding_id" not in have:
            self._conn.execute("ALTER TABLE outbox ADD COLUMN finding_id INTEGER")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def digest(self) -> str:
        return self.get_meta("steam_digest")

    def rotation_for_digest(self, digest: str) -> dict | None:
        return self.one("SELECT * FROM rotation WHERE digest = ?", (digest,))

    def open_rotation(self) -> dict | None:
        return self.one("SELECT * FROM rotation ORDER BY id DESC LIMIT 1")

    def current_rotation_id(self) -> int | None:
        row = self.one("SELECT id FROM rotation ORDER BY id DESC LIMIT 1")
        return row["id"] if row else None

    def counts(self) -> dict:
        skins = self.one("SELECT COUNT(*) AS n FROM skin") or {"n": 0}
        open_findings = self.one("SELECT COUNT(*) AS n FROM finding WHERE status = 'open'") or {"n": 0}
        cleared = self.one("SELECT COUNT(*) AS n FROM finding WHERE status = 'cleared'") or {"n": 0}
        escalated = self.one("SELECT COUNT(*) AS n FROM finding WHERE status = 'escalated'") or {"n": 0}
        pending = self.one("SELECT COUNT(*) AS n FROM skin WHERE scan_status = 'unscanned'") or {"n": 0}
        unreadable = self.one("SELECT COUNT(*) AS n FROM skin WHERE scan_status = 'unreadable'") or {"n": 0}
        screened = self.one("SELECT COUNT(*) AS n FROM skin WHERE scan_status != 'unscanned'") or {"n": 0}
        return {
            "skins": skins["n"],
            "openFindings": open_findings["n"],
            "clearedFindings": cleared["n"],
            "escalatedFindings": escalated["n"],
            "pendingSkins": pending["n"],
            "unreadableSkins": unreadable["n"],
            "screenedSkins": screened["n"],
        }

    def queue(self, limit: int = 200) -> list[dict]:
        rows = self.rows(
            """
            SELECT f.id, f.skin_id, f.code, f.severity, f.title, f.created_at, f.crop_path,
                   f.decided_at, f.decision_note, s.name, s.item_shortname,
                   r.id AS rotation_id,
                   (SELECT COUNT(*) FROM finding f2 WHERE f2.skin_id = f.skin_id AND f2.status = 'open') AS open_on_skin
            FROM finding f
            JOIN skin s ON s.id = f.skin_id
            LEFT JOIN rotation r ON r.id = s.first_seen_rotation
            WHERE f.status = 'open'
            ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     f.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return rows

    def evidence(self, finding_id: int) -> dict | None:
        finding = self.one(
            """
            SELECT f.*, s.name AS skin_name, s.item_shortname, s.icon_url, s.files_path, s.store_tags
            FROM finding f JOIN skin s ON s.id = f.skin_id WHERE f.id = ?
            """,
            (finding_id,),
        )
        if not finding:
            return None
        finding["sources"] = json.loads(finding.get("sources") or "[]")
        finding["textures"] = self.rows("SELECT * FROM texture WHERE skin_id = ? ORDER BY group_index, slot", (finding["skin_id"],))
        finding["skinFindings"] = self.rows("SELECT id, code, severity, title, status, decided_at FROM finding WHERE skin_id = ? ORDER BY id", (finding["skin_id"],))
        return finding

    def decide(self, finding_ids: list[int], action: str, who: str, note: str) -> int:
        stamp = utcnow()
        # The route takes the verb (clear) and the row stores the state (cleared). Counting queries
        # and the re-scan skip both read the state, so translating here is the one place to do it.
        status = {"clear": "cleared", "escalate": "escalated"}.get(action, action)
        changed = 0
        with self.tx() as conn:
            for fid in finding_ids:
                cur = conn.execute(
                    "UPDATE finding SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
                    (status, who, stamp, note, fid),
                )
                changed += cur.rowcount
        return changed

    def record_outbox(self, channel: str, kind: str, payload: dict, rotation_id: int | None = None, skin_id: str | None = None, finding_id: int | None = None) -> int:
        with self.tx() as conn:
            cur = conn.execute(
                "INSERT INTO outbox(channel, kind, payload, created_at, rotation_id, skin_id, finding_id) VALUES(?,?,?,?,?,?,?)",
                (channel, kind, json.dumps(payload), utcnow(), rotation_id, skin_id, finding_id),
            )
        return int(cur.lastrowid or 0)

    def mark_sent(self, outbox_id: int, error: str = "") -> None:
        state = "sent" if not error else "failed"
        with self.tx() as conn:
            conn.execute("UPDATE outbox SET state = ?, error = ?, sent_at = ? WHERE id = ?", (state, error, utcnow(), outbox_id))

    def mark_queued(self, outbox_id: int, reason: str) -> None:
        """Nothing was delivered and nothing will be, but the post is kept for the operator to read."""
        with self.tx() as conn:
            conn.execute("UPDATE outbox SET state = 'queued', error = ? WHERE id = ?", (reason, outbox_id))

    def outbox(self, limit: int = 50) -> list[dict]:
        rows = self.rows("SELECT * FROM outbox ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["payload"] = json.loads(row["payload"] or "{}")
        return rows

    def pending_outbox(self) -> list[dict]:
        return self.rows("SELECT * FROM outbox WHERE state = 'pending' ORDER BY id")
