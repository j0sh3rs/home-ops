# Grafana Dashboard Organization

Created: 2026-01-05

## Overview

This document describes the organization and provisioning of Grafana dashboards for the home-ops observability stack.

## Dashboard Provisioning Pattern

Dashboards are provisioned using the Grafana Operator pattern:

```
kubernetes/apps/monitoring/grafana/dashboards/
├── ks.yaml                                    # Flux Kustomization entry point
└── app/
    ├── kustomization.yaml                     # Kustomize overlay
    ├── {dashboard-name}-dashboard.json        # Dashboard JSON definition
    ├── {dashboard-name}-configmap.yaml        # ConfigMap containing dashboard
    └── {dashboard-name}-grafanadashboard.yaml # GrafanaDashboard CR
```

### Key Components

1. **Dashboard JSON**: Standard Grafana dashboard JSON export with templating variables
2. **ConfigMap**: Kubernetes ConfigMap storing the dashboard JSON
3. **GrafanaDashboard CR**: Custom resource managed by Grafana Operator
4. **Flux Kustomization**: GitOps deployment via FluxCD

## Deployed Dashboards

### VictoriaLogs Dashboard

**Source**: Official dashboard from Grafana.com (ID: 22084)
**Type**: Upstream dashboard (single-node deployment)
**Version**: VictoriaLogs v1.29.0+
**Datasource**: Prometheus

**Dashboard Sections**:
- **Stats**: Total log entries, ingestion rates, disk usage, version info
- **Overview**: Real-time ingestion, request patterns, error tracking, response latency
- **Resource Usage**: CPU, memory, network, garbage collection metrics
- **Troubleshooting**: Process restarts, stream churn, configuration flags, dropped logs
- **Slow Query Troubleshooting**: Query performance analysis and latency diagnostics
- **Storage Operations**: Merge performance and indexing metrics
- **Ingestion Pipeline**: Flush operations and data flow rates
- **Querying Performance**: Request latencies and timeout tracking

**Requirements**:
- Prometheus datasource configured to scrape `victorialogs-addr/metrics`
- VictoriaLogs ServiceMonitor must be enabled for metrics collection

**Files**:
- `victorialogs-dashboard.json` - Dashboard definition
- `victorialogs-configmap.yaml` - ConfigMap resource
- `victorialogs-grafanadashboard.yaml` - GrafanaDashboard CR

### Tetragon Security Observability Dashboard

**Source**: Custom dashboard based on Tetragon metrics documentation
**Type**: Custom-built (no official dashboard available)
**Version**: Compatible with Tetragon DaemonSet deployments
**Datasource**: Prometheus

**Dashboard Panels**:

1. **Tetragon Events Rate by Type**
   - Metric: `rate(tetragon_events_total[5m])`
   - Shows: Process execution, kprobe, LSM, tracepoint, uprobe events
   - Purpose: Real-time security event monitoring

2. **Error Rate**
   - Metric: `rate(tetragon_errors_total[5m])`
   - Shows: Total Tetragon error rate
   - Purpose: System health monitoring

3. **Active Tracing Policies**
   - Metric: `tetragon_tracingpolicy_loaded{state="enabled"}`
   - Shows: Number of enabled security policies
   - Purpose: Policy coverage visibility

4. **Policy Events Rate by Policy**
   - Metric: `rate(tetragon_policy_events_total[5m])`
   - Shows: Event rate per loaded policy
   - Purpose: Policy effectiveness analysis

5. **Memory Usage**
   - Metric: `process_resident_memory_bytes{job="tetragon"}`
   - Shows: Memory consumption per Tetragon pod
   - Purpose: Resource utilization tracking

6. **Goroutines**
   - Metric: `go_goroutines{job="tetragon"}`
   - Shows: Active goroutines per pod
   - Purpose: Concurrency and performance monitoring

7. **Syscalls Rate by Binary**
   - Metric: `rate(tetragon_syscalls_total[5m])`
   - Shows: System call activity by binary
   - Purpose: Security behavior analysis

8. **CPU Usage**
   - Metric: `rate(process_cpu_seconds_total{job="tetragon"}[5m])`
   - Shows: CPU percentage per pod
   - Purpose: Resource utilization tracking

**Requirements**:
- Tetragon DaemonSet deployed with metrics enabled
- Prometheus ServiceMonitor for Tetragon metrics scraping
- Metrics endpoint: typically `tetragon:9090/metrics`

**Note**: This is a custom dashboard created from Tetragon's metrics documentation as no official Grafana dashboard exists yet. The Isovalent blog mentioned an "upcoming Tetragon dashboard" in the Grafana Hubble plugin, but this has not been released.

**Files**:
- `tetragon-dashboard.json` - Dashboard definition
- `tetragon-configmap.yaml` - ConfigMap resource
- `tetragon-grafanadashboard.yaml` - GrafanaDashboard CR

## Dashboard Lifecycle

### Deployment

Dashboards are deployed via Flux GitOps:

