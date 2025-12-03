# Technical Design: MCP Toolhive Conversion

**Design Date**: 2025-12-02
**Designer**: Kiro Design Agent
**Status**: Design In Progress
**Language**: en

---

## 1. Design Overview

### Purpose

Convert 18 identified MCP servers from Claude Code configurations to Kubernetes-native MCPServer custom resources using the toolhive deployment pattern established in `kubernetes/apps/toolhive/mcp_servers/`.

### Scope

- **In Scope**:
  - MCPServer CRD generation for 18 identified servers
  - SOPS-encrypted secret management with age keys
  - Kustomization structure for GitOps integration
  - Resource configuration following home-lab constraints
  - stdio and sse transport protocol implementations
  - Template bug fixes (memory limit correction)
  - Validation and documentation procedures

- **Out of Scope**:
  - toolhive operator installation/upgrades
  - Custom MCP server image creation
  - Custom permission profile development
  - Claude Code client configuration changes
  - Migration away from Claude Code

### Design Principles

1. **Template-Based Consistency**: Use corrected github.yaml as authoritative pattern
2. **Security First**: SOPS encryption mandatory, credential isolation via dedicated keys
3. **Resource Efficiency**: Honor home-lab constraints (cpu ≤1000m, memory ≤2Gi)
4. **GitOps Native**: All changes via declarative Kustomize + Flux reconciliation
5. **Incremental Validation**: Validate each batch before proceeding
6. **Fail-Safe Design**: Rollback capability at every stage

---

## 2. Architecture Design

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Git Repository (GitOps Source)              │
│  kubernetes/apps/toolhive/mcp_servers/                          │
│    ├── kustomization.yaml (namespace + resource list)           │
│    ├── secret.sops.yaml (SOPS-encrypted credentials)            │
│    ├── github.yaml (reference MCPServer - FIXED)                │
│    ├── context7.yaml (new)                                      │
│    ├── sequential-thinking.yaml (new)                           │
│    └── [15 more MCPServer YAML files]                           │
└─────────────────────────────────────────────────────────────────┘
                            │ Flux Reconciliation
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              Kubernetes Cluster (toolhive-system namespace)      │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ FluxCD Kustomization Controller                           │  │
│  │  - Watches Git repository                                 │  │
│  │  - Decrypts SOPS secrets via age key                      │  │
│  │  - Applies MCPServer CRDs + Secret                        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                      │
│                            ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ toolhive Operator                                         │  │
│  │  - Watches MCPServer CRDs                                 │  │
│  │  - Creates Deployments + Services                         │  │
│  │  - Injects secrets as environment variables               │  │
│  │  - Enforces permission profiles                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                      │
│                            ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ MCPServer Pods (18 servers)                              │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │  │
│  │  │ github pod  │ │context7 pod │ │sequential...│  ...   │  │
│  │  │  stdio      │ │  stdio/sse  │ │  stdio      │        │  │
│  │  │  network    │ │  network    │ │  none       │        │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │ MCP Protocol
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code Client                            │
│  - Connects to MCPServer services                                │
│  - stdio: direct pod communication                               │
│  - sse: HTTP/service endpoint                                    │
└─────────────────────────────────────────────────────────────────┘
```

### Component Relationships

**WHEN** FluxCD detects Git changes, **SHALL** reconcile within 1 minute
**WHEN** MCPServer CRD is created, toolhive operator **SHALL** provision pod within 30 seconds
**WHEN** pod starts, **SHALL** inject secrets from shared Secret resource
**WHERE** permission profile = "network", **SHALL** allow external API calls
**WHERE** permission profile = "filesystem", **SHALL** allow local file access
**WHERE** permission profile = "none", **SHALL** restrict to process-only operations

---

## 3. Component Design

### 3.1 MCPServer Template Pattern (Corrected)

**Reference Template** (github.yaml after bug fix):

```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: {server-name}
  namespace: toolhive-system
spec:
  image: {container-image}
  transport: {stdio|sse}
  port: {8080|optional}
  permissionProfile:
    type: builtin
    name: {network|filesystem|none}
  secrets:
    - name: mcp-server-secrets
      key: {SERVER_NAME_API_KEY}
      targetEnvName: {SERVER_NAME_API_KEY}
  env:
    - name: {CONFIG_VAR}
      value: {config-value}
  resources:
    limits:
      cpu: "1000m"
      memory: "2Gi"  # FIXED: was 2048Gi
    requests:
      cpu: "100m"
      memory: "128Mi"
