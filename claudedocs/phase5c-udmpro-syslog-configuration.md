# Phase 5C: UDM Pro Syslog Configuration Guide

**Status**: User action required
**Phase**: Phase 5C - Configure UDM Pro syslog → VictoriaLogs
**Date**: 2026-01-06
**Prerequisites**: Phase 5B complete (Tetragon alerts deployed and verified)

## Overview

This guide provides step-by-step instructions for configuring UniFi Dream Machine Pro (UDM Pro) to send Deep Packet Inspection (DPI) logs and system logs to VictoriaLogs via external syslog.

## VictoriaLogs Syslog Configuration (Already Complete)

✅ **External syslog endpoint**: 192.168.35.15:514 (TCP and UDP)
✅ **Hostname**: internal.68cc.io
✅ **Protocols**: RFC 5424 (structured) and RFC 3164 (BSD syslog)
✅ **Gateway**: Envoy-internal with TCPRoute and UDPRoute
✅ **Status**: Validated and working (tested 2026-01-05)
✅ **Retention**: 14 days

## UDM Pro Configuration Steps

### Step 1: Access UDM Pro Web Interface

1. Navigate to your UDM Pro web interface (typically `https://192.168.1.1` or your gateway IP)
2. Log in with admin credentials
3. Go to **Settings** → **System** → **Advanced**

### Step 2: Enable Remote Syslog

1. In the **System** settings page, locate the **Remote Syslog** section
2. Enable **Remote Syslog Server**
3. Configure the following settings:

   **Syslog Server Configuration**:
   - **Host**: `192.168.35.15` (or `internal.68cc.io`)
   - **Port**: `514`
   - **Protocol**: Choose `UDP` (recommended) or `TCP`
     - **UDP**: Fire-and-forget, better performance, lower overhead
     - **TCP**: Guaranteed delivery, better for critical logs, slightly higher overhead

### Step 3: Configure Syslog Options

**Recommended Settings**:
- **Facility**: `Local0` (or any available local facility)
- **Severity Level**: `Info` (captures all logs including DPI events)
- **Format**: `RFC 5424` (structured, recommended) or `RFC 3164` (legacy, compatible)

**Advanced Options** (if available):
- **Include Hostname**: `Enabled` (helps identify source in multi-device environments)
- **Include Timestamp**: `Enabled` (preserves original event time)
- **Tag**: `udmpro-dpi` (optional, for filtering in VictoriaLogs)

### Step 4: Enable Deep Packet Inspection (DPI) Logging

1. Navigate to **Settings** → **Traffic Management** → **Deep Packet Inspection**
2. Ensure **Deep Packet Inspection** is **Enabled**
3. Enable **DPI Event Logging** (if available as separate toggle)
4. Select categories to log:
   - **Network Security**: Threats, intrusion attempts, malware
   - **Application Control**: App usage, bandwidth, categories
   - **All DPI Events**: Comprehensive logging (high volume, use with caution)

**Recommended DPI Categories for Security Monitoring**:
- ✅ Security threats and anomalies
- ✅ Intrusion detection events
- ✅ Malware and botnet activity
- ✅ Unusual traffic patterns
- ⚠️ Application usage (high volume, filter carefully)
- ⚠️ Bandwidth monitoring (very high volume, optional)

### Step 5: Save and Apply Configuration

1. Click **Apply Changes** at the bottom of the page
2. Wait for UDM Pro to apply the configuration (typically 30-60 seconds)
3. Verify syslog service is running in UDM Pro console (SSH access):
   ```bash
   # SSH into UDM Pro
   ssh admin@192.168.1.1

   # Check syslog configuration
   cat /etc/rsyslog.conf | grep -A5 "remote syslog"

   # Verify syslog is sending logs
   tail -f /var/log/messages
   ```

## Verification Steps

### Step 1: Verify Logs Reaching VictoriaLogs

Within 1-2 minutes of configuration, check VictoriaLogs for incoming logs from UDM Pro:

```bash
# SSH into Kubernetes cluster or use kubectl from local machine
kubectl logs -n monitoring victoria-logs-server-0 --context home --tail=100 | grep -i "udm\|unifi"
```

**Expected Output**:
```
2026-01-06T10:30:15Z [INFO] Received syslog message from 192.168.1.1
2026-01-06T10:30:16Z [INFO] Parsed RFC 5424 message: facility=local0, severity=info
```

### Step 2: Query Logs in Grafana

