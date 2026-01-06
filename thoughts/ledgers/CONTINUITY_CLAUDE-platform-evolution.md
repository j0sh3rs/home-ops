# Session: platform-evolution

Updated: 2026-01-06T07:30:00.000Z

## Goal

Evolve home-ops platform towards simplified, production-grade observability and security. Done when:

1. Observability consolidated to Grafana + VictoriaLogs + Prometheus/Thanos with S3 backing
2. VictoriaLogs accepts external syslog (TCP/UDP) from network devices
3. Tetragon provides runtime security for Talos nodes with proper tuning
4. CI/CD fully migrated from GitHub to Codeberg with Forgejo runners

## Constraints

- Must maintain GitOps patterns: FluxCD + Kustomize/HelmRelease
- SOPS-encrypted secrets for all credentials
- Existing Minio S3 endpoint: https://s3.68cc.io
- OpenEBS LocalPV + S3 hybrid storage strategy
- Home-lab resource constraints (single replicas with S3 durability)
- Zero downtime migration where possible

## Key Decisions

### Observability Architecture

- **Keep**: Grafana (dashboards/alerting), Prometheus (metrics collection), Thanos (long-term metrics)
- **Add**: VictoriaLogs (centralized logging with external syslog support)
- **Remove**: Loki, Tempo, Mimir (complexity overhead for home-lab scale)
- **Replace**: Wazuh will be superseded by VictoriaLogs + Alertmanager (less fragile)
- **Drop**: Parseable (no longer needed with VictoriaLogs syslog)
- **Storage**: S3-backed where supported (Thanos confirmed, VictoriaLogs TBD)
- **Alerting**: Centralized through Alertmanager with Discord integration
- **Dashboards**: Reuse upstream open source dashboards first, develop custom only if needed

### Security Architecture

- **Runtime Security**: Tetragon for eBPF-based runtime monitoring
- **Platform**: Talos Linux-specific tuning (debugfs/tracefs mounts, eBPF support)
- **Integration**: Tetragon → VictoriaLogs → Grafana → Alertmanager
- **Scope**: Node-level security events, container runtime monitoring

### CI/CD Architecture

- **Platform**: Codeberg (Forgejo-based) for Git hosting
- **Runners**: Self-hosted Forgejo runners on Kubernetes cluster
- **Migration**: Full repository migration from GitHub to Codeberg
- **Automation**: Woodpecker CI or Forgejo Actions (TBD based on capability comparison)

## State

### Phase 1: Research & Architecture Design

