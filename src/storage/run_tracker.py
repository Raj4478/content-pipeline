"""
Run Tracker
Persists every pipeline run to SQLite for observability and debugging.
No external service needed — file lives in data/runs.db
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          TEXT PRIMARY KEY,
    niche       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    topic       TEXT,
    hook        TEXT,
    video_url   TEXT,
    post_ids    TEXT,
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    metadata    TEXT
);
"""


class RunTracker:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(CREATE_TABLE)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def start_run(self, niche: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (id, niche, status, started_at) VALUES (?,?,?,?)",
                (run_id, niche, "running", datetime.utcnow().isoformat()),
            )
        return run_id

    def complete_run(self, run_id: str, result: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE pipeline_runs
                   SET status=?, topic=?, hook=?, video_url=?, post_ids=?, finished_at=?, metadata=?
                   WHERE id=?""",
                (
                    "success",
                    result.get("topic"),
                    result.get("hook"),
                    result.get("video_url"),
                    json.dumps(result.get("post_ids", {})),
                    datetime.utcnow().isoformat(),
                    json.dumps(result),
                    run_id,
                ),
            )

    def fail_run(self, run_id: str, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE pipeline_runs SET status=?, error=?, finished_at=? WHERE id=?",
                ("failed", error[:500], datetime.utcnow().isoformat(), run_id),
            )

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def success_rate(self) -> float:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            ok = conn.execute(
                "SELECT COUNT(*) FROM pipeline_runs WHERE status='success'"
            ).fetchone()[0]
        return round(ok / total, 2) if total else 0.0
