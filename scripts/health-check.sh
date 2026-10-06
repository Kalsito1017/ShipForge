#!/usr/bin/env bash
# Health check for a running ShipForge deployment.
# Works against Docker Compose (localhost:8000) or the local kind ingress
# (localhost:8080 with host header). Exits non-zero when unhealthy.
set -euo pipefail

BASE_URL="${SHIPFORGE_URL:-http://localhost:8000}"
HOST_HEADER="${SHIPFORGE_HOST:-shipforge.local}"

if [[ "${BASE_URL}" == *"18080"* ]]; then
  CURL=(curl -sf -H "Host: ${HOST_HEADER}")
else
  CURL=(curl -sf)
fi

fail=0

check() {
  local name="$1" url="$2"
  if body="$("${CURL[@]}" --max-time 5 "${url}")"; then
    printf 'OK   %-12s %s\n' "${name}" "${body}"
  else
    printf 'FAIL %-12s %s\n' "${name}" "${url}"
    fail=1
  fi
}

check health "${BASE_URL}/health"
check ready "${BASE_URL}/ready"
check shipments "${BASE_URL}/api/v1/shipments?limit=1"

if command -v kubectl >/dev/null 2>&1 && kubectl get pods >/dev/null 2>&1; then
  echo "--- pods ---"
  kubectl get pods -o wide
fi

exit "${fail}"