```

**EARS Behavioral Contracts**:

- **WHEN** MCPServer is created, **SHALL** use template above with server-specific values
- **WHEN** memory limit is set, **SHALL NOT** exceed 2Gi (home-lab constraint)
- **WHEN** cpu limit is set, **SHALL NOT** exceed 1000m (1 vCPU)
- **WHERE** server requires credentials, **SHALL** reference shared secret with unique key
- **IF** transport = sse, **SHALL** specify port field

### 3.2 Server Configuration Matrix

**18 MCP Servers** grouped by batch for parallel conversion:

#### Batch 1: Core MCP Servers (stdio, mixed permissions)

| Server | Image | Transport | Permission | Secret Key | Notes |
|--------|-------|-----------|------------|------------|-------|
| context7 | ghcr.io/context7/context7-server | stdio | network | CONTEXT7_API_KEY | Documentation lookup |
| sequential-thinking | ghcr.io/sequential/thinking-server | stdio | none | N/A | No external calls |
| serena | ghcr.io/serena/serena-server | stdio | filesystem | N/A | Local code analysis |

#### Batch 2: Cloud Infrastructure (stdio, network permissions)

| Server | Image | Transport | Permission | Secret Key | Notes |
|--------|-------|-----------|------------|------------|-------|
| pagerduty-mcp | ghcr.io/pagerduty/pagerduty-mcp | stdio | network | PAGERDUTY_API_TOKEN | Incident management |
| datadog | ghcr.io/datadog/datadog-mcp | stdio | network | DATADOG_API_KEY | Monitoring integration |
| terraform | ghcr.io/terraform/terraform-mcp | stdio | network | N/A | IaC operations |
| aws-terraform | ghcr.io/awslabs/aws-terraform-mcp | stdio | network | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | AWS IaC |
| aws-diagrams | ghcr.io/awslabs/aws-diagrams-mcp | stdio | network | N/A | Architecture viz |
| aws-pricing | ghcr.io/awslabs/aws-pricing-mcp-server | stdio | network | N/A | Cost analysis |
| aws-iam | ghcr.io/awslabs/iam-mcp-server | stdio | network | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | Identity mgmt |
| aws-ecs | ghcr.io/awslabs/ecs-mcp-server | stdio | network | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | Container orchestration |

#### Batch 3: Development Tools (stdio, mixed permissions)

| Server | Image | Transport | Permission | Secret Key | Notes |
|--------|-------|-----------|------------|------------|-------|
| playwright | ghcr.io/playwright/playwright-mcp | stdio | network | N/A | Browser automation |
| magic | ghcr.io/magic/magic-mcp | stdio | none | N/A | UI generation |
| morphllm | ghcr.io/morphllm/morphllm-mcp | stdio | none | N/A | Code transformation |
| homebrew | ghcr.io/homebrew/homebrew-mcp | stdio | filesystem | N/A | Package management |

#### Batch 4: Specialized Servers (mixed transport)

| Server | Image | Transport | Permission | Secret Key | Notes |
|--------|-------|-----------|------------|------------|-------|
| tavily | ghcr.io/tavily/tavily-mcp | sse | network | TAVILY_API_KEY | Web search (SSE example) |
| chrome-devtools | ghcr.io/chrome/devtools-mcp | stdio | network | N/A | Browser debugging |

**NOTE**: Image URLs and configurations are PLACEHOLDERS pending verification against actual Claude Code configurations. Design assumes standard naming conventions but requires validation during implementation.

### 3.3 Secret Management Design

**Shared Secret Structure** (secret.sops.yaml):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-server-secrets
  namespace: toolhive-system
stringData:
  # Batch 1: Core
  GITHUB_PERSONAL_ACCESS_TOKEN: <github-token>
  CONTEXT7_API_KEY: <context7-key>

  # Batch 2: Cloud Infrastructure
  PAGERDUTY_API_TOKEN: <pagerduty-token>
  DATADOG_API_KEY: <datadog-key>
  AWS_ACCESS_KEY_ID: <aws-access-key>
  AWS_SECRET_ACCESS_KEY: <aws-secret-key>

  # Batch 3: Development Tools
  # (no additional keys - most use filesystem or no auth)

  # Batch 4: Specialized
  TAVILY_API_KEY: <tavily-key>
sops:
  kms: []
  gcp_kms: []
  azure_kv: []
  hc_vault: []
  age:
    - recipient: age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n
      enc: |
        -----BEGIN AGE ENCRYPTED FILE-----
        [SOPS encrypted content]
        -----END AGE ENCRYPTED FILE-----
  lastmodified: "2025-12-02T00:00:00Z"
  mac: ENC[AES256_GCM,data:...,type:comment]
  pgp: []
  encrypted_regex: ^(data|stringData)$
  version: 3.8.1
```

**EARS Secret Management Contracts**:

- **WHEN** secret key is added, **SHALL** use UPPERCASE_WITH_UNDERSCORES naming convention
- **WHEN** secret contains credentials, **SHALL** encrypt with SOPS before Git commit
- **WHERE** multiple servers need same credential (e.g., AWS keys), **SHALL** reuse single key
- **IF** credential is API token, **SHALL** use pattern: {SERVICE}_API_KEY or {SERVICE}_API_TOKEN
- **IF** credential is AWS, **SHALL** use standard AWS environment variable names

**Secret Key Organization**:
- Alphabetical ordering within batches for maintainability
- Comment headers separating batches for clarity
- Reuse credentials where applicable (AWS keys for multiple AWS services)

### 3.4 Kustomization Design

**Updated kustomization.yaml**:

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: toolhive-system
resources:
  # Secret must be listed first (dependency order)
  - ./secret.sops.yaml

  # Batch 1: Core MCP Servers
  - ./github.yaml
  - ./context7.yaml
  - ./sequential-thinking.yaml
  - ./serena.yaml

  # Batch 2: Cloud Infrastructure
  - ./pagerduty-mcp.yaml
  - ./datadog.yaml
  - ./terraform.yaml
  - ./aws-terraform.yaml
  - ./aws-diagrams.yaml
  - ./aws-pricing.yaml
  - ./aws-iam.yaml
  - ./aws-ecs.yaml

  # Batch 3: Development Tools
  - ./playwright.yaml
  - ./magic.yaml
  - ./morphllm.yaml
  - ./homebrew.yaml

  # Batch 4: Specialized Servers
  - ./tavily.yaml
  - ./chrome-devtools.yaml
