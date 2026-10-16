"""No-key command-line demonstration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from .adapter import TelecomIncidentRuntimeAdapter
from .compat import run_non_yielding
from .models import Alarm, IncidentRequest, MetricSample


def sample_incident(*, high_risk: bool = False) -> IncidentRequest:
    now = datetime.now(timezone.utc)
    return IncidentRequest(
        case_id="demo-optical-001",
        topology_summary="synthetic edge-r1 -- GigabitEthernet0/0/1 -- agg-r1",
        alarms=[Alarm(alarm_id="A-001", device_id="edge-r1", interface="GigabitEthernet0/0/1", alarm_type="rx_power_low", severity="major", observed_at=now)],
        metrics=[MetricSample(target="edge-r1:GigabitEthernet0/0/1", metric="rx_power_dbm", value=-27.4, unit="dBm", observed_at=now)],
        allowed_runbooks=["rb-optical-001"],
        requested_actions=["replace_optic"] if high_risk else [],
    )


async def _run() -> None:
    with TemporaryDirectory(prefix="telecom-agent-demo-") as directory:
        adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=Path(directory) / "runtime.sqlite3")
        incident = sample_incident(high_risk=True)
        result = await adapter.diagnose(incident)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        if result.status.value == "waiting_review":
            result = await adapter.resume(incident, result.run_id, approved=True, review_message="demo operator approved draft creation")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    run_non_yielding(_run())


if __name__ == "__main__":
    main()
