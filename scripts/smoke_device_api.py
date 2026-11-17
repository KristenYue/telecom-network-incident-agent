"""Submit and poll real HTTP device tasks against a freshly started simulator."""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, data, {"Content-Type": "application/json"}), timeout=3) as reply:
        return json.load(reply)


def wait_for_result(root, scenario):
    created = request(root, {"scenario": scenario, "allow_sim_write": True})
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        task = request(f"{root}/{created['id']}")
        if task["status"] not in {"queued", "running"}:
            return task
        time.sleep(0.1)
    raise TimeoutError(f"still pending: {created['id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18000")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root = f"{args.url}/v1/device-tasks"
    if args.offline:
        task = wait_for_result(root, "status")
        assert task["status"] == "outcome_unknown", task
        assert task["result"]["events"][0]["code"] == "OUTCOME_UNKNOWN", task
        print(json.dumps(task))
        diagnosis = wait_for_result(root, "diagnose")
        assert diagnosis["result"]["result"]["fault"] == "transport", diagnosis
        print(json.dumps(diagnosis))
        return
    try:
        request(root, {"scenario": "run"})
    except HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("write without consent was accepted")
    for scenario, expected in (("run", "RUN_COMPLETE"), ("interlock", "SAFETY_INTERLOCK")):
        task = wait_for_result(root, scenario)
        assert task["status"] == "completed", task
        assert any(event["response"]["code"] == expected for event in task["result"]["events"]), task
        print(json.dumps(task))
    diagnosis = wait_for_result(root, "diagnose")
    assert diagnosis["status"] == "completed", diagnosis
    assert diagnosis["result"]["result"]["fault"] == "interlock", diagnosis
    assert diagnosis["result"]["result"]["runbook"]["runbook_id"] == "sim-interlock-001", diagnosis
    print(json.dumps(diagnosis))


if __name__ == "__main__":
    main()
