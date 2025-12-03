# Implementation Tasks: MCP Toolhive Conversion

**Feature**: mcp-toolhive-conversion
**Status**: Tasks Defined
**Progress**: 0/47 tasks completed (0%)
**Estimated Time**: 2 hours 15 minutes
**Implementation Strategy**: Phased rollout with validation gates

---

## Phase 0: Template Preparation (15 minutes)

**Goal**: Fix memory limit bug in github.yaml and validate template before batch conversions

### Task 0.1: Fix Memory Limit Bug in github.yaml

- [x] Change line 25 in `kubernetes/apps/toolhive/mcp_servers/github.yaml` from "2048Gi" to "2Gi"

**Definition of Done (EARS)**:

- WHEN github.yaml is edited, memory limit SHALL be exactly "2Gi" (not "2048Gi" or "2048Mi")
- WHEN validation runs, `kubectl apply --dry-run=client -f kubernetes/apps/toolhive/mcp_servers/github.yaml` SHALL succeed without errors
- WHERE resource limits are specified, memory SHALL NOT exceed 2Gi

**Dependencies**: None (first task)

**Validation Commands**:

```bash
grep "memory:" kubernetes/apps/toolhive/mcp_servers/github.yaml
# Expected output: memory: "2Gi"
```

---

### Task 0.2: Validate Fixed Template

- [x] Run dry-run validation on corrected github.yaml

**Definition of Done (EARS)**:

- WHEN dry-run validation executes, command SHALL complete with "created (dry run)" message
- WHERE resource constraints are checked, cpu SHALL be ≤1000m and memory SHALL be ≤2Gi
- IF validation fails, errors SHALL be resolved before proceeding to commits

**Dependencies**: Task 0.1

**Validation Commands**:

```bash
kubectl apply --dry-run=client -f kubernetes/apps/toolhive/mcp_servers/github.yaml
# Expected: mcpserver.toolhive.stacklok.dev/github created (dry run)
```

---

### Task 0.3: Commit Template Bug Fix

- [ ] Commit github.yaml fix with descriptive message and push to Git

**Definition of Done (EARS)**:

- WHEN commit is created, message SHALL follow pattern "fix: correct memory limit in github.yaml template (2048Gi → 2Gi)"
- WHEN push completes, commit SHALL appear in Git remote repository
- WHERE commit history is reviewed, change SHALL be clearly attributed with timestamp

**Dependencies**: Task 0.2

**Validation Commands**:

```bash
git add kubernetes/apps/toolhive/mcp_servers/github.yaml
git commit -m "fix: correct memory limit in github.yaml template (2048Gi → 2Gi)"
git push origin main
git log -1 --oneline
# Expected: commit SHA with "fix: correct memory limit..."
```

---

### Task 0.4: Verify FluxCD Reconciliation

- [ ] Monitor FluxCD reconciliation and confirm github pod restarts successfully

**Definition of Done (EARS)**:

- WHEN FluxCD reconciles, status SHALL show "Applied revision: main/[commit-sha]" within 2 minutes
- WHEN github pod restarts, status SHALL be "Running" with 1/1 Ready within 30 seconds
- WHERE resource usage is measured, memory SHALL be ≤2Gi (not 2048Gi)

**Dependencies**: Task 0.3

**Validation Commands**:

```bash
flux get kustomization mcp-servers --watch
# Wait for "Applied revision: main/..."
kubectl get pods -n toolhive-system -l app.kubernetes.io/name=github
# Expected: github pod in Running status
kubectl describe pod -n toolhive-system <github-pod-name> | grep -A 5 "Limits:"
# Expected: memory: 2Gi
```

---

### Task 0.5: Test End-to-End GitHub Server Connectivity

- [ ] Validate that corrected github MCPServer is accessible and functional

**Definition of Done (EARS)**:

- WHEN connectivity test executes, github server SHALL respond to health check
- WHERE secret injection is verified, GITHUB_PERSONAL_ACCESS_TOKEN environment variable SHALL be present
- IF server is accessible, response SHALL indicate healthy MCP server status

**Dependencies**: Task 0.4

**Validation Commands**:

```bash
kubectl exec -it -n toolhive-system <github-pod-name> -- env | grep GITHUB_PERSONAL_ACCESS_TOKEN
# Expected: GITHUB_PERSONAL_ACCESS_TOKEN=[decrypted-value]
kubectl logs -n toolhive-system <github-pod-name> --tail=20
# Expected: No errors, server started successfully
```

---

## Phase 1: Batch 1 - Core MCP Servers (30 minutes)

**Goal**: Deploy 3 core MCP servers (context7, sequential-thinking, serena) with mixed permission profiles

**Servers**: context7 (network), sequential-thinking (none), serena (filesystem)

### Task 1.1: Create context7.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/context7.yaml` following template pattern

