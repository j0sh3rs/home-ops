# Home-Ops Cluster: Current State Analysis

**Analysis Date**: January 5, 2026
**Cluster**: home (Talos Linux v1.12.0, Kubernetes v1.34.3)
**Purpose**: Platform evolution baseline for LGTM simplification and Tetragon migration planning

---

## Executive Summary

### Current Architecture
- **Observability**: Prometheus + Thanos (S3-backed long-term storage) + Grafana + Victoria Logs (configured but not running)
- **Security**: Wazuh (full SIEM stack), CrowdSec (intrusion prevention), **Tetragon (eBPF runtime security - ALREADY DEPLOYED)**
- **Storage**: OpenEBS LocalPV for volumes, Minio S3 (s3.68cc.io) for object storage
- **Cluster Health**: 3 control-plane nodes, healthy resource utilization (17-37% memory)

### Key Findings
1. **Victoria Logs**: Configured in Grafana datasources but HelmRelease not deployed (planned but not activated)
2. **Tetragon**: Already operational with eBPF monitoring (46h uptime, ServiceMonitor enabled)
3. **LGTM Stack**: Only Prometheus/Thanos/Grafana deployed - Loki, Tempo, Mimir **NOT** present
4. **Resource Intensive**: Wazuh indexers consume 3x 1.5Gi memory each (4.5Gi total for security namespace)
5. **S3 Integration**: Thanos successfully using Minio S3 backend (bucket: "thanos")

### Migration Complexity Assessment
- **Low Complexity**: Tetragon already deployed, just needs configuration refinement
- **Medium Complexity**: Victoria Logs activation (HelmRelease exists, needs deployment)
- **High Complexity**: Wazuh decommissioning (150Gi+ storage, 3-node OpenSearch cluster, backup CronJobs)

---

## 1. Monitoring Namespace Inventory

### 1.1 Deployed Components

| Component | Version | Replicas | Resource Usage | Storage |
|-----------|---------|----------|----------------|---------|
| **Prometheus** | v2.55.1 (prompp/prompp:0.7.2) | 1 StatefulSet | 48m CPU, 433Mi RAM | 60Gi PVC (openebs-hostpath) |
| **Thanos Query** | v0.40.1 | 2 Deployment | 1m CPU, 15-16Mi RAM each | None |
| **Thanos Compact** | v0.40.1 | 1 StatefulSet | 3m CPU, 372Mi RAM | 10Gi PVC (openebs-hostpath) |
| **Thanos Store Gateway** | v0.40.1 | 1 StatefulSet | 1m CPU, 174Mi RAM | 10Gi PVC (openebs-hostpath) |
| **Alertmanager** | v0.30.0 | 1 StatefulSet | 1m CPU, 67Mi RAM | 1Gi PVC (nfs-client) |
| **Grafana** | 12.1.0 | 1 Deployment | 3m CPU, 350Mi RAM | 30Gi PVC (openebs-hostpath) |
| **Grafana Operator** | v5.21.3 | 1 Deployment | 2m CPU, 34Mi RAM | None |
| **Prometheus Operator** | v0.87.1 | 1 Deployment | 2m CPU, 25Mi RAM | None |
| **kube-state-metrics** | v2.17.0 | 1 Deployment | 2m CPU, 76Mi RAM | None |
| **node-exporter** | v1.10.2 | 3 DaemonSet | 1m CPU, 28-30Mi RAM each | None |
| **unpoller** | v2.21.0 | 1 Deployment | 1m CPU, 14Mi RAM | None |

**Total Monitoring Namespace Resources**:
- **CPU**: ~130m (across all pods)
- **Memory**: ~1.7Gi (peak usage)
- **Storage**: 171Gi (6 PVCs)

### 1.2 Thanos S3 Configuration

**S3 Backend**: Local Minio at `s3.68cc.io:443`

```yaml
type: S3
config:
  bucket: thanos
  endpoint: s3.68cc.io:443
  access_key: thanos
  secret_key: [REDACTED]
  insecure: false
  http_config:
    tls_config:
      insecure_skip_verify: false
```

**Retention Policies** (Thanos Compact):
- Raw data: 120 days
- 5m resolution: 365 days
- 1h resolution: 730 days (2 years)

