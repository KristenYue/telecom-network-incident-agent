import argparse
import json
from pathlib import Path
from telecom_incident_agent.vehicle_signals import ProjectDBC


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    args = p.parse_args()
    decoder = ProjectDBC(Path(__file__).resolve().parents[1]/"examples/vehicle.dbc")
    status = decoder.decode(256, bytes.fromhex("d2043e0100000000"))
    tires = decoder.decode(257, bytes.fromhex("be00f000f000f000"))
    assert status["signals"] == {"Speed": 12.34, "Battery": 62.0, "DoorOpen": 1.0}
    assert tires["signals"]["FrontLeft"] == 190
    rejected = []
    for name, frame, payload in [("unknown_id", 999, bytes(8)), ("wrong_dlc",256,bytes(3)),
                                  ("out_of_range",256,bytes.fromhex("ffff000000000000"))]:
        try:
            decoder.decode(frame,payload)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError(name)
    report = {"status": status, "tires": tires, "rejected": rejected, "socketcan_used": False}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"decoded_frames": 2, "rejected": rejected}))


if __name__ == "__main__":
    main()