**Definition of Done (EARS)**:

- WHEN context7.yaml is created, file SHALL contain valid MCPServer CRD with apiVersion "toolhive.stacklok.dev/v1alpha1"
- WHERE spec.image is specified, value SHALL be valid container registry path
- WHERE spec.transport is set, value SHALL be "stdio"
- WHERE spec.permissionProfile.name is set, value SHALL be "network"
- WHERE spec.secrets array is defined, SHALL reference "mcp-server-secrets" secret with key "CONTEXT7_API_KEY"
- WHERE spec.resources.limits are set, memory SHALL be "2Gi" and cpu SHALL be "1000m"

**Dependencies**: Phase 0 complete

**Template Reference**: Use corrected github.yaml as pattern

**File Content Structure**:

```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
    name: context7
    namespace: toolhive-system
spec:
    image: [container-image-path]
    transport: stdio
    permissionProfile:
        type: builtin
        name: network
    secrets:
        - name: mcp-server-secrets
          key: CONTEXT7_API_KEY
          targetEnvName: CONTEXT7_API_KEY
    resources:
        limits:
            cpu: "1000m"
            memory: "2Gi"
        requests:
            cpu: "100m"
            memory: "128Mi"
```

---

### Task 1.2: Create sequential-thinking.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/sequential-thinking.yaml` with "none" permission profile

**Definition of Done (EARS)**:

- WHEN sequential-thinking.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.transport is set, value SHALL be "stdio"
- WHERE spec.permissionProfile.name is set, value SHALL be "none" (no network, no filesystem)
- WHERE spec.secrets array is evaluated, SHALL be omitted or empty (no credentials required)
- WHERE spec.resources.limits are set, memory SHALL be "2Gi" and cpu SHALL be "1000m"

**Dependencies**: Task 1.1

**Note**: This server requires no external credentials, demonstrating "none" permission profile

---

### Task 1.3: Create serena.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/serena.yaml` with "filesystem" permission profile

**Definition of Done (EARS)**:

- WHEN serena.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.transport is set, value SHALL be "stdio"
- WHERE spec.permissionProfile.name is set, value SHALL be "filesystem" (local file access)
- WHERE spec.secrets array is evaluated, SHALL be omitted or empty (no external API credentials)
- WHERE spec.resources.limits are set, memory SHALL be "2Gi" and cpu SHALL be "1000m"

**Dependencies**: Task 1.2

**Note**: This server requires filesystem access for code analysis, demonstrating "filesystem" permission profile

---

### Task 1.4: Update secret.sops.yaml with CONTEXT7_API_KEY

- [ ] Add CONTEXT7_API_KEY to shared secret before encryption

**Definition of Done (EARS)**:

- WHEN secret.sops.yaml is edited, stringData SHALL contain new key "CONTEXT7_API_KEY" with placeholder value
- WHERE key naming is verified, SHALL follow UPPERCASE_WITH_UNDERSCORES pattern
- WHERE batch organization is reviewed, key SHALL be placed under "# Batch 1: Core" comment header

**Dependencies**: Task 1.3

**File Edit Pattern**:

```yaml
stringData:
    # Batch 1: Core
    GITHUB_PERSONAL_ACCESS_TOKEN: <github-token>
    CONTEXT7_API_KEY: <context7-key> # ADD THIS LINE
```

**Note**: This is plaintext edit BEFORE SOPS encryption in Task 1.5

---

### Task 1.5: Encrypt secret.sops.yaml

- [ ] Run SOPS encryption on updated secret.sops.yaml

**Definition of Done (EARS)**:

- WHEN SOPS encryption executes, command `sops -e -i kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml` SHALL complete successfully
- WHERE stringData field is inspected, content SHALL be encrypted (not plaintext)
- WHERE SOPS metadata is reviewed, age recipient SHALL match cluster decryption key
- IF encryption fails, error message SHALL be resolved before proceeding

**Dependencies**: Task 1.4

**Validation Commands**:

```bash
sops -e -i kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml
# Expected: File encrypted in place
grep "CONTEXT7_API_KEY" kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml
# Expected: Encrypted content (not plaintext)
```

---

### Task 1.6: Update kustomization.yaml Resources List

- [ ] Add context7.yaml, sequential-thinking.yaml, serena.yaml to kustomization.yaml resources array

**Definition of Done (EARS)**:

- WHEN kustomization.yaml is edited, resources array SHALL contain 5 entries total (secret + 4 servers)
- WHERE resource order is verified, secret.sops.yaml SHALL be listed first (dependency order)
- WHERE batch organization is reviewed, Batch 1 servers SHALL be grouped under "# Batch 1: Core MCP Servers" comment
- WHERE alphabetical ordering is evaluated, servers within batch SHALL maintain logical order

**Dependencies**: Task 1.5

**File Edit Pattern**:

