# Session: wazuh-deployment

Updated: 2025-12-31T23:07:28.205Z

## Goal

Complete Wazuh security monitoring deployment on home-ops Kubernetes cluster. Done when Wazuh cluster is running with S3-backed backups and dashboard is accessible. Primary use case: Protect family (especially kids) from unwanted internet exposures, improve home security monitoring, and create reusable DevOps/SRE workflows.

## User Context

- **Experience**: Very experienced with Kubernetes/FluxCD/GitOps, learning Talos API-driven approach
- **Hardware**: 3 NUC nodes + Synology NAS (RustFS for S3)
- **Network**: Ubiquiti UDM Pro
- **Primary Goals**:
    1. Protect kids from bad content/YouTube videos
    2. Improve home security monitoring
    3. Accelerate DevOps/SRE workflows
- **Resource Constraints**: Home-lab scale, efficiency matters

## Constraints

- Must follow home-ops patterns: FluxCD + Kustomize flat manifests (converted from HelmRelease)
- SOPS-encrypted secrets for S3 credentials
- Use existing Minio S3 endpoint: https://s3.68cc.io
- OpenEBS LocalPV storage for runtime data
- S3 for backup snapshots (durability strategy)
- Namespace: security
- Sizing profile: S (home-lab resource constraints)

## Key Decisions

- Using Wazuh v4.14.1 (current stable)
- **Converted to Kustomize flat deployment** (from Helm) for better control
- Dual backup strategy: OpenSearch snapshots (indices) + Wazuh manager backups (config/databases)
- S3 bucket: wazuh-backups with separate prefixes for opensearch/ and manager/
- Daily backup schedule: 02:00 EST (07:00 UTC) for consistency with other backups
- 30-day retention for OpenSearch snapshots, 14-day for manager backups

## State

- Done:
    - [x] Wazuh Kustomize deployment configured and running
    - [x] OpenSearch indexer cluster (3 replicas) - GREEN status
    - [x] Wazuh manager master + 2 workers deployed and healthy
    - [x] Wazuh dashboard accessible at wazuh.68cc.io
    - [x] Verified wazuh-secrets exists (SOPS-encrypted with S3 credentials)
    - [x] Confirmed wazuh-backups bucket exists in RustFS at s3.68cc.io
    - [x] Validated DNS resolution and API connectivity
    - [x] Data flowing: wazuh-alerts-4.x-2025.12.30
    - [x] TLS issue resolved (was transient DNS caching during pod restarts)
    - [x] Created S3 backup implementation plan
    - [x] **Phase 1**: Install repository-s3 plugin via InitContainer on indexer StatefulSet
    - [x] **Phase 2**: Register S3 snapshot repository via Job
    - [x] **Phase 3**: Create OpenSearch snapshot CronJob (02:00 EST, 30-day retention)
    - [x] **Phase 4**: Create Wazuh manager backup CronJob (02:05 EST, 14-day retention)
    - [x] **Phase 5**: Verified backup functionality - both CronJobs tested successfully
    - [x] **Agent Deployment**: Wazuh agents running on all 3 nodes (bee-jms-01, bee-jms-02, bee-jms-03)
    - [x] **Agent Registration**: All agents successfully registered with manager (Agent IDs 001-003)
    - [x] **Agent Communication**: All agents connected to wazuh-workers (port 1514), data flowing
    - [x] **Syslog TCP Listener**: Configured on port 514 for external device logs (UDM Pro)
    - [x] **Agent Log Collection**: Comprehensive log collection configured (host logs, K8s pods, security events)
    - [x] **Dashboard API Issue Resolved**: Fixed invalid queue_size configuration in syslog remote section
    - [x] **Agent Connectivity Issue Resolved**: Fixed empty decoder file preventing wazuh-remoted from starting
    - [x] **External Agent Integration**: UDM Pro agent (ID 006) successfully connected via Envoy Gateway
- Now: [→] **WAZUH DEPLOYMENT COMPLETE** - All components operational, 4 agents (3 internal + 1 external) collecting logs, dashboard accessible
- Next:
    - [ ] Monitoring/Alerting rules for security events
    - [ ] Dashboard customization for home security use cases
    - [ ] Integration with external tools (alerts, notifications)