```

**EARS Kustomization Contracts**:

- **WHEN** new MCPServer is added, **SHALL** append to appropriate batch section with comment
- **WHEN** kustomization is built, **SHALL** validate with `flux build kustomize` command
- **WHERE** resources have dependencies, **SHALL** list dependencies first (secret before servers)
- **IF** kustomization changes, **SHALL** trigger Flux reconciliation within 1 minute

---

## 4. Data Design

### 4.1 MCPServer CRD Schema

**API Version**: `toolhive.stacklok.dev/v1alpha1`
**Kind**: `MCPServer`

**Required Fields**:
- `metadata.name`: Unique server identifier (lowercase, hyphenated)
- `metadata.namespace`: Must be "toolhive-system"
- `spec.image`: Container image reference (full registry path)
- `spec.transport`: Communication protocol ("stdio" or "sse")

**Optional Fields**:
- `spec.port`: Service port (required if transport = "sse", default 8080)
- `spec.permissionProfile.type`: "builtin" (only supported type)
- `spec.permissionProfile.name`: "network", "filesystem", or "none"
- `spec.secrets[]`: Array of secret references
- `spec.env[]`: Array of environment variables
- `spec.resources.limits`: Resource upper bounds
- `spec.resources.requests`: Resource scheduling requests

**Field Validation Rules**:

- **WHEN** transport = "sse", spec.port **SHALL** be specified
- **WHEN** permissionProfile is set, type **SHALL** be "builtin"
- **WHERE** secrets are referenced, secret name **SHALL** be "mcp-server-secrets"
- **IF** resource limits are set, memory **SHALL** be ≤2Gi and cpu **SHALL** be ≤1000m
- **IF** resource requests are set, memory **SHALL** be ≥128Mi and cpu **SHALL** be ≥100m

### 4.2 Secret Data Schema

**Secret Type**: Opaque (Kubernetes generic secret)
**Secret Name**: `mcp-server-secrets` (shared across all servers)
**Namespace**: `toolhive-system`

**Data Field Constraints**:

- **Key Format**: UPPERCASE_WITH_UNDERSCORES
- **Encryption**: SOPS with age encryption, encrypted_regex = `^(data|stringData)$`
- **Value Format**: Plain text in `stringData` before encryption
- **Key Naming Patterns**:
  - API Keys: `{SERVICE}_API_KEY`
  - Tokens: `{SERVICE}_TOKEN` or `{SERVICE}_API_TOKEN`
  - AWS Credentials: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (standard AWS naming)

**Example Secret Reference in MCPServer**:

```yaml
secrets:
  - name: mcp-server-secrets      # Always shared secret
    key: GITHUB_PERSONAL_ACCESS_TOKEN  # Key from secret
    targetEnvName: GITHUB_PERSONAL_ACCESS_TOKEN  # Env var in pod
```

**EARS Secret Reference Contracts**:

- **WHEN** MCPServer needs credentials, **SHALL** reference shared secret by name "mcp-server-secrets"
- **WHEN** secret key is mapped to pod, targetEnvName **SHALL** match the secret key (for consistency)
- **WHERE** multiple servers use same credential, **SHALL** reference same secret key

---

## 5. Interface Design

### 5.1 GitOps Interfaces

**Interface: Git Repository → FluxCD**

- **Protocol**: Git (HTTPS/SSH)
- **Source**: `kubernetes/apps/toolhive/mcp_servers/` directory
- **Reconciliation**: Automatic, 1-minute interval
- **Contract**:
  - **WHEN** Git commit is pushed, FluxCD **SHALL** detect within 1 minute
  - **WHEN** Kustomization is applied, FluxCD **SHALL** decrypt SOPS secrets using age key
  - **IF** YAML validation fails, FluxCD **SHALL** report error and halt reconciliation

**Interface: FluxCD → Kubernetes API**

- **Protocol**: Kubernetes API (HTTPS, in-cluster)
- **Operations**: Create/Update/Delete MCPServer CRDs, Apply Secrets
- **Contract**:
  - **WHEN** Kustomization is valid, FluxCD **SHALL** apply resources to cluster
  - **WHERE** namespace does not exist, FluxCD **SHALL** create it first
  - **IF** resource conflicts exist, FluxCD **SHALL** use server-side apply for merge

### 5.2 Operator Interfaces

**Interface: toolhive Operator → MCPServer CRD**

- **Protocol**: Kubernetes Watch API
- **Operations**: Create Deployment, Create Service, Inject Secrets, Enforce Permissions
- **Contract**:
  - **WHEN** MCPServer CRD is created, operator **SHALL** provision pod within 30 seconds
  - **WHEN** secret reference is specified, operator **SHALL** inject as environment variable
  - **WHERE** permissionProfile = "network", operator **SHALL** configure NetworkPolicy allowing egress
  - **WHERE** permissionProfile = "filesystem", operator **SHALL** mount ConfigMap/volume if specified
  - **WHERE** permissionProfile = "none", operator **SHALL** restrict to namespace-only access

**Interface: MCPServer Pod → Kubernetes Services**

- **Protocol**: Kubernetes Service (ClusterIP)
- **Endpoints**: `{server-name}.toolhive-system.svc.cluster.local:{port}`
- **Contract**:
  - **WHEN** pod is ready, Kubernetes **SHALL** add pod IP to service endpoints
  - **IF** transport = "sse", service **SHALL** expose HTTP endpoint on spec.port
  - **IF** transport = "stdio", service **SHALL** provide direct pod access

### 5.3 Client Interfaces

**Interface: Claude Code → MCPServer (stdio transport)**

- **Protocol**: Standard I/O (stdin/stdout)
- **Connection**: Direct pod exec or sidecar pattern
- **Contract**:
  - **WHEN** Claude Code connects, **SHALL** establish bidirectional stream
  - **WHEN** server responds, **SHALL** use MCP protocol (JSON-RPC 2.0)
  - **IF** connection drops, Claude Code **SHALL** reconnect automatically

**Interface: Claude Code → MCPServer (sse transport)**

- **Protocol**: HTTP + Server-Sent Events (SSE)
- **Connection**: HTTP POST to service endpoint
- **Contract**:
  - **WHEN** Claude Code connects, **SHALL** send HTTP request to `http://{service-endpoint}:{port}`
  - **WHEN** server responds, **SHALL** stream events via SSE protocol
  - **IF** connection drops, Claude Code **SHALL** reconnect with exponential backoff