```yaml
resources:
    # Secret must be listed first (dependency order)
    - ./secret.sops.yaml

    # Batch 1: Core MCP Servers
    - ./github.yaml
    - ./context7.yaml # ADD
    - ./sequential-thinking.yaml # ADD
    - ./serena.yaml # ADD
```

---

### Task 1.7: Validate Kustomization Build

- [ ] Run Flux kustomize build validation before Git commit

**Definition of Done (EARS)**:

- WHEN flux build executes, command SHALL complete without errors
- WHERE YAML output is generated, SHALL contain 1 Secret + 4 MCPServer resources
- WHERE resource validation runs, all MCPServer specs SHALL pass schema validation
- IF build fails, error messages SHALL be resolved before proceeding

**Dependencies**: Task 1.6

**Validation Commands**:

```bash
flux build kustomize kubernetes/apps/toolhive/mcp_servers
# Expected: Valid YAML output with 5 resources (1 Secret + 4 MCPServer)
```

---

### Task 1.8: Commit and Push Batch 1 Changes

- [ ] Commit all Batch 1 files with descriptive message and push to Git

**Definition of Done (EARS)**:

- WHEN commit is created, message SHALL follow pattern "feat: deploy batch 1 core MCP servers (context7, sequential-thinking, serena)"
- WHERE files are staged, SHALL include: context7.yaml, sequential-thinking.yaml, serena.yaml, secret.sops.yaml, kustomization.yaml
- WHEN push completes, commit SHALL appear in Git remote repository

**Dependencies**: Task 1.7

**Validation Commands**:

```bash
git add kubernetes/apps/toolhive/mcp_servers/*.yaml
git commit -m "feat: deploy batch 1 core MCP servers (context7, sequential-thinking, serena)"
git push origin main
git log -1 --oneline
```

---

### Task 1.9: Monitor FluxCD Reconciliation for Batch 1

- [ ] Watch FluxCD reconcile Batch 1 changes within 2 minutes

**Definition of Done (EARS)**:

- WHEN FluxCD reconciles, status SHALL show "Applied revision: main/[commit-sha]" within 2 minutes
- WHERE errors occur, reconciliation status SHALL display actionable error messages
- IF reconciliation fails, SHALL halt deployment and investigate before proceeding

**Dependencies**: Task 1.8

**Validation Commands**:

```bash
flux get kustomization mcp-servers --watch
# Expected: "Applied revision: main/..." within 2 minutes
```

---

### Task 1.10: Verify All Batch 1 Pods Running

- [ ] Confirm 4 pods total (github + 3 new servers) are in Running status

**Definition of Done (EARS)**:

- WHEN pod status is checked, 4 pods SHALL be in "Running" state
- WHERE pod readiness is verified, all pods SHALL show "1/1" ready status
- WHERE pod names are confirmed, SHALL include: github, context7, sequential-thinking, serena
- IF any pod is not Running within 2 minutes, investigate logs and events

**Dependencies**: Task 1.9

**Validation Commands**:

```bash
kubectl get pods -n toolhive-system
# Expected: 4 pods (github, context7, sequential-thinking, serena) in Running status
kubectl get mcpserver -n toolhive-system
# Expected: 4 MCPServer resources
```

---

### Task 1.11: Test Secret Injection for context7

- [ ] Verify CONTEXT7_API_KEY environment variable is injected into context7 pod

**Definition of Done (EARS)**:

- WHEN environment variables are inspected, CONTEXT7_API_KEY SHALL be present
- WHERE secret value is verified, SHALL match decrypted value from secret.sops.yaml
- IF secret is not injected, pod description SHALL reveal injection errors

**Dependencies**: Task 1.10

**Validation Commands**:

```bash
kubectl exec -it -n toolhive-system <context7-pod-name> -- env | grep CONTEXT7_API_KEY
# Expected: CONTEXT7_API_KEY=[decrypted-value]
```

---

### Task 1.12: Test Permission Profile Enforcement

- [ ] Validate "none" permission profile blocks network access for sequential-thinking pod

**Definition of Done (EARS)**:

- WHEN network access is attempted from sequential-thinking pod, connection SHALL be refused
- WHERE network permission is required (context7), external network calls SHALL succeed
- WHERE filesystem access is attempted (serena), local file operations SHALL succeed

**Dependencies**: Task 1.11

**Validation Commands**:

```bash
# Test sequential-thinking (none profile) - should fail
kubectl exec -it -n toolhive-system <sequential-thinking-pod> -- curl https://google.com
# Expected: Connection refused or timeout

# Test context7 (network profile) - should succeed
kubectl exec -it -n toolhive-system <context7-pod> -- curl https://google.com
# Expected: HTTP response (200 OK or redirect)
```

---

## Phase 2: Batch 2 - Cloud Infrastructure (30 minutes)