1. Open Grafana (http://your-grafana-url)
2. Navigate to **Explore** → Select **VictoriaLogs** datasource
3. Run the following VictoriaLogs query:

   ```
   {hostname="udmpro"} | json
   ```

   Or filter by specific log types:

   ```
   {hostname="udmpro", severity="info"} | json | _msg =~ "DPI|threat|intrusion"
   ```

**Expected Results**:
- DPI events with application names, categories, and traffic patterns
- Security events (threats, intrusion attempts, malware detection)
- Network events (connections, bandwidth usage, device activity)

### Step 3: Verify Alert Integration (Optional)

If you want to create alerts for specific UDM Pro events:

1. Navigate to **Alerting** → **Alert Rules** in Grafana
2. Create a new alert rule based on VictoriaLogs query
3. Example alert for security threats:

   ```yaml
   # Example PrometheusRule for UDM Pro security events
   - alert: UDMProSecurityThreat
     expr: |
       count_over_time({hostname="udmpro"} | json | _msg =~ "threat|intrusion|malware" [5m]) > 0
     for: 1m
     labels:
       severity: warning
       source: udmpro
     annotations:
       summary: "UDM Pro detected security threat"
       description: "{{ $labels.hostname }} reported security event: {{ $labels._msg }}"
   ```

## Common Log Patterns from UDM Pro

### DPI Application Events
```
Jan 06 10:30:15 udmpro kernel: [DPI] Application detected: Netflix, Category: Streaming, Bytes: 1024000
Jan 06 10:30:16 udmpro kernel: [DPI] Application detected: Zoom, Category: Video Conferencing, Bytes: 512000
```

### Security Events
```
Jan 06 10:31:20 udmpro kernel: [IDS] Intrusion attempt detected from 203.0.113.45
Jan 06 10:31:21 udmpro kernel: [IDS] Blocked malicious traffic to internal host 192.168.1.50
```

### Network Events
```
Jan 06 10:32:00 udmpro kernel: [NET] New DHCP lease for 192.168.1.100 (iPhone-John)
Jan 06 10:32:01 udmpro kernel: [NET] Client connected to SSID "Home-WiFi": aa:bb:cc:dd:ee:ff
```

## Troubleshooting

### Problem: No logs appearing in VictoriaLogs

**Diagnosis**:
```bash
# Check VictoriaLogs is listening on port 514
kubectl get svc -n monitoring victoria-logs-server --context home

# Verify Envoy Gateway routes are active
kubectl get tcproute,udproute -n monitoring --context home

# Check VictoriaLogs logs for errors
kubectl logs -n monitoring victoria-logs-server-0 --context home --tail=100
```

**Common Causes**:
1. **Firewall blocking UDP/TCP 514**: Ensure network allows syslog traffic
2. **Wrong IP address**: Verify 192.168.35.15 is reachable from UDM Pro
3. **UDM Pro syslog service not started**: SSH into UDM Pro and check `rsyslog` status
4. **Format mismatch**: Try switching between RFC 5424 and RFC 3164

### Problem: Logs arriving but not parsed correctly

**Diagnosis**:
```bash
# Check raw logs in VictoriaLogs
kubectl logs -n monitoring victoria-logs-server-0 --context home --tail=200 | grep "udmpro\|192.168.1.1"
```

**Common Causes**:
1. **Non-standard syslog format**: UDM Pro may send custom-formatted logs
2. **Missing hostname tag**: Enable hostname in UDM Pro syslog settings
3. **Timestamp parsing issues**: Ensure timezone is configured correctly

**Solution**:
- Switch to RFC 5424 format (more structured)
- Enable all metadata fields (hostname, timestamp, facility, severity)
- Use VictoriaLogs stream parsing rules if needed

### Problem: High log volume overwhelming VictoriaLogs

**Symptoms**:
- VictoriaLogs pod using excessive memory or CPU
- Slow query performance in Grafana
- Storage filling up faster than 14-day retention

**Solution**:
1. **Reduce DPI logging scope**: Disable high-volume categories (app usage, bandwidth)
2. **Increase syslog severity level**: Change from `Info` to `Warning` or `Error`
3. **Implement filtering in UDM Pro**: If available, filter logs before sending
4. **Adjust VictoriaLogs retention**: Reduce from 14 days to 7 days if needed

## Post-Configuration Monitoring

### Week 1: Initial Observation
- Monitor VictoriaLogs resource usage (memory, CPU, storage)
- Identify high-volume log sources and adjust DPI categories
- Create dashboards for key UDM Pro metrics

### Week 2-4: Tuning Phase
- Fine-tune syslog severity levels based on log volume
- Create custom alerts for security events
- Document patterns for common DPI events
- Adjust retention policies if needed

### Ongoing Maintenance
- Review UDM Pro firmware updates for syslog changes
- Monitor VictoriaLogs storage usage trends
- Update alert rules based on false positive/negative rates

## Integration with Phase 5D (Parallel Run)

During Phase 5D (Tetragon + Wazuh parallel run), UDM Pro syslog provides additional network-level security visibility:

**Coverage Matrix**:
- **Tetragon**: Runtime security (process exec, file access, network connections) at pod/container level
- **UDM Pro DPI**: Network security (app detection, threats, intrusion) at network edge
- **Wazuh** (deprecated): Host-level security (file integrity, syscalls) - to be removed after validation

**Complementary Capabilities**:
- Tetragon detects malicious container activity → UDM Pro logs external C2 connections
- UDM Pro detects network intrusion attempts → Tetragon monitors if any pods are compromised
- Combined view provides defense-in-depth security posture

## Success Criteria

Phase 5C is complete when:
- ✅ UDM Pro syslog configuration applied and saved
- ✅ Logs appearing in VictoriaLogs within 2 minutes
- ✅ DPI events visible in Grafana VictoriaLogs datasource
- ✅ Security events (if any) properly formatted and parseable
- ✅ Log volume sustainable (VictoriaLogs resource usage stable)
- ✅ No dropped logs or parsing errors in VictoriaLogs

## Next Steps (Phase 5D)

After Phase 5C completion, proceed to Phase 5D:
1. Begin 2-week parallel run of Tetragon + Wazuh
2. Compare security event coverage between systems
3. Validate no critical events missed by Tetragon
4. Document tuning requirements for Tetragon TracingPolicies
5. Prepare for Phase 5E (Wazuh removal) after validation period

## References

- **VictoriaLogs External Syslog**: Validated 2026-01-05 in `victorialogs-phase2-external-syslog-validation.md`
- **Tetragon Alert Rules**: Deployed in `kubernetes/apps/monitoring/kube-prometheus-stack/app/prometheusrule-security.yaml`
- **Wazuh Capability Assessment**: Documented in `claudedocs/wazuh-capability-assessment.md`
- **UDM Pro Documentation**: https://help.ui.com/hc/en-us/articles/204976094-UniFi-How-to-View-Log-Files