**Prometheus Local Retention**:
- Time: 6h (reduced since Thanos handles long-term storage)
- Size: 50GB limit

### 1.3 Grafana Datasources

Currently configured datasources:
1. **prometheus** (default) - `http://prometheus-prometheus.monitoring.svc.cluster.local:9090`
2. **thanos** - `http://thanos-query.monitoring.svc.cluster.local:9090` (5m interval, 300s timeout)
3. **alertmanager** - `http://prometheus-alertmanager.monitoring.svc.cluster.local:9093`
4. **victoria-logs** - `http://victoria-logs-server.monitoring.svc.cluster.local:9428` (configured but service not running)

**Victoria Logs Plugin**: victoriametrics-logs-datasource v0.22.0 (LogsQL enabled, maxLines: 1000)

### 1.4 Victoria Logs Status

**Configuration**: HelmRelease exists at `kubernetes/apps/monitoring/victoria-logs/app/helmrelease.yaml`

```yaml
Key Settings:
- Retention: 14d
- Storage: 50Gi (openebs-hostpath)
- Syslog listeners: TCP:514, UDP:514
- Timezone: America/New_York
- Route: logs.68cc.io
- ServiceMonitor: enabled
```

**Current Status**:
- ✅ HelmRelease configuration exists
- ❌ No running pods (victoria-logs-server StatefulSet not found)
- ❌ No PVC created yet
- ✅ Grafana datasource pre-configured

**Action Required**: Deploy the HelmRelease or check Flux reconciliation status

### 1.5 Missing LGTM Components

**NOT DEPLOYED**:
- ❌ Loki (log aggregation)
- ❌ Tempo (distributed tracing)
- ❌ Mimir (long-term metrics storage)

**Current Reality**: Cluster uses **Prometheus + Thanos + Grafana** (PTG stack), not full LGTM.

---

## 2. Security Namespace Inventory

### 2.1 Wazuh Deployment

**Architecture**: Full SIEM stack with OpenSearch backend

| Component | Replicas | Image | Resource Usage | Storage |
|-----------|----------|-------|----------------|---------|
| **wazuh-indexer** | 3 StatefulSet | wazuh-indexer:4.14.1 | 7-13m CPU, 1.5Gi RAM each | 3x 50Gi + 3x 500Mi PVC |
| **wazuh-manager-master** | 1 StatefulSet | wazuh-manager:4.14.1 | 4m CPU, 582Mi RAM | 20Gi + 500Mi PVC |
| **wazuh-manager-worker** | 2 StatefulSet | wazuh-manager:4.14.1 | 1-7m CPU, 70-509Mi RAM | 2x 20Gi + 2x 500Mi PVC |
| **wazuh-dashboard** | 1 Deployment | wazuh-dashboard:4.14.1 | 1m CPU, 212Mi RAM | None |
| **wazuh-agent** | 3 DaemonSet | wazuh-agent:4.14.1 | 1m CPU, 10-12Mi RAM each | None |

**Total Wazuh Resources**:
- **CPU**: ~50m (across all components)
- **Memory**: ~5.1Gi (3x indexers = 4.5Gi + managers/dashboard = 600Mi)
- **Storage**: 151.5Gi (12 PVCs on openebs-hostpath)

**Backup Infrastructure**:
- **opensearch-snapshot CronJob**: Daily at 07:00 EST (S3 snapshots)
- **wazuh-manager-backup CronJob**: Daily at 07:05 EST (manager config backups)

**Network Exposure**:
- HTTPRoute: `wazuh.68cc.io` (dashboard)
- TCPRoute: Syslog port 514 (external log ingestion)
- UDPRoute: Syslog port 514 (external log ingestion)
- Internal services: API (55000), registration (1515), cluster (1516), workers (1514)

### 2.2 CrowdSec Deployment

**Architecture**: Intrusion prevention with LAPI + agents

