# VictoriaLogs Phase 2: External Syslog Validation Guide

**Date**: 2026-01-05
**Session**: platform-evolution
**Phase**: Phase 2 - External Syslog Validation
**Status**: Infrastructure deployed, ready for device testing

## Deployment Summary

VictoriaLogs external syslog infrastructure is fully deployed and operational:

- **Gateway IP**: `192.168.35.15`
- **Gateway Hostname**: `internal.68cc.io`
- **Protocols**: TCP port 514, UDP port 514
- **Format Support**: RFC 5424 (structured syslog), RFC 3164 (BSD syslog)
- **Timezone**: America/New_York
- **Pod Status**: `victoria-logs-server-0` (Running 1/1, accepting syslog messages)
- **Routes**: TCPRoute and UDPRoute both in "Accepted" and "ResolvedRefs" status
- **Commit**: `5e4eac0565e90b7dc4547f6e3d91d8fe55522bd8`

## Testing Checklist

### Pre-Validation Verification

Before configuring external devices, verify the infrastructure is ready:

```bash
# 1. Confirm VictoriaLogs pod is running and accepting syslog
kubectl logs -n monitoring victoria-logs-server-0 --context home | grep -i syslog

# Expected output:
# INFO    VictoriaLogs/lib/logstorage/syslog.go:XXX started accepting syslog messages at -syslog.listenAddr.udp=":514"
# INFO    VictoriaLogs/lib/logstorage/syslog.go:XXX started accepting syslog messages at -syslog.listenAddr.tcp=":514"

# 2. Verify routes are in place and accepted
kubectl get tcproute,udproute -n monitoring --context home

# Expected status:
# - victoria-logs-syslog-tcp: Accepted=True, ResolvedRefs=True
# - victoria-logs-syslog-udp: Accepted=True, ResolvedRefs=True

# 3. Confirm gateway listeners are programmed
kubectl get gateway envoy-internal -n network -o yaml --context home | grep -A 5 victoria-logs-syslog

# Expected: TCP and UDP listeners on port 514 with "Programmed: True"
```

### UDM Pro Configuration

**Access**: UniFi Network Application → Settings → System → Advanced

1. **Enable Remote Syslog**:
   - Navigate to: Settings > System > Advanced
   - Remote Logging: Enable
   - Remote Syslog Server: `192.168.35.15`
   - Remote Syslog Port: `514`
   - Protocol: `UDP` (recommended) or `TCP`

2. **Syslog Level** (optional):
   - Default: `Informational`
   - For testing: `Debug` (generates more logs)
   - For production: `Notice` or `Warning`

3. **Apply and Save**

### Synology NAS Configuration

**Access**: Control Panel → Log Center → Archive

1. **Enable Syslog Archive**:
   - Navigate to: Control Panel > Log Center > Archive
   - Transfer logs: Enable
   - Server name: `internal.68cc.io` or `192.168.35.15`
   - Port: `514`
   - Protocol: `UDP` (recommended) or `TCP`
   - Format: `BSD (RFC 3164)`

2. **Log Selection**:
   - Select which logs to forward:
     - System warnings/errors (recommended)
     - Connection logs (optional)
     - File station logs (optional)

3. **Apply**

### Other Network Devices

For other devices supporting syslog:

- **Server**: `192.168.35.15` or `internal.68cc.io`
- **Port**: `514`
- **Protocol**: UDP or TCP (both supported)
- **Format**: RFC 5424 or RFC 3164
- **Facility**: User (default) or appropriate facility code
- **Severity**: Info or higher for production, Debug for testing

## Validation Steps

### Step 1: Generate Test Log Entry

After configuring a device, generate a test event:

**UDM Pro**:
- Reconnect a wireless client
- Access the UniFi controller web UI
- Check System Logs for recent activity

**Synology NAS**:
- Login to DSM
- Access File Station
- Create/delete a test folder
- Check Log Center for the event

### Step 2: Verify Logs in VictoriaLogs

Query VictoriaLogs to confirm log ingestion:

```bash
# Method 1: Check VictoriaLogs pod logs for incoming connections
kubectl logs -n monitoring victoria-logs-server-0 --tail=100 --context home | grep -E "syslog|connection"

# Look for entries like:
# - New syslog connection from <device-ip>
# - Received syslog message from <device-ip>
```

