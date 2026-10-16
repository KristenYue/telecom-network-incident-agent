"""Small SQLite incident index; Runtime checkpoints remain owned by Runtime."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import IncidentRequest


class IncidentRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    runtime_status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reviewer TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
                );
                """
            )

    def save(self, incident_id: str, request: IncidentRequest, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents(incident_id, run_id, runtime_status, request_json, result_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    runtime_status=excluded.runtime_status,
                    result_json=excluded.result_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    incident_id,
                    str(result["run_id"]),
                    result["status"],
                    json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def get(self, incident_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if row is None:
            raise LookupError(f"incident not found: {incident_id}")
        return {
            "incident_id": row["incident_id"],
            "run_id": row["run_id"],
            "runtime_status": row["runtime_status"],
            "request": json.loads(row["request_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def add_review(self, incident_id: str, *, approved: bool, reviewer: str, message: str | None) -> int:
        self.get(incident_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reviews(incident_id, approved, reviewer, message) VALUES (?, ?, ?, ?)",
                (incident_id, int(approved), reviewer, message),
            )
            return int(cursor.lastrowid)

    def latest_review(self, incident_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE incident_id = ? ORDER BY review_id DESC LIMIT 1",
                (incident_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"review not found for incident: {incident_id}")
        return {
            "review_id": row["review_id"], "approved": bool(row["approved"]),
            "reviewer": row["reviewer"], "message": row["message"], "created_at": row["created_at"],
        }