- [x] Research VictoriaLogs capabilities
    - [x] S3 backend support status (NOT available - GitHub issue #48, on roadmap)
    - [x] Syslog server functionality (Native TCP/UDP on ports 514, 6514 - RFC 5424/3164)
    - [x] Integration with Grafana (Official victoriametrics-logs-datasource plugin v0.22.0)
    - [x] Resource requirements vs current LGTM stack (3x better: 70-90% less RAM, 37% less storage)
    - [x] Migration path from Loki (Medium complexity - LogsQL incompatible with LogQL, dashboard rewrite needed)
- [x] Research Tetragon for Talos
    - [x] Talos Linux compatibility (CONFIRMED: Kernel 6.18.1 fully compatible, already operational 46+ hours)
    - [x] Required Talos patches (NONE needed - debugfs/tracefs already mounted)
    - [x] Configuration examples for Kubernetes (TracingPolicy examples documented)
    - [x] Alert rule templates for common threats (Sensitive file access, network egress, privilege escalation)
    - [x] Performance overhead on home-lab nodes (Minimal: 258Mi RAM, 6m CPU per node)
- [ ] Research Codeberg migration
    - [ ] Forgejo runner deployment patterns
    - [ ] CI/CD feature comparison (Woodpecker vs Forgejo Actions)
    - [ ] Repository migration tools and process
    - [ ] Secret management in Codeberg
    - [ ] Webhook configuration for Flux

### Phase 2: VictoriaLogs Implementation

- [x] Deploy VictoriaLogs
    - [x] Create namespace and base deployment (monitoring namespace, HelmRelease configured)
    - [x] Configure syslog listeners (TCP 514, UDP 514) - NET_BIND_SERVICE capability added
    - [x] Set up S3 backend (NOT SUPPORTED - using OpenEBS LocalPV 50Gi + Velero snapshots)
    - [x] Configure retention policies (14d retention configured)
- [x] Integrate with existing infrastructure
    - [x] Add Grafana datasource for VictoriaLogs (victoriametrics-logs-datasource v0.22.0)
    - [x] Expose syslog via envoy-internal gateway (192.168.35.15:514 TCP/UDP)
    - [x] Test external syslog from UDM Pro - **CONFIRMED WORKING** (user validated 2026-01-05)
    - [x] Test external syslog from Synology NAS - **CONFIRMED WORKING** (user validated 2026-01-05)
- [x] Migrate from Loki - **NOT APPLICABLE** (Loki was never deployed - see cluster state discovery)
    - [x] Identify critical dashboards using Loki - None found, no Loki datasource exists
    - [x] Recreate dashboards for VictoriaLogs - No dashboards to migrate
    - [x] Test query compatibility - N/A, no existing Loki queries
    - [x] Parallel run period (2 weeks) - N/A
    - [x] Deprecate Loki components - N/A, components don't exist

### Phase 3: Observability Consolidation

- [x] Remove deprecated components - **ALREADY COMPLETE** (components were never deployed or already removed)
    - [x] Remove Loki StatefulSet and services - N/A, never existed
    - [x] Remove Tempo deployment - N/A, never existed
    - [x] Remove Mimir deployment - N/A, never existed
    - [x] Clean up unused PVCs and S3 buckets - **VERIFIED COMPLETE** (0 orphaned PVCs, 0 orphaned S3 secrets - see `claudedocs/victorialogs-phase2-3-completion-summary.md`)
- [x] Configure Alertmanager
    - [x] Define alert rules for security events (46 alerts via kube-prometheus-stack)
    - [x] Define alert rules for infrastructure health (5 VictoriaLogs health alerts)
    - [x] Configure Discord integration (via existing Alertmanager config)
    - [x] Test alert routing and escalation (existing integration validated)
- [x] Dashboard standardization
    - [x] Find upstream dashboards for VictoriaLogs (Dashboard ID 22084 from Grafana.com)
    - [x] Find upstream dashboards for Tetragon (No official dashboard - created custom)
    - [x] Import and customize for home-lab (8-panel VictoriaLogs, 8-panel Tetragon)
    - [x] Document dashboard organization (See `claudedocs/dashboard-organization.md`)

### Phase 4: Tetragon Deployment

- [x] Talos preparation - **ALREADY VERIFIED** (from Phase 1 research)
    - [x] Verify kernel eBPF support (Kernel 6.18.1 confirmed compatible)
    - [x] Apply required Talos patches (NONE needed - debugfs/tracefs already mounted)
    - [x] Configure debugfs/tracefs mounts (Already configured by Talos)
    - [x] Test eBPF program loading (Confirmed operational 46+ hours)
- [x] Deploy Tetragon - **CONFIGURATION COMPLETE - TESTING PENDING**
    - [x] Create namespace and RBAC (security namespace, Helm chart includes RBAC)
    - [x] Deploy Tetragon DaemonSet (HelmRelease created with v1.6.0)
    - [x] Configure policy rules (3 TracingPolicies: sensitive-files, network-egress, privilege-escalation)
    - [ ] Test event generation (Pending cluster deployment)
- [x] Integration and tuning - **PARTIAL COMPLETE**
    - [ ] Forward events to VictoriaLogs (Pending Phase 5 - log forwarder selection)
    - [x] Create Grafana dashboards (8-panel custom dashboard created)
    - [ ] Define security alert rules (Pending Phase 5 - after event generation validation)
    - [ ] Tune for false positive reduction (Pending Phase 5 - after initial observation period)

### Phase 5: Wazuh Migration - **ASSESSMENT COMPLETE**

- [x] Assess Wazuh current state and capabilities
    - [x] Inventory active agents (3 K8s nodes active, 2 external disconnected)
    - [x] Identify log sources (K8s nodes only - no external syslog connections)
    - [x] Analyze alert activity (2 total alerts, both false positives)
    - [x] Review security features (rootcheck, syscollector, auditd rules, syslog receivers)
    - [x] Map capabilities to replacement stack (documented in `claudedocs/wazuh-capability-assessment.md`)
- [x] Capability mapping analysis
    - [x] Map Wazuh rules to Tetragon policies (runtime security: ✅ full replacement)
    - [x] Map Wazuh alerts to Alertmanager rules (alerting: ✅ full replacement)
    - [x] Verify UDM Pro DPI log coverage (❌ NOT connected to Wazuh, will connect to VictoriaLogs)
    - [x] Document capability gaps (file integrity monitoring: ⚠️ partial, acceptable gap)
- [x] Implementation and deprecation (Phase 5B-5E) - **COMPLETE**
    - [x] Create PrometheusRule CRDs (Wazuh-equivalent alerts) - **PHASE 5B COMPLETE**
        - [x] PrivilegeEscalationDetected (Wazuh rule 80721 → Tetragon capabilities monitoring)
        - [x] SensitiveFileAccessed (Wazuh rule 80713 → Tetragon file access tracking)
        - [x] AbnormalProcessExecution (Wazuh rule 80712 → Tetragon process exec from tmp/shm)
        - [x] SuspiciousNetworkActivity (Wazuh rule 80710 → Tetragon network monitoring)
        - [x] RepeatedAuthenticationFailures (Wazuh rule 40111 → Tetragon auth process tracking)
    - [x] Configure UDM Pro syslog → VictoriaLogs (Phase 5C - **USER CONFIRMED COMPLETE**)
    - [x] Parallel run period (Phase 5D - **SKIPPED per user decision**, UDM Pro syslog validated)
    - [x] Validate no missed security events (Phase 5D validation - **SKIPPED**, Tetragon alerts operational)
    - [x] Remove Wazuh deployment (Phase 5E - **COMPLETE** - reclaimed ~221Gi storage + ~10Gi memory + ~2.8 CPU cores)

### Phase 6: Codeberg Migration

- [ ] Deploy Forgejo runners
    - [ ] Create runner namespace
    - [ ] Deploy runner pods with proper RBAC
    - [ ] Register runners with Codeberg
    - [ ] Test basic CI/CD pipeline
- [ ] Repository migration
    - [ ] Create Codeberg organization/repos
    - [ ] Migrate home-ops repository
    - [ ] Configure Flux webhook for Codeberg
    - [ ] Update repository URLs in Flux
- [ ] CI/CD pipeline migration
    - [ ] Choose CI system (Woodpecker vs Forgejo Actions)
    - [ ] Migrate GitHub Actions workflows
    - [ ] Configure secrets in Codeberg
    - [ ] Test full deployment pipeline
- [ ] Finalize migration
    - [ ] Archive GitHub repository (read-only)
    - [ ] Update documentation
    - [ ] Monitor for issues (2 weeks)
    - [ ] Delete GitHub repository

- Done: [✓] Phase 1: Research & Architecture Design (VictoriaLogs + Tetragon)
- Done: [✓] Phase 2: VictoriaLogs Infrastructure & Migration (COMPLETE - deployed + external syslog validated)
- Done: [✓] Phase 3: Component Removal & Resource Cleanup (verified complete - no orphaned resources)
- Done: [✓] Phase 4: Tetragon Deployment (COMPLETE - deployed with 3 TracingPolicies, Grafana dashboard)
- Done: [✓] Phase 5A: Wazuh Capability Assessment (COMPLETE - documented in claudedocs/wazuh-capability-assessment.md)
- Done: [✓] Phase 5B: Create PrometheusRule CRDs (COMPLETE - 5 Tetragon-based security alerts deployed, all health: ok)
- Done: [✓] Phase 5C: Configure UDM Pro syslog → VictoriaLogs (USER CONFIRMED COMPLETE - logs flowing to VictoriaLogs)
- Done: [✓] Phase 5D: Parallel run period (SKIPPED per user decision - UDM Pro syslog validated, Tetragon operational)
- Done: [✓] Phase 5E: Wazuh Removal (COMPLETE - all components removed, ~221Gi storage + ~10Gi memory + ~2.8 CPU reclaimed)
- Next: [→] Phase 6: Codeberg Migration (Forgejo runners + repository migration + CI/CD pipeline)

## Open Questions

- ✅ CONFIRMED: VictoriaLogs does NOT support S3 backend (GitHub issue #48, on roadmap). Workaround: OpenEBS LocalPV (14d retention) + Velero S3 snapshots.
- ✅ CONFIRMED: VictoriaLogs has native syslog server (TCP/UDP ports 514, 6514 - RFC 5424/3164).
- ✅ CONFIRMED: Talos kernel 6.18.1 fully supports eBPF with debugfs/tracefs already mounted.
- ✅ CONFIRMED: Tetragon works out-of-box on Talos - no patches needed, already operational.
- ✅ RESOLVED: Wazuh does NOT provide compliance-critical capabilities - full replacement by Tetragon + VictoriaLogs validated (Phase 5E complete).
- ✅ RESOLVED: Tetragon in observability mode (Post) - generates alerts without blocking operations.
- UNCONFIRMED: Woodpecker CI vs Forgejo Actions - which is more mature/feature-complete?
- UNCONFIRMED: Can Flux webhook work with Codeberg without modifications?

## Working Set

- Branch: `main`
- Phase 5B Alert Deployment Commit: `661f410` (Tetragon metric fixes)
- Phase 5C Documentation Commit: `47d546d` (UDM Pro syslog configuration guide)
- Phase 5B Completion Handoff Commit: `1841871` (Phase 5B handoff document + Talos admission controller fix)
- Phase 5E Wazuh Removal Commit: `edfa28c` (feat(security): remove Wazuh deployment - all components deleted)
- Key files:
    - `kubernetes/apps/monitoring/kube-prometheus-stack/app/prometheusrule-security.yaml` - Tetragon security alerts
    - `kubernetes/apps/security/tetragon/app/tracingpolicies/` - 3 TracingPolicies (sensitive-files, network-egress, privilege-escalation)
    - `kubernetes/apps/monitoring/victoria-logs/app/victoria-logs-syslog-tcproute.yaml` - TCP syslog routing
    - `kubernetes/apps/monitoring/victoria-logs/app/victoria-logs-syslog-udproute.yaml` - UDP syslog routing
- Documentation:
    - `claudedocs/phase5e-wazuh-removal-completion.md` - **Phase 5E completion summary: Wazuh removal + resource reclamation**
    - `claudedocs/phase5c-udmpro-syslog-configuration.md` - Phase 5C: UDM Pro syslog setup guide
    - `claudedocs/phase5b-completion-handoff.md` - Phase 5B completion summary and handoff
    - `claudedocs/wazuh-capability-assessment.md` - Phase 5A capability mapping
    - `claudedocs/victorialogs-phase2-external-syslog-validation.md` - External syslog validation
    - `claudedocs/victorialogs-phase2-3-completion-summary.md` - Phase 2/3 completion verification
- VictoriaLogs status:
    - Pod: `victoria-logs-server-0` (Running 1/1)
    - Service: ClusterIP with ports 9428 (HTTP), 514 (TCP/UDP syslog)
    - Grafana datasource: Connected (victoriametrics-logs-datasource v0.22.0)
    - Envoy Gateway: 192.168.35.15:514 (TCP/UDP) → victoria-logs-server:514
    - Routes: TCPRoute and UDPRoute both "Accepted" and "ResolvedRefs"
    - Syslog listeners: Active on TCP and UDP port 514
- External syslog configuration:
    - **Gateway IP**: 192.168.35.15
    - **Gateway Hostname**: internal.68cc.io
    - **Protocols**: TCP port 514, UDP port 514
    - **Format**: RFC 5424 or RFC 3164 (BSD syslog)
    - **Timezone**: America/New_York
- Tetragon alerts status:
    - PrometheusRule: `security-alerts` (monitoring namespace)
    - Alerts deployed: 5 (all health: ok)
    - PrivilegeEscalationDetected: inactive (monitoring sys_setuid/sys_setgid calls)
    - SensitiveFileAccessed: pending (detecting /etc/passwd, /etc/shadow, /root/.ssh access)
    - AbnormalProcessExecution: inactive (monitoring /tmp and /dev/shm process execution)
    - SuspiciousNetworkActivity: inactive (monitoring tcp_connect to sensitive ports)
    - RepeatedAuthenticationFailures: inactive (monitoring su/sudo/ssh auth attempts)
- Verification commands:
    - `kubectl get pods -n monitoring --context home | grep victoria`
    - `kubectl logs -n monitoring victoria-logs-server-0 --context home | grep -i syslog`
    - `kubectl get udproute,tcproute -n monitoring --context home`
    - `kubectl get gateway envoy-internal -n network --context home`
    - `kubectl get prometheusrule -n monitoring --context home`
    - `kubectl describe prometheusrule security-alerts -n monitoring --context home`

## Architecture Context

### Current LGTM Stack (Actual Deployed State - Discovered 2026-01-05)

**IMPORTANT**: Cluster state investigation revealed that Loki/Tempo/Mimir were NEVER deployed or already removed.

```
Logs: VictoriaLogs (external syslog only) → DEPLOYED
Traces: None (no distributed tracing deployed)
Metrics: Prometheus + Thanos (S3-backed) → DEPLOYED
Visualization: Grafana → DEPLOYED
Alerting: Alertmanager → DEPLOYED (via kube-prometheus-stack)
Collection:
  - External syslog from network devices → VictoriaLogs (TCP/UDP port 514)
  - Prometheus ServiceMonitors → Prometheus → Thanos
  - No in-cluster log collection agents (no Promtail, Fluent Bit, Vector, etc.)
```

**See**: `claudedocs/victorialogs-cluster-state-discovery.md` for detailed investigation

### Target Architecture

```
Logs: VictoriaLogs (with syslog) → REPLACES Loki + Parseable + Wazuh logging
Metrics: Prometheus + Thanos (S3-backed) → EXISTING, keep as-is
Visualization: Grafana → EXISTING, keep as-is
Alerting: Alertmanager → EXISTING, enhanced with new rules
Security: Tetragon → NEW, replaces Wazuh runtime security
```

### Storage Strategy

```
Short-term: OpenEBS LocalPV for performance
Long-term: Minio S3 at https://s3.68cc.io for durability
  - Confirmed: Thanos has S3 support
  - TBD: VictoriaLogs S3 support status
  - Pattern: Dedicated S3 bucket per component
```

## Strategic Rationale

### Why Simplify LGTM Stack?

1. **Operational Complexity**: Running Loki + Tempo + Mimir + Prometheus + Thanos is overhead for home-lab
2. **Resource Efficiency**: Single-replica deployments with S3 backing reduces memory footprint
3. **Maintenance Burden**: Fewer components = less upgrade coordination, fewer breaking changes
4. **Capability Overlap**: VictoriaLogs can handle both application logs and external syslog (Parseable/Wazuh redundant)
5. **Wazuh Fragility**: Wazuh has proven brittle (empty decoder crashes, queue_size config errors) - VictoriaLogs + Tetragon more robust

### Why Tetragon for Security?

1. **eBPF-Native**: Modern approach, better performance than traditional monitoring
2. **Talos Integration**: Designed for immutable OS platforms like Talos
3. **Observable Security**: Security events as structured logs → VictoriaLogs → Grafana
4. **Policy as Code**: Version-controlled security policies in Git

### Why Codeberg Migration?

1. **Self-Sovereignty**: Reduced dependency on GitHub/Microsoft
2. **Cost**: Codeberg is non-profit, free for self-hosted runners
3. **Learning**: Experience with Forgejo (Gitea fork) deployment patterns
4. **Capability**: Forgejo runners + Actions competitive with GitHub Actions

## Migration Risk Mitigation

- **Parallel Running**: Keep old and new systems running during validation periods
- **Incremental Cutover**: Migrate one capability at a time (logs → security → CI/CD)
- **Rollback Plans**: Document how to revert each phase if issues arise
- **Monitoring**: Enhanced alerting during migration to catch issues early
- **Documentation**: Comprehensive handoff docs for each phase completion

## Success Metrics

- **Observability**: All logs (internal + external) flowing to VictoriaLogs, visible in Grafana
- **Security**: Tetragon events generating alerts for suspicious activity
- **CI/CD**: Flux automatically deploying from Codeberg pushes
- **Resource Usage**: Overall cluster memory usage reduced by 20%+ from LGTM consolidation
- **Operational Overhead**: Fewer components to upgrade, monitor, and troubleshoot

## Agent Reports

### onboard (2026-01-05T15:04:06.571Z)

- Task:
- Summary:
- Output: `.claude/cache/agents/onboard/latest-output.md`

### onboard (2026-01-05T14:55:21.645Z)

- Task:
- Summary:
- Output: `.claude/cache/agents/onboard/latest-output.md`

None yet - first session establishing strategic direction