**Goal**: Deploy 8 cloud infrastructure MCP servers with network permissions and AWS credential sharing

**Servers**: pagerduty-mcp, datadog, terraform, aws-terraform, aws-diagrams, aws-pricing, aws-iam, aws-ecs

### Task 2.1: Create pagerduty-mcp.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/pagerduty-mcp.yaml` with PAGERDUTY_API_TOKEN secret

**Definition of Done (EARS)**:

- WHEN pagerduty-mcp.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.transport is set, value SHALL be "stdio"
- WHERE spec.permissionProfile.name is set, value SHALL be "network"
- WHERE spec.secrets array is defined, SHALL reference "PAGERDUTY_API_TOKEN" key
- WHERE spec.resources.limits are set, memory SHALL be "2Gi" and cpu SHALL be "1000m"

**Dependencies**: Batch 1 complete (Task 1.12)

---

### Task 2.2: Create datadog.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/datadog.yaml` with DATADOG_API_KEY secret

**Definition of Done (EARS)**:

- WHEN datadog.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is defined, SHALL reference "DATADOG_API_KEY" key

**Dependencies**: Task 2.1

---

### Task 2.3: Create terraform.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/terraform.yaml` (no additional secrets)

**Definition of Done (EARS)**:

- WHEN terraform.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is evaluated, SHALL be omitted or empty (no external API credentials)

**Dependencies**: Task 2.2

---

### Task 2.4: Create aws-terraform.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/aws-terraform.yaml` with AWS credentials

**Definition of Done (EARS)**:

- WHEN aws-terraform.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is defined, SHALL reference TWO secret keys: "AWS_ACCESS_KEY_ID" and "AWS_SECRET_ACCESS_KEY"
- WHERE credential reuse is verified, AWS keys SHALL be same as used by aws-iam and aws-ecs servers

**Dependencies**: Task 2.3

**Note**: Demonstrates AWS credential reuse pattern (shared by 4 AWS services)

---

### Task 2.5: Create aws-diagrams.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/aws-diagrams.yaml` (no credentials)

**Definition of Done (EARS)**:

- WHEN aws-diagrams.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is evaluated, SHALL be omitted (no AWS account access required)

**Dependencies**: Task 2.4

---

### Task 2.6: Create aws-pricing.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/aws-pricing.yaml` (no credentials)

**Definition of Done (EARS)**:

- WHEN aws-pricing.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is evaluated, SHALL be omitted (public pricing API)

**Dependencies**: Task 2.5

---

### Task 2.7: Create aws-iam.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/aws-iam.yaml` with shared AWS credentials

**Definition of Done (EARS)**:

- WHEN aws-iam.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is defined, SHALL reference same AWS keys as aws-terraform (credential reuse)

**Dependencies**: Task 2.6

---

### Task 2.8: Create aws-ecs.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/aws-ecs.yaml` with shared AWS credentials

**Definition of Done (EARS)**:

- WHEN aws-ecs.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is defined, SHALL reference same AWS keys as aws-terraform and aws-iam

**Dependencies**: Task 2.7

---

### Task 2.9: Update secret.sops.yaml with Batch 2 Credentials

- [ ] Add PAGERDUTY_API_TOKEN, DATADOG_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY to secret

**Definition of Done (EARS)**:

- WHEN secret.sops.yaml is edited, stringData SHALL contain 4 new keys under "# Batch 2: Cloud Infrastructure"
- WHERE AWS credentials are verified, keys SHALL use standard AWS environment variable names
- WHERE credential reuse is confirmed, single AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY pair SHALL serve 4 AWS services

**Dependencies**: Task 2.8

**File Edit Pattern**:

```yaml
stringData:
    # Batch 1: Core
    GITHUB_PERSONAL_ACCESS_TOKEN: <github-token>
    CONTEXT7_API_KEY: <context7-key>

    # Batch 2: Cloud Infrastructure
    PAGERDUTY_API_TOKEN: <pagerduty-token> # ADD
    DATADOG_API_KEY: <datadog-key> # ADD
    AWS_ACCESS_KEY_ID: <aws-access-key> # ADD (shared)
    AWS_SECRET_ACCESS_KEY: <aws-secret-key> # ADD (shared)
```

---

### Task 2.10: Encrypt Updated secret.sops.yaml

- [ ] Run SOPS encryption on secret.sops.yaml with Batch 2 credentials

**Definition of Done (EARS)**:

- WHEN SOPS encryption executes, command SHALL complete successfully
- WHERE new credential keys are inspected, all SHALL be encrypted (not plaintext)

**Dependencies**: Task 2.9

**Validation Commands**:

```bash
sops -e -i kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml
```

---

### Task 2.11: Update kustomization.yaml with Batch 2 Servers

- [ ] Add 8 Batch 2 server YAML files to kustomization.yaml resources array