| Component | Replicas | Image | Resource Usage | Storage |
|-----------|----------|-------|----------------|---------|
| **crowdsec-lapi** | 1 | crowdsecurity/crowdsec:v1.7.4 | 150m CPU (req), 2Gi RAM (limit) | 10Gi data + 250Mi config (nfs-client) |
| **crowdsec-agent** | DaemonSet | crowdsecurity/crowdsec:v1.7.4 | 150m CPU (req), 2Gi RAM (limit) | 100Mi config (nfs-client) |

**Collections**:
- crowdsecurity/traefik
- crowdsecurity/appsec-crs
- crowdsecurity/http-cve
- crowdsecurity/appsec-crs-inband
- crowdsecurity/base-http-scenarios
- LePresidente/grafana
- crowdsecurity/unifi

**Acquisition Sources**:
- Traefik (network namespace)
- Grafana (monitoring namespace)

**Enrollment**: Connected to CrowdSec console with tags: `kubernetes`, `homelab`

---

## 3. Tetragon Runtime Security (Already Deployed!)

### 3.1 Current Deployment Status

**Deployment Age**: 46 hours (recently deployed on January 3, 2026)
**Chart Version**: tetragon-1.6.0
**HelmRepository**: https://helm.cilium.io

| Component | Replicas | Resource Usage | ServiceMonitor |
|-----------|----------|----------------|----------------|
| **tetragon** | 3 DaemonSet | 1-2m CPU, 70-90Mi RAM each | ✅ Enabled |
| **tetragon-operator** | 1 Deployment | 1m CPU, 12Mi RAM | ✅ Enabled |

**Total Tetragon Resources**:
- **CPU**: ~6m (across all pods)
- **Memory**: ~258Mi (3 agents + operator)
- **Storage**: None (stateless)

### 3.2 Tetragon Configuration

**Key Settings**:
- **Export**: stdout (real-time event streaming)
- **Export Rate Limit**: 1000 events/sec
- **gRPC**: Enabled on localhost:54321
- **CRI Socket**: `/run/containerd/containerd.sock`
- **eBPF Filesystem Support**: Configured for Talos Linux

**Talos-Specific eBPF Mounts**:
```yaml
extraVolumes:
  - name: debugfs
    hostPath: /sys/kernel/debug
  - name: tracefs
    hostPath: /sys/kernel/tracing

extraVolumeMounts:
  - name: debugfs
    mountPath: /sys/kernel/debug
  - name: tracefs
    mountPath: /sys/kernel/tracing
```

**Prometheus Integration**: ServiceMonitor enabled for both Tetragon and Tetragon Operator

### 3.3 Tetragon vs Wazuh Comparison

| Feature | Tetragon (eBPF) | Wazuh (Agent-based) |
|---------|-----------------|---------------------|
| **Architecture** | Kernel-level eBPF, no syscall hooks | User-space agents, file integrity monitoring |
| **Resource Usage** | ~258Mi RAM, ~6m CPU | ~5.1Gi RAM, ~50m CPU |
| **Storage** | Stateless | 151.5Gi (OpenSearch cluster) |
| **Observability** | Real-time kernel events | Log aggregation + SIEM correlation |
| **Maintenance** | Low (3 DaemonSet pods + operator) | High (3-node OpenSearch, 3 managers, agents, backups) |
| **Detection Scope** | Process execution, network, file access | Log-based detections, compliance checks |
| **Response Speed** | Microseconds (kernel-level) | Seconds (log parsing + analysis) |

**Migration Implications**: Tetragon provides kernel-level runtime security that Wazuh cannot match, but Wazuh offers SIEM correlation and compliance reporting. If user needs are focused on runtime threat detection (not compliance), Tetragon is the superior solution.

---

## 4. Cilium Network Observability

### 4.1 Cilium Deployment

**Chart Version**: cilium-1.18.5
**Deployment Age**: 52 days (deployed November 14, 2025)

| Component | Replicas | Resource Usage |
|-----------|----------|----------------|
| **cilium** | 3 DaemonSet | 37-52m CPU, 181-198Mi RAM each |
| **cilium-envoy** | 3 DaemonSet | 4-5m CPU, 15-17Mi RAM each |
| **cilium-operator** | 2 Deployment | 1-3m CPU, 39-68Mi RAM each |

**Total Cilium Resources**:
- **CPU**: ~175m (across all pods)
- **Memory**: ~740Mi (agents + envoy + operators)