```bash
# Force Flux reconciliation
flux reconcile kustomization grafana-dashboards -n flux-system

# Check dashboard status
kubectl get grafanadashboard -n monitoring

# Verify ConfigMaps
kubectl get configmap -n monitoring | grep dashboard
```

### Updates

To update a dashboard:

1. Modify the dashboard JSON file
2. Regenerate the ConfigMap:
   ```bash
   cd kubernetes/apps/monitoring/grafana/dashboards/app
   kubectl create configmap {dashboard-name}-dashboard \
     --from-file={dashboard-name}-dashboard.json \
     --dry-run=client -o yaml > {dashboard-name}-configmap.yaml
   ```
3. Commit and push changes
4. Flux will automatically reconcile

### Adding New Dashboards

To add a new dashboard:

1. **Obtain dashboard JSON**:
   - Export from Grafana UI
   - Download from Grafana.com
   - Create custom dashboard JSON

2. **Create resources**:
   ```bash
   cd kubernetes/apps/monitoring/grafana/dashboards/app

   # Create ConfigMap
   kubectl create configmap {dashboard-name}-dashboard \
     --from-file={dashboard-name}-dashboard.json \
     --dry-run=client -o yaml > {dashboard-name}-configmap.yaml

   # Create GrafanaDashboard CR
   cat > {dashboard-name}-grafanadashboard.yaml <<EOF
   ---
   apiVersion: grafana.integreatly.org/v1beta1
   kind: GrafanaDashboard
   metadata:
     name: {dashboard-name}
     namespace: monitoring
   spec:
     allowCrossNamespaceImport: true
     instanceSelector:
       matchLabels:
         grafana.internal/instance: grafana
     datasources:
       - datasourceName: prometheus
         inputName: DS_PROMETHEUS
     configMapRef:
       name: {dashboard-name}-dashboard
       key: {dashboard-name}-dashboard.json
   EOF
   ```

3. **Update kustomization**:
   - Add resources to `app/kustomization.yaml`

4. **Commit and deploy**:
   ```bash
   git add .
   git commit -m "feat(grafana): add {dashboard-name} dashboard"
   git push
   flux reconcile kustomization grafana-dashboards -n flux-system
   ```

## Dashboard Access

Once deployed, dashboards are accessible via Grafana UI:

1. Navigate to Grafana: `https://grafana.{domain}`
2. Go to Dashboards → Browse
3. Filter by tags:
   - `victorialogs` - VictoriaLogs observability
   - `tetragon`, `security`, `ebpf` - Tetragon security monitoring

## Datasource Configuration

All dashboards use the Prometheus datasource configured via GrafanaDataSource CR:

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDataSource
metadata:
  name: prometheus
spec:
  datasource:
    name: prometheus
    type: prometheus
    access: proxy
    url: http://thanos-query-frontend.monitoring:9090
```

The `datasources` field in GrafanaDashboard CR maps template variables to actual datasource names:

```yaml
datasources:
  - datasourceName: prometheus    # Actual datasource name in Grafana
    inputName: DS_PROMETHEUS       # Template variable in dashboard JSON
```

## Monitoring Dashboard Health

### Check Dashboard Provisioning

```bash
# List all GrafanaDashboard resources
kubectl get grafanadashboard -n monitoring

# Check specific dashboard status
kubectl describe grafanadashboard victorialogs -n monitoring
kubectl describe grafanadashboard tetragon -n monitoring

# View Grafana Operator logs
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana-operator -f
```

### Common Issues

**Dashboard not appearing in Grafana**:
- Check GrafanaDashboard CR status: `kubectl describe grafanadashboard {name} -n monitoring`
- Verify ConfigMap exists: `kubectl get configmap {name}-dashboard -n monitoring`
- Check Grafana Operator logs for errors

**Datasource not found**:
- Verify Prometheus datasource exists in Grafana
- Check datasource name mapping in GrafanaDashboard spec
- Confirm Prometheus is accessible from Grafana pod

**Panels showing "No Data"**:
- Verify metrics are being collected (check Prometheus targets)
- Confirm ServiceMonitor is configured correctly
- Check metric names match between dashboard queries and actual metrics

## Future Enhancements

### Planned Dashboards

When Tetragon is deployed in Phase 4:
- Consider replacing custom Tetragon dashboard with official version if released
- Add additional security-focused panels based on deployed TracingPolicies
- Create alerting dashboards for security events

### Dashboard Improvements

- Add organization folders in Grafana for logical grouping
- Implement dashboard versioning and rollback capability
- Create dashboard templates for common observability patterns
- Add annotations for deployment events and configuration changes

## References

- VictoriaLogs Dashboard: https://grafana.com/grafana/dashboards/22084-victorialogs-single-node/
- Tetragon Metrics: https://github.com/cilium/tetragon/blob/main/docs/content/en/docs/reference/metrics.md
- Grafana Operator: https://grafana.github.io/grafana-operator/docs/
- Flux Kustomization: https://fluxcd.io/flux/components/kustomize/kustomization/