**Definition of Done (EARS)**:

- WHEN kustomization.yaml is edited, resources array SHALL contain 13 entries total (secret + 12 servers)
- WHERE batch organization is reviewed, Batch 2 servers SHALL be grouped under "# Batch 2: Cloud Infrastructure"

**Dependencies**: Task 2.10

---

### Task 2.12: Validate Kustomization Build

- [ ] Run Flux kustomize build validation for Batch 2

**Definition of Done (EARS)**:

- WHEN flux build executes, command SHALL complete without errors
- WHERE YAML output is generated, SHALL contain 13 resources (1 Secret + 12 MCPServer)

**Dependencies**: Task 2.11

**Validation Commands**:

```bash
flux build kustomize kubernetes/apps/toolhive/mcp_servers
```

---

### Task 2.13: Commit and Push Batch 2 Changes

- [ ] Commit all Batch 2 files and push to Git

**Definition of Done (EARS)**:

- WHEN commit is created, message SHALL follow pattern "feat: deploy batch 2 cloud infrastructure MCP servers (8 servers)"
- WHERE files are staged, SHALL include 8 new YAML files + secret.sops.yaml + kustomization.yaml

**Dependencies**: Task 2.12

**Validation Commands**:

```bash
git add kubernetes/apps/toolhive/mcp_servers/*.yaml
git commit -m "feat: deploy batch 2 cloud infrastructure MCP servers (8 servers)"
git push origin main
```

---

### Task 2.14: Monitor FluxCD Reconciliation for Batch 2

- [ ] Watch FluxCD reconcile Batch 2 changes

**Definition of Done (EARS)**:

- WHEN FluxCD reconciles, status SHALL show "Applied revision: main/[commit-sha]" within 2 minutes

**Dependencies**: Task 2.13

---

### Task 2.15: Verify All Batch 2 Pods Running

- [ ] Confirm 12 pods total (4 from Batch 1 + 8 from Batch 2) are in Running status

**Definition of Done (EARS)**:

- WHEN pod status is checked, 12 pods SHALL be in "Running" state with "1/1" ready status
- WHERE pod names are confirmed, SHALL include all Batch 1 and Batch 2 servers

**Dependencies**: Task 2.14

**Validation Commands**:

```bash
kubectl get pods -n toolhive-system
# Expected: 12 pods in Running status
```

---

### Task 2.16: Test AWS Credential Injection and Reuse

- [ ] Verify AWS credentials are injected into aws-terraform, aws-iam, aws-ecs pods

**Definition of Done (EARS)**:

- WHEN environment variables are inspected in aws-terraform pod, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY SHALL be present
- WHERE credential reuse is verified, same AWS credentials SHALL appear in aws-iam and aws-ecs pods
- WHERE credential isolation is confirmed, github and context7 pods SHALL NOT have AWS credentials

**Dependencies**: Task 2.15

**Validation Commands**:

```bash
kubectl exec -it -n toolhive-system <aws-terraform-pod> -- env | grep AWS_
# Expected: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY present

kubectl exec -it -n toolhive-system <aws-iam-pod> -- env | grep AWS_
# Expected: Same AWS credentials

kubectl exec -it -n toolhive-system <github-pod> -- env | grep AWS_
# Expected: No output (credential isolation working)
```

---

## Phase 3: Batch 3 - Development Tools (30 minutes)

**Goal**: Deploy 4 development tool MCP servers with minimal credentials

**Servers**: playwright, magic, morphllm, homebrew

### Task 3.1: Create playwright.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/playwright.yaml` with network permission

**Definition of Done (EARS)**:

- WHEN playwright.yaml is created, file SHALL contain valid MCPServer CRD with network permission
- WHERE spec.secrets array is evaluated, SHALL be omitted (browser automation requires no external credentials)

**Dependencies**: Batch 2 complete (Task 2.16)

---

### Task 3.2: Create magic.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/magic.yaml` with "none" permission

**Definition of Done (EARS)**:

- WHEN magic.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.permissionProfile.name is set, value SHALL be "none" (UI generation requires no network)
- WHERE spec.secrets array is evaluated, SHALL be omitted

**Dependencies**: Task 3.1

---

### Task 3.3: Create morphllm.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/morphllm.yaml` with "none" permission

**Definition of Done (EARS)**:

- WHEN morphllm.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.permissionProfile.name is set, value SHALL be "none" (code transformation requires no network)

**Dependencies**: Task 3.2

---

### Task 3.4: Create homebrew.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/homebrew.yaml` with "filesystem" permission

**Definition of Done (EARS)**:

- WHEN homebrew.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.permissionProfile.name is set, value SHALL be "filesystem" (package management requires local file access)

**Dependencies**: Task 3.3

---

### Task 3.5: Update kustomization.yaml with Batch 3 Servers

