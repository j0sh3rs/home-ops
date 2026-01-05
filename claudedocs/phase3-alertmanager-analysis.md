# Phase 3: Alertmanager Analysis and Configuration

**Date**: 2026-01-05
**Session**: platform-evolution
**Phase**: Phase 3 - Alerting & Dashboards

## Executive Summary

Alertmanager is deployed via kube-prometheus-stack with Discord integration already configured. Comprehensive infrastructure monitoring alerts exist for Kubernetes components. New alert rules needed for VictoriaLogs service health and preparation for Tetragon security alerts (Phase 4).

## Current Alertmanager Configuration

### Deployment Status

```
Pod: alertmanager-prometheus-0 (2/2 Running)
Age: 17 days
Namespace: monitoring
Chart: kube-prometheus-stack 80.11.0
```

### Discord Integration

**Status**: ✅ Configured and Active

- **Receiver**: `discord` configured in AlertmanagerConfig
- **Webhook Secret**: `alertmanager-secret` in monitoring namespace
- **Routing**: Critical alerts → Discord, Watchdog/InfoInhibitor → blackhole
- **Group Settings**:
  - Group by: alertname, cluster, job
  - Group wait: 1m
  - Group interval: 5m
  - Repeat interval: 12h

### Existing Alert Rules (35 PrometheusRules)

#### Infrastructure Health Alerts (Already Configured)

**Kubernetes Apps** (`prometheus-kubernetes-apps`):
- KubePodCrashLooping - Pod crash loop detection
- KubePodNotReady - Pod not ready >15 minutes
- KubeDeploymentReplicasMismatch - Deployment replica issues
- KubeDeploymentRolloutStuck - Stuck deployments
- KubeStatefulSetReplicasMismatch - StatefulSet issues
- KubeStatefulSetUpdateNotRolledOut - StatefulSet rollout issues
- KubeDaemonSetRolloutStuck - DaemonSet issues
- KubeContainerWaiting - Container waiting >1 hour
- KubeJobFailed - Job failure detection
- KubeHpaReplicasMismatch - HPA scaling issues

**Storage** (`prometheus-kubernetes-storage`):
- KubePersistentVolumeFillingUp - PVC capacity monitoring
- (Additional storage alerts for volume claim issues)

**System Components**:
- prometheus-kube-apiserver-availability.rules
- prometheus-kube-apiserver-slos
- prometheus-kube-scheduler.rules
- prometheus-kubelet.rules
- prometheus-kubernetes-system
- prometheus-kubernetes-system-controller-manager

**Node Monitoring**:
- prometheus-node-exporter.rules
- prometheus-node-network
- prometheus-node.rules

**Custom Alerts** (`additionalPrometheusRulesMap`):
- **OomKilled**: Container OOM detection (>1 restart in 10min)
- **DockerhubRateLimitRisk**: Container image pull rate limit warning (>100 containers)

### Alert Routing Configuration

```yaml
route:
  receiver: discord
  groupBy: [alertname, cluster, job]
  routes:
    - matchers:
        - {alertname: Watchdog}
      receiver: blackhole
    - matchers:
        - {alertname: InfoInhibitor}
      receiver: blackhole
    - matchers:
        - {severity: critical}
      receiver: discord
```

**Inhibit Rules**:
- Critical alerts suppress warning alerts for same alertname/namespace

## Gap Analysis: Missing Alert Rules

### 1. VictoriaLogs Service Health (NEW - Required)

**Alert: VictoriaLogsDown**
- **Description**: VictoriaLogs pod is not running
- **Severity**: critical
- **Impact**: Log ingestion stopped, syslog data loss

**Alert: VictoriaLogsSyslogReceiverDown**
- **Description**: Syslog TCP/UDP receivers not accepting connections
- **Severity**: critical
- **Impact**: External syslog sources cannot send logs

**Alert: VictoriaLogsHighMemoryUsage**
- **Description**: VictoriaLogs memory usage >1.5Gi (approaching 2Gi limit)
- **Severity**: warning
- **Impact**: Risk of OOMKill

**Alert: VictoriaLogsPVCFillingUp**
- **Description**: VictoriaLogs PVC >80% full (>40Gi of 50Gi)
- **Severity**: warning
- **Impact**: Log retention may need adjustment, disk space exhaustion risk

**Alert: VictoriaLogsNoRecentLogs**
- **Description**: No logs ingested in last 10 minutes
- **Severity**: warning
- **Impact**: Possible syslog source issue or ingestion problem

### 2. Security Event Alerts (Preparation for Phase 4)

**Note**: These will be fully implemented when Tetragon is deployed (Phase 4). Creating placeholder structure now.

**Alert Template Structure**:
```yaml
- alert: TetragonSuspiciousActivity
  expr: tetragon_suspicious_events_total > 0
  labels:
    severity: critical
  annotations:
    summary: Suspicious activity detected on {{ $labels.node }}
```