## Agent Deployment Complete (2025-12-30)

### Agent DaemonSet Configuration

- **Deployment**: DaemonSet running on all 3 Kubernetes nodes
- **Image**: wazuh/wazuh-agent:4.14.1
- **Registration**: Automatic via authd protocol (port 1515)
- **Communication**: TCP connection to wazuh-workers (port 1514)
- **Secret**: Uses `wazuh-secrets` SOPS-encrypted secret with `wazuhAuthdPass` key (8 chars)

### Registered Agents

```
ID: 000, Name: wazuh-manager-master-0 (server), IP: 127.0.0.1, Active/Local
ID: 001, Name: bee-jms-03, IP: any, Active
ID: 002, Name: bee-jms-01, IP: any, Active
ID: 003, Name: bee-jms-02, IP: any, Active
ID: 006, Name: udm-pro, IP: any, Active
```

### Agent Components Running

- **wazuh-agentd**: Main agent daemon - connected to manager
- **wazuh-execd**: Active response module
- **wazuh-logcollector**: Log collection (ready for configuration)
- **wazuh-modulesd**: Module management (upgrade, control)

### Key Configuration Fixes Applied

1. **Secret Reference**: Changed from non-existent `wazuh-authd-pass` to existing `wazuh-secrets`
2. **SubPath Correction**: Fixed `wazuhAuthdPassword` (30 chars) → `wazuhAuthdPass` (8 chars) to match manager
3. **YAML Separator**: Added `---` document separator for proper Flux recognition
4. **InitContainers**: 5-stage initialization (cleanup, seed, permissions, config, authd.pass)

### Agent Logs Verification

- ✅ "Valid key received" - successful registration
- ✅ "Connected to the server ([wazuh-workers]:1514/tcp)" - communication established
- ✅ All agent modules started successfully

## Log Collection Configuration (2025-12-30)

### Syslog TCP Listener

- **Manager Configuration**: Added syslog listener on port 514 (both master.conf and worker.conf)
- **Service Exposure**: wazuh-workers service exposes 514/TCP for external syslog
- **Protocol**: TCP for reliable log delivery
- **Access**: Open to all IPs (0.0.0.0/0) for UDM Pro and other network devices
- **Queue Size**: 131072 messages

### Agent Log Collection

**Host System Logs**:

- `/var/log/syslog` - General system logs
- `/var/log/messages` - System messages
- `/var/log/kern.log` - Kernel logs

**Security Logs**:

- `/var/log/auth.log` - Authentication events
- `/var/log/secure` - Security-related logs
- `/var/log/audit/audit.log` - Linux audit framework logs (audit format)

**Kubernetes Logs**:

- `/var/log/pods/*/*/*.log` - All Kubernetes pod logs (wildcard pattern)
- `/var/log/containerd.log` - Container runtime logs

### Log Collection Status

- **wazuh-logcollector**: Running on all 3 agents
- **Active Collection**: Confirmed analyzing pod logs from multiple namespaces
- **Example Collected**: security/wazuh-indexer, security/wazuh-manager-worker, system-upgrade/tuppr
- **Configuration**: Loaded successfully via InitContainer-generated ossec.conf

## Dashboard API Issue Resolution (2025-12-30)

### Issue

- **Symptom**: Dashboard showing "ERROR3099 - Server not ready yet" at https://wazuh.68cc.io/app/server-apis
- **Dashboard Logs**: `Error: connect ECONNREFUSED 10.43.244.128:55000`
- **Root Cause**: Manager logs showed `wazuh-remoted: ERROR: Invalid option <queue_size> for Syslog remote connection`

### Analysis

During syslog TCP listener configuration, I incorrectly added `<queue_size>131072</queue_size>` to the syslog remote connection section. According to Wazuh documentation and error logs, the `queue_size` option is ONLY valid for `<connection>secure</connection>` (agent connections), NOT for `<connection>syslog</connection>` (external device logs). This caused wazuh-remoted to crash on startup with a CRITICAL configuration error, preventing the entire manager from functioning and causing the dashboard API to be unreachable.

### Fix Applied