**Observability Features**:
- ✅ ServiceMonitors available (agent, operator, envoy metrics)
- ✅ Hubble for network flow visibility
- ✅ eBPF-based packet filtering and routing

---

## 5. Storage Architecture

### 5.1 Persistent Volume Claims (Monitoring)

| PVC Name | Size | StorageClass | Consumer | Age |
|----------|------|--------------|----------|-----|
| alertmanager-prometheus-db-* | 1Gi | nfs-client | Alertmanager | 43d |
| data-thanos-compact-0 | 10Gi | openebs-hostpath | Thanos Compact | 14d |
| data-thanos-store-gateway-0 | 10Gi | openebs-hostpath | Thanos Store | 14d |
| grafana-pvc | 30Gi | openebs-hostpath | Grafana | 45d |
| prometheus-prometheus-db-* | 60Gi | openebs-hostpath | Prometheus | 16d |
| server-volume-victoria-logs-* | 50Gi | openebs-hostpath | Victoria Logs (not running) | 45d |

**Total Monitoring Storage**: 171Gi (6 PVCs)

### 5.2 Persistent Volume Claims (Security)

| PVC Name | Size | StorageClass | Consumer | Age |
|----------|------|--------------|----------|-----|
| opensearch-data-wazuh-indexer-[0-2] | 3x 50Gi | openebs-hostpath | Wazuh Indexers | 22d |
| wazuh-indexer-wazuh-indexer-[0-2] | 3x 500Mi | openebs-hostpath | Wazuh Indexers (config) | 5d |
| wazuh-manager-data-master-0 | 20Gi | openebs-hostpath | Wazuh Manager Master | 22d |
| wazuh-manager-data-worker-[0-1] | 2x 20Gi | openebs-hostpath | Wazuh Manager Workers | 22d |
| wazuh-manager-master-* | 500Mi | openebs-hostpath | Wazuh Manager (config) | 5d |
| wazuh-manager-worker-* | 2x 500Mi | openebs-hostpath | Wazuh Workers (config) | 5d |

**Total Security Storage**: 151.5Gi (12 PVCs)

### 5.3 S3 Object Storage

**S3 Endpoint**: https://s3.68cc.io (Minio)

**Known Buckets**:
- `thanos` - Thanos long-term metrics storage (verified active)
- `openebs-backups` - Velero snapshots (from CLAUDE.md)
- `loki-chunks` - Loki persistence (documented but not deployed)
- `tempo-traces` - Tempo persistence (documented but not deployed)
- `mimir-blocks` - Mimir persistence (documented but not deployed)

**S3 Integration Pattern**: Each component has dedicated SOPS-encrypted secrets with `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT`, `S3_BUCKET`.

---

## 6. Node Infrastructure

### 6.1 Cluster Nodes

| Node | Role | Age | OS | Kernel | CPU | Memory Used |
|------|------|-----|----|----|-----|-------------|
| bee-jms-01 | control-plane | 53d | Talos v1.12.0 | 6.18.1-talos | 351m (4%) | 6340Mi (24%) |
| bee-jms-02 | control-plane | 53d | Talos v1.12.0 | 6.18.1-talos | 557m (3%) | 9764Mi (37%) |
| bee-jms-03 | control-plane | 53d | Talos v1.12.0 | 6.18.1-talos | 359m (2%) | 10021Mi (17%) |

**Total Cluster Capacity**:
- **Nodes**: 3 (control-plane only, no workers)
- **Kubernetes**: v1.34.3
- **Container Runtime**: containerd 2.1.6
- **Average Resource Usage**: 2.6% CPU, 26% Memory (healthy)

### 6.2 Talos Security Features

**eBPF Support**:
- ✅ debugfs mounted at `/sys/kernel/debug`
- ✅ tracefs mounted at `/sys/kernel/tracing`
- ✅ Kernel version 6.18.1 (modern eBPF capabilities)

**Security Context**:
- Immutable OS (API-driven configuration)
- Secure by default (no SSH, minimal attack surface)
- systemd-free (reduced complexity)

---

## 7. Migration Impact Analysis

