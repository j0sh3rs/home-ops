# VPA and horizontal scaling rollout

Tracks [issue #510](https://github.com/j0sh3rs/home-ops/issues/510).

## Baseline: October 26, 2026

- Kubernetes 1.37.1 and Talos 1.14.4 on all four nodes.
- VPA 1.8.1, Helm chart 0.15.0; all three components have two ready replicas.
- Goldilocks 4.16.2, Helm chart 11.2.0; 64 VPAs, all `Off`, with 62 recommendations.
- VPAs were created October 23, 23:13–23:45 UTC. November 6 is the earliest
  two-week review date, subject to representative usage and sufficient data.
- No HPA or KEDA installation exists yet.
- The dashboard's internal HTTPS route redirects unauthenticated users to
  Authentik. An authenticated dashboard session has not been tested here.

VPA currently uses Metrics Server and persisted checkpoints, not Prometheus
history. Its recommendations do not establish that VictoriaMetrics scraping
works. The recommender's default memory recommendation floor was 250Mi because
the previous `args` values were ignored by the chart. The corrected
`extraArgs` lower that floor to 32Mi; this is not a resource limit. Review
recommendations again after the configuration change before acting on them.

## Initial repairs and deployment checks

The Goldilocks namespace directory must include only its child Flux
Kustomization. Without that boundary, Flux auto-discovers its application
resources in `cluster-apps`, including an HTTPRoute without a namespace.
The namespace itself is bootstrapped by `cluster-meta`.

Kubelet `/metrics`, `/metrics/cadvisor`, and `/metrics/probes` returned HTTP 401
on every node. The monitoring chart's default authorization references a
Prometheus token Secret, but Prometheus is disabled. Clearing authorization
allowed rendering but made the scrapes unauthenticated. The Helm postRenderer
now supplies the scraping vmagent's mounted service-account token on all three
endpoints. vmagent has permission to get `nodes/metrics`; no token is stored in
Git. Keep the endpoint patches aligned with the pinned chart when upgrading.

After publishing these repairs through GitOps:

1. Verify `cluster-apps`, `goldilocks`, `vpa`, and `kube-prometheus-stack` Flux
   Kustomizations and HelmReleases are Ready at the intended revision.
2. Confirm Goldilocks application resources are owned by its child
   Kustomization and the HTTPS route still redirects to Authentik.
3. Verify every live VPA remains `Off` and both recommender replicas have the
   intended arguments. The chart installs CRDs; there is no global `Update`
   mode or `api.enabled` setting controlling workload behavior.
4. Verify the converted kubelet VMServiceScrape retains `bearerTokenFile`,
   vmagent reloads successfully, and kubelet scrapes return 200.
5. Check these queries at `https://metrics.68cc.io/api/v1/query`:

   ```promql
   min by (instance, metrics_path) (up{job="kubelet"})
   count by (namespace) (container_memory_working_set_bytes{container!="",pod!=""})
   sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!="",pod!=""}[5m]))
   ```

   All expected node/path pairs must be present and up; the container queries
   must include the targeted workloads. Compare CPU and memory usage with
   requested resources, peaks, OOM events, and CPU throttling. Record when
   healthy historical metric collection resumes; do not assume missing
   historical series can be recovered from the VPA checkpoints.

## Coverage exclusions

These two VPAs are `Off` and must stay outside the automatic resizing pilot:

| VPA in monitoring | Reason |
| --- | --- |
| `goldilocks-alertmanager-prometheus` | StatefulSet is owned by an Alertmanager controller; VPA rejects the child target. |
| `goldilocks-vmagent-vmagent` | VPA cannot resolve the owning VMAgent scale subresource because `.spec.shardCount` is absent. |

These are unresolved coverage gaps, not evidence of idle workloads. Their
resource settings remain owned by their operators. Resolve supported top-level
targeting separately before considering automation; avoid creating a second
overlapping VPA or broad exclusions that remove valid monitoring recommendations.

## Observation and first VPA pilot

Keep all VPAs `Off` while collecting a representative two-week baseline,
including background jobs and normal peak load. Export each candidate's
container-level recommendations alongside configured requests/limits and
historical usage. Do not infer GPU memory sizing from CPU/memory recommendations.

Choose a small stateless, noncritical workload after reviewing its actual
configuration and usage. `services/homepage` is a candidate for that review,
not an automatic selection. Before enabling it:

- Verify supported Goldilocks per-workload update-mode/resource-policy
  annotations in the installed version, and keep one VPA owner per workload.
- Start with requests-only control; preserve existing limits until justified
  by observed usage. Do not add arbitrary maximum resource ceilings.
- Validate node headroom, QoS, resize policy, disruption budget, and minimum
  replicas. The updater defaults to requiring two replicas; do not globally
  lower that threshold to accommodate a singleton.
- Use `InPlaceOrRecreate` only after testing both an in-place change and the
  possible eviction/recreation fallback. The installed Kubernetes version and
  VPA CRD support this mode; that does not prove a workload can resize safely.
- Track successful/failed resizes, restarts, pending pods, OOMs, and application
  errors. Roll back by returning the workload VPA to `Off`; separately restore
  its previous resource settings if needed. `Off` does not undo prior changes.

The updater configuration retains disruption checks for in-place updates.

## KEDA pilot

After the measurement checks pass, install a pinned KEDA release compatible
with the cluster and pilot a single namespaced ScaledObject. Confirm the
Prometheus-compatible query returns one scalar/vector element, set a threshold
from measured demand, and begin with `minReplicaCount: 1`. Keep its VPA `Off`
initially and ensure GitOps/Helm does not fight HPA ownership of replicas.

Test scale-out and scale-in under controlled traffic, stabilization/cooldown,
metric-source outage behavior, node/GPU placement, and rollback. Set
`ignoreNullValues: "false"` when missing series should be treated as an error.
If later combining active VPA with horizontal scaling, use separate resource
metrics or custom/external demand metrics.

Scale-to-zero is a later gate: it needs a demand signal available when the
target is stopped, plus tested request buffering/retry behavior and acceptable
cold-start latency. `llama-swap` deliberately preloads and keeps gpt-oss-20b
resident for Hindsight; it is not the default zero-replica candidate.

## References

- [Pinned VPA chart values](https://github.com/kubernetes/autoscaler/blob/vertical-pod-autoscaler-chart-0.15.0/vertical-pod-autoscaler/charts/vertical-pod-autoscaler/values.yaml)
- [VPA 1.8.1 flags](https://github.com/kubernetes/autoscaler/blob/vertical-pod-autoscaler-1.8.1/vertical-pod-autoscaler/docs/flags.md)
- [VPA update behavior](https://github.com/kubernetes/autoscaler/blob/master/vertical-pod-autoscaler/docs/features.md)
- [Goldilocks configuration](https://goldilocks.docs.fairwinds.com/advanced/)
- [KEDA Prometheus scaler](https://keda.sh/docs/2.21/scalers/prometheus/)
