from datetime import datetime, timezone

import pytest

from telecom_incident_agent.models import Alarm, IncidentRequest, MetricSample


@pytest.fixture
def optical_incident():
    now = datetime.now(timezone.utc)
    return IncidentRequest(
        case_id="test-optical-001",
        topology_summary="synthetic edge-r1 to agg-r1",
        alarms=[Alarm(
            alarm_id="A-1", device_id="edge-r1", interface="GigabitEthernet0/0/1",
            alarm_type="rx_power_low", severity="major", observed_at=now,
        )],
        metrics=[MetricSample(
            target="edge-r1:GigabitEthernet0/0/1", metric="rx_power_dbm",
            value=-27.0, unit="dBm", observed_at=now,
        )],
        allowed_runbooks=["rb-optical-001"],
    )