### 7.1 Victoria Logs Activation (Low Complexity)

**Current State**:
- ✅ HelmRelease configuration exists
- ✅ Grafana datasource pre-configured
- ✅ Storage allocated (50Gi PVC created but not attached)
- ❌ No running pods

**Required Actions**:
1. Check Flux reconciliation status: `flux get helmrelease victoria-logs -n monitoring`
2. If suspended, resume: `flux resume helmrelease victoria-logs -n monitoring`
3. Force reconciliation: `flux reconcile helmrelease victoria-logs -n monitoring`

**Expected Outcome**: Victoria Logs StatefulSet deploys, syslog listeners activate, Grafana datasource becomes functional.

**Timeline**: <1 hour (assuming no configuration issues)

### 7.2 Tetragon Configuration Refinement (Low Complexity)

**Current State**:
- ✅ Deployed and running (46h uptime)
- ✅ ServiceMonitors enabled
- ✅ Talos-specific eBPF mounts configured
- ⚠️ Default policy (allow-all with export)

**Recommended Actions**:
1. Define TracingPolicies for critical security events:
   - Process execution monitoring (privilege escalation attempts)
   - Network connection tracking (egress to suspicious IPs)
   - File access monitoring (sensitive paths like /etc/shadow, /root/.ssh)
2. Configure event filtering (exportAllowList/exportDenyList)
3. Set up Grafana dashboards for Tetragon metrics
4. Define alerting rules for security events

**Timeline**: 2-4 hours (policy definition + testing)

### 7.3 Wazuh Decommissioning (High Complexity)

**Current State**:
- 12 PVCs (151.5Gi storage)
- 3-node OpenSearch cluster (production SIEM data)
- 2 CronJob backups (snapshots + manager configs)
- HTTPRoute, TCPRoute, UDPRoute (external exposure)
- 3 DaemonSet agents on all nodes

**Decommissioning Considerations**:

1. **Data Preservation** (if required):
   - Trigger final opensearch-snapshot before deletion
   - Archive compliance reports (if any)
   - Preserve audit logs per retention policy

2. **Dependency Mapping**:
   - Check if external systems send logs to Wazuh syslog endpoints (TCP/UDP 514)
   - Identify any dashboards or alerts dependent on Wazuh data
   - Verify if compliance reports are required

3. **Replacement Validation**:
   - Ensure Tetragon covers runtime security requirements
   - Confirm Victoria Logs handles syslog ingestion (TCP/UDP 514)
   - Validate Grafana dashboards migrate to Tetragon/Victoria Logs data

4. **Decommissioning Steps**:
   ```bash
   # 1. Suspend agent collection (stop DaemonSet)
   kubectl scale daemonset wazuh-agent -n security --replicas=0

   # 2. Trigger final backup
   kubectl create job -n security manual-snapshot --from=cronjob/opensearch-snapshot
   kubectl create job -n security manual-backup --from=cronjob/wazuh-manager-backup

   # 3. Delete Flux Kustomization (removes all resources)
   kubectl delete kustomization wazuh -n flux-system

   # 4. Archive and delete PVCs (after data export if needed)
   kubectl delete pvc -n security -l app=wazuh-indexer
   kubectl delete pvc -n security -l app=wazuh-manager

   # 5. Remove GitOps configuration
   rm -rf kubernetes/apps/security/wazuh/
   git commit -m "feat(security): decommission Wazuh, migrate to Tetragon"
   ```

**Timeline**: 4-8 hours (with data archival) or 1-2 hours (without data preservation)

**Risks**:
- **Compliance Impact**: If Wazuh provides PCI-DSS/HIPAA/SOC2 reports, replacement must be validated
- **Alert Loss**: 150+ detection rules may need recreation in Tetragon/Grafana
- **Historical Data**: 22 days of indexed security events will be lost unless archived

### 7.4 CrowdSec Evaluation (Medium Complexity)

**Current State**:
- LAPI + agents collecting from Traefik/Grafana
- Enrolled in CrowdSec console (community threat intelligence)
- 10.35Gi storage (nfs-client)

