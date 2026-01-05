# Tetragon Runtime Security Deployment

**Date**: 2026-01-05
**Phase**: Phase 4 - Tetragon Deployment
**Status**: Deployment Complete - Testing Pending

## Overview

This document covers the deployment of Tetragon v1.6.0 for eBPF-based runtime security monitoring on the home-lab Kubernetes cluster. Tetragon provides security observability by monitoring system calls, file access, network connections, and privilege escalation attempts.

## Architecture

### Components

- **Tetragon Agent**: DaemonSet running on each node with eBPF programs for security monitoring
- **Tetragon Operator**: Manages TracingPolicy CRDs and policy lifecycle
- **ServiceMonitor**: Prometheus metrics scraping for observability integration
- **TracingPolicies**: Security policies defining what events to monitor

### Integration Points

- **Prometheus**: Metrics collection via ServiceMonitor (port 2112)
- **Grafana**: Visualization via custom Tetragon dashboard
- **VictoriaLogs**: Future integration for security event logs
- **Alertmanager**: Future integration for security alerts

## Deployment Structure

```
kubernetes/apps/security/tetragon/
├── ks.yaml                                    # Flux Kustomization entry point
└── app/
    ├── kustomization.yaml                     # Resource list
    ├── helmrelease.yaml                       # Helm chart configuration
    ├── tracingpolicy-sensitive-files.yaml     # Monitor /etc/shadow, SSH keys, K8s secrets
    ├── tracingpolicy-network-egress.yaml      # Monitor network connections
    └── tracingpolicy-privilege-escalation.yaml # Monitor setuid/setgid to root
```

## Configuration Details

### Tetragon Agent (helmrelease.yaml)

**Resource Allocation** (home-lab optimized):
```yaml
resources:
  requests:
    cpu: 10m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

**Security Context**:
```yaml
securityContext:
  privileged: true  # Required for loading eBPF programs
```

**Host Network**:
```yaml
hostNetwork: true  # Required for process visibility across host namespaces
```

**Event Export Configuration**:
```yaml
exportFilename: tetragon.log
exportFilePerm: "600"
exportFileMaxSizeMB: 10
exportFileMaxBackups: 5

exportAllowList: |-
  {"event_set":["PROCESS_EXEC", "PROCESS_EXIT", "PROCESS_KPROBE", "PROCESS_TRACEPOINT", "PROCESS_LSM"]}

exportDenyList: |-
  {"health_check":true}
  {"namespace":["", "cilium", "kube-system", "flux-system"]}
```

**Prometheus Integration**:
```yaml
prometheus:
  enabled: true
  port: 2112
  metricsLabelFilter: "namespace,workload,pod,binary"
  serviceMonitor:
    enabled: true
    labelsOverride:
      prometheus.io/operator: kube-prometheus-stack
    scrapeInterval: 60s
```

### Tetragon Operator (helmrelease.yaml)

**Resource Allocation**:
```yaml
tetragonOperator:
  enabled: true
  replicas: 1
  resources:
    requests:
      cpu: 10m
      memory: 64Mi
    limits:
      cpu: 500m
      memory: 128Mi

  tracingPolicy:
    enabled: true  # Enables TracingPolicy CRD management