**Method 2: Query via Grafana** (recommended):

1. Access Grafana: `https://grafana.68cc.io` (or appropriate URL)
2. Navigate to Explore
3. Select VictoriaLogs datasource
4. Query examples:

```logql
# All logs from specific source IP (replace with device IP)
{} | source_ip="192.168.1.100"

# Logs from UDM Pro (hostname pattern)
{} | hostname=~"udm.*"

# Logs from Synology NAS
{} | hostname=~"synology.*"

# Recent syslog entries (last 5 minutes)
{} | received > now-5m

# Filter by facility and severity
{} | facility="user" | severity="info"
```

### Step 3: Verify Log Structure

Check that logs contain expected syslog fields:

```logql
# Query a single log entry to inspect structure
{} | limit 1
```

**Expected fields** (RFC 5424):
- `timestamp`: Log timestamp
- `hostname`: Source device hostname
- `app_name`: Application or service name
- `facility`: Syslog facility (0-23)
- `severity`: Syslog severity (0-7)
- `message`: Log message content
- `source_ip`: Source device IP (if available)

**Expected fields** (RFC 3164):
- `timestamp`: Log timestamp
- `hostname`: Source device hostname
- `tag`: Process tag
- `message`: Log message content

## Troubleshooting

### No Logs Appearing in VictoriaLogs

1. **Verify device configuration**:
   - Correct IP: `192.168.35.15`
   - Correct port: `514`
   - Syslog enabled and saved

2. **Check network connectivity**:
   ```bash
   # From a machine on the same network, test UDP connectivity
   echo "<13>1 2026-01-05T20:30:00Z test-host test-app - - - Test syslog message" | nc -u 192.168.35.15 514

   # Check VictoriaLogs logs immediately after
   kubectl logs -n monitoring victoria-logs-server-0 --tail=20 --context home
   ```

3. **Verify route status**:
   ```bash
   kubectl describe tcproute victoria-logs-syslog-tcp -n monitoring --context home
   kubectl describe udproute victoria-logs-syslog-udp -n monitoring --context home

   # Status should show:
   # - Accepted: True
   # - ResolvedRefs: True
   # - No error conditions
   ```

4. **Check gateway configuration**:
   ```bash
   kubectl describe gateway envoy-internal -n network --context home | grep -A 10 victoria-logs

   # Listeners should show:
   # - victoria-logs-syslog-tcp: Programmed=True
   # - victoria-logs-syslog-udp: Programmed=True
   ```

5. **Verify service endpoints**:
   ```bash
   kubectl get endpoints victoria-logs-server -n monitoring --context home

   # Should show pod IP and ports: 9428, 514
   ```

### Logs Arriving but Not Queryable

1. **Check log format**:
   - VictoriaLogs expects RFC 5424 or RFC 3164
   - Some devices send non-standard formats
   - Check pod logs for parsing errors:
   ```bash
   kubectl logs -n monitoring victoria-logs-server-0 --context home | grep -i error
   ```

2. **Verify Grafana datasource**:
   - Datasource: `victoriametrics-logs-datasource` v0.22.0
   - URL should point to VictoriaLogs service
   - Test datasource connection in Grafana

### High Latency or Dropped Messages

1. **Check pod resources**:
   ```bash
   kubectl top pod victoria-logs-server-0 -n monitoring --context home

   # Monitor memory and CPU usage
   # If consistently high, consider increasing resource limits
   ```

2. **Monitor ingestion rate**:
   ```bash
   # Check VictoriaLogs metrics
   kubectl exec -n monitoring victoria-logs-server-0 --context home -- curl localhost:9428/metrics | grep ingestion
   ```

3. **Network issues**:
   - UDP: Packets may be dropped under network congestion (no retry)
   - TCP: More reliable but higher overhead
   - Consider TCP for critical logs, UDP for high-volume low-priority logs

## Performance Baselines

Expected performance for home-lab deployment:

- **Ingestion Rate**: 1-10K logs/sec (typical home-lab volume)
- **Storage**: ~50Gi local volume (14-day retention)
- **Memory**: <2Gi per pod
- **Latency**: <100ms from device to queryable in VictoriaLogs
- **Query Performance**: Sub-second for typical time ranges (1h-1d)

