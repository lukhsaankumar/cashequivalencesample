"""SQLite persistence for runs, responsibility state, rate records, artifacts, errors, findings.

Kept as thin, explicit sqlite3 (no ORM) so the schema and every query are easy to audit — this
data may include internal rate information and must never leave the local machine.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from cash_equivalents_mvp.models import (
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    Run,
    SourceArtifact,
    ValidationFinding,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS responsibility_state (
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    detail_json TEXT,
    PRIMARY KEY (run_id, responsibility_id)
);
CREATE TABLE IF NOT EXISTS rate_records (
    record_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS responsibility_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    responsibility_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def _cursor(self):
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        finally:
            cur.close()

    # --- runs ---
    def create_run(self, run: Run) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT INTO runs (run_id, data_json) VALUES (?, ?)",
                        (run.run_id, run.model_dump_json()))

    def save_run(self, run: Run) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT OR REPLACE INTO runs (run_id, data_json) VALUES (?, ?)",
                        (run.run_id, run.model_dump_json()))

    def get_run(self, run_id: str) -> Run | None:
        with self._cursor() as cur:
            cur.execute("SELECT data_json FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            return Run.model_validate_json(row["data_json"]) if row else None

    def get_run_or_raise(self, run_id: str) -> Run:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run {run_id!r}")
        return run

    def list_runs(self) -> list[Run]:
        with self._cursor() as cur:
            cur.execute("SELECT data_json FROM runs ORDER BY run_id DESC")
            return [Run.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    def latest_run_for_date(self, report_date: date) -> Run | None:
        for run in self.list_runs():
            if run.report_date == report_date:
                return run
        return None

    # --- responsibility state ---
    def set_responsibility_status(self, run_id: str, responsibility_id: str,
                                   status: ResponsibilityStatus, attempts: int | None = None,
                                   detail: dict | None = None) -> None:
        import json
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                "SELECT attempts FROM responsibility_state WHERE run_id=? AND responsibility_id=?",
                (run_id, responsibility_id),
            )
            row = cur.fetchone()
            if attempts is None:
                attempts = (row["attempts"] if row else 0)
            cur.execute(
                """INSERT INTO responsibility_state (run_id, responsibility_id, status, attempts, updated_at, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, responsibility_id) DO UPDATE SET
                       status=excluded.status, attempts=excluded.attempts,
                       updated_at=excluded.updated_at, detail_json=excluded.detail_json""",
                (run_id, responsibility_id, status.value, attempts, now,
                 json.dumps(detail) if detail else None),
            )

    def get_responsibility_status(self, run_id: str, responsibility_id: str) -> ResponsibilityStatus | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT status FROM responsibility_state WHERE run_id=? AND responsibility_id=?",
                (run_id, responsibility_id),
            )
            row = cur.fetchone()
            return ResponsibilityStatus(row["status"]) if row else None

    def all_responsibility_states(self, run_id: str) -> dict[str, dict]:
        import json
        with self._cursor() as cur:
            cur.execute(
                "SELECT responsibility_id, status, attempts, updated_at, detail_json "
                "FROM responsibility_state WHERE run_id=?", (run_id,),
            )
            out = {}
            for r in cur.fetchall():
                out[r["responsibility_id"]] = {
                    "status": r["status"],
                    "attempts": r["attempts"],
                    "updated_at": r["updated_at"],
                    "detail": json.loads(r["detail_json"]) if r["detail_json"] else None,
                }
            return out

    # --- rate records ---
    def save_rate_records(self, records: list[RateRecord]) -> None:
        with self._cursor() as cur:
            for r in records:
                cur.execute("INSERT OR REPLACE INTO rate_records (record_id, run_id, responsibility_id, data_json) "
                            "VALUES (?, ?, ?, ?)", (r.record_id, r.run_id, r.responsibility_id, r.model_dump_json()))

    def clear_rate_records(self, run_id: str, responsibility_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM rate_records WHERE run_id=? AND responsibility_id=?",
                        (run_id, responsibility_id))

    def get_rate_records(self, run_id: str, responsibility_id: str | None = None) -> list[RateRecord]:
        with self._cursor() as cur:
            if responsibility_id:
                cur.execute("SELECT data_json FROM rate_records WHERE run_id=? AND responsibility_id=?",
                            (run_id, responsibility_id))
            else:
                cur.execute("SELECT data_json FROM rate_records WHERE run_id=?", (run_id,))
            return [RateRecord.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    # --- artifacts ---
    def save_artifact(self, artifact: SourceArtifact) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT OR REPLACE INTO source_artifacts (artifact_id, run_id, responsibility_id, data_json) "
                        "VALUES (?, ?, ?, ?)",
                        (artifact.artifact_id, artifact.run_id, artifact.responsibility_id,
                         artifact.model_dump_json()))

    def get_artifacts(self, run_id: str) -> list[SourceArtifact]:
        with self._cursor() as cur:
            cur.execute("SELECT data_json FROM source_artifacts WHERE run_id=?", (run_id,))
            return [SourceArtifact.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    # --- errors ---
    def save_error(self, error: ResponsibilityError) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT INTO responsibility_errors (run_id, responsibility_id, data_json) VALUES (?, ?, ?)",
                        (error.run_id, error.responsibility_id, error.model_dump_json()))

    def get_errors(self, run_id: str, responsibility_id: str | None = None) -> list[ResponsibilityError]:
        with self._cursor() as cur:
            if responsibility_id:
                cur.execute("SELECT data_json FROM responsibility_errors WHERE run_id=? AND responsibility_id=?",
                            (run_id, responsibility_id))
            else:
                cur.execute("SELECT data_json FROM responsibility_errors WHERE run_id=?", (run_id,))
            return [ResponsibilityError.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    # --- validation findings ---
    def save_findings(self, findings: list[ValidationFinding]) -> None:
        with self._cursor() as cur:
            for f in findings:
                cur.execute("INSERT INTO validation_findings (run_id, responsibility_id, data_json) VALUES (?, ?, ?)",
                            (f.run_id, f.responsibility_id, f.model_dump_json()))

    def clear_findings(self, run_id: str, responsibility_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM validation_findings WHERE run_id=? AND responsibility_id=?",
                        (run_id, responsibility_id))

    def get_findings(self, run_id: str) -> list[ValidationFinding]:
        with self._cursor() as cur:
            cur.execute("SELECT data_json FROM validation_findings WHERE run_id=?", (run_id,))
            return [ValidationFinding.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    # --- manual inputs ---
    def save_manual_input(self, mi: ManualInput, run_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT INTO manual_inputs (run_id, responsibility_id, data_json, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (run_id, mi.responsibility_id, mi.model_dump_json(), datetime.utcnow().isoformat()))

    def get_manual_inputs(self, run_id: str, responsibility_id: str) -> list[ManualInput]:
        with self._cursor() as cur:
            cur.execute("SELECT data_json FROM manual_inputs WHERE run_id=? AND responsibility_id=? "
                        "ORDER BY id DESC", (run_id, responsibility_id))
            return [ManualInput.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
