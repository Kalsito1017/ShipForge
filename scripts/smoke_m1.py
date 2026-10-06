"""M1 smoke test: boot uvicorn in-process, exercise endpoints, exit."""

import json
import sys
import threading
import time
from typing import Any

import httpx
import uvicorn

from app.main import app


class _Server(uvicorn.Server):
    """Server that never installs signal handlers (we run in a thread)."""

    def install_signal_handlers(self) -> None:  # noqa: D102
        pass


def main() -> int:
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(2.0)

    results: list[tuple[str, Any]] = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=5.0) as client:
        r = client.get("/health")
        results.append(("GET /health", r.status_code, r.json()))

        r = client.get("/ready")
        results.append(("GET /ready", r.status_code, r.json()))

        payload = {"product": "smoke-test", "version": "0.0.1"}
        r = client.post("/api/v1/shipments", json=payload)
        results.append(("POST /api/v1/shipments", r.status_code, r.json()))

        r = client.post("/api/v1/shipments", json=payload)
        results.append(("POST duplicate", r.status_code, r.json()))

        if results[2][1] == 201:
            sid = results[2][2]["id"]
            r = client.get(f"/api/v1/shipments/{sid}/events")
            results.append(("GET events", r.status_code, r.json()))
            r = client.post(f"/api/v1/shipments/{sid}/retry")
            results.append(("POST retry (CREATED)", r.status_code, r.json()))

        r = client.get("/api/v1/shipments", params={"limit": 5})
        results.append(("GET list", r.status_code, r.json()))

    server.should_exit = True
    thread.join(timeout=5)

    failed = False
    for item in results:
        name, code, body = item
        print(f"{name}: {code} {json.dumps(body)[:120]}")
        if code >= 500:
            failed = True

    expectations = {
        "GET /health": 200,
        "GET /ready": 200,
        "POST /api/v1/shipments": 201,
        "POST duplicate": 409,
        "POST retry (CREATED)": 409,
    }
    for name, code, _ in results:
        if name in expectations and code != expectations[name]:
            print(f"FAIL: {name} expected {expectations[name]} got {code}")
            failed = True

    print("SMOKE OK" if not failed else "SMOKE FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