## Success Criteria

Phase 2 validation is complete when:

- [ ] UDM Pro sending logs to VictoriaLogs (visible in Grafana)
- [ ] Synology NAS sending logs to VictoriaLogs (visible in Grafana)
- [ ] Logs queryable via VictoriaLogs datasource in Grafana
- [ ] No parsing errors in VictoriaLogs pod logs
- [ ] Log timestamps accurate (America/New_York timezone)
- [ ] Both TCP and UDP protocols tested (at least one device each)
- [ ] Performance within expected baselines
- [ ] Documentation updated with any device-specific quirks

## Next Steps After Validation

Once external syslog validation is complete:

1. **Update continuity ledger**:
   - Mark UDM Pro and Synology NAS testing as complete
   - Document any device-specific configuration notes
   - Update Working Set with validation results

2. **Configure additional devices** (if any):
   - Follow the same pattern for other syslog-capable devices
   - Document each device's configuration

3. **Proceed to Phase 3**:
   - Configure log forwarding from Promtail/agents
   - Identify critical Loki dashboards
   - Begin Loki → VictoriaLogs migration planning
   - 2-week parallel run period

## Reference Information

### Key Files

- **Routes**: `kubernetes/apps/monitoring/victoria-logs/app/victoria-logs-syslog-{tcp,udp}route.yaml`
- **Gateway**: `kubernetes/apps/network/envoy-gateway/app/envoy.yaml`
- **Kustomization**: `kubernetes/apps/monitoring/victoria-logs/app/kustomization.yaml`
- **HelmRelease**: `kubernetes/apps/monitoring/victoria-logs/app/helmrelease.yaml`
- **Continuity Ledger**: `thoughts/ledgers/CONTINUITY_CLAUDE-platform-evolution.md`

### Useful Commands

```bash
# Watch VictoriaLogs logs in real-time
kubectl logs -n monitoring victoria-logs-server-0 -f --context home

# Check all monitoring namespace pods
kubectl get pods -n monitoring --context home

# Describe VictoriaLogs service
kubectl describe service victoria-logs-server -n monitoring --context home

# Verify Flux reconciliation status
flux get kustomizations -A --context home
flux get helmreleases -A --context home

# Force Flux to pull latest changes
flux reconcile source git flux-system --context home
flux reconcile kustomization cluster-apps --context home
```

### Syslog Format Examples

**RFC 5424 (structured syslog)**:
```
<34>1 2026-01-05T20:30:00.123Z hostname app-name procid msgid [sd@32473 key="value"] Message text
```

**RFC 3164 (BSD syslog)**:
```
<34>Jan 5 20:30:00 hostname app-name[12345]: Message text
```

### Priority Values

Syslog priority = (facility × 8) + severity

**Common facilities**:
- 0: kernel
- 1: user-level
- 3: system daemon
- 4: security/authorization
- 16: local use 0 (local0)

**Severity levels**:
- 0: Emergency
- 1: Alert
- 2: Critical
- 3: Error
- 4: Warning
- 5: Notice
- 6: Informational
- 7: Debug

## Appendix: Session Context

This validation guide completes Phase 2 of the platform-evolution project:

**Goal**: VictoriaLogs accepts external syslog (TCP/UDP) from network devices

**Constraints**:
- Home-lab resource constraints (single replicas)
- Must maintain GitOps patterns (FluxCD + Kustomize/HelmRelease)
- SOPS-encrypted secrets for all credentials
- Zero downtime migration where possible

**Strategic Context**: This is part of a larger observability consolidation effort to simplify the LGTM stack by replacing Loki with VictoriaLogs (which also handles external syslog, eliminating the need for Parseable and eventually Wazuh logging).

**Previous Phase**: Phase 1 (Research & Architecture Design) - Completed
**Current Phase**: Phase 2 (VictoriaLogs Implementation) - Infrastructure deployed, awaiting validation
**Next Phase**: Phase 3 (Observability Consolidation) - Loki migration, dashboard standardization

---

**For questions or issues during validation, update the continuity ledger with findings and any UNCONFIRMED items that need clarification.**
