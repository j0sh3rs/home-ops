# VictoriaLogs Phase 2 Deployment - Handoff Document

**Date**: 2026-01-05
**Session**: platform-evolution
**Phase**: Phase 2 - VictoriaLogs Implementation (Partial)
**Status**: Deployment Complete, External Syslog Testing Pending

## Executive Summary

VictoriaLogs has been successfully deployed and integrated with the home-ops cluster. The service is operational with:

- ✅ Pod running (victoria-logs-server-0) with 1/1 Ready status
- ✅ HTTP API available at http://victoria-logs-server.monitoring.svc.cluster.local:9428
- ✅ Syslog TCP/UDP listeners active on port 514
- ✅ Grafana datasource configured and synchronized
- ✅ 14-day retention period configured
- ✅ 50Gi OpenEBS LocalPV storage provisioned
- ⏳ External syslog testing pending (UDM Pro / Synology NAS)

## What Was Accomplished

### 1. Configuration Changes

**File: kubernetes/apps/monitoring/kustomization.yaml**
- Uncommented `./victoria-logs/ks.yaml` to enable VictoriaLogs deployment

**File: kubernetes/apps/monitoring/victoria-logs/app/helmrelease.yaml**
- Added `NET_BIND_SERVICE` capability for privileged port 514 binding
- Configured both TCP and UDP syslog service ports (514)
- Fixed targetPort from named port to numeric port (514)

**File: thoughts/ledgers/CONTINUITY_CLAUDE-platform-evolution.md**
- Updated Phase 1 research tasks as complete
- Updated Open Questions with confirmed answers
- Changed status from "Phase 1 Research" to "Phase 2 Implementation"

### 2. Deployment Verification

**Flux Reconciliation**:
```bash
flux-system/flux-system: e37dba7bb85f8063e89e7d0534b12302273c2677
cluster-apps: Applied revision refs/heads/main@sha1:e37dba7bb85f8063e89e7d0534b12302273c2677
victoria-logs Kustomization: ReconciliationSucceeded
```

**HelmRelease Status**:
```
NAME            AGE   READY   STATUS
victoria-logs   52s   True    Helm install succeeded for release monitoring/victoria-logs.v1
```

**Pod Status**:
```
NAME                       READY   STATUS    AGE
victoria-logs-server-0     1/1     Running   56s
```

**Service Configuration**:
- ClusterIP: None (Headless for StatefulSet)
- Ports: 9428/http, 514/syslog-tcp, 514/syslog-udp

### 3. Grafana Integration

**Datasource Configuration**:
- Name: victoria-logs
- Type: victoriametrics-logs-datasource (v0.22.0)
- URL: http://victoria-logs-server.monitoring.svc.cluster.local:9428
- Status: "Datasource was successfully applied to 1 instances"
- LogsQL Enabled: true
- Max Lines: 1000

### 4. VictoriaLogs Startup Logs

```json
{"ts":"2026-01-05T14:50:06.283Z","level":"info","msg":"started accepting syslog messages at -syslog.listenAddr.udp=\":514\""}
{"ts":"2026-01-05T14:50:06.285Z","level":"info","msg":"started accepting syslog messages at -syslog.listenAddr.tcp=\":514\""}
{"ts":"2026-01-05T14:50:06.285Z","level":"info","msg":"started server at http://0.0.0.0:9428/"}
```

**Storage Metrics**:
- Opened successfully in 0.021 seconds
- Existing data: 528,991 rows (11.15 MB) from previous deployment attempts
- Storage path: /storage (mounted on OpenEBS LocalPV)

## Configuration Details

### VictoriaLogs HelmRelease Values

```yaml
server:
  extraArgs:
    envflag.enable: true
    envflag.prefix: VM_
    loggerFormat: json
    httpListenAddr: :9428
    http.shutdownDelay: 15s
    syslog.listenAddr.tcp: ":514"
    syslog.listenAddr.udp: ":514"
    syslog.timezone: "America/New_York"

  securityContext:
    capabilities:
      add:
        - NET_BIND_SERVICE  # Required for port <1024

  persistentVolume:
    enabled: true
    storageClassName: openebs-hostpath
    size: 50Gi

  retentionPeriod: 14d

  service:
    extraPorts:
      - name: syslog-tcp
        port: 514
        targetPort: 514
        protocol: TCP
      - name: syslog-udp
        port: 514
        targetPort: 514
        protocol: UDP

  serviceMonitor:
    enabled: true  # Prometheus monitoring

dashboards:
  enabled: true
```

### Network Access

**Internal Cluster Access**:
- HTTP API: `victoria-logs-server.monitoring.svc.cluster.local:9428`
- Syslog TCP: `victoria-logs-server.monitoring.svc.cluster.local:514`
- Syslog UDP: `victoria-logs-server.monitoring.svc.cluster.local:514`

**External Access (Gateway Route)**:
- UI: `https://logs.68cc.io` (redirects to `/select/vmui/`)
- Gateway: `envoy-internal` in `network` namespace

## Next Steps: External Syslog Testing

### Testing Overview

VictoriaLogs is now ready to accept external syslog messages from network devices. The following devices should be configured to forward syslog:

1. **UniFi Dream Machine Pro (UDM Pro)**
2. **Synology NAS**

### Testing Procedure

#### Option 1: Test from Local Machine

```bash
# Test UDP syslog
echo '<14>1 2026-01-05T15:00:00.000Z test-host test-app - - - Test UDP message' | \
  nc -u victoria-logs-server.monitoring.svc.cluster.local 514

# Test TCP syslog
echo '<14>1 2026-01-05T15:00:00.000Z test-host test-app - - - Test TCP message' | \
  nc victoria-logs-server.monitoring.svc.cluster.local 514
```

