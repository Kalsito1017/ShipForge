#!/usr/bin/env bash
# Create the local kind cluster, build images, load them into the cluster,
# and install the ingress controller.
set -euo pipefail

CLUSTER_NAME="${KIND_CLUSTER:-shipment-platform}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"
CONFIG_FILE="${ROOT_DIR}/infrastructure/kubernetes/kind-config.yaml"

log() { printf '[cluster-create] %s\n' "$*"; }

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  log "cluster '${CLUSTER_NAME}' already exists — reusing it"
else
  log "creating kind cluster '${CLUSTER_NAME}'"
  kind create cluster --name "${CLUSTER_NAME}" --config "${CONFIG_FILE}"
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null
log "cluster is reachable"

log "building application images"
docker build -t shipforge-api:local -f "${ROOT_DIR}/infrastructure/docker/api.Dockerfile" "${ROOT_DIR}"
docker build -t shipforge-worker:local -f "${ROOT_DIR}/infrastructure/docker/worker.Dockerfile" "${ROOT_DIR}"

log "loading images into kind"
kind load docker-image shipforge-api:local --name "${CLUSTER_NAME}"
kind load docker-image shipforge-worker:local --name "${CLUSTER_NAME}"

# Ingress controller (pinned version).
INGRESS_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml"
if kubectl get namespace ingress-nginx >/dev/null 2>&1 \
  && kubectl get deployment ingress-nginx-controller -n ingress-nginx >/dev/null 2>&1; then
  log "ingress-nginx already installed"
else
  log "installing ingress-nginx controller"
  kubectl apply -f "${INGRESS_MANIFEST}"
fi

log "waiting for ingress controller to be ready"
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=180s

log "cluster ready. deploy with: make deploy"
