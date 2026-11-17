from __future__ import annotations

import json

from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.jobs import ClaimedJob, RedisIncidentJobQueue
from telecom_incident_agent.worker import process_claimed_job
from telecom_incident_agent.service import IncidentService
from telecom_incident_agent.repository import PostgresIncidentRepository

import pytest


def test_outbox_replays_same_event_after_publish_before_delete(tmp_path):
    class FailingOutbox(PostgresIncidentRepository):
        def __init__(self):
            self.event = {"event_id": 42, "incident_id": "INC-1", "kind": "diagnose"}
            self.crash = True

        def pending_dispatches(self):
            return [self.event] if self.event is not None else []

        def finish_dispatch(self, event_id):
            assert event_id == 42
            if self.crash:
                raise RuntimeError("simulated crash before outbox removal")
            self.event = None

    repository = FailingOutbox()
    redis = ScriptedRedis()
    queue = RedisIncidentJobQueue("redis://test", consumer_id="worker-b", client=redis)
    service = IncidentService(tmp_path, repository=repository, queue=queue)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_non_yielding(service.publish_pending_jobs())
    repository.crash = False
    run_non_yielding(service.publish_pending_jobs())
    run_non_yielding(service.publish_pending_jobs())
    assert len(redis.entries) == 2
    first, second = redis.entries.values()
    assert first == second


@pytest.mark.parametrize(
    ("runtime_status", "result_status"),
    [("completed", "completed"), ("queued_resume", "waiting_review")],
)
def test_redelivery_after_result_commit_acknowledges_without_writing(
    tmp_path, runtime_status, result_status
):
    class CommittedRepository:
        def get(self, incident_id):
            assert incident_id == "INC-1"
            return {"runtime_status": runtime_status, "result": {"status": result_status}}

    redis = ScriptedRedis()
    queue = RedisIncidentJobQueue("redis://test", consumer_id="worker-b", client=redis)
    service = IncidentService(tmp_path, repository=CommittedRepository(), queue=queue)
    claimed = ClaimedJob("1-0", {"incident_id": "INC-1", "kind": "diagnose"}, 2)
    assert run_non_yielding(process_claimed_job(service, claimed))
    assert redis.acked == ["1-0"]


class ScriptedRedis:
    def __init__(self) -> None:
        self.entries = {}
        self.new = []
        self.stale = []
        self.delivery_count = 1
        self.errors = {}
        self.dead_letters = []
        self.acked = []
        self.deleted = []
        self.closed = False
        self.next_id = 1
        self.read_blocks = []

    async def xgroup_create(self, *args, **kwargs):
        return True

    async def xadd(self, stream, fields):
        message_id = f"{self.next_id}-0"
        self.next_id += 1
        if stream.endswith("dead-letter"):
            self.dead_letters.append((message_id, fields))
        else:
            self.entries[message_id] = fields
            self.new.append((message_id, fields))
        return message_id

    async def xautoclaim(self, *args, **kwargs):
        messages = list(self.stale)
        self.stale.clear()
        return ["0-0", messages, []]

    async def xreadgroup(self, group, consumer, streams, *, count, block):
        self.read_blocks.append(block)
        if not self.new:
            return []
        item = self.new.pop(0)
        return [(next(iter(streams)), [item])]

    async def xpending_range(self, *args, **kwargs):
        return [{"times_delivered": self.delivery_count}]

    async def xack(self, stream, group, message_id):
        self.acked.append(message_id)

    async def xdel(self, stream, message_id):
        self.deleted.append(message_id)

    async def hset(self, key, message_id, error):
        self.errors[(key, message_id)] = error

    async def hget(self, key, message_id):
        return self.errors.get((key, message_id))

    async def hdel(self, key, message_id):
        self.errors.pop((key, message_id), None)

    async def ping(self):
        return True

    async def aclose(self):
        self.closed = True


def test_stream_job_is_acknowledged_only_after_success():
    redis = ScriptedRedis()
    queue = RedisIncidentJobQueue(
        "redis://test", consumer_id="worker-a", client=redis
    )
    message_id = run_non_yielding(
        queue.enqueue({"kind": "diagnose", "incident_id": "INC-1"})
    )
    claimed = run_non_yielding(queue.dequeue(timeout_seconds=0))
    assert claimed == ClaimedJob(
        message_id, {"incident_id": "INC-1", "kind": "diagnose"}, 1
    )
    assert redis.acked == []
    assert redis.read_blocks == [None]

    run_non_yielding(queue.ack(claimed))
    assert redis.acked == [message_id]
    assert redis.deleted == [message_id]


def test_failed_job_is_reclaimed_with_delivery_count_and_last_error():
    redis = ScriptedRedis()
    queue = RedisIncidentJobQueue(
        "redis://test",
        consumer_id="worker-a",
        visibility_timeout_seconds=0,
        client=redis,
    )
    message_id = run_non_yielding(
        queue.enqueue({"kind": "diagnose", "incident_id": "INC-2"})
    )
    first = run_non_yielding(queue.dequeue(timeout_seconds=0))
    run_non_yielding(queue.fail(first, "injected worker failure"))

    redis.stale.append((message_id, redis.entries[message_id]))
    redis.delivery_count = 2
    second = run_non_yielding(queue.dequeue(timeout_seconds=0))

    assert second.deliveries == 2
    assert second.payload["incident_id"] == "INC-2"
    assert redis.errors[(queue.error_hash_key, message_id)] == "injected worker failure"


def test_delivery_limit_moves_job_to_dead_letter_stream():
    redis = ScriptedRedis()
    queue = RedisIncidentJobQueue(
        "redis://test", consumer_id="worker-a", max_deliveries=2, client=redis
    )
    payload = json.dumps({"kind": "diagnose", "incident_id": "INC-3"})
    redis.entries["9-0"] = {"payload": payload}
    redis.stale.append(("9-0", redis.entries["9-0"]))
    redis.delivery_count = 3

    assert run_non_yielding(queue.dequeue(timeout_seconds=0)) is None
    assert redis.acked == ["9-0"]
    assert redis.deleted == ["9-0"]
    assert redis.dead_letters[0][1]["deliveries"] == "3"
    assert redis.dead_letters[0][1]["last_error"] == "delivery_limit_exceeded"


class RecordingQueue:
    def __init__(self) -> None:
        self.acked = []
        self.failed = []

    async def ack(self, claimed):
        self.acked.append(claimed.message_id)

    async def fail(self, claimed, error):
        self.failed.append((claimed.message_id, error))


class WorkerService:
    def __init__(self, *, fails: bool) -> None:
        self.queue = RecordingQueue()
        self.fails = fails

    async def process_job(self, payload):
        if self.fails:
            raise RuntimeError("injected")
        return payload


def test_worker_settles_success_and_keeps_failure_pending():
    claimed = ClaimedJob("1-0", {"kind": "diagnose", "incident_id": "INC-4"}, 1)
    successful = WorkerService(fails=False)
    assert run_non_yielding(process_claimed_job(successful, claimed)) is True
    assert successful.queue.acked == ["1-0"]

    failing = WorkerService(fails=True)
    assert run_non_yielding(process_claimed_job(failing, claimed)) is False
    assert failing.queue.acked == []
    assert failing.queue.failed[0][0] == "1-0"
    assert "RuntimeError: injected" in failing.queue.failed[0][1]