---

## 6. Security Design

### 6.1 Secret Encryption

**SOPS + age Encryption**:

- **Encryption Target**: `stringData` field in secret.sops.yaml
- **Algorithm**: AES256-GCM via age encryption
- **Key Management**: age private key stored securely outside Git, public key (`age1qww...`) in .sops.yaml
- **Decryption**: FluxCD decrypts in-cluster using age private key from Kubernetes Secret

**EARS Security Contracts**:

- **WHEN** secret is created/modified, **SHALL** encrypt with SOPS before Git commit
- **WHEN** secret contains credentials, **SHALL NEVER** commit unencrypted to Git
- **WHERE** SOPS decryption fails, FluxCD **SHALL** halt reconciliation and report error
- **IF** age key is rotated, **SHALL** re-encrypt all secrets with new key

**Secret Lifecycle**:

```
Developer modifies stringData
  → Run: sops -e secret.sops.yaml
  → Commit encrypted YAML to Git
  → FluxCD pulls from Git
  → FluxCD decrypts using cluster age key
  → Apply decrypted Secret to cluster
  → toolhive operator injects as env vars in pods
```

### 6.2 Permission Profiles

**Builtin Permission Profiles**:

1. **network**: Allows external API calls, DNS resolution, egress traffic
   - **Use Cases**: API integrations (github, pagerduty, datadog, aws-*, tavily)
   - **Enforcement**: NetworkPolicy allows egress, no filesystem access

2. **filesystem**: Allows local file access within pod/namespace
   - **Use Cases**: Code analysis (serena), package management (homebrew)
   - **Enforcement**: Volume mounts enabled, no external network access

3. **none**: Restricts to process-only operations
   - **Use Cases**: Pure computation (sequential-thinking, magic, morphllm)
   - **Enforcement**: No network, no filesystem, namespace-only access

**EARS Permission Contracts**:

- **WHEN** server needs API access, **SHALL** use permissionProfile = "network"
- **WHEN** server needs file access, **SHALL** use permissionProfile = "filesystem"
- **WHERE** server requires neither, **SHALL** use permissionProfile = "none"
- **IF** permission profile is misconfigured, operator **SHALL** reject MCPServer creation

### 6.3 Credential Isolation

**Principle**: Each MCP server receives only the credentials it needs (least privilege)

**Implementation**:
- Shared Secret resource with multiple keys
- Each MCPServer spec references only the keys it requires
- toolhive operator injects only referenced secrets as environment variables

**Example** (aws-ecs server needs AWS creds, but not GitHub token):

```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: aws-ecs
spec:
  secrets:
    - name: mcp-server-secrets
      key: AWS_ACCESS_KEY_ID
      targetEnvName: AWS_ACCESS_KEY_ID
    - name: mcp-server-secrets
      key: AWS_SECRET_ACCESS_KEY
      targetEnvName: AWS_SECRET_ACCESS_KEY
  # Does NOT reference GITHUB_PERSONAL_ACCESS_TOKEN
```

**EARS Credential Isolation Contracts**:

- **WHEN** MCPServer spec is created, **SHALL** reference ONLY required secret keys
- **WHERE** server does not need credentials, **SHALL** omit secrets array
- **IF** unauthorized access is attempted, Kubernetes RBAC **SHALL** deny

---

## 7. Implementation Plan

### 7.1 Phased Rollout Strategy

**Recommended: Parallel Batch Conversion** (from gap analysis)

**Phase 0: Template Preparation** (15 minutes)
1. Fix memory limit bug in github.yaml (2048Gi → 2Gi)
2. Validate fixed template with `kubectl apply --dry-run`
3. Commit bug fix to Git
4. Verify FluxCD reconciliation success
5. Test end-to-end: github MCPServer pod running and accessible

**Phase 1: Batch 1 - Core MCP Servers** (30 minutes)
1. Create MCPServer YAML files:
   - context7.yaml (stdio, network permission, CONTEXT7_API_KEY)
   - sequential-thinking.yaml (stdio, none permission, no secrets)
   - serena.yaml (stdio, filesystem permission, no secrets)