- **Removed** invalid `<queue_size>131072</queue_size>` from syslog remote section in `master.conf`
- **Removed** invalid `<queue_size>131072</queue_size>` from syslog remote section in `worker.conf`
- **Kept** `<queue_size>131072</queue_size>` only in secure connection sections where it's valid
- **Commit**: `fix(wazuh): remove invalid queue_size from syslog remote connection`

### Verification

- ✅ All 3 manager pods restarted successfully
- ✅ wazuh-remoted now running (was crashing before)
- ✅ wazuh-apid (manager API) running on port 55000
- ✅ Dashboard logs show successful 200 responses to `/api/check-stored-api`
- ✅ Dashboard accessible and functional at https://wazuh.68cc.io

### Configuration Correction

```xml
<!-- BEFORE (INVALID) -->
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>tcp</protocol>
  <allowed-ips>0.0.0.0/0</allowed-ips>
  <queue_size>131072</queue_size>  <!-- Invalid for syslog -->
</remote>

<!-- AFTER (FIXED) -->
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>tcp</protocol>
  <allowed-ips>0.0.0.0/0</allowed-ips>
</remote>
```

## Agent Connectivity Issue Resolution (2025-12-31)

### Issue

After applying TCPRoute fixes in previous session, ALL agents (both internal K8s and external UDM Pro) lost connectivity:

- **Internal K8s Agents**: `ERROR: (1216): Unable to connect to '[10.43.13.116]:1514/tcp': 'Transport endpoint is not connected'`
- **External UDM Pro Agent**: Successful registration on port 1515 but immediate disconnect from port 1514 in infinite auth loop
- **Both internal and external agents**: Could register successfully but could not maintain data streaming connection

### Root Cause Analysis

Investigation revealed critical configuration error preventing Wazuh services from starting:

1. **Decoder Configuration Error**: Empty `kubernetes_container.xml` decoder file (0 bytes) in `/var/ossec/etc/decoders/`
2. **Service Crash**: wazuh-analysisd crashed on startup with `CRITICAL: (1202): Configuration error at 'etc/decoders/kubernetes_container.xml'`
3. **Dependency Chain Failure**: s6-supervise dependency chain prevented other Wazuh services from starting when analysisd failed
4. **No Port Listener**: wazuh-remoted never started, so nothing listened on port 1514
5. **Impact**: Backend pods were Running but had no active Wazuh services, causing "transport endpoint not connected" errors

### Investigation Process

1. Verified service IP mappings (10.43.13.116 = wazuh-workers, 10.43.244.128 = wazuh)
2. Checked service endpoints (2 healthy backends registered: 10.42.0.155, 10.42.1.84)
3. Verified worker pods showing Running 1/1 status
4. Verified TCPRoutes all showing "Accepted: True"
5. Verified Envoy Gateway pods running
6. **Breakthrough**: Checked manager logs and found critical decoder errors
7. Listed running processes in manager pod - confirmed NO Wazuh services running (only s6-supervisor, filebeat, tail)
8. Examined decoder directory - identified empty `kubernetes_container.xml` file (0 bytes)
9. Read valid decoder file `00-kubernetes_container.xml` (276 bytes) to understand correct format

### Fix Applied

1. **Removed empty decoder file**:

    ```bash
    kubectl exec -n security wazuh-manager-worker-0 --context home -- \
      rm -f /var/ossec/etc/decoders/kubernetes_container.xml
    ```

2. **Restarted manager pod** to reload configuration:

    ```bash
    kubectl delete pod -n security wazuh-manager-worker-0 --context home
    ```

3. **Verified Wazuh services started** including wazuh-remoted listening on port 1514

4. **Tested agent connectivity**:
    - Internal agents bee-jms-02 and bee-jms-03 reconnected immediately
    - Internal agent bee-jms-01 required pod restart to exit retry backoff
    - External UDM Pro agent reconnected successfully

### Verification

```
All agents now Active:
ID: 000, Name: wazuh-manager-master-0 (server), IP: 127.0.0.1, Active/Local
ID: 001, Name: bee-jms-03, IP: any, Active
ID: 002, Name: bee-jms-01, IP: any, Active
ID: 003, Name: bee-jms-02, IP: any, Active
ID: 006, Name: udm-pro, IP: any, Active
```

### External Agent Configuration

Added UDM Pro as external agent:

- **Location**: 192.168.35.1 (UDM Pro device)
- **Connection**: Via Envoy Gateway at 192.168.35.18
- **Ports**: Registration (1515), Events (1514)
- **Authentication**: Uses same wazuhAuthdPass from wazuh-secrets
- **Status**: Active (ID 006)
- **TCPRoute**: External traffic routed through Envoy Gateway to wazuh-workers service

### Lessons Learned

1. **Check Backend Services**: Running pods don't guarantee listening processes - always verify services are actually running
2. **Configuration Errors**: Empty or malformed configuration files can cause cascade failures in supervisor dependency chains
3. **Decoder Files**: Valid decoder files in `/var/ossec/etc/decoders/` are critical - empty files cause analysisd to crash
4. **External Agents**: Envoy Gateway TCPRoute configuration was correct - backend service failure was the root cause

## Syslog TCP Infrastructure Validation (2025-12-31)

### Objective

Validate complete syslog TCP infrastructure for external device integration (UDM Pro and Synology NAS).

### Key Discovery

**Infrastructure Already Operational**: During testing, discovered UDM Pro (agent ID 006, 192.168.35.1) already sending syslog messages successfully through the infrastructure.

### Validation Process

1. **Decoder Library**: Verified `/var/ossec/ruleset/decoders/` contains 876 files (~200+ service-specific decoders)
2. **Service Status**: Confirmed wazuh-remoted listening on port 514/TCP for syslog
3. **Archives Config**: Confirmed `<logall>no</logall>` - raw log archiving disabled by design
4. **OpenSearch Query**: Found active UDM Pro logs with recent timestamps
5. **Format Analysis**: Confirmed BSD (RFC3164) format from actual message timestamps

### Traffic Flow Validated

```
UDM Pro (192.168.35.1:514)
  → Envoy Gateway (192.168.35.18:514)
  → TCPRoute wazuh-syslog
  → wazuh-workers Service (ClusterIP:514)
  → wazuh-manager-worker-0/1
  → wazuh-remoted → wazuh-analysisd
  → OpenSearch (wazuh-alerts-4.x-*)
```

### Syslog Format Determination

**Question**: BSD (RFC3164) or IETF (RFC5424)?

**Answer**: **BSD (RFC3164)** - Confirmed from UDM Pro traffic

**Sample Message**:

```
Dec 31 23:04:55 udm-jms-01 sudo[1296899]: ucs-update : PWD=/data/unifi-identity-update ; USER=root ; COMMAND=/sbin/ubnt-tools id
```

**Recommendation**: Use BSD (RFC3164) for Synology NAS for consistency and proven compatibility

### Documentation Deliverables

**Created**: `claudedocs/wazuh-external-syslog-setup.md` - Comprehensive setup guide including:

- Complete traffic flow and architecture
- UDM Pro working configuration
- Synology NAS setup steps (DSM Log Center)
- Syslog format comparison and recommendation
- Troubleshooting guide with verification queries
- Dashboard access instructions

**Created**: `claudedocs/wazuh-syslog-validation-handoff.md` - Session handoff document with:

- Complete investigation steps taken
- All technical findings
- Configuration references
- User action items

### Current Status

**Infrastructure**: ✅ PRODUCTION-READY

- UDM Pro actively sending logs (validated in OpenSearch)
- Syslog TCP listener operational on port 514
- Messages successfully decoded and indexed
- Dashboard accessible for log review

### User Action Items

1. **Immediate** (Optional): Access dashboard at https://wazuh.68cc.io to view UDM Pro logs
2. **Next Phase** (If desired): Configure Synology NAS using documentation in `claudedocs/wazuh-external-syslog-setup.md`

### Technical Configuration

**Syslog Listener**: `/var/ossec/etc/ossec.conf`

```xml
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>tcp</protocol>
  <allowed-ips>0.0.0.0/0</allowed-ips>
</remote>
```

**Service Exposure**: `wazuh-workers-svc.yaml` exposes port 514/TCP
**Envoy Gateway**: `wazuh-syslog-tcproute.yaml` routes to wazuh-workers

## Backup System Verified (2025-12-30)

### OpenSearch Snapshots

