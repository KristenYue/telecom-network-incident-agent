"""Actual SocketCAN loopback, then decode the received frame using project DBC."""
import argparse
import json
import platform
import socket
import struct
from pathlib import Path
from telecom_incident_agent.vehicle_signals import ProjectDBC


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interface", default="vcan0")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if not hasattr(socket, "AF_CAN"):
        raise RuntimeError("Linux SocketCAN required; no simulation fallback")
    frame_format = "=IB3x8s"
    payload = bytes.fromhex("be00f000f000f000")
    with socket.socket(socket.AF_CAN,socket.SOCK_RAW,socket.CAN_RAW) as rx, socket.socket(socket.AF_CAN,socket.SOCK_RAW,socket.CAN_RAW) as tx:
        rx.settimeout(3)
        rx.bind((args.interface,))
        tx.bind((args.interface,))
        tx.send(struct.pack(frame_format,257,8,payload))
        frame_id, dlc, data = struct.unpack(frame_format,rx.recv(16))
    assert frame_id == 257 and dlc == 8 and data == payload
    decoded = ProjectDBC(Path(__file__).resolve().parents[1]/"examples/vehicle.dbc").decode(frame_id,data[:dlc])
    assert decoded["signals"]["FrontLeft"] == 190
    report = {"platform":platform.platform(),"socketcan_used":True,"interface":args.interface,
              "transport_boundary":"linux_virtual_can_not_physical_bus", "decoded":decoded}
    out = Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