2. Update secret.sops.yaml with CONTEXT7_API_KEY
3. Encrypt secret: `sops -e -i secret.sops.yaml`
4. Update kustomization.yaml resources list
5. Validate: `flux build kustomize kubernetes/apps/toolhive/mcp_servers`
6. Commit and push to Git
7. Monitor FluxCD reconciliation
8. Verify all 4 pods (github + batch 1) are running
9. Test connectivity for each server

**Phase 2: Batch 2 - Cloud Infrastructure** (30 minutes)
1. Create MCPServer YAML files for 8 cloud servers
2. Update secret.sops.yaml with:
   - PAGERDUTY_API_TOKEN
   - DATADOG_API_KEY
   - AWS_ACCESS_KEY_ID (shared by aws-terraform, aws-iam, aws-ecs)
   - AWS_SECRET_ACCESS_KEY (shared)
3. Encrypt secret: `sops -e -i secret.sops.yaml`
4. Update kustomization.yaml resources list
5. Validate, commit, push
6. Monitor reconciliation
7. Verify all 12 pods running (4 + 8)
8. Test AWS service connectivity

**Phase 3: Batch 3 - Development Tools** (30 minutes)
1. Create MCPServer YAML files for 4 dev tool servers
2. No new secrets required (filesystem or none permissions)
3. Update kustomization.yaml resources list
4. Validate, commit, push
5. Monitor reconciliation
6. Verify all 16 pods running (12 + 4)
7. Test playwright browser automation, homebrew package access

**Phase 4: Batch 4 - Specialized Servers (includes SSE)** (30 minutes)
1. Create MCPServer YAML files:
   - tavily.yaml (sse transport, network permission, TAVILY_API_KEY)
   - chrome-devtools.yaml (stdio, network permission, no secrets)
2. Update secret.sops.yaml with TAVILY_API_KEY
3. Encrypt secret: `sops -e -i secret.sops.yaml`
4. Update kustomization.yaml resources list
5. Validate, commit, push
6. Monitor reconciliation
7. Verify all 18 pods running (16 + 2)
8. Test SSE connectivity for tavily (validates SSE transport requirement)

**Total Estimated Time**: 2 hours 15 minutes (including validation gates)

### 7.2 Rollback Strategy

**Per-Batch Rollback**:

1. **Immediate Rollback** (if batch deployment fails):
   ```bash
   git revert HEAD  # Revert last commit
   git push origin main
   # FluxCD will reconcile back to previous state within 1 minute
   ```

2. **Selective Rollback** (if specific server fails):
   ```bash
   # Remove server from kustomization.yaml resources list
   # Delete server's YAML file
   git commit -m "rollback: remove failing {server-name}"
   git push origin main
   ```

3. **Complete Rollback** (if entire conversion fails):
   ```bash
   git revert <commit-range>  # Revert all conversion commits
   git push origin main
   # Returns to github.yaml-only state
   ```

**EARS Rollback Contracts**:

- **WHEN** batch deployment fails, **SHALL** rollback within 5 minutes
- **WHERE** individual server fails, **SHALL** remove from batch and proceed with others
- **IF** critical infrastructure failure, **SHALL** halt all deployments and rollback completely

### 7.3 Validation Gates

**Pre-Deployment Validation** (before each batch):
```bash
# 1. YAML schema validation
kubectl apply --dry-run=client -f kubernetes/apps/toolhive/mcp_servers/

# 2. Kustomize build validation
flux build kustomize kubernetes/apps/toolhive/mcp_servers

# 3. SOPS decryption test
sops -d kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml

# 4. Resource limit validation (ensure no >2Gi memory)
grep -r "memory:" kubernetes/apps/toolhive/mcp_servers/*.yaml | grep -v "128Mi\|256Mi\|512Mi\|1Gi\|2Gi"
# Expected: No output (all limits valid)
```

**Post-Deployment Validation** (after each batch):
```bash
# 1. Check MCPServer resources created
kubectl get mcpserver -n toolhive-system

# 2. Check pod status
kubectl get pods -n toolhive-system -l app.kubernetes.io/managed-by=toolhive

# 3. Check secret injection
kubectl describe pod <pod-name> -n toolhive-system | grep -A 10 "Environment:"

# 4. Check logs for errors
kubectl logs -n toolhive-system <pod-name> --tail=50

# 5. Test connectivity (example for github server)
kubectl exec -it -n toolhive-system <github-pod-name> -- /bin/sh -c "echo '{}' | nc localhost 8080"
```

**EARS Validation Contracts**:

- **WHEN** batch is deployed, **SHALL** pass all pre-deployment validation checks
- **WHEN** pods are running, **SHALL** verify healthy status within 2 minutes
- **WHERE** validation fails, **SHALL** halt deployment and investigate before proceeding
- **IF** post-deployment checks fail, **SHALL** trigger rollback procedure

---

## 8. Non-Functional Requirements

### 8.1 Performance

- **Deployment Speed**:
  - **WHEN** commit is pushed, FluxCD **SHALL** reconcile within 1 minute
  - **WHEN** MCPServer CRD is created, pod **SHALL** start within 30 seconds

- **Resource Utilization**:
  - **WHERE** all 18 servers are running, cluster **SHALL** consume ≤18 vCPU, ≤36Gi memory maximum (limits)
  - **WHERE** all 18 servers are running, cluster **SHALL** consume ≥1.8 vCPU, ≥2.3Gi memory baseline (requests)