- **CronJob**: `opensearch-snapshot` (daily at 02:00 EST / 07:00 UTC)
- **Repository**: `wazuh-s3-snapshots` in S3 bucket `wazuh-backups/opensearch/`
- **Retention**: 30 days
- **Status**: 7 successful snapshots verified
- **Key fixes applied**:
    - Replaced `wait_for_completion=true` with polling loop (curl timeout issue)
    - BusyBox-compatible date commands for epoch math

### Manager Backups

- **CronJob**: `wazuh-manager-backup` (daily at 02:05 EST / 07:05 UTC)
- **Target**: S3 bucket `wazuh-backups/manager/`
- **Retention**: 14 days
- **Archive Size**: ~565KB (config, rules, decoders, databases)
- **Key fixes applied**:
    - Changed from amazon/aws-cli to alpine:3.21 (tar command missing)
    - Fixed PVC mount path (raw PVC with `wazuh/var/ossec/` prefix)

### CronJob Summary

```
NAME                   SCHEDULE    TIMEZONE           SUSPEND   ACTIVE
opensearch-snapshot    0 7 * * *   America/New_York   False     0
wazuh-manager-backup   5 7 * * *   America/New_York   False     0
```

## OpenSearch Cluster Status

```
Cluster: GREEN
- Nodes: 3/3 active
- Shards: 33 active (100%)
- Indices: wazuh-alerts-*, wazuh-states-inventory-*, wazuh-monitoring-*
- Snapshots: 7 successful in S3 repository
```

## Pods Status

```
All Running 1/1:
- wazuh-dashboard-5bdfdb494-qq82q
- wazuh-indexer-0, wazuh-indexer-1, wazuh-indexer-2
- wazuh-manager-master-0
- wazuh-manager-worker-0, wazuh-manager-worker-1
```

## Open Questions

- RESOLVED: TLS verification failure was transient DNS caching during restarts
- CONFIRMED: Dashboard uses DNS name wazuh-manager-master-0.wazuh-cluster for API
- CONFIRMED: S3 credentials available in wazuh-secrets (accessKeyId, secretAccessKey)

## Working Set

- Branch: `main`
- Key files:
    - `kubernetes/apps/security/wazuh/app/` - Kustomize deployment
    - `kubernetes/apps/security/wazuh/app/indexer_stack/wazuh-indexer/cluster/indexer-sts.yaml` - S3 plugin InitContainer
    - `kubernetes/apps/security/wazuh/app/indexer_stack/wazuh-indexer/opensearch-snapshot-cronjob.yaml` - Snapshot CronJob
    - `kubernetes/apps/security/wazuh/app/wazuh_managers/wazuh-backup-cronjob.yaml` - Manager backup CronJob
    - `kubernetes/apps/security/wazuh/app/secret.sops.yaml`
- **Implementation Plan**: `thoughts/shared/plans/2025-12-30-wazuh-s3-backups.md`
- Verify commands:
    - `kubectl get cronjobs -n security --context home`
    - `kubectl exec -n security wazuh-indexer-0 --context home -- curl -sk -u admin:***REDACTED*** 'https://localhost:9200/_snapshot/wazuh-s3-snapshots/_all'`
    - `kubectl logs -n security -l job-name=opensearch-snapshot-XXXXX --context home`
- Deploy commands:
    - `flux reconcile ks wazuh -n security --with-source --context home`

## Agent Reports

### implementation-agent (2025-12-30T18:35:00Z)

- Task: Implement S3 backup system (5 phases)
- Summary: All phases completed successfully with bug fixes for:
    - OpenSearch snapshot API timeout (polling instead of wait_for_completion)
    - BusyBox date command compatibility (epoch math)
    - Manager backup image missing tar (alpine:3.21)
    - PVC mount path structure (wazuh/var/ossec/ prefix)
- Output: Both CronJobs deployed and verified working

### plan-agent (2025-12-30T16:30:00Z)

- Task: Create S3 backup implementation plan
- Summary: 5-phase plan for OpenSearch snapshots and manager backups
- Output: `thoughts/shared/plans/2025-12-30-wazuh-s3-backups.md`

### onboard (2025-12-30T01:33:22.562Z)

- Task: Initial project analysis
- Summary: Tech stack detected, user goals documented
- Output: `.claude/cache/agents/onboard/latest-output.md`