**Planned Security Alerts** (Phase 4):
- TetragonSensitiveFileAccess - Unauthorized /etc/shadow, /etc/passwd access
- TetragonPrivilegeEscalation - Unexpected privilege escalation attempts
- TetragonNetworkEgress - Unexpected external network connections
- TetragonProcessExecution - Suspicious process execution patterns

### 3. Observability Stack Integration

**Alert: GrafanaDatasourceDown**
- **Description**: Grafana cannot reach VictoriaLogs datasource
- **Severity**: warning
- **Impact**: VictoriaLogs dashboards non-functional

## Recommendations

### Immediate Actions (This Session)

1. **Create VictoriaLogs Health PrometheusRule**:
   - Add to `kubernetes/apps/monitoring/victoria-logs/app/`
   - Include service availability, memory, storage, ingestion alerts
   - Set appropriate thresholds for home-lab scale

2. **Test Alert Delivery**:
   - Trigger test alert to verify Discord webhook functionality
   - Validate alert formatting and notification content

3. **Document Alert Philosophy**:
   - Define severity levels (critical vs warning)
   - Establish on-call expectations (home-lab context)
   - Create alert response playbooks

### Phase 4 Preparation

1. **Create Tetragon Alert Rule Template**:
   - Prepare structure for security event alerts
   - Define baseline behavioral policies
   - Establish security alert severity matrix

### Future Enhancements

1. **Log-Based Alerting** (VictoriaLogs vmalert integration):
   - Consider VictoriaLogs log pattern alerts
   - Example: Alert on specific error patterns in logs
   - Requires vmalert deployment or LogsQL alert rules

2. **Alert Optimization**:
   - Review alert noise vs signal ratio after 1 month
   - Tune thresholds based on actual cluster behavior
   - Consider alert aggregation for related issues

## Implementation Plan

### Task 1: Create VictoriaLogs PrometheusRule

**File**: `kubernetes/apps/monitoring/victoria-logs/app/prometheusrule.yaml`

**Content Structure**:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: victoria-logs-alerts
  namespace: monitoring
spec:
  groups:
    - name: victorialogs
      rules:
        - alert: VictoriaLogsDown
        - alert: VictoriaLogsSyslogReceiverDown
        - alert: VictoriaLogsHighMemoryUsage
        - alert: VictoriaLogsPVCFillingUp
        - alert: VictoriaLogsNoRecentLogs
```

**Kustomization Update**: Add prometheusrule.yaml to resources list

### Task 2: Test Alert Delivery

**Method**: Port-forward to Prometheus and create test alert
```bash
kubectl port-forward -n monitoring svc/prometheus-prometheus 9090:9090 --context home
# Manually trigger test alert via Prometheus UI
```

**Verification**:
- Discord channel receives test alert
- Alert formatting is clear and actionable
- Alert includes relevant labels and annotations

### Task 3: Documentation

**Create**: Alert Response Guide
- Document what each alert means
- Define response steps for each alert
- Include query commands for investigation

## Success Criteria

- ✅ Discord integration verified functional
- ✅ Comprehensive Kubernetes infrastructure alerts exist
- ⏳ VictoriaLogs service health alerts created
- ⏳ Alert delivery tested and verified
- ⏳ Alert response documentation created
- 🔜 Tetragon alert templates prepared (Phase 4)

## Architecture Context

### Observability Stack Integration

```
Prometheus → Scrapes metrics from:
  - VictoriaLogs StatefulSet
  - kube-state-metrics
  - node-exporter
  ↓
PrometheusRules → Evaluate alert conditions
  ↓
Alertmanager → Routes alerts to:
  - Discord (critical)
  - Blackhole (noise reduction)
  ↓
Discord Webhook → Notification delivery
```

### VictoriaLogs Monitoring Points

```
victoria-logs-server-0 Pod:
  - Container metrics: CPU, memory, restarts
  - ServiceMonitor: victorialogs_* metrics
  - PVC metrics: storage capacity, usage
  - Syslog receiver: port 514 TCP/UDP availability
  - Log ingestion rate: logs/second metric
```

## Related Documentation

- VictoriaLogs deployment: `claudedocs/victorialogs-phase2-deployment-handoff.md`
- Phase 2/3 completion: `claudedocs/victorialogs-phase2-3-completion-summary.md`
- External syslog validation: `claudedocs/victorialogs-phase2-external-syslog-validation.md`
- Continuity ledger: `thoughts/ledgers/CONTINUITY_CLAUDE-platform-evolution.md`

## Next Steps

1. Implement VictoriaLogs PrometheusRule (current task)
2. Test alert delivery via Discord
3. Move to dashboard standardization (remaining Phase 3 work)
4. Decide on in-cluster log collection strategy
