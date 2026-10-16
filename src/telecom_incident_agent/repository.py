"""Incident indexes for local SQLite and the Compose PostgreSQL topology."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from .models import IncidentRequest


class IncidentRepositoryProtocol(Protocol):
    def create_pending(self, incident_id: str, request: IncidentRequest) -> None: ...
    def save(self, incident_id: str, request: IncidentRequest, result: dict[str, Any]) -> None: ...
    def update_status(self, incident_id: str, status: str) -> None: ...
    def get(self, incident_id: str) -> dict[str, Any]: ...
    def add_review(self, incident_id: str, *, approved: bool, reviewer: str, message: str | None) -> int: ...
    def latest_review(self, incident_id: str) -> dict[str, Any]: ...
    def ping(self) -> bool: ...


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
                    run_id TEXT,
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

    def create_pending(self, incident_id: str, request: IncidentRequest) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents(incident_id, run_id, runtime_status, request_json, result_json)
                VALUES (?, NULL, 'queued', ?, NULL)
                """,
                (incident_id, json.dumps(request.model_dump(mode="json"), ensure_ascii=False)),
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

    def update_status(self, incident_id: str, status: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE incidents SET runtime_status = ?, updated_at = CURRENT_TIMESTAMP WHERE incident_id = ?",
                (status, incident_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"incident not found: {incident_id}")

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

    def ping(self) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1


class PostgresIncidentRepository:
    """Shared incident index used by the API and Runtime Worker."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("database DSN must not be blank")
        self.dsn = dsn
        self._migrate()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - deploy optional dependency
            raise RuntimeError("PostgreSQL incident storage requires the deploy extra") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telecom_incidents (
                    incident_id VARCHAR(64) PRIMARY KEY,
                    run_id UUID,
                    runtime_status VARCHAR(40) NOT NULL,
                    request_json JSONB NOT NULL,
                    result_json JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telecom_reviews (
                    review_id BIGSERIAL PRIMARY KEY,
                    incident_id VARCHAR(64) NOT NULL REFERENCES telecom_incidents(incident_id),
                    approved BOOLEAN NOT NULL,
                    reviewer VARCHAR(100) NOT NULL,
                    message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def create_pending(self, incident_id: str, request: IncidentRequest) -> None:
        payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telecom_incidents(incident_id, run_id, runtime_status, request_json, result_json)
                VALUES (%s, NULL, 'queued', %s::jsonb, NULL)
                """,
                (incident_id, payload),
            )

    def save(self, incident_id: str, request: IncidentRequest, result: dict[str, Any]) -> None:
        request_json = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        result_json = json.dumps(result, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telecom_incidents(incident_id, run_id, runtime_status, request_json, result_json)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT(incident_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    runtime_status=excluded.runtime_status,
                    result_json=excluded.result_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (incident_id, str(result["run_id"]), result["status"], request_json, result_json),
            )

    def update_status(self, incident_id: str, status: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE telecom_incidents
                SET runtime_status=%s, updated_at=CURRENT_TIMESTAMP
                WHERE incident_id=%s
                """,
                (status, incident_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"incident not found: {incident_id}")

    @staticmethod
    def _json(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    def get(self, incident_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telecom_incidents WHERE incident_id=%s", (incident_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"incident not found: {incident_id}")
        return {
            "incident_id": row["incident_id"],
            "run_id": str(row["run_id"]) if row["run_id"] else None,
            "runtime_status": row["runtime_status"],
            "request": self._json(row["request_json"]),
            "result": self._json(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    def add_review(self, incident_id: str, *, approved: bool, reviewer: str, message: str | None) -> int:
        self.get(incident_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO telecom_reviews(incident_id, approved, reviewer, message)
                VALUES (%s, %s, %s, %s) RETURNING review_id
                """,
                (incident_id, approved, reviewer, message),
            ).fetchone()
        return int(row["review_id"])

    def latest_review(self, incident_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM telecom_reviews
                WHERE incident_id=%s ORDER BY review_id DESC LIMIT 1
                """,
                (incident_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"review not found for incident: {incident_id}")
        return {
            "review_id": row["review_id"],
            "approved": bool(row["approved"]),
            "reviewer": row["reviewer"],
            "message": row["message"],
            "created_at": row["created_at"].isoformat(),
        }

    def ping(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 AS ok").fetchone()
        return row["ok"] == 1