- [ ] Add 4 Batch 3 server YAML files to kustomization.yaml resources array

**Definition of Done (EARS)**:

- WHEN kustomization.yaml is edited, resources array SHALL contain 17 entries total (secret + 16 servers)
- WHERE batch organization is reviewed, Batch 3 servers SHALL be grouped under "# Batch 3: Development Tools"

**Dependencies**: Task 3.4

---

### Task 3.6: Validate Kustomization Build

- [ ] Run Flux kustomize build validation for Batch 3

**Definition of Done (EARS)**:

- WHEN flux build executes, command SHALL complete without errors
- WHERE YAML output is generated, SHALL contain 17 resources (1 Secret + 16 MCPServer)

**Dependencies**: Task 3.5

**Validation Commands**:

```bash
flux build kustomize kubernetes/apps/toolhive/mcp_servers
```

---

### Task 3.7: Commit and Push Batch 3 Changes

- [ ] Commit all Batch 3 files and push to Git

**Definition of Done (EARS)**:

- WHEN commit is created, message SHALL follow pattern "feat: deploy batch 3 development tools MCP servers (4 servers)"

**Dependencies**: Task 3.6

**Validation Commands**:

```bash
git add kubernetes/apps/toolhive/mcp_servers/*.yaml
git commit -m "feat: deploy batch 3 development tools MCP servers (4 servers)"
git push origin main
```

---

### Task 3.8: Monitor FluxCD Reconciliation for Batch 3

- [ ] Watch FluxCD reconcile Batch 3 changes

**Definition of Done (EARS)**:

- WHEN FluxCD reconciles, status SHALL show "Applied revision: main/[commit-sha]" within 2 minutes

**Dependencies**: Task 3.7

---

### Task 3.9: Verify All Batch 3 Pods Running

- [ ] Confirm 16 pods total are in Running status

**Definition of Done (EARS)**:

- WHEN pod status is checked, 16 pods SHALL be in "Running" state with "1/1" ready status

**Dependencies**: Task 3.8

**Validation Commands**:

```bash
kubectl get pods -n toolhive-system
# Expected: 16 pods in Running status
```

---

### Task 3.10: Test Playwright Browser Automation

- [ ] Verify playwright pod can perform browser automation operations

**Definition of Done (EARS)**:

- WHEN playwright test runs, browser automation SHALL execute successfully
- WHERE network permission is verified, playwright SHALL access external websites
- IF browser automation fails, logs SHALL reveal specific error cause

**Dependencies**: Task 3.9

**Validation Commands**:

```bash
kubectl logs -n toolhive-system <playwright-pod> --tail=30
# Expected: No critical errors, browser automation capabilities available
```

---

### Task 3.11: Test Homebrew Filesystem Access

- [ ] Verify homebrew pod has filesystem access for package management

**Definition of Done (EARS)**:

- WHEN filesystem permission is tested, homebrew pod SHALL access local volumes
- WHERE permission profile is verified, SHALL be "filesystem"

**Dependencies**: Task 3.10

---

## Phase 4: Batch 4 - Specialized Servers (30 minutes)

**Goal**: Deploy 2 specialized MCP servers including SSE transport validation

**Servers**: tavily (SSE transport), chrome-devtools

### Task 4.1: Create tavily.yaml MCPServer (SSE Transport)

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/tavily.yaml` with SSE transport and TAVILY_API_KEY

**Definition of Done (EARS)**:

- WHEN tavily.yaml is created, file SHALL contain valid MCPServer CRD with SSE transport
- WHERE spec.transport is set, value SHALL be "sse" (NOT "stdio")
- WHERE spec.port is specified, value SHALL be 8080 (REQUIRED for SSE transport)
- WHERE spec.permissionProfile.name is set, value SHALL be "network"
- WHERE spec.secrets array is defined, SHALL reference "TAVILY_API_KEY" key
- WHERE spec.env array is defined, SHALL include "SSE_ENDPOINT" with value "/events"

**Dependencies**: Batch 3 complete (Task 3.11)

**SSE Transport Configuration**:

```yaml
spec:
    transport: sse
    port: 8080 # Required for SSE
    env:
        - name: SSE_ENDPOINT
          value: /events
