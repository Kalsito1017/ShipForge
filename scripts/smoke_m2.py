"""M2 smoke: real API + real Celery worker + real Redis/MinIO -> PUBLISHED."""

import io
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from typing import Any

import httpx
import uvicorn

from app.main import app


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


def _make_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="main.py")
        payload = b"print('ship me')\n"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _wait_for_status(
    client: httpx.Client, shipment_id: str, want: set[str], timeout: float
) -> dict:
    deadline = time.time() + timeout
    body: dict[str, Any] = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/shipments/{shipment_id}")
        body = r.json()
        if body.get("status") in want:
            return body
        time.sleep(1.0)
    return body


def main() -> int:
    config = uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="warning")
    server = _Server(config)
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()

    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "worker_app.main.celery_app",
            "worker",
            "--loglevel=WARNING",
            "--concurrency=1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(4.0)
    failures: list[str] = []
    try:
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=5.0) as client:
            # Happy path: create -> upload -> worker publishes.
            version = f"2.0.0-{uuid.uuid4().hex[:8]}"
            r = client.post(
                "/api/v1/shipments",
                json={"product": "smoke-service", "version": version},
            )
            print("create:", r.status_code)
            if r.status_code != 202:
                failures.append(f"create {r.status_code}")
            sid = r.json()["id"]

            r = client.post(
                f"/api/v1/shipments/{sid}/artifact",
                files={
                    "file": (
                        f"smoke-service-{version}.tar.gz",
                        _make_tarball(),
                        "application/gzip",
                    )
                },
            )
            print("upload:", r.status_code, r.json().get("artifact", {}).get("sha256", "")[:12])
            if r.status_code != 202:
                failures.append(f"upload {r.status_code}")

            body = _wait_for_status(client, sid, {"PUBLISHED", "FAILED"}, timeout=45)
            print("final status:", body.get("status"))
            if body.get("status") != "PUBLISHED":
                failures.append(f"pipeline ended {body.get('status')} {body.get('error_code')}")

            # Idempotent publish on an already-published shipment.
            r = client.post(f"/api/v1/shipments/{sid}/publish")
            print("publish idempotent:", r.status_code, r.json().get("status"))
            if r.status_code != 200 or r.json().get("status") != "PUBLISHED":
                failures.append(f"publish {r.status_code}")

            events = client.get(f"/api/v1/shipments/{sid}/events").json()
            types = [e["event_type"] for e in events]
            print("events:", types)
            if types.count("PUBLISHED") != 1:
                failures.append(f"published events {types.count('PUBLISHED')}")

            # Failure simulation: failure-build must end FAILED/BUILD_FAILED.
            fversion = f"1.0.0-{uuid.uuid4().hex[:8]}"
            r = client.post(
                "/api/v1/shipments",
                json={"product": "failure-build", "version": fversion},
            )
            fid = r.json()["id"]
            client.post(
                f"/api/v1/shipments/{fid}/artifact",
                files={
                    "file": (
                        f"failure-build-{fversion}.tar.gz",
                        _make_tarball(),
                        "application/gzip",
                    )
                },
            )
            body = _wait_for_status(client, fid, {"PUBLISHED", "FAILED"}, timeout=45)
            print("failure-build:", body.get("status"), body.get("error_code"))
            if body.get("status") != "FAILED" or body.get("error_code") != "BUILD_FAILED":
                failures.append(f"failure sim {body.get('status')}/{body.get('error_code')}")

            # Retry: FAILED -> VALIDATING, worker resumes.
            r = client.post(f"/api/v1/shipments/{fid}/retry")
            print("retry:", r.status_code, r.json().get("status"))
            if r.status_code != 202:
                failures.append(f"retry {r.status_code}")

            # Download the published artifact.
            r = client.get(f"/api/v1/shipments/{sid}/artifact")
            print("download:", r.status_code, r.headers.get("x-artifact-sha256", "")[:12])
            if r.status_code != 200:
                failures.append(f"download {r.status_code}")
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        server.should_exit = True
        api_thread.join(timeout=5)

    if failures:
        print("SMOKE FAILED:", failures)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
