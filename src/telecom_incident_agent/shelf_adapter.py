"""Read MQTT-originated telemetry through the Smart Shelf cloud read API."""

import json
import re
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ShelfTelemetryAdapter:
    def __init__(self, base_url: str, device_id: str, token: str = "", *, max_age: int = 60):
        url = urlsplit(base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.query or url.fragment:
            raise ValueError("shelf source must be an HTTP(S) base URL")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote shelf sources require HTTPS")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", device_id):
            raise ValueError("invalid shelf device ID")
        self.url = f"{base_url.rstrip('/')}/api/shelves/{device_id}/telemetry?limit=1"
        self.device_id = device_id
        self.token = token
        self.max_age = max_age
        self.http = build_opener(NoRedirect())

    def read_snapshot(self):
        return {"source": "smart_shelf_cloud", **self._read_snapshot()}

    def _read_snapshot(self):
        request = Request(self.url, headers={"X-API-Token": self.token} if self.token else {})
        try:
            with self.http.open(request, timeout=2) as reply:
                payload = reply.read(16_385)
                if len(payload) > 16_384:
                    return {"reachable": False, "code": "TELEMETRY_PAYLOAD_TOO_LARGE"}
                rows = json.loads(payload)
        except (OSError, URLError, ValueError):
            return {"reachable": False, "code": "TELEMETRY_READ_FAILED"}
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return {"reachable": False, "code": "NO_TELEMETRY"}
        row = rows[0]
        received = row.get("receivedAt")
        if row.get("deviceID") != self.device_id or type(received) is not int:
            return {"reachable": False, "code": "TELEMETRY_IDENTITY_INVALID"}
        age = time.time() - received / 1000
        if not -5 <= age <= self.max_age:
            return {"reachable": False, "code": "TELEMETRY_STALE"}
        state = row.get("state")
        if type(row.get("environmentAlert")) is bool:
            state = "ENV_ALERT" if row["environmentAlert"] else "NORMAL"
        if state not in ("NORMAL", "LOW_STOCK", "OUT_OF_STOCK", "ALERT_LIGHT", "ALERT_SOUND", "MANUAL_ALARM", "ENV_ALERT"):
            return {"reachable": False, "code": "TELEMETRY_STATE_UNAVAILABLE"}
        return {
            "reachable": True,
            "device_id": self.device_id,
            "received_at_ms": received,
            "state": state,
            "data": {},
        }
