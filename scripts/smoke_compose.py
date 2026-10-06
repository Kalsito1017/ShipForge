"""Compose smoke: exercise the deployed API (localhost:8000) end to end.

Used by CI (test.yml) and local verification after `docker compose up -d`.
Requires the full stack (api, worker, postgres, redis, minio) to be running.
"""

import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"


def _make_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="main.py")
        data = b"print('ship me')\n"
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _request(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=headers or {}, method=method
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.load(response) if response.length != 0 else {}


def _upload(sid: str, filename: str, payload: bytes) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/gzip\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{BASE}/api/v1/shipments/{sid}/artifact",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _wait_for_status(sid: str, want: set[str], timeout: int = 60) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        _, body = _request("GET", f"/api/v1/shipments/{sid}")
        if body.get("status") in want:
            return body
        time.sleep(1.0)
    return body


def main() -> int:
    failures: list[str] = []
    version = f"0.0.1-{uuid.uuid4().hex[:8]}"

    # 1. Happy path: create -> upload -> worker publishes.
    status, body = _request(
        "POST",
        "/api/v1/shipments",
        json.dumps({"product": "ci-service", "version": version}).encode(),
        {"Content-Type": "application/json"},
    )
    print("create:", status)
    if status != 202:
        failures.append(f"create {status}")
    sid = body["id"]

    payload = _make_tarball()
    upload = _upload(sid, f"ci-service-{version}.tar.gz", payload)
    uploaded_sha = upload["artifact"]["sha256"]
    print("upload:", uploaded_sha[:12])
    if not upload.get("queued"):
        failures.append("upload not queued")

    body = _wait_for_status(sid, {"PUBLISHED", "FAILED"})
    print("final status:", body.get("status"))
    if body.get("status") != "PUBLISHED":
        failures.append(f"pipeline ended {body.get('status')}/{body.get('error_code')}")

    # 2. Idempotent publish.
    _, pub = _request("POST", f"/api/v1/shipments/{sid}/publish", b"")
    print("publish idempotent:", pub.get("status"))
    if pub.get("status") != "PUBLISHED":
        failures.append(f"publish {pub.get('status')}")

    # 3. Exactly one publication event.
    _, events = _request("GET", f"/api/v1/shipments/{sid}/events")
    types = [e["event_type"] for e in events]
    print("events:", types)
    if types.count("PUBLISHED") != 1:
        failures.append(f"published events {types.count('PUBLISHED')}")

    # 4. Download integrity.
    request = urllib.request.Request(f"{BASE}/api/v1/shipments/{sid}/artifact")
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    print("download sha:", digest[:12], "match:", digest == uploaded_sha)
    if digest != uploaded_sha:
        failures.append("artifact checksum mismatch")

    # 5. Failure simulation + retry.
    fversion = f"0.0.2-{uuid.uuid4().hex[:8]}"
    status, body = _request(
        "POST",
        "/api/v1/shipments",
        json.dumps({"product": "failure-build", "version": fversion}).encode(),
        {"Content-Type": "application/json"},
    )
    fid = body["id"]
    _upload(fid, f"failure-build-{fversion}.tar.gz", payload)
    body = _wait_for_status(fid, {"PUBLISHED", "FAILED"})
    print("failure-build:", body.get("status"), body.get("error_code"))
    if body.get("status") != "FAILED" or body.get("error_code") != "BUILD_FAILED":
        failures.append(f"failure sim {body.get('status')}/{body.get('error_code')}")

    status, retry = _request("POST", f"/api/v1/shipments/{fid}/retry", b"")
    print("retry:", status, retry.get("status"))
    if status != 202:
        failures.append(f"retry {status}")

    if failures:
        print("COMPOSE SMOKE FAILED:", failures)
        return 1
    print("COMPOSE SMOKE OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        print(f"COMPOSE SMOKE FAILED: cannot reach API at {BASE}: {exc}")
        sys.exit(1)