- **Scalability**:
  - Architecture **SHALL** support adding new MCP servers without redesign
  - Shared secret pattern **SHALL** support >100 credential keys without performance degradation

### 8.2 Reliability

- **Availability**:
  - Single-replica deployments (home-lab philosophy)
  - No high-availability requirements
  - Acceptable downtime during pod restarts (home-lab context)

- **Fault Tolerance**:
  - **WHEN** MCPServer pod crashes, Kubernetes **SHALL** restart within 10 seconds
  - **WHERE** secret decryption fails, deployment **SHALL** halt (fail-safe)
  - **IF** operator is unavailable, existing pods **SHALL** continue running (stateless)

- **Data Integrity**:
  - **WHEN** secret is updated, existing pods **SHALL** NOT receive update (requires pod restart)
  - **WHERE** secret contains sensitive data, **SHALL** be encrypted in Git (SOPS)
  - **IF** SOPS key is lost, secret recovery **SHALL** require re-entering credentials

### 8.3 Security

- **Authentication**:
  - All API credentials stored as SOPS-encrypted secrets
  - No plaintext credentials in Git repository
  - Kubernetes RBAC enforces access control

- **Authorization**:
  - Permission profiles enforce least-privilege access
  - NetworkPolicy controls egress traffic for network-enabled servers
  - Credential isolation via selective secret injection

- **Encryption**:
  - Secrets encrypted at rest in Git (SOPS + age)
  - Secrets decrypted in-memory during FluxCD reconciliation
  - TLS for service-to-service communication (if applicable)

### 8.4 Maintainability

- **Code Organization**:
  - One MCPServer YAML per file (`{server-name}.yaml`)
  - Alphabetical ordering within batches in kustomization.yaml
  - Comment headers separating batches for readability

- **Documentation**:
  - This design document provides architectural overview
  - Inline comments in kustomization.yaml explain batch groupings
  - Secret key comments in secret.sops.yaml explain credential ownership

- **Testing**:
  - Pre-deployment validation commands documented
  - Post-deployment verification commands documented
  - Rollback procedures clearly defined

- **Monitoring**:
  - Kubernetes pod status monitoring via `kubectl get pods`
  - FluxCD reconciliation status via `flux get kustomization`
  - Application logs via `kubectl logs`

### 8.5 Compliance

- **GitOps Standards**:
  - All changes via Git commits (declarative)
  - FluxCD reconciliation enforces desired state
  - Audit trail via Git commit history

- **Security Standards**:
  - SOPS encryption mandatory for secrets
  - age key management follows best practices
  - Credential isolation via permission profiles

- **Home-Lab Standards**:
  - Resource limits honor cluster constraints
  - Single-replica deployments conserve resources
  - S3-backed persistence for durability (future enhancement)

---

## 9. Testing Strategy

### 9.1 Unit Testing

**Template Validation**:
```bash
# Test: MCPServer YAML schema validation
kubectl apply --dry-run=client -f kubernetes/apps/toolhive/mcp_servers/github.yaml
# Expected: "created (dry run)"

# Test: Kustomize build produces valid output
flux build kustomize kubernetes/apps/toolhive/mcp_servers
# Expected: Valid YAML output with Secret + 18 MCPServer resources

# Test: SOPS decryption succeeds
sops -d kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml
# Expected: Decrypted YAML with plaintext stringData
```

### 9.2 Integration Testing

**End-to-End Deployment**:
```bash
# Test: Deploy Batch 1 (github + 3 core servers)
git add kubernetes/apps/toolhive/mcp_servers/*.yaml
git commit -m "feat: deploy batch 1 core MCP servers"
git push origin main

# Verify: FluxCD reconciliation
flux get kustomization mcp-servers --watch
# Expected: "Applied revision: main/<commit-sha>" within 1 minute

# Verify: Pods running
kubectl get pods -n toolhive-system
# Expected: 4 pods (github, context7, sequential-thinking, serena) in Running status

# Test: Secret injection
kubectl exec -it -n toolhive-system <github-pod> -- env | grep GITHUB_PERSONAL_ACCESS_TOKEN
# Expected: GITHUB_PERSONAL_ACCESS_TOKEN=<decrypted-value>

# Test: Permission profile enforcement
kubectl exec -it -n toolhive-system <sequential-thinking-pod> -- curl https://google.com
# Expected: Connection refused (none permission profile blocks network)

kubectl exec -it -n toolhive-system <context7-pod> -- curl https://google.com
# Expected: HTTP response (network permission profile allows egress)
```

### 9.3 Rollback Testing

**Rollback Scenario**:
```bash
# Simulate failure: Deploy invalid MCPServer
cat > kubernetes/apps/toolhive/mcp_servers/invalid.yaml <<EOF
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: invalid
spec:
  image: "nonexistent/image"
  transport: stdio
  resources:
    limits:
      memory: "999Gi"  # Exceeds constraint
EOF

git add invalid.yaml
git commit -m "test: deploy invalid server"
git push origin main

# Verify: FluxCD reports error (but doesn't break existing servers)
flux get kustomization mcp-servers
# Expected: Status = "False" with error message

# Execute: Rollback
git revert HEAD
git push origin main

# Verify: FluxCD reconciles back to valid state
flux get kustomization mcp-servers
# Expected: Status = "True", existing 4 pods still running
```

### 9.4 SSE Transport Testing