**Evaluation Questions**:
1. Does CrowdSec provide value beyond Tetragon's process/network monitoring?
2. Is community threat intel blocking malicious IPs effectively?
3. Can Tetragon network policies replace CrowdSec IPS functionality?

**Recommendation**:
- **Keep CrowdSec** if intrusion prevention (IP blocking) is required
- **Decommission** if only runtime monitoring is needed (Tetragon covers this)

---

## 8. Resource Usage Summary

### 8.1 Current State (Baseline)

| Namespace | Pods | CPU (Total) | Memory (Total) | Storage (PVCs) |
|-----------|------|-------------|----------------|----------------|
| **monitoring** | 14 | ~130m | ~1.7Gi | 171Gi (6 PVCs) |
| **security** | 12 | ~50m | ~5.1Gi | 151.5Gi (12 PVCs) + 10.35Gi (CrowdSec) |
| **kube-system** (Cilium) | 8 | ~175m | ~740Mi | 0 |
| **kube-system** (Tetragon) | 4 | ~6m | ~258Mi | 0 |
| **TOTAL** | 38 | ~361m | ~7.8Gi | 332.85Gi |

### 8.2 Post-Migration Projection

**If Wazuh is decommissioned**:

| Component | Change | Impact |
|-----------|--------|--------|
| Wazuh Indexers | -3 pods | -4.5Gi RAM, -30m CPU, -150Gi storage |
| Wazuh Managers | -3 pods | -1.1Gi RAM, -12m CPU, -60Gi storage |
| Wazuh Dashboard | -1 pod | -212Mi RAM, -1m CPU, 0 storage |
| Wazuh Agents | -3 pods | -33Mi RAM, -3m CPU, 0 storage |
| Victoria Logs | +1 pod | +200Mi RAM, +10m CPU, +50Gi storage (already allocated) |
| **NET CHANGE** | **-9 pods** | **-5.6Gi RAM, -36m CPU, -160Gi storage** |

**Post-Migration Totals**:
- **Pods**: 29 (-24% reduction)
- **CPU**: ~325m (-10% reduction)
- **Memory**: ~2.2Gi (-72% reduction!)
- **Storage**: 172.85Gi (-48% reduction!)

### 8.3 Node Capacity Headroom

**Current Usage**: 26% average memory utilization
**Post-Migration**: ~15% average memory utilization
**Headroom Gained**: ~11% cluster-wide (3.3Gi freed)

---

## 9. Recommendations

### 9.1 Immediate Actions (Week 1)

1. **Activate Victoria Logs**:
   - Force Flux reconciliation of `victoria-logs` HelmRelease
   - Validate syslog ingestion (TCP/UDP 514)
   - Test Grafana datasource connectivity

2. **Tetragon Policy Development**:
   - Create initial TracingPolicies for:
     - Privilege escalation monitoring
     - Suspicious network connections
     - Sensitive file access
   - Configure Grafana dashboards for Tetragon events

3. **Wazuh Data Audit**:
   - Identify critical compliance reports or alerts
   - Determine if historical data archival is required
   - Create migration plan for detection rules

### 9.2 Migration Phase (Week 2-3)

1. **Parallel Operation**:
   - Run Tetragon + Victoria Logs + Wazuh concurrently for 1 week
   - Validate Tetragon detections vs Wazuh alerts
   - Ensure no detection gaps

2. **CrowdSec Evaluation**:
   - Assess CrowdSec blocked IPs (value analysis)
   - Determine if Tetragon network policies can replace IPS functionality

3. **Gradual Wazuh Shutdown**:
   - Disable Wazuh agents (stop collection)
   - Monitor for any missing detections
   - Archive final snapshots

### 9.3 Post-Migration (Week 4)

1. **Resource Verification**:
   - Confirm 5.6Gi RAM freed
   - Validate Victoria Logs retention (14d) sufficient
   - Monitor Tetragon event volume (rate limit: 1000/sec)

2. **Alert Migration**:
   - Recreate critical Wazuh alerts in Grafana/Alertmanager
   - Test alert delivery (PagerDuty, Slack, etc.)

3. **Documentation Update**:
   - Update CLAUDE.md with new observability stack (Victoria Logs, Tetragon)
   - Remove Wazuh references from architecture documentation
   - Document Tetragon TracingPolicies