#### Option 2: Configure UDM Pro

**UniFi Controller → Settings → System Settings → Remote Logging**:
1. Enable Remote Logging
2. Server: `<KUBERNETES_NODE_IP>` or `<LOAD_BALANCER_IP>`
3. Port: 514
4. Protocol: UDP (primary) or TCP
5. Format: RFC 5424 (modern) or RFC 3164 (BSD)

**Important**: You'll need to expose the syslog service externally, either via:
- LoadBalancer service type with MetalLB
- NodePort service
- Dedicated ingress for syslog (not recommended for UDP)

#### Option 3: Configure Synology NAS

**Synology DSM → Control Panel → Log Center → Archive Settings**:
1. Enable "Transfer logs to a syslog server"
2. Server name: `<KUBERNETES_NODE_IP>`
3. Port: 514
4. Protocol: TCP or UDP
5. Format: BSD or IETF

### Service Exposure Options

**Current State**: Service is ClusterIP (internal only)

**Recommended Approach - NodePort**:
```yaml
# Add to kubernetes/apps/monitoring/victoria-logs/app/helmrelease.yaml
server:
  service:
    type: NodePort
    nodePort: 30514  # External port on cluster nodes
```

**Alternative - LoadBalancer** (requires MetalLB):
```yaml
server:
  service:
    type: LoadBalancer
    loadBalancerIP: <RESERVED_IP>
```

### Verification Commands

```bash
# Check if syslog messages are being received
kubectl logs victoria-logs-server-0 -n monitoring --context home -f | grep syslog

# Query received syslog messages via LogsQL
curl -s "http://victoria-logs-server.monitoring.svc.cluster.local:9428/select/logsql/query" \
  -d 'query={_stream="syslog"}' | jq

# Check ingestion stats
curl -s "http://victoria-logs-server.monitoring.svc.cluster.local:9428/metrics" | grep syslog
```

### Expected Behavior

Once external devices are configured:
1. Syslog messages arrive at NodePort 30514 (or LoadBalancer IP)
2. VictoriaLogs ingests messages with automatic field parsing
3. Messages queryable via LogsQL in Grafana
4. Logs visible in VictoriaLogs UI at `https://logs.68cc.io`

### Troubleshooting

**If messages aren't arriving**:
```bash
# Verify service is listening
kubectl exec -it victoria-logs-server-0 -n monitoring --context home -- netstat -tuln | grep 514

# Check for firewall rules blocking UDP/514
# Check if NodePort service is accessible from external device
telnet <NODE_IP> 30514

# Review VictoriaLogs logs for ingestion errors
kubectl logs victoria-logs-server-0 -n monitoring --context home --tail=100
```

## Phase 2 Completion Checklist

- [x] Deploy VictoriaLogs to cluster
- [x] Configure syslog listeners (TCP/UDP 514)
- [x] Verify Grafana datasource integration
- [ ] Expose syslog service externally (NodePort or LoadBalancer)
- [ ] Configure UDM Pro syslog forwarding
- [ ] Configure Synology NAS syslog forwarding
- [ ] Verify external syslog ingestion
- [ ] Create initial Grafana dashboards with LogsQL queries
- [ ] Document query patterns for common use cases

## Phase 3 Preview: Observability Consolidation

Once external syslog is validated, the next phase will focus on:

1. **Dashboard Migration**:
   - Identify any critical Loki dashboards (if they exist)
   - Recreate dashboards using LogsQL syntax
   - Import upstream VictoriaLogs community dashboards

2. **Tetragon Integration**:
   - Configure Tetragon events to forward to VictoriaLogs
   - Create security event dashboards
   - Define Alertmanager rules for security violations

3. **Loki Deprecation** (if applicable):
   - Parallel operation period (2 weeks)
   - Validate query parity and performance
   - Remove Loki StatefulSet and PVCs

## Key Decisions Made

1. **No S3 Backend**: Accepted 14-day retention with OpenEBS LocalPV + Velero snapshots workaround
2. **Syslog Port 514**: Using standard privileged port with NET_BIND_SERVICE capability
3. **Service Type**: ClusterIP initially, NodePort required for external access
4. **Retention Period**: 14 days balances storage constraints with operational needs

## References

- Research Document: `claudedocs/victorialogs-tetragon-research.md`
- Current State Analysis: `claudedocs/platform-evolution-current-state.md`
- Continuity Ledger: `thoughts/ledgers/CONTINUITY_CLAUDE-platform-evolution.md`
- VictoriaLogs Documentation: https://docs.victoriametrics.com/victorialogs/
- Syslog RFC 5424: https://datatracker.ietf.org/doc/html/rfc5424

## Git Commit Reference

```
commit e37dba7bb85f8063e89e7d0534b12302273c2677
Author: josh.simmonds
Date:   2026-01-05

feat(victoria-logs): enable VictoriaLogs with syslog support

- Enable victoria-logs deployment in monitoring kustomization
- Add NET_BIND_SERVICE capability for privileged port binding
- Configure both TCP and UDP syslog listeners on port 514
- Update continuity ledger with Phase 1 research completion
```

## Contact & Escalation

**For Questions**:
- Review research findings in `claudedocs/victorialogs-tetragon-research.md`
- Check VictoriaLogs official documentation for LogsQL syntax
- Consult continuity ledger for strategic context

**Escalation Scenarios**:
- External syslog devices cannot reach cluster (networking/firewall issue)
- VictoriaLogs pod crashlooping (check resource limits, storage)
- Grafana datasource not showing data (verify service connectivity)
- LogsQL queries not returning expected results (syntax/field mapping)
