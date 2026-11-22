"""Decoder for the project's unsigned little-endian classic CAN DBC subset.

Not a general DBC implementation: rejects signed/Motorola/multiplexed signals.
"""
import re
from pathlib import Path


class ProjectDBC:
    def __init__(self, path):
        self.messages = {}
        current = None
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("BO_ "):
                match = re.fullmatch(r"BO_ (\d+) (\w+): (\d+) \w+", line)
                if not match:
                    raise ValueError("unsupported DBC message")
                frame_id, name, size = match.groups()
                if not 0 <= int(frame_id) <= 0x7ff or not 1 <= int(size) <= 8:
                    raise ValueError("classic CAN standard frame required")
                if int(frame_id) in self.messages:
                    raise ValueError("duplicate CAN identifier")
                current = self.messages[int(frame_id)] = {"name": name, "size": int(size), "signals": []}
            elif line.startswith("SG_ "):
                match = re.fullmatch(r'SG_ (\w+) : (\d+)\|(\d+)@1\+ \(([-\d.]+),([-\d.]+)\) \[([-\d.]+)\|([-\d.]+)\] "[^"]*" \w+', line)
                if not match or current is None:
                    raise ValueError("unsupported DBC signal format")
                name, start, width, scale, offset, low, high = match.groups()
                start, width = int(start), int(width)
                if width < 1 or start + width > current["size"]*8:
                    raise ValueError("signal outside CAN payload")
                occupied = set(range(start, start+width))
                if any(occupied.intersection(range(s[1], s[1]+s[2])) for s in current["signals"]):
                    raise ValueError("overlapping CAN signals")
                current["signals"].append((name,start,width,float(scale),float(offset),float(low),float(high)))
        if not self.messages:
            raise ValueError("empty DBC")

    def decode(self, frame_id, payload):
        if frame_id not in self.messages:
            raise ValueError("unknown CAN identifier")
        message = self.messages[frame_id]
        if not isinstance(payload, bytes) or len(payload) != message["size"]:
            raise ValueError("invalid CAN DLC")
        bits = int.from_bytes(payload, "little")
        result = {}
        for name,start,width,scale,offset,low,high in message["signals"]:
            value = ((bits >> start) & ((1 << width)-1))*scale+offset
            if not low <= value <= high:
                raise ValueError(f"signal out of declared range: {name}")
            result[name] = value
        return {"frame_id": frame_id, "message": message["name"], "signals": result,
                "data_boundary": "synthetic_can_frame", "decoder": "project_dbc_subset"}