---

## 10. Open Questions

1. **Compliance Requirements**: Does this cluster require PCI-DSS, HIPAA, or SOC2 compliance reports that Wazuh currently provides?
2. **Wazuh Historical Data**: Is there a legal or business requirement to preserve 22 days of security event logs?
3. **CrowdSec Value**: Is the community threat intelligence from CrowdSec blocking significant threats, or is it noise?
4. **Victoria Logs Activation**: Why is Victoria Logs HelmRelease not deploying? (Flux reconciliation issue, suspended resource, or configuration error?)
5. **Alert Coverage**: Which Wazuh detection rules are critical and must be recreated in Tetragon/Grafana?

---

## 11. Architecture Diagrams

### 11.1 Current State (Observability)

```
┌─────────────────────────────────────────────────────────────────┐
│                      MONITORING NAMESPACE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐      ┌─────────────┐      ┌─────────────┐       │
│  │ Prometheus│─────▶│   Thanos    │─────▶│   Minio S3  │       │
│  │  (6h ret) │      │(Query/Store)│      │(thanos bucket)      │
│  └──────────┘      └─────────────┘      └─────────────┘       │
│       │                    │                                    │
│       │                    ▼                                    │
│       │              ┌──────────┐                               │
│       └─────────────▶│  Grafana │                               │
│                      │ Operator │                               │
│                      └──────────┘                               │
│                            │                                    │
│                            ▼                                    │
│                ┌─────────────────────────┐                      │
│                │ Victoria Logs (Config)  │ ⚠️ NOT RUNNING       │
│                │ - Grafana datasource ✅ │                      │
│                │ - HelmRelease exists ✅ │                      │
│                │ - Pods deployed      ❌ │                      │
│                └─────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 Current State (Security)

```
┌─────────────────────────────────────────────────────────────────┐
│                       SECURITY NAMESPACE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   WAZUH SIEM STACK                       │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌────────────┐  │   │
│  │  │ OpenSearch   │◀──│ Wazuh Manager│◀──│   Agents   │  │   │
│  │  │ (3 indexers) │   │ (1M + 2W)    │   │(DaemonSet) │  │   │
│  │  │  4.5Gi RAM   │   │  1.1Gi RAM   │   │  33Mi RAM  │  │   │
│  │  │ 150Gi Storage│   │  60Gi Storage│   │            │  │   │
│  │  └──────────────┘   └──────────────┘   └────────────┘  │   │
│  │         │                                                │   │
│  │         ▼                                                │   │
│  │  ┌──────────────┐         ┌─────────────────────┐       │   │
│  │  │   Dashboard  │         │  CronJob Backups    │       │   │
│  │  │   212Mi RAM  │         │(OpenSearch + Manager)│      │   │
│  │  └──────────────┘         └─────────────────────┘       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      CROWDSEC IPS                        │   │
│  │  ┌──────────┐                   ┌──────────┐            │   │
│  │  │   LAPI   │◀─────────────────▶│  Agents  │            │   │
│  │  │ (Enrolled)│                   │(DaemonSet)│            │   │
│  │  └──────────┘                   └──────────┘            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      KUBE-SYSTEM NAMESPACE                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                TETRAGON eBPF (DEPLOYED!)                 │   │
│  │  ┌──────────────┐         ┌──────────────────────┐      │   │
│  │  │  Tetragon    │────────▶│  Prometheus Metrics  │      │   │
│  │  │ (DaemonSet)  │         │  (ServiceMonitor)    │      │   │
│  │  │  258Mi RAM   │         └──────────────────────┘      │   │
│  │  │  Kernel eBPF │                                        │   │
│  │  └──────────────┘                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 11.3 Target State (Post-Migration)

