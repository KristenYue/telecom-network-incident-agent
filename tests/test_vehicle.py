import time
from types import SimpleNamespace

import pytest

from telecom_incident_agent.vehicle import VehicleService


def test_old_upload_does_not_overwrite_latest_and_duplicate_conflicts(tmp_path):
    service = VehicleService(tmp_path/"vehicle.sqlite3", capacity=1)
    service.ingest(2, {"battery_percent": 60})
    service.ingest(1, {"battery_percent": 10}, event_time=time.time()-100, online=False)
    with pytest.raises(OverflowError):
        service.ingest(3, {}, online=False)
    assert service.reconnect()["flushed"] == 1
    assert service.latest()["sequence"] == 2
    assert service.ingest(2, {"battery_percent": 60})["outcome"] == "duplicate"
    with pytest.raises(ValueError):
        service.ingest(2, {"battery_percent": 20})


def test_cabin_command_ledger_is_atomic_and_range_checked(tmp_path):
    service = VehicleService(tmp_path/"vehicle.sqlite3")
    context = SimpleNamespace(idempotency_key="command-1")
    assert not service.set_temperature(22.0, runtime_context=context)["replayed"]
    assert service.set_temperature(22.0, runtime_context=context)["replayed"]
    with pytest.raises(ValueError):
        service.set_temperature(23.0, runtime_context=context)
    with pytest.raises(ValueError):
        service.set_temperature(99.0, runtime_context=context)
    with service.connect() as db:
        assert db.execute("SELECT temperature FROM cabin").fetchone()[0] == 22
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1


def test_stale_telemetry_cannot_claim_tire_diagnosis(tmp_path):
    service = VehicleService(tmp_path/"vehicle.sqlite3")
    service.ingest(1, {"tire_kpa": {"front_left": 190}}, event_time=time.time()-120)
    assert service.tire_pressure()["outcome"] == "unknown"
