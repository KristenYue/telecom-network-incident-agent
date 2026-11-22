"""Run inside FRR's network namespace; exposes only two read-only CLI commands."""
import hmac
import json
import os
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ["TELECOM_NETWORK_TOKEN"]
if not TOKEN:
    raise ValueError("empty gateway token")


def read(command):
    result = subprocess.run(["vtysh", "-c", command], capture_output=True, text=True,
                            check=True, timeout=2)
    return json.loads(result.stdout)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/snapshot":
            self.send_error(404)
            return
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN):
            self.send_error(401)
            return
        try:
            snapshot = {"source": "frr_vtysh", "device_id": "lab-r1",
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "bgp": read("show bgp ipv4 unicast summary json"),
                        "interfaces": read("show interface json")}
            body = json.dumps(snapshot).encode()
            self.send_response(200)
        except (subprocess.SubprocessError, ValueError, OSError):
            body = b'{"error":"FRR evidence unavailable"}'
            self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


ThreadingHTTPServer(("0.0.0.0", 8092), Handler).serve_forever()