```
┌─────────────────────────────────────────────────────────────────┐
│                      MONITORING NAMESPACE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐      ┌─────────────┐      ┌─────────────┐       │
│  │ Prometheus│─────▶│   Thanos    │─────▶│   Minio S3  │       │
│  │  (6h ret) │      │(Query/Store)│      │(thanos bucket)      │
│  └──────────┘      └─────────────┘      └─────────────┘       │
│       │                    │                                    │
│       │                    ▼                                    │
│       │              ┌──────────┐                               │
│       └─────────────▶│  Grafana │◀────────────────────┐        │
│                      │ Operator │                     │        │
│                      └──────────┘                     │        │
│                            │                          │        │
│                            ▼                          │        │
│                ┌─────────────────────────┐            │        │
│                │  Victoria Logs          │            │        │
│                │  - 14d retention        │────────────┘        │
│                │  - Syslog TCP/UDP :514  │                     │
│                │  - 50Gi storage         │                     │
│                └─────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      KUBE-SYSTEM NAMESPACE                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          TETRAGON eBPF (PRIMARY SECURITY)                │   │
│  │  ┌──────────────┐         ┌──────────────────────┐      │   │
│  │  │  Tetragon    │────────▶│  Grafana Dashboards  │      │   │
│  │  │ (DaemonSet)  │         │  (Security Events)   │      │   │
│  │  │  TracingPolicies:      └──────────────────────┘      │   │
│  │  │  - Privilege Escalation                              │   │
│  │  │  - Network Monitoring                                │   │
│  │  │  - File Access Control                               │   │
│  │  └──────────────┘                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       SECURITY NAMESPACE                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              CROWDSEC IPS (OPTIONAL KEEP)                │   │
│  │  ┌──────────┐                   ┌──────────┐            │   │
│  │  │   LAPI   │◀─────────────────▶│  Agents  │            │   │
│  │  │ (Enrolled)│                   │(DaemonSet)│            │   │
│  │  └──────────┘                   └──────────┘            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ❌ WAZUH DECOMMISSIONED (5.6Gi RAM + 151.5Gi storage freed)   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 12. Key Files for Reference

### 12.1 Monitoring Configuration

```
kubernetes/apps/monitoring/
├── kube-prometheus-stack/app/helmrelease.yaml   # Prometheus + Thanos config
├── thanos/app/helmrelease.yaml                  # Thanos deployment settings
├── victoria-logs/app/helmrelease.yaml           # Victoria Logs (not running)
├── grafana/instance/grafanadatasource.yaml      # Grafana datasources
└── grafana/operator/helmrelease.yaml            # Grafana Operator

Secret: thanos-objstore-config (monitoring namespace) # S3 credentials
```

### 12.2 Security Configuration

```
kubernetes/apps/security/
├── wazuh/app/indexer_stack/                     # Wazuh OpenSearch cluster
├── wazuh/app/wazuh_managers/                    # Wazuh manager StatefulSets
├── wazuh/app/wazuh-agent.yaml                   # Wazuh agent DaemonSet
└── crowdsec/app/helmrelease.yaml                # CrowdSec configuration

kubernetes/apps/kube-system/
└── tetragon/app/helmrelease.yaml                # Tetragon eBPF configuration
```

---

## Appendix A: Useful Commands

### A.1 Monitoring

```bash
# Check Prometheus targets
kubectl port-forward -n monitoring svc/prometheus-prometheus 9090:9090 --context home
# Visit: http://localhost:9090/targets

# Check Thanos Query
kubectl port-forward -n monitoring svc/thanos-query 9090:10901 --context home

# Force Victoria Logs reconciliation
flux reconcile helmrelease victoria-logs -n monitoring

# View Grafana datasources
kubectl get grafanadatasource -n monitoring --context home
```

### A.2 Security

```bash
# Wazuh dashboard access
kubectl port-forward -n security svc/wazuh-dashboard 8443:443 --context home
# Visit: https://localhost:8443

# Tetragon live events
kubectl exec -n kube-system ds/tetragon -c tetragon -- tetra getevents -o compact --context home

# CrowdSec decisions (blocked IPs)
kubectl exec -n security deploy/crowdsec-lapi -- cscli decisions list --context home
```

### A.3 Resource Monitoring

```bash
# Top pods by memory
kubectl top pods -A --context home --sort-by=memory | head -20

# Storage usage
kubectl get pvc -A --context home -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,SIZE:.status.capacity.storage,STORAGECLASS:.spec.storageClassName

# Node resource usage
kubectl top nodes --context home
```

---

**End of Report**
