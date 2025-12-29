# Session: wazuh-deployment

Updated: 2025-12-29T19:30:00Z

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

- Must follow home-ops patterns: FluxCD + HelmRelease + OCIRepository
- SOPS-encrypted secrets for S3 credentials
- Use existing Minio S3 endpoint: https://s3.68cc.io
- OpenEBS LocalPV storage for runtime data
- S3 for backup snapshots (durability strategy)
- Namespace: security
- Sizing profile: S (home-lab resource constraints)

## Key Decisions

- Using Wazuh v4.14.1 (current stable)
- Dual backup strategy: OpenSearch snapshots (indices) + Wazuh manager backups (config/databases)
- S3 bucket: wazuh-backups with separate prefixes for opensearch/ and manager/
- Daily backup schedule: 02:00 EST for consistency with other backups
- 30-day retention for OpenSearch snapshots, 14-day for manager backups
- Hot-reload TLS enabled for certificate rotation

## State

- Done:
    - HelmRelease configuration with S3 backup setup
    - OpenSearch snapshot repository and policy configured
    - Wazuh manager backup configuration completed
    - Verified wazuh-secrets exists (SOPS-encrypted with S3 credentials)
    - Confirmed wazuh-backups bucket exists in RustFS at s3.68cc.io
    - Validated S3 credentials are correct and working
    - Created 2 commits: 46fbdd2 (gitignore) and 9f3bd38 (wazuh config)
- Now: **Debug wazuh-dashboard TLS verification failure**
- Next:
    1. Complete Wazuh deployment (resolve TLS issue)
    2. Validate backup functionality
    3. **Monitoring/Alerting Refinement Phase**:
        - Review available Grafana/Prometheus dashboards
        - Identify monitoring gaps
        - Ensure strong foundation for alerts
        - Configure alerting for family safety use cases

## Open Questions

- UNCONFIRMED: What specific TLS verification error is wazuh-dashboard showing?
- UNCONFIRMED: Are certificates properly configured for dashboard ingress?
- UNCONFIRMED: Does dashboard need custom CA trust for Minio S3 endpoint?

## Working Set

- Branch: `main`
- Key files:
    - `kubernetes/apps/security/wazuh/cluster/helmrelease.yaml`
    - `kubernetes/apps/security/wazuh/cluster/secret.sops.yaml`
    - `.gitignore`
- Debug commands:
    - `kubectl get pods -n security --context home` (check pod status)
    - `kubectl logs -n security -l app=wazuh-dashboard --context home` (dashboard logs)
    - `kubectl describe pod -n security -l app=wazuh-dashboard --context home` (pod events)
    - `kubectl get ingress -n security --context home` (ingress config)
    - `kubectl get certificates -n security --context home` (cert-manager status)
- Deploy commands:
    - `task reconcile` (force Flux sync)
    - `flux reconcile ks wazuh-cluster --with-source --context home`

## Agent Reports

### onboard (2025-12-29T18:04:45.213Z)
- Task:
- Summary:
- Output: `.claude/cache/agents/onboard/latest-output.md`

### onboard (2025-12-29T17:49:59.031Z)

- Task: Initial project analysis
- Summary: Tech stack detected, user goals documented
- Output: `.claude/cache/agents/onboard/latest-output.md`