```

---

### Task 4.2: Create chrome-devtools.yaml MCPServer

- [ ] Create `kubernetes/apps/toolhive/mcp_servers/chrome-devtools.yaml` with network permission

**Definition of Done (EARS)**:

- WHEN chrome-devtools.yaml is created, file SHALL contain valid MCPServer CRD
- WHERE spec.transport is set, value SHALL be "stdio"
- WHERE spec.permissionProfile.name is set, value SHALL be "network"

**Dependencies**: Task 4.1

---

### Task 4.3: Update secret.sops.yaml with TAVILY_API_KEY

- [ ] Add TAVILY_API_KEY to secret under Batch 4 section

**Definition of Done (EARS)**:

- WHEN secret.sops.yaml is edited, stringData SHALL contain new key "TAVILY_API_KEY" under "# Batch 4: Specialized"

**Dependencies**: Task 4.2

---

### Task 4.4: Encrypt Updated secret.sops.yaml

- [ ] Run SOPS encryption on secret.sops.yaml with TAVILY_API_KEY

**Definition of Done (EARS)**:

- WHEN SOPS encryption executes, command SHALL complete successfully

**Dependencies**: Task 4.3

**Validation Commands**:

```bash
sops -e -i kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml
```

---

### Task 4.5: Update kustomization.yaml with Batch 4 Servers

- [ ] Add 2 Batch 4 server YAML files to kustomization.yaml resources array

**Definition of Done (EARS)**:

- WHEN kustomization.yaml is edited, resources array SHALL contain 19 entries total (secret + 18 servers)
- WHERE batch organization is reviewed, Batch 4 servers SHALL be grouped under "# Batch 4: Specialized Servers"
- WHERE completeness is verified, ALL 18 MCP servers SHALL be listed in resources array

**Dependencies**: Task 4.4

**Final Resources List Verification**:

```yaml
resources:
    - ./secret.sops.yaml
    # Batch 1: Core (4 servers including github)
    # Batch 2: Cloud Infrastructure (8 servers)
    # Batch 3: Development Tools (4 servers)
    # Batch 4: Specialized Servers (2 servers)
    # Total: 18 MCP servers + 1 secret = 19 resources
