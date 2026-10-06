# Kubernetes manifests

Raw deployment resources for ShipForge are defined in the Helm chart at
`infrastructure/helm/shipment-platform` (Deployment, Service, ConfigMap, Secret,
Ingress, StatefulSet for stateful components) and rendered to plain YAML with:

```bash
make manifests        # writes rendered manifests to infrastructure/kubernetes/rendered/
```

or manually:

```bash
helm template shipment-platform ../helm/shipment-platform \
  --values ../helm/shipment-platform/values-local.yaml
```

This directory also holds the local cluster configuration:

- `kind-config.yaml` — single-node kind cluster `shipment-platform` with
  ingress port mappings (host `:18080` -> node `:80`)

Workflow:

```bash
make cluster    # create cluster + build/load images + ingress controller
make deploy     # helm upgrade --install with values-local.yaml
make status     # pod status
```