**SSE Connectivity Test** (tavily server):
```bash
# Deploy tavily (Batch 4)
# Verify pod exposes HTTP service
kubectl get svc -n toolhive-system tavily
# Expected: ClusterIP service on port 8080

# Test SSE connection from another pod
kubectl run -it --rm test-sse --image=curlimages/curl --restart=Never -- \
  curl -N -H "Accept: text/event-stream" http://tavily.toolhive-system.svc.cluster.local:8080/events

# Expected: SSE stream with events:
# data: {"event":"connected"}
# data: {"event":"message", ...}
```

### 9.5 Performance Testing

**Resource Usage Validation**:
```bash
# Deploy all 18 servers (Phase 4 complete)
# Monitor cluster resource usage
kubectl top nodes
# Expected: CPU usage ≤18 cores (18 × 1000m limit)
# Expected: Memory usage ≤36Gi (18 × 2Gi limit)

kubectl top pods -n toolhive-system
# Expected: Each pod CPU ≤1000m, memory ≤2Gi
```

**Deployment Speed Testing**:
```bash
# Measure FluxCD reconciliation time
time flux reconcile kustomization mcp-servers --with-source

# Expected: <60 seconds for full reconciliation
```

---

## 10. Deployment Documentation

### 10.1 Pre-Deployment Checklist

- [ ] toolhive operator installed and running in cluster
- [ ] FluxCD configured with Git repository access
- [ ] SOPS age key configured for FluxCD decryption
- [ ] Namespace `toolhive-system` exists (or will be created by kustomization)
- [ ] GitHub personal access token available for GITHUB_PERSONAL_ACCESS_TOKEN
- [ ] API keys/tokens available for other services (context7, pagerduty, datadog, etc.)
- [ ] `kubectl` and `flux` CLI tools installed and configured
- [ ] Git repository cloned locally with write access

### 10.2 Deployment Commands

**Phase 0: Fix Template**
```bash
cd kubernetes/apps/toolhive/mcp_servers/
# Edit github.yaml line 25: change "2048Gi" to "2Gi"
kubectl apply --dry-run=client -f github.yaml
git commit -am "fix: correct memory limit in github.yaml template"
git push origin main
flux reconcile kustomization mcp-servers --with-source
kubectl get pods -n toolhive-system  # Verify github pod running
```

**Phase 1: Deploy Batch 1**
```bash
# Create context7.yaml, sequential-thinking.yaml, serena.yaml
# Update secret.sops.yaml with CONTEXT7_API_KEY
sops -e -i secret.sops.yaml
# Update kustomization.yaml resources list

flux build kustomize .  # Validate
git add *.yaml
git commit -m "feat: deploy batch 1 core MCP servers"
git push origin main
flux reconcile kustomization mcp-servers --with-source
kubectl get pods -n toolhive-system  # Verify 4 pods running
```

**Phases 2-4**: Repeat similar pattern for each batch

### 10.3 Validation Commands

**Check MCPServer Resources**:
```bash
kubectl get mcpserver -n toolhive-system
# Expected: 18 MCPServer resources listed
```

**Check Pod Status**:
```bash
kubectl get pods -n toolhive-system -o wide
# Expected: 18 pods in Running status, 1/1 Ready
```

**Check Secret Decryption**:
```bash
kubectl get secret mcp-server-secrets -n toolhive-system -o jsonpath='{.data.GITHUB_PERSONAL_ACCESS_TOKEN}' | base64 -d
# Expected: Decrypted token value
```

**Check FluxCD Status**:
```bash
flux get kustomization mcp-servers
# Expected: READY=True, MESSAGE="Applied revision: main/<sha>"
```

### 10.4 Troubleshooting Guide

**Issue: MCPServer CRD not found**
```bash
# Symptom: Error "no matches for kind MCPServer"
# Solution: Verify toolhive operator installed
kubectl get crd mcpservers.toolhive.stacklok.dev
# If missing, install toolhive operator
```

**Issue: Secret decryption fails**
```bash
# Symptom: FluxCD error "failed to decrypt sops secret"
# Solution: Verify age key configured for FluxCD
kubectl get secret sops-age -n flux-system
# If missing, create age key secret
```

**Issue: Pod stuck in Pending**
```bash
# Symptom: Pod status "Pending" for >2 minutes
# Diagnosis: Check events
kubectl describe pod <pod-name> -n toolhive-system

# Common causes:
# - Insufficient resources: Reduce limits or add nodes
# - Image pull failure: Verify image exists in registry
# - Secret not found: Verify secret.sops.yaml decrypted and applied
```

**Issue: Pod CrashLoopBackOff**
```bash
# Symptom: Pod restarts repeatedly
# Diagnosis: Check logs
kubectl logs -n toolhive-system <pod-name> --previous

# Common causes:
# - Missing environment variable: Verify secret injection
# - Invalid configuration: Check env vars in MCPServer spec
# - Permission denied: Verify permissionProfile matches server needs
```

**Issue: SSE transport not working**
```bash
# Symptom: Cannot connect to SSE endpoint
# Diagnosis: Verify service exposed
kubectl get svc -n toolhive-system <server-name>
# Expected: ClusterIP service on spec.port

# Test from inside cluster
kubectl run -it --rm test-curl --image=curlimages/curl --restart=Never -- \
  curl http://<server-name>.toolhive-system.svc.cluster.local:<port>/

# If service missing: Verify MCPServer spec.port is set for sse transport
```

