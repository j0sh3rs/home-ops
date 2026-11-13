# VPA post-merge observation baseline, October 27, 2026

Captured at 2026-10-27T13:21:33.583655+00:00. PR #815 revision: `2565a703`.

## Deployment verification

- All Flux Kustomizations are Ready at the merged revision; `cluster-apps` is repaired.
- VPA recommender, updater, and admission controller each have two ready replicas.
- 64 VPAs remain Off; 62 provide recommendations.
- Live recommender uses the 25m CPU and 32Mi memory recommendation floors.
- Live updater retains in-place disruption checks.
- Kubelet, cAdvisor, and probe scrapes are healthy on all four nodes; the converted monitor retains token-file authentication.
- Goldilocks HTTPRoute remains Accepted with ResolvedRefs.

## Metrics storage recovery

`metrics.68cc.io` resolves to the external NAS at `192.168.35.5`. Initial HTTPS, HTTP, and direct port 8428 checks refused connections. The operator confirmed the NAS Docker services had stopped and restored them. vmagent initially had 1,073,723,430 bytes (approximately 1 GiB) queued and 5,539 cumulative remote-write errors.

Recovery was verified at 13:26 UTC:

- VictoriaMetrics `/health` responds `OK`, and query requests succeed.
- vmagent's pending remote-write data decreased to zero without restarting it. Its sent-byte counter increased, while the final two error-counter readings remained at 5,571.
- All 12 unique kubelet node/path combinations return `up=1` through VictoriaMetrics.
- Current CPU rates and container memory usage are queryable across 13 namespaces. The latest AI memory sample was approximately 0.65 seconds old.
- Historical `up` samples are present for 121 series within the previous day.

The persistent queue reports 735,235,403 cumulative dropped bytes (approximately 701 MiB). This counter cannot establish the exact missing time range or attribute all drops to this outage; do not treat the historical baseline as complete. VPA recommendations continue independently through Metrics Server/checkpoints.

The kubelet scrape discovery currently includes duplicate targets for some nodes. Coverage was checked with `min by (instance, metrics_path) (up{job="kubelet"})`; namespace CPU/memory summaries used `max by (namespace,pod,container)` before aggregation so duplicate scrape series do not inflate the baseline.

## Largest memory recommendations

Per-container values in MiB. Requests, usage, and limits are averaged over matched running pods; usage is an instantaneous Metrics Server sample, not a peak or sizing decision. A dash means the resource/sample is absent. VPA targets are recommendations per pod, not totals across replicas.

| Workload | Container | Pods | Request MiB | Usage MiB | Limit MiB | VPA target MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ai/llama-swap | app | 1 | 4096.0 | 9001.2 | 16384.0 | 11195.3 |
| ai/hindsight-api | api | 1 | 1024.0 | 2029.4 | 4096.0 | 2553.8 |
| monitoring/vector | vector | 4 | 256.0 | 1259.8 | 3072.0 | 2553.8 |
| monitoring/netdata-parent | netdata | 1 | 768.0 | 1146.3 | 1536.0 | 1483.1 |
| monitoring/trivy-operator | trivy-operator | 1 | 256.0 | 853.3 | 1024.0 | 1483.1 |
| services/paperless | app | 1 | 1024.0 | 727.3 | 4096.0 | 990.6 |
| services/konflate | konflate | 1 | 256.0 | 146.7 | 1024.0 | 878.1 |
| services/home-assistant | app | 1 | 512.0 | 513.5 | 2048.0 | 825.8 |
| security/authentik-server | server | 1 | 768.0 | 535.3 | 1024.0 | 776.1 |
| services/homebridge | app | 1 | 256.0 | 552.3 | 1024.0 | 683.5 |
| monitoring/netdata-child | netdata | 4 | 256.0 | 409.4 | 512.0 | 599.6 |
| services/linkwarden | app | 1 | 1024.0 | 496.1 | 2048.0 | 599.6 |
| services/n8n | app | 1 | 512.0 | 371.4 | 1024.0 | 560.6 |
| ai/omniroute | app | 1 | 1024.0 | 419.3 | 6144.0 | 523.4 |
| services/paperless-gotenberg | app | 1 | 256.0 | 346.8 | 512.0 | 523.4 |
| ai/holyclaude | app | 1 | 1536.0 | 212.3 | 6144.0 | 488.1 |
| monitoring/trivy-server | trivy-server | 1 | 512.0 | 150.7 | 2048.0 | 454.4 |
| security/authentik-worker | worker | 1 | 320.0 | 360.9 | 512.0 | 454.4 |
| monitoring/netdata-k8s-state | netdata | 1 | 192.0 | 283.8 | 512.0 | 362.6 |
| monitoring/kube-state-metrics | kube-state-metrics | 1 | 192.0 | 155.7 | 512.0 | 236.7 |

## Remaining gates

- Preserve the outage gap in historical analysis and confirm ongoing metrics delivery stays healthy. NAS recovery and backlog drain are verified; dropped queue data cannot be assumed recovered.
- Keep Alertmanager and vmagent outside automatic VPA pilots; their existing target-resolution errors remain.
- Continue representative observation before changing workload resources. November 6 is the earliest original two-week review date; extend the review if reliable data are insufficient.
- Evaluate a small stateless VPA pilot, then a single KEDA pilot with minimum one replica. GPU scale-to-zero remains a separate decision.

See [the rollout runbook](vpa-hpa-rollout.md) for verification queries and rollout/rollback criteria.