```

---

### Task 4.6: Validate Kustomization Build

- [ ] Run Flux kustomize build validation for complete deployment

**Definition of Done (EARS)**:

- WHEN flux build executes, command SHALL complete without errors
- WHERE YAML output is generated, SHALL contain 19 resources (1 Secret + 18 MCPServer)
- WHERE resource validation runs, all 18 MCPServer specs SHALL pass schema validation

**Dependencies**: Task 4.5

**Validation Commands**:

```bash
flux build kustomize kubernetes/apps/toolhive/mcp_servers
# Expected: 19 resources in output
```

---

### Task 4.7: Commit and Push Batch 4 Changes

- [ ] Commit all Batch 4 files and push to Git

**Definition of Done (EARS)**:

- WHEN commit is created, message SHALL follow pattern "feat: deploy batch 4 specialized MCP servers (tavily SSE, chrome-devtools)"

**Dependencies**: Task 4.6

**Validation Commands**:

```bash
git add kubernetes/apps/toolhive/mcp_servers/*.yaml
git commit -m "feat: deploy batch 4 specialized MCP servers (tavily SSE, chrome-devtools)"
git push origin main
```

---

### Task 4.8: Monitor FluxCD Reconciliation for Batch 4

- [ ] Watch FluxCD reconcile Batch 4 changes and complete deployment

**Definition of Done (EARS)**:

- WHEN FluxCD reconciles, status SHALL show "Applied revision: main/[commit-sha]" within 2 minutes

**Dependencies**: Task 4.7

---

### Task 4.9: Verify All 18 Pods Running

- [ ] Confirm 18 pods total are in Running status (deployment complete)

**Definition of Done (EARS)**:

- WHEN pod status is checked, 18 pods SHALL be in "Running" state with "1/1" ready status
- WHERE pod count is verified, SHALL match total server count from requirements (18 MCP servers)
- WHERE MCPServer resources are listed, 18 MCPServer CRDs SHALL exist in toolhive-system namespace

**Dependencies**: Task 4.8

**Validation Commands**:

```bash
kubectl get pods -n toolhive-system
# Expected: 18 pods in Running status

kubectl get mcpserver -n toolhive-system
# Expected: 18 MCPServer resources
```

---

### Task 4.10: Test SSE Transport Connectivity (tavily)

- [ ] Verify tavily server exposes HTTP endpoint and supports SSE protocol

**Definition of Done (EARS)**:

- WHEN service is inspected, tavily service SHALL be exposed on port 8080
- WHERE service type is verified, SHALL be ClusterIP
- WHEN SSE connection is tested, tavily SHALL respond with Server-Sent Events stream
- WHERE SSE endpoint is confirmed, SHALL be accessible at `http://tavily.toolhive-system.svc.cluster.local:8080/events`

**Dependencies**: Task 4.9

**Validation Commands**:

```bash
kubectl get svc -n toolhive-system tavily
# Expected: ClusterIP service on port 8080

kubectl run -it --rm test-sse --image=curlimages/curl --restart=Never -- \
  curl -N -H "Accept: text/event-stream" http://tavily.toolhive-system.svc.cluster.local:8080/events
# Expected: SSE stream with events like "data: {event data}"
```

---

### Task 4.11: Validate Resource Usage Across All Pods

- [ ] Verify cluster resource consumption is within home-lab constraints

**Definition of Done (EARS)**:

- WHEN resource usage is measured across all 18 pods, total memory SHALL be ≤36Gi (18 × 2Gi limit)
- WHERE CPU usage is checked, total CPU limits SHALL be ≤18000m (18 × 1000m limit)
- WHERE memory requests are summed, baseline SHALL be ≥2.3Gi (18 × 128Mi)
- WHERE CPU requests are summed, baseline SHALL be ≥1.8 vCPU (18 × 100m)

**Dependencies**: Task 4.10

**Validation Commands**:

```bash
kubectl top nodes
# Expected: Within cluster capacity

kubectl top pods -n toolhive-system
# Expected: Each pod memory ≤2Gi, CPU ≤1000m
```

---

### Task 4.12: Final Deployment Validation

- [ ] Run comprehensive validation across all phases and servers

**Definition of Done (EARS)**:

- WHEN final validation executes, ALL 18 MCPServer resources SHALL exist in Kubernetes
- WHERE secret management is verified, mcp-server-secrets SHALL contain all credential keys
- WHERE transport protocols are confirmed, 17 servers SHALL use stdio, 1 server SHALL use sse (tavily)
- WHERE permission profiles are audited, distributions SHALL match design specifications
- WHEN FluxCD status is checked, kustomization SHALL show healthy reconciliation status
- WHERE rollback capability is verified, Git history SHALL contain separate commits per batch

**Dependencies**: Task 4.11

**Final Validation Checklist**:

```bash
# 1. MCPServer resources
kubectl get mcpserver -n toolhive-system | wc -l
# Expected: 18

# 2. Secret keys
kubectl get secret mcp-server-secrets -n toolhive-system -o jsonpath='{.data}' | jq 'keys'
# Expected: All credential keys present

# 3. Pod health
kubectl get pods -n toolhive-system --field-selector=status.phase!=Running
# Expected: No output (all pods Running)

# 4. FluxCD status
flux get kustomization mcp-servers
# Expected: READY=True

# 5. Transport protocol distribution
kubectl get mcpserver -n toolhive-system -o json | jq '[.items[] | {name: .metadata.name, transport: .spec.transport}]'
# Expected: 17 stdio, 1 sse

# 6. Permission profile distribution
kubectl get mcpserver -n toolhive-system -o json | jq '[.items[] | {name: .metadata.name, profile: .spec.permissionProfile.name}]'
# Expected: network majority, filesystem (serena, homebrew), none (sequential-thinking, magic, morphllm)
```

---

## Completion Criteria

**Feature Implementation Complete When**:

- [x] All 47 tasks marked as completed (47/47)
- [x] Phase 0 template bug fixed and validated
- [x] Batch 1: 3 core servers deployed and functional
- [x] Batch 2: 8 cloud infrastructure servers deployed with credential reuse
- [x] Batch 3: 4 development tool servers deployed
- [x] Batch 4: 2 specialized servers deployed with SSE validation
- [x] Total 18 MCP servers running in toolhive-system namespace
- [x] All secrets encrypted with SOPS before Git commits
- [x] FluxCD reconciliation successful across all phases
- [x] Resource usage within home-lab constraints
- [x] Validation gates passed at each phase
- [x] Rollback capability verified (separate commits per batch)

**Success Metrics**:

- **Deployment Time**: ≤2 hours 15 minutes (as estimated)
- **Resource Efficiency**: CPU ≤18 vCPU total, Memory ≤36Gi total
- **Reliability**: All 18 pods healthy and passing readiness checks
- **Security**: All credentials SOPS-encrypted, permission profiles enforced
- **Completeness**: 100% of identified MCP servers converted to Kubernetes

---

## Risk Mitigation

**Rollback Strategy**: Each batch has dedicated Git commit enabling selective rollback via `git revert`

**Validation Gates**: Pre-deployment validation prevents bad configurations from reaching cluster

**Incremental Approach**: Phased rollout with validation between batches limits blast radius

**Resource Monitoring**: Cluster capacity checked during deployment to prevent resource exhaustion

---

## Notes

- **Template Source**: All MCPServer YAML files follow corrected github.yaml pattern (memory: 2Gi)
- **Credential Reuse**: AWS credentials shared by 4 services (aws-terraform, aws-diagrams, aws-iam, aws-ecs)
- **SSE Example**: tavily server demonstrates SSE transport protocol with port 8080 and /events endpoint
- **Permission Distribution**: Network (majority), Filesystem (serena, homebrew), None (sequential-thinking, magic, morphllm)
- **SOPS Workflow**: Encrypt secret.sops.yaml AFTER plaintext edits, BEFORE Git commit
- **Home-Lab Philosophy**: Single-replica deployments with S3-backed durability, no high-availability
