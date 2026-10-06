#!/usr/bin/env bash
# Delete the local kind cluster.
set -euo pipefail

CLUSTER_NAME="${KIND_CLUSTER:-shipment-platform}"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  kind delete cluster --name "${CLUSTER_NAME}"
  echo "[cluster-delete] cluster '${CLUSTER_NAME}' deleted"
else
  echo "[cluster-delete] cluster '${CLUSTER_NAME}' does not exist"
fi
