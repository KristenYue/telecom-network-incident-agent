"""Durable queue for operations whose external effects cannot safely be retried."""

import asyncio
import json
import time
from contextlib import closing
from uuid import UUID, uuid4

from .device_execution import run


class DeviceTasks:
    lease_seconds = 30

    def __init__(
        self, connect, *, postgres: bool, port: int | None, writes: bool,
        diagnose=None, agent_diagnosis=None, shelf_diagnosis=None,
    ) -> None:
        self.connect = connect
        self.postgres = postgres
        self.port = port
        self.writes = writes
        self.diagnose = diagnose
        self.agent_diagnosis = agent_diagnosis
        self.shelf_diagnosis = shelf_diagnosis
        with closing(connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS telecom_device_tasks (
                    id TEXT PRIMARY KEY, scenario TEXT NOT NULL, status TEXT NOT NULL,
                    request TEXT, created_at DOUBLE PRECISION NOT NULL, lease_until DOUBLE PRECISION,
                    owner TEXT, result TEXT
                )"""
            )
            if postgres:
                db.execute("ALTER TABLE telecom_device_tasks ADD COLUMN IF NOT EXISTS request TEXT")
            else:
                columns = {row[1] for row in db.execute("PRAGMA table_info(telecom_device_tasks)")}
                if "request" not in columns:
                    db.execute("ALTER TABLE telecom_device_tasks ADD COLUMN request TEXT")
            db.execute(
                """CREATE INDEX IF NOT EXISTS telecom_device_tasks_status
                   ON telecom_device_tasks(status, created_at)"""
            )
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS telecom_device_tasks_single_runner
                   ON telecom_device_tasks(status) WHERE status='running'"""
            )

    def _execute(self, db, sql, params=()):
        return db.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def submit(self, scenario, allow_write, request=None):
        if scenario == "diagnose_shelf" and self.shelf_diagnosis is None:
            raise LookupError("shelf telemetry integration is disabled")
        if scenario != "diagnose_shelf" and self.port is None:
            raise LookupError("C++ simulator integration is disabled")
        if scenario == "agent":
            if self.agent_diagnosis is None:
                raise LookupError("model-driven industrial agent is disabled")
            if not isinstance(request, str) or not request.strip():
                raise ValueError("agent scenario requires a natural-language request")
        if scenario in {"run", "interlock"} and not (self.writes and allow_write):
            raise PermissionError("simulation writes must be enabled by server and request")
        task_id = str(uuid4())
        with closing(self.connect()) as db, db:
            self._execute(
                db,
                "INSERT INTO telecom_device_tasks(id, scenario, status, request, created_at) VALUES (?, ?, 'queued', ?, ?)",
                (task_id, scenario, request, time.time()),
            )
        return self.get(task_id)

    def get(self, task_id):
        with closing(self.connect()) as db, db:
            row = self._execute(
                db, "SELECT id, scenario, status, request, result FROM telecom_device_tasks WHERE id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise LookupError(task_id)
        return {**dict(row), "result": json.loads(row["result"]) if row["result"] else None}

    def claim(self):
        now = time.time()
        owner = str(uuid4())
        expired = json.dumps({"code": "LEASE_EXPIRED", "action": "inspect device before resubmitting"})
        with closing(self.connect()) as db, db:
            self._execute(
                db,
                """UPDATE telecom_device_tasks SET status='outcome_unknown', result=?, owner=NULL
                   WHERE status='running' AND lease_until <= ?""",
                (expired, now),
            )
            lock = " FOR UPDATE SKIP LOCKED" if self.postgres else ""
            return self._execute(
                db,
                f"""UPDATE telecom_device_tasks SET status='running', owner=?, lease_until=?
                    WHERE id=(SELECT id FROM telecom_device_tasks WHERE status='queued'
                              AND NOT EXISTS (SELECT 1 FROM telecom_device_tasks WHERE status='running')
                              ORDER BY created_at, id LIMIT 1{lock}) AND status='queued'
                    RETURNING id, scenario, request, owner, lease_until""",
                (owner, now + self.lease_seconds),
            ).fetchone()

    def finish(self, task, status, result):
        with closing(self.connect()) as db, db:
            return self._execute(
                db,
                """UPDATE telecom_device_tasks SET status=?, result=?, owner=NULL
                   WHERE id=? AND owner=? AND status='running' AND lease_until > ?""",
                (status, json.dumps(result), task["id"], task["owner"], time.time()),
            ).rowcount == 1

    def work_once(self):
        task = self.claim()
        if task is None:
            return
        events = []

        def may_send():
            return time.time() < task["lease_until"]

        try:
            if task["scenario"] == "diagnose_shelf":
                if self.shelf_diagnosis is None:
                    self.finish(task, "failed", {"code": "SHELF_TELEMETRY_UNAVAILABLE"})
                    return
                result = asyncio.run(self.shelf_diagnosis(task_id=task["id"], may_send=may_send))
                self.finish(task, result.status, result.model_dump(mode="json"))
                return
            from edge_validation.client import DeviceClient

            if self.port is None:
                self.finish(task, "failed", {"code": "SIMULATOR_UNAVAILABLE"})
                return
            client = DeviceClient(port=self.port, timeout=1)

            if task["scenario"] == "agent":
                if self.agent_diagnosis is None:
                    self.finish(task, "failed", {"code": "MODEL_AGENT_UNAVAILABLE"})
                    return
                diagnosis = asyncio.run(self.agent_diagnosis(
                    client, request=task["request"], task_id=task["id"], may_send=may_send,
                ))
                self.finish(task, diagnosis.status, diagnosis.model_dump(mode="json"))
                return
            if task["scenario"] == "diagnose":
                if self.diagnose is None:
                    self.finish(task, "failed", {"code": "DIAGNOSIS_UNAVAILABLE"})
                    return
                diagnosis = asyncio.run(self.diagnose(client, task_id=task["id"], may_send=may_send))
                self.finish(task, diagnosis.status, diagnosis.model_dump(mode="json"))
                return
            code = run(
                client,
                UUID(task["id"]),
                task["scenario"],
                self.writes,
                emit=lambda **event: events.append(event),
                may_send=may_send,
            )
        except ImportError:
            self.finish(task, "failed", {"code": "DEVICE_CLIENT_UNAVAILABLE"})
            return
        except Exception as exc:
            self.finish(task, "outcome_unknown", {"code": type(exc).__name__, "events": events})
            return
        status = {0: "completed", 2: "rejected", 3: "outcome_unknown", 4: "rejected"}[code]
        self.finish(task, status, {"exit_code": code, "events": events})

    async def run_local_worker(self):
        while True:
            await asyncio.to_thread(self.work_once)
            await asyncio.sleep(0.25)
