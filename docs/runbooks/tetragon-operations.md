# Tetragon Operations Runbook

Runtime security observability via Tetragon (cilium/tetragon) on Talos + Cilium.
All commands use `--context home`; prefix with `rtk` for token-savings where
applicable.

## Architecture

- **Chart**: `tetragon@1.7.0` via HelmRelease `kube-system/tetragon`
- **DaemonSet**: `tetragon` — one pod per node, 2 containers (tetragon agent + export-stdout)
- **gRPC socket**: `/var/run/tetragon/tetragon.sock` (chart default since 1.7.0)
- **Host-path mount**: `/var/run/tetragon` on each node (via chart's `tetragon-run` volume)
- **Operator**: `tetragon-operator` deployment, replicas=1; manages TracingPolicy CRDs
- **TracingPolicies** live in two places:
  - Cluster-wide: `kubernetes/apps/kube-system/tetragon/app/tracingpolicy-*.yaml`
  - Namespaced: `kubernetes/apps/{ns}/{app}/app/tracingpolicy-*.yaml` (reside in the target namespace)

## tetra CLI access

The agent exposes a unix-socket gRPC endpoint at `/var/run/tetragon/tetragon.sock`. Run `tetra` commands via `kubectl exec`:

```bash
# List active policies
rtk kubectl exec -n kube-system ds/tetragon -c tetragon --context home -- tetra tracingpolicy list

# Tail live events (Ctrl-C to stop)
rtk kubectl exec -it -n kube-system ds/tetragon -c tetragon --context home -- tetra getevents

# Tail events scoped to a namespace
rtk kubectl exec -it -n kube-system ds/tetragon -c tetragon --context home -- tetra getevents -n services

# Filter events by pod name
rtk kubectl exec -it -n kube-system ds/tetragon -c tetragon --context home -- tetra getevents --pod n8n

# Inspect kernel probe/hook availability
rtk kubectl exec -n kube-system ds/tetragon -c tetragon --context home -- tetra probe config
```

## Policy lifecycle

### Adding a policy

1. Choose scope:
   - **Cluster-wide**: use `kind: TracingPolicy`, place under `kubernetes/apps/kube-system/tetragon/app/`, wire into `kustomization.yaml`.
   - **Namespaced**: use `kind: TracingPolicyNamespaced`, place in the target workload's app dir (e.g. `kubernetes/apps/databases/dolt/app/`). The parent Flux Kustomization's `targetNamespace` must match the CR's `metadata.namespace`, otherwise Flux will overwrite the namespace.
2. Start with `matchActions: [{action: Post}]` (monitor-only).
3. Validate locally: `kustomize build <path>`.
4. Open PR; let Flux reconcile.
5. Verify policy loaded: `tetra tracingpolicy list` shows it in `enabled` state with NPOST counter ticking (or zero if no matches yet).

### Disabling a policy (non-destructive)

Flip `matchActions` or drop the selector in git. Flux reconciles in ~30min on default interval.

### Emergency: disable a policy immediately (no git)

```bash
# Remove the CR directly — Flux will recreate on next reconcile,
# giving a window to diagnose or push a fix
rtk kubectl delete tracingpolicy <name> --context home

# Or suspend the entire tetragon HelmRelease
rtk flux suspend hr tetragon -n kube-system --context home

# Resume after the git-side fix is merged + reconciled
rtk flux resume hr tetragon -n kube-system --context home
```

### Suspending the full DaemonSet (if agent itself misbehaves)

```bash
rtk flux suspend ks tetragon -n flux-system --context home
rtk kubectl delete ds tetragon -n kube-system --context home
# Validate + fix git; then resume
rtk flux resume ks tetragon -n flux-system --context home
```

## Investigating an alert

When a Prometheus/VMAlert rule fires based on `tetragon_policy_events_total`:

1. Get the policy name from the alert label.
2. Pull the most recent events for that policy:
   ```bash
   rtk kubectl exec -it -n kube-system ds/tetragon -c tetragon --context home -- \
     tetra getevents -o compact --last 100 | grep <policy-name>
   ```
3. For JSON payload with full process ancestry:
   ```bash
   rtk kubectl exec -it -n kube-system ds/tetragon -c tetragon --context home -- \
     tetra getevents -o json --last 20
   ```
4. For historical queries, metrics are in vmsingle under:
   - `tetragon_policy_events_total{policy="<name>"}` — per-policy rate
   - `tetragon_events_total{type="PROCESS_EXEC"}` — exec firehose
   - `tetragon_tracingpolicy_loaded{state="enabled"}` — liveness of each policy

## Metrics + dashboards

- **Grafana dashboard**: `Tetragon Security Observability` (uid `tetragon-security`)
  - Datasource: `vmsingle` (wired via GrafanaDashboard CR in `kubernetes/apps/monitoring/grafana/dashboards/app/`)
- **ServiceMonitor**: auto-provisioned by chart (`tetragon.prometheus.serviceMonitor.enabled=true`); scrape interval 60s; label filter `namespace,workload,pod` (`binary` dropped for cardinality).

## Known config decisions

See `kubernetes/apps/kube-system/tetragon/app/helmrelease.yaml`:

- `hostNetwork: true` + Talos eBPF volumes (debugfs, tracefs) — required for process visibility on Talos.
- `exportFilename: /dev/stdout` — events stream to pod stdout. Log aggregation currently disabled (tracked in `home-ops-d1e`); events are lost on pod restart. Switch to file export + vector-agent once VictoriaLogs is back.
- `exportDenyList` covers platform namespaces (cilium, kube-system, flux-system, monitoring, network, velero, system-upgrade). Workload namespaces (services, databases) always go through.
- `metricsLabelFilter: "namespace,workload,pod"` — `binary` dropped to avoid unbounded cardinality.
- `processAncestors: base,kprobe,lsm`, `enableProcessCred: true`, `enableProcessNs: true` — parent-chain + capability + namespace-transition enrichment enabled.
- `cgidmap: enabled: true` — required on Talos cgroupv2 for accurate container→pod mapping.

## Before adopting Sigkill / Signal enforcement

Tetragon supports `action: Sigkill` and `action: Signal` for in-kernel enforcement. Before flipping any policy from `Post` to enforcing:

1. Baseline for ≥14 days in `Post` mode.
2. Confirm zero false positives in that window.
3. Document the rollback path (policy name, git path, how to `tetra tracingpolicy disable` or delete).
4. Stage in a single non-critical workload first, not cluster-wide.
5. Ensure Flux suspend + reconcile access is functional before rollout.

A `Sigkill` on a policy that fires against kube-apiserver, kubelet, or core system binaries can take the cluster down. No policy in this repo currently uses enforcement actions.

## References

- Upstream docs: https://tetragon.io/docs/
- TracingPolicy selectors: https://tetragon.io/docs/concepts/tracing-policy/selectors/
- Metric reference: https://tetragon.io/docs/reference/metrics/
- Beads epic: `home-ops-y5m` — harden config, expand coverage