---

## 11. Risks and Mitigations

### 11.1 Critical Risks (from Gap Analysis)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Memory limit bug propagates to all conversions | HIGH (if not fixed) | HIGH | Fix github.yaml template in Phase 0 before batch conversions; add resource limit validation to pre-deployment checks |
| Claude Code cannot connect to Kubernetes-hosted servers | LOW | HIGH | Test end-to-end github server connectivity in Phase 0; document client connection configuration; maintain parallel local servers during transition |
| SOPS decryption fails during deployment | LOW | MEDIUM | Verify age key availability in pre-deployment checklist; test SOPS decryption in validation gates; implement age key rotation procedure |

### 11.2 Design-Specific Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Shared secret pattern creates single point of failure | MEDIUM | MEDIUM | SOPS encryption + Git version control provides backup; document secret recovery procedure; consider splitting into per-service secrets if scaling beyond 50 servers |
| Permission profiles misconfigured causing runtime failures | MEDIUM | MEDIUM | Document permission requirements in server configuration matrix; validate with integration tests; implement pod security policies as additional layer |
| SSE transport examples insufficient for all use cases | LOW | LOW | Start with tavily as SSE reference implementation; document SSE pattern clearly; validate with comprehensive testing |
| Batch deployment order causes dependency failures | LOW | MEDIUM | Validate batch independence before deployment; implement retry logic in FluxCD reconciliation; document rollback procedure |

---

## 12. Future Enhancements

**Post-Conversion Improvements** (out of scope for initial implementation):

1. **Monitoring Integration**:
   - ServiceMonitor resources for Prometheus scraping
   - Grafana dashboards for MCP server metrics
   - Alerting rules for pod failures or high resource usage

2. **Auto-Scaling**:
   - HorizontalPodAutoscaler for high-demand servers
   - Vertical scaling recommendations based on usage patterns

3. **Backup and Recovery**:
   - S3-backed persistence for stateful MCP servers (if applicable)
   - Velero integration for disaster recovery
   - Automated secret backup and rotation

4. **Performance Optimization**:
   - Pod anti-affinity rules for distribution across nodes
   - Resource request/limit tuning based on actual usage
   - Connection pooling for frequently-used servers

5. **Security Enhancements**:
   - Separate secrets per service category (instead of shared secret)
   - OPA/Gatekeeper policies for MCPServer validation
   - Network policies for inter-pod communication restrictions
   - Secret rotation automation with external secret management (Vault/AWS Secrets Manager)

---

## 13. Approval

**Design Review Status**: ⏳ Awaiting Approval

**Reviewers**:
- [ ] Technical Lead: Architecture and implementation strategy review
- [ ] Security Review: SOPS encryption, permission profiles, credential isolation
- [ ] Operations Review: Deployment strategy, rollback procedures, monitoring

**Approval Signatures**:
- Technical Lead: ___________________ Date: ___________
- Security Lead: ___________________ Date: ___________
- Operations Lead: ___________________ Date: ___________

**Post-Approval Actions**:
1. Update spec.json status to "design-approved"
2. Proceed to tasks.md creation (task breakdown for implementation)
3. Schedule implementation kickoff meeting

---

## Appendix A: Server Configuration Details (Placeholders)

**CRITICAL NOTE**: The following server configurations are PLACEHOLDERS based on standard naming conventions. Actual image URLs, environment variables, and credential requirements MUST be validated against real Claude Code MCP server configurations before implementation.

### Context7 Server
```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: context7
  namespace: toolhive-system
spec:
  image: ghcr.io/context7/context7-server:latest  # PLACEHOLDER
  transport: stdio
  permissionProfile:
    type: builtin
    name: network
  secrets:
    - name: mcp-server-secrets
      key: CONTEXT7_API_KEY
      targetEnvName: CONTEXT7_API_KEY
  env:
    - name: LOG_LEVEL
      value: info
  resources:
    limits:
      cpu: "1000m"
      memory: "2Gi"
    requests:
      cpu: "100m"
      memory: "128Mi"
```

### Tavily Server (SSE Transport Example)
```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: tavily
  namespace: toolhive-system
spec:
  image: ghcr.io/tavily/tavily-mcp:latest  # PLACEHOLDER
  transport: sse
  port: 8080  # Required for SSE
  permissionProfile:
    type: builtin
    name: network
  secrets:
    - name: mcp-server-secrets
      key: TAVILY_API_KEY
      targetEnvName: TAVILY_API_KEY
  env:
    - name: SSE_ENDPOINT
      value: /events
    - name: LOG_LEVEL
      value: info
  resources:
    limits:
      cpu: "1000m"
      memory: "2Gi"
    requests:
      cpu: "100m"
      memory: "128Mi"
```

**Validation Required Before Implementation**:
- Actual container image registry and tags
- Required environment variables and their expected formats
- Secret key names and authentication methods
- Port numbers for SSE servers
- Any server-specific resource requirements deviating from template

---

## Document Metadata

**Document Version**: 1.0
**Last Updated**: 2025-12-02
**Next Review Date**: Upon design approval
**Related Documents**:
- `.kiro/specs/mcp-toolhive-conversion/requirements.md`
- `.kiro/specs/mcp-toolhive-conversion/gap-analysis.md`
- `kubernetes/apps/toolhive/mcp_servers/github.yaml` (reference implementation)