```

## TracingPolicy Resources

### 1. Sensitive File Access Monitoring

**File**: `tracingpolicy-sensitive-files.yaml`
**Purpose**: Detect unauthorized access to sensitive files

**Monitored Files**:
- `/etc/shadow` - User password hashes
- `/etc/passwd` - User account information
- `/etc/sudoers` - Sudo privilege configuration
- `/root/.ssh` - Root SSH keys
- `/home/*/.ssh/id_*` - User SSH private keys
- `/var/run/secrets/kubernetes.io` - Kubernetes service account tokens

**eBPF Hook**:
```yaml
kprobes:
  - call: "security_file_open"
    syscall: false
    args:
      - index: 0
        type: "file"
```

**Action**: `Post` - Log event when file is accessed

### 2. Network Egress Monitoring

**File**: `tracingpolicy-network-egress.yaml`
**Purpose**: Detect unexpected network connections from pods

**Monitored Connections**:
- All TCP connections to any destination (0.0.0.0/0)

**eBPF Hook**:
```yaml
kprobes:
  - call: "tcp_connect"
    syscall: false
    args:
      - index: 0
        type: "sock"
```

**Action**: `Post` - Log event when TCP connection is initiated

**Use Cases**:
- Detect data exfiltration attempts
- Identify unexpected external dependencies
- Monitor for command-and-control (C2) communication

### 3. Privilege Escalation Monitoring

**File**: `tracingpolicy-privilege-escalation.yaml`
**Purpose**: Detect attempts to escalate privileges to root (UID/GID 0)

**Monitored System Calls**:
- `sys_setuid(0)` - Set user ID to root
- `sys_setgid(0)` - Set group ID to root

**eBPF Hooks**:
```yaml
kprobes:
  - call: "sys_setuid"
    syscall: true
  - call: "sys_setgid"
    syscall: true
```

**Action**: `Post` - Log event when process attempts to become root

**Use Cases**:
- Detect privilege escalation exploits
- Monitor for container breakout attempts
- Identify unauthorized privilege changes

## Deployment Procedures

### Initial Deployment

1. **Commit Changes**:
```bash
git add kubernetes/apps/security/tetragon/
git add kubernetes/apps/security/kustomization.yaml
git add kubernetes/flux/meta/repos/cilium.yaml
git add kubernetes/flux/meta/repos/kustomization.yaml
git commit -m "feat(security): add Tetragon v1.6.0 runtime security monitoring"
git push
```

2. **Force Flux Reconciliation**:
```bash
# Reconcile Helm repository
flux reconcile source helm cilium --context home

# Reconcile Tetragon deployment
flux reconcile kustomization tetragon --context home
```

3. **Verify Deployment**:
```bash
# Check DaemonSet status
kubectl get daemonset -n security --context home | grep tetragon

# Check pod status (should be 1 pod per node)
kubectl get pods -n security -l app.kubernetes.io/name=tetragon --context home

# Check Tetragon Operator
kubectl get deployment -n security --context home | grep tetragon-operator
```

4. **Verify TracingPolicies**:
```bash
# List TracingPolicy CRDs
kubectl get tracingpolicies -n security --context home

# Expected output:
# NAME                              AGE
# monitor-sensitive-files          Xm
# monitor-network-egress           Xm
# monitor-privilege-escalation     Xm
```

5. **Verify Prometheus Integration**:
```bash
# Check ServiceMonitor
kubectl get servicemonitor -n security --context home

# Check if Prometheus is scraping Tetragon metrics
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 --context home
# Visit http://localhost:9090 and query: tetragon_events_total
```

## Monitoring and Observability

### Prometheus Metrics

**Key Metrics Exposed**:
- `tetragon_events_total` - Total security events by type
- `tetragon_policy_events_total` - Events matched by TracingPolicy
- `tetragon_syscalls_total` - System calls monitored
- `tetragon_errors_total` - Tetragon errors by type
- `tetragon_process_cache_size` - Current process cache size
- `tetragon_memory_usage_bytes` - Tetragon memory consumption
- `tetragon_goroutines` - Active goroutines in Tetragon agent

**Query Examples**:
```promql
# Event rate by type (last 5 minutes)
rate(tetragon_events_total[5m])

# Events by namespace
sum(rate(tetragon_events_total[5m])) by (namespace)

# Policy match rate
rate(tetragon_policy_events_total[5m])

# Syscall monitoring rate by binary
sum(rate(tetragon_syscalls_total[5m])) by (binary)
```

### Grafana Dashboard

**Location**: `kubernetes/apps/monitoring/grafana/dashboards/app/tetragon-dashboard.json`

**Panels**:
1. **Events Rate by Type** - Line graph of security events over time
2. **Error Rate** - Tetragon internal errors
3. **Active Tracing Policies** - Number of enabled policies
4. **Policy Events** - Events matched by specific policies
5. **Memory Usage** - Tetragon agent memory consumption
6. **Goroutines** - Tetragon agent goroutine count
7. **Syscalls Rate by Binary** - Top processes generating syscall events
8. **CPU Usage** - Tetragon agent CPU utilization

### Event Logs

**Export Configuration**:
- **Format**: JSON logs written to `/var/run/tetragon/tetragon.log`
- **Rotation**: 10MB max size, 5 backups retained
- **Permissions**: 600 (root only)

**Log Access**:
```bash
# View Tetragon events from a specific pod
kubectl exec -n security tetragon-xxxxx --context home -- cat /var/run/tetragon/tetragon.log | jq

# Stream events in real-time
kubectl exec -n security tetragon-xxxxx --context home -- tail -f /var/run/tetragon/tetragon.log | jq
```

**Future Integration**: Events will be forwarded to VictoriaLogs for centralized logging and long-term retention.

## Troubleshooting

### Pod Not Starting

**Check Events**:
```bash
kubectl describe pod -n security -l app.kubernetes.io/name=tetragon --context home
```

**Common Issues**:
- **eBPF not supported**: Verify Talos kernel version supports eBPF (kernel 6.18.1+ confirmed)
- **Privileged security context denied**: Ensure PSP/PSA allows privileged containers
- **Host network conflict**: Check for port 2112 conflicts on nodes

### No Metrics in Prometheus

**Verify ServiceMonitor**:
```bash
kubectl get servicemonitor -n security tetragon --context home -o yaml
```

**Check Prometheus Target**:
```bash
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 --context home
# Visit http://localhost:9090/targets and search for "tetragon"
```

**Common Issues**:
- ServiceMonitor label selector mismatch
- Prometheus RBAC missing for security namespace
- Network policy blocking scraping

### TracingPolicy Not Working

**Check Policy Status**:
```bash
kubectl get tracingpolicy -n security monitor-sensitive-files --context home -o yaml
```

**Verify Events Generated**:
```bash
# Test sensitive file access
kubectl exec -n security tetragon-xxxxx --context home -- cat /etc/shadow

# Check for event in logs
kubectl logs -n security tetragon-xxxxx --context home | grep security_file_open
```

**Common Issues**:
- Policy selector too restrictive
- eBPF program compilation failed
- Kernel version missing required hooks

### High Memory Usage

**Check Process Cache Size**:
```bash
kubectl exec -n security tetragon-xxxxx --context home -- tetra status
```

**Tuning Options** (edit helmrelease.yaml):
```yaml
tetragon:
  processCacheSize: 32768  # Reduce from 65536 if memory constrained
```

### Too Many Events (False Positives)

**Adjust Export Filters** (edit helmrelease.yaml):

Add more namespaces to denyList:
```yaml
exportDenyList: |-
  {"health_check":true}
  {"namespace":["", "cilium", "kube-system", "flux-system", "monitoring", "cert-manager"]}
```

Add specific binaries to denyList:
```yaml
exportDenyList: |-
  {"binary":["systemd", "containerd", "runc"]}
```

## Security Considerations

### Privileged Containers

Tetragon requires privileged containers to load eBPF programs. This is necessary for runtime security monitoring but increases attack surface.

**Mitigations**:
- Tetragon pods run in dedicated `security` namespace
- eBPF programs provide read-only visibility (observability mode)
- Tetragon itself is monitored via Prometheus metrics
- Regular updates from Cilium security team

### Host Network Access

Tetragon runs on host network for process visibility across all network namespaces.

**Implications**:
- Tetragon can see all network traffic on the node
- Port 2112 exposed on all nodes for metrics
- Network policies should exclude Tetragon pods

### Event Data Sensitivity

Tetragon events may contain sensitive information (file paths, command arguments, network destinations).

**Best Practices**:
- Event logs restricted to root (600 permissions)
- VictoriaLogs access controlled via RBAC
- Event retention limited to 14 days
- Consider redaction for highly sensitive environments

## Future Enhancements

### Phase 4 Completion Tasks
- [ ] Deploy to cluster and verify pod startup
- [ ] Test event generation for each TracingPolicy
- [ ] Validate Prometheus metrics collection
- [ ] Review Grafana dashboard with real data

### VictoriaLogs Integration (Phase 5)
- [ ] Configure Tetragon to export JSON events to stdout
- [ ] Deploy Fluent Bit or Vector to collect Tetragon pod logs
- [ ] Forward events to VictoriaLogs via syslog or HTTP
- [ ] Create VictoriaLogs queries for security event analysis
- [ ] Build Grafana panels using VictoriaLogs datasource

### Alertmanager Integration (Phase 5)
- [ ] Define PrometheusRule for critical security events
  - Sensitive file access rate > threshold
  - Privilege escalation attempts
  - Unexpected network egress
- [ ] Configure alert severity and grouping
- [ ] Test Discord notification delivery
- [ ] Document alert triage procedures

### Policy Tuning
- [ ] Monitor false positive rate for 1 week
- [ ] Refine exportDenyList based on observed noise
- [ ] Add namespace-specific policies
- [ ] Create policies for container runtime monitoring
- [ ] Add policies for kernel module loading

### Advanced Policies
- [ ] Container escape detection (mount namespace changes)
- [ ] Cryptocurrency mining detection (process patterns)
- [ ] Reverse shell detection (network patterns)
- [ ] Credential harvesting detection (memory access patterns)

## References

- **Tetragon Documentation**: https://tetragon.io/docs/
- **TracingPolicy Examples**: https://github.com/cilium/tetragon/tree/main/examples/tracingpolicy
- **Helm Chart Values**: https://github.com/cilium/tetragon/blob/main/install/kubernetes/tetragon/values.yaml
- **eBPF Security**: https://ebpf.io/
- **Cilium Community**: https://cilium.io/slack

## Deployment Summary

**Tetragon v1.6.0 Deployment**:
- ✅ Cilium Helm repository added to Flux
- ✅ HelmRelease configured with home-lab optimized resources
- ✅ ServiceMonitor enabled for Prometheus integration
- ✅ Three initial TracingPolicies created
- ✅ Grafana dashboard provisioned
- ⏳ Deployment testing pending
- ⏳ VictoriaLogs integration pending (Phase 5)
- ⏳ Alertmanager rules pending (Phase 5)

**Next Steps**: Deploy to cluster and validate event generation.
