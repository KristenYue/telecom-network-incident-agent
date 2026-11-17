"""Run a deterministic task against the C++ simulation over its TCP protocol."""

import argparse
from uuid import UUID, uuid4

from edge_validation.client import DeviceClient
from telecom_incident_agent.device_execution import run

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("status", "run", "interlock"))
    parser.add_argument("--allow-sim-write", action="store_true")
    parser.add_argument("--task-id", type=UUID)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    return run(
        DeviceClient(port=args.port),
        args.task_id or uuid4(),
        args.scenario,
        args.allow_sim_write,
    )


if __name__ == "__main__":
    raise SystemExit(main())
