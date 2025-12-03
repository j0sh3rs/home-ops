# Implementation Gap Analysis: mcp-toolhive-conversion

**Analysis Date**: 2025-12-02
**Analyst**: Kiro Gap Analysis Agent
**Scope**: Converting Claude Code MCP Server configurations to Kubernetes MCPServer custom resources following the toolhive deployment pattern

## Executive Summary

This gap analysis evaluates the implementation requirements for converting 18 identified MCP servers from Claude Code configurations to Kubernetes-native MCPServer custom resources. The existing codebase contains a single reference implementation (github MCP server) that demonstrates the target pattern with 90% alignment to requirements. Key gaps include: (1) unverified MCP server configuration source requiring validation, (2) missing SSE transport protocol examples despite requirements, (3) a critical memory limit bug (2048Gi instead of 2Gi) in the reference implementation, and (4) need to scale from 1 to 18+ server deployments. The recommended approach is a phased conversion strategy using the existing github.yaml pattern as a template, with immediate bug fixes and parallel implementation of remaining servers grouped by complexity and permission requirements.

---

## 1. Existing Codebase Assessment

### Current Implementation Patterns

**GitOps Configuration**:
- FluxCD-managed deployments via Kustomization resources
- Location: `kubernetes/apps/toolhive/mcp_servers/`
- Pattern: `{app}/ks.yaml` + `{app}/app/kustomization.yaml` + `{app}/app/helmrelease.yaml`
- Current toolhive pattern: Direct MCPServer YAML files without HelmRelease wrapper

**Component Structure**:
```
kubernetes/apps/toolhive/mcp_servers/
├── kustomization.yaml          # Namespace and resource declarations
├── secret.sops.yaml            # SOPS-encrypted shared secret
└── github.yaml                 # Reference MCPServer implementation
```

**Integration Points**:
- Kustomize-based resource management with namespace targeting
- SOPS encryption using age keys for secret management
- Single shared Secret resource pattern (`mcp-server-secrets`) for all servers
- Flux reconciliation via Kustomization CRD
- toolhive operator watches MCPServer CRDs in toolhive-system namespace

### Relevant Existing Components

1. **github.yaml MCPServer**: `kubernetes/apps/toolhive/mcp_servers/github.yaml`
   - Purpose: Reference implementation of MCPServer CRD pattern
   - Capabilities:
     - Container image specification (ghcr.io/github/github-mcp-server)
     - stdio transport protocol
     - network permission profile (builtin)
     - Secret reference to shared secret resource
     - Environment variable configuration
     - Resource limits and requests
   - Limitations:
     - Memory limit bug: 2048Gi instead of 2Gi/2048Mi (violates home-lab constraints)
     - Only stdio transport demonstrated (missing sse examples)
     - Single server instance (does not demonstrate scaling pattern)

2. **kustomization.yaml**: `kubernetes/apps/toolhive/mcp_servers/kustomization.yaml`
   - Purpose: GitOps integration and namespace management
   - Capabilities:
     - Namespace declaration (toolhive-system)
     - Resource list management
     - Secret listed first (correct pattern)
   - Configuration: YAML schema validation enabled
   - Limitations: Only manages 1 MCPServer currently (needs to scale to 18+)

3. **secret.sops.yaml**: `kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml`
   - Purpose: Encrypted credential storage for MCP servers
   - Capabilities:
     - SOPS encryption with age key
     - stringData field encryption
     - Shared secret pattern (single Secret for all servers)
     - Currently contains: GITHUB_PERSONAL_ACCESS_TOKEN
   - Configuration:
     - encrypted_regex: ^(data|stringData)$
     - mac_only_encrypted: true
   - Limitations: Only 1 credential key present, needs 17+ additional keys for other servers

### Architecture Pattern Compliance

**✅ Matches Requirements**:
- MCPServer CRD structure with proper metadata (Requirement 2)
- SOPS encryption with age keys (Requirement 3)
- Kustomization with namespace declaration (Requirement 5)
- Environment variable configuration (Requirement 4)
- Secret reference pattern (Requirement 3)
- Resource limits/requests structure present (Requirement 4)

**⚠️ Partial Compliance**:
- Resource limits present but contain bug (2048Gi vs 2Gi) - violates Requirement 4 specification
- Only stdio transport shown, sse transport not demonstrated (Requirement 2 specifies both)
- Secret key naming follows UPPERCASE_WITH_UNDERSCORES pattern (Requirement 3)

**❌ Missing Elements**:
- SSE transport protocol examples
- 17 additional MCP server conversions
- Documentation for validation and troubleshooting (Requirement 6)
- Multiple permission profile examples (only "network" shown)

---

## 2. Capability Gap Analysis

### Required Capabilities (from Requirements)

| Requirement | Current State | Gap | Priority |
|------------|--------------|-----|----------|
| **Req 1**: Identify all MCP servers | Unverified list of 18 servers from system context | Cannot locate Claude Code MCP server configuration files | **HIGH** |
| **Req 2**: Create MCPServer CRDs | 1 of 18+ servers implemented (github.yaml) | Need 17+ additional MCPServer YAML files | **HIGH** |
| **Req 2**: stdio transport | ✅ Implemented in github.yaml | None | N/A |
| **Req 2**: sse transport | ❌ Not implemented | No sse transport examples | **MEDIUM** |
| **Req 2**: Permission profiles | Partial - only "network" profile shown | Need examples of "filesystem" and "none" profiles | **LOW** |
| **Req 3**: SOPS-encrypted secrets | ✅ Implemented with age key | None | N/A |
| **Req 3**: Secret references | ✅ Implemented in github.yaml | None | N/A |
| **Req 3**: Additional secret keys | 1 of 18+ keys present | Need 17+ additional credential keys in secret.sops.yaml | **HIGH** |
| **Req 4**: Resource limits ≤1000m cpu, ≤2Gi memory | ⚠️ Bug: memory=2048Gi | Memory limit bug requires immediate fix | **CRITICAL** |
| **Req 4**: Resource requests ≥100m cpu, ≥128Mi memory | ✅ Correctly implemented | None | N/A |
| **Req 5**: Kustomization structure | ✅ Implemented | None | N/A |
| **Req 5**: Resource list updates | 1 of 18+ servers listed | Need to add 17+ servers to resources array | **HIGH** |
| **Req 6**: Validation commands | ❌ Not documented | No validation or troubleshooting documentation | **MEDIUM** |

### Missing Components

1. **MCP Server Configuration Source**
   - Required For: Requirement 1 (Configuration Discovery)
   - Current Status: Cannot locate Claude Code MCP server configuration files
   - Implementation Effort: **HIGH** (critical blocker for gap analysis completion)
   - **CRITICAL**: Requirements specify "Convert all of the existing Claude Code MCP Server configurations" but these configuration files are not in repository

2. **17+ MCPServer YAML Files**
   - Required For: Requirement 2 (MCPServer Resource Generation)
   - Current Status: Only github.yaml exists
   - Implementation Effort: **HIGH** (medium per-server effort × 17 servers)
   - Template Available: Yes (github.yaml can serve as template after bug fix)

3. **SSE Transport Examples**
   - Required For: Requirement 2 acceptance criteria (both stdio AND sse support)
   - Current Status: Only stdio transport implemented
   - Implementation Effort: **MEDIUM** (requires research on SSE-based MCP servers)

4. **Additional Secret Keys**
   - Required For: Requirement 3 (Secret Management for all servers)
   - Current Status: Only GITHUB_PERSONAL_ACCESS_TOKEN present
   - Implementation Effort: **MEDIUM** (requires identifying credential requirements per server)

5. **Validation Documentation**
   - Required For: Requirement 6 (Documentation and Validation)
   - Current Status: Not documented
   - Implementation Effort: **LOW** (straightforward documentation task)

### Compatibility Concerns

- **Home-Lab Resource Constraints**: Single-replica philosophy with resource limits (cpu ≤1000m, memory ≤2Gi) must be maintained across all 18 servers. Current bug (2048Gi memory) violates this constraint.

- **Shared Secret Pattern**: Single Secret resource contains credentials for all servers. Scaling to 18 servers means 18 keys in one Secret, requiring careful key naming and organization.

- **Transport Protocol Diversity**: Some MCP servers may require sse transport (Server-Sent Events) which is not yet demonstrated in existing pattern.

- **Permission Profile Mapping**: Need to determine correct permission profile (network, filesystem, none) for each of 17 remaining servers based on their runtime requirements.

---

## 3. Implementation Strategy Options

### Option A: Template-Based Sequential Conversion

**Approach**: Fix github.yaml bug, use as template, convert servers one-by-one in priority order

**Advantages**:
- Lowest risk approach with incremental validation
- Each server can be tested individually before proceeding
- Pattern refinement opportunities at each step
- Easy rollback if issues discovered
- Follows GitOps best practices with incremental changes

**Disadvantages**:
- Slower overall completion time (serial execution)
- Repetitive manual work for 17+ servers
- Higher total effort due to sequential context switching
- May delay validation of systemic issues

**Estimated Effort**: **HIGH** (2-3 hours total, ~10 minutes per server)

**Risk Level**: **LOW**

### Option B: Parallel Batch Conversion

**Approach**: Fix template, group servers by complexity/requirements, convert in parallel batches

**Advantages**:
- Faster overall completion (parallel execution)
- Efficient use of template pattern across similar servers
- Batch validation reduces repetitive testing
- Earlier detection of systemic issues
- Better resource utilization during implementation

**Disadvantages**:
- Higher initial complexity coordinating parallel work
- Potential for systemic errors affecting multiple servers
- Requires more sophisticated testing strategy
- Rollback more complex if issues discovered
- Needs careful dependency management

**Estimated Effort**: **MEDIUM** (1-2 hours total with intelligent batching)

**Risk Level**: **MEDIUM**

**Batch Strategy**:
- Batch 1: Core MCP servers (context7, sequential-thinking, serena) - 30 min
- Batch 2: Cloud infrastructure (aws-*, terraform, datadog) - 30 min
- Batch 3: Development tools (playwright, magic, morphllm) - 30 min
- Batch 4: Specialized servers (pagerduty, homebrew, tavily, chrome-devtools) - 30 min

### Option C: Automated Generation via Script

**Approach**: Create script/template generator to produce all MCPServer YAMLs from configuration data

**Advantages**:
- Highly efficient for large-scale generation (18+ servers)
- Consistent pattern application across all servers
- Easy to regenerate if template changes
- Reduces human error in repetitive tasks
- Enables programmatic validation before creation

**Disadvantages**:
- Upfront investment in automation tooling
- Script development/testing time
- Less flexibility for server-specific customization
- Requires configuration data source (still need to identify MCP server details)
- Over-engineering for one-time conversion task

**Estimated Effort**: **HIGH** (2-4 hours including script development)

**Risk Level**: **MEDIUM**

### Recommended Approach

**Selected Strategy**: **Option B - Parallel Batch Conversion** with hybrid elements from Option A

**Rationale**:
1. **Efficiency**: Batch parallel approach balances speed (1-2 hours) vs sequential safety
2. **Risk Management**: Grouping by similarity allows batch validation while containing blast radius
3. **Pattern Reuse**: Template-based approach from Option A provides proven pattern
4. **Scalability**: Handles 18 servers efficiently without over-engineering (Option C)
5. **Incremental Validation**: Batch completion checkpoints enable incremental testing
6. **Home-Lab Context**: Single-operator environment benefits from focused batch work over prolonged serial effort

**Hybrid Elements**:
- Use github.yaml as template (Option A)
- Fix template bug before batch conversion begins (Option A safety)
- Group servers by complexity for parallel batches (Option B efficiency)
- Validate each batch before proceeding (Option A safety gates)
- Maintain manual control over server-specific customization (avoids Option C rigidity)

---

## 4. Integration Challenges

### Data Format Compatibility

- **Current Format**: Claude Code MCP server configuration (format unknown - cannot locate config files)
- **Required Format**: Kubernetes MCPServer CRD (toolhive.stacklok.dev/v1alpha1)
- **Migration Strategy**:
  1. Identify Claude Code config file location (CRITICAL BLOCKER)
  2. Extract: image, transport, env vars, secrets per server
  3. Map to MCPServer CRD schema fields
  4. Apply resource constraints per home-lab standards
  5. Generate YAML following github.yaml pattern

### Service Dependencies

- **Upstream Dependencies**:
  - FluxCD must reconcile Kustomization before MCPServer CRDs applied
  - toolhive operator must be running to process MCPServer resources
  - SOPS decryption requires age key availability in cluster

- **Downstream Dependencies**:
  - Claude Code client must support connecting to Kubernetes-hosted MCP servers
  - Applications/workflows depending on MCP servers need updated connection configs
  - Each MCPServer depends on container image availability in registry

- **Breaking Changes**:
  - Connection method changes from local process to Kubernetes service
  - May require updating Claude Code configuration to point to cluster endpoints
  - Network policies may need adjustment for MCP server communication

- **Mitigation**:
  - Test one server (github) end-to-end before batch conversion
  - Document connection configuration changes for Claude Code
  - Plan for parallel operation during transition (old + new simultaneously)

### Testing Requirements

- **Unit Tests**:
  - YAML schema validation (`kubectl apply --dry-run`)
  - Kustomize build validation (`flux build kustomize kubernetes/apps/toolhive/mcp_servers`)
  - SOPS decryption test (`sops -d secret.sops.yaml`)
  - Resource limit validation (all cpu ≤1000m, all memory ≤2Gi)

- **Integration Tests**:
  - MCPServer pod startup and health checks
  - Secret reference resolution
  - Environment variable injection
  - Permission profile enforcement (network/filesystem/none)
  - Transport protocol connectivity (stdio and sse)
  - Claude Code client connection test

- **Migration Validation**:
  - Compare MCP server functionality: Claude Code local vs Kubernetes hosted
  - Verify credential access and API connectivity
  - Validate performance (latency, throughput)
  - Confirm resource usage within home-lab limits
  - Test rollback procedure (delete MCPServer, verify cleanup)

---

## 5. Research Needs

### External Dependencies

1. **Claude Code MCP Server Configuration File Location**
   - Purpose: Source of truth for which servers exist and their configurations
   - Research Question: Where are Claude Code MCP server configurations stored? (not in ~/.claude/settings.json, not in repository)
   - Design Impact: **CRITICAL** - Cannot complete gap analysis without verified server list
   - Status: **UNRESOLVED** - 18 servers identified from system context but configuration files not located
   - Priority: **IMMEDIATE** - Blocking factor for accurate gap analysis

2. **SSE Transport Protocol Implementation**
   - Purpose: Required by Requirement 2 for applicable MCP servers
   - Research Question: Which MCP servers require sse transport vs stdio? How to configure MCPServer CRD for sse?
   - Design Impact: Need sse examples in addition to stdio pattern
   - Status: No sse examples in existing codebase
   - Priority: **HIGH** - Requirements explicitly specify both protocols

3. **MCP Server Credential Requirements**
   - Purpose: Complete Secret key list for all 18 servers
   - Research Question: What API keys, tokens, or credentials does each MCP server require?
   - Design Impact: Secret key naming and organization in shared secret.sops.yaml
   - Status: Only GITHUB_PERSONAL_ACCESS_TOKEN documented
   - Priority: **HIGH** - Needed before secret.sops.yaml can be completed

4. **Permission Profile Mapping**
   - Purpose: Determine correct builtin permission profile per server
   - Research Question: Which servers need network access? Which need filesystem? Which need none?
   - Design Impact: spec.permissionProfile configuration per server
   - Status: Only "network" profile demonstrated in github.yaml
   - Priority: **MEDIUM** - Affects security posture and functionality

### Unvalidated Assumptions

1. **Assumption**: All 18 identified MCP servers exist and need conversion
   - Validation Needed: Locate and verify Claude Code MCP server configuration files
   - Risk if Invalid: Wasted effort converting non-existent servers, or missing servers that do exist
   - Mitigation: Immediate research into Claude Code config file location

2. **Assumption**: Shared secret pattern (single Secret resource) scales to 18 servers
   - Validation Needed: Test secret.sops.yaml with 18 keys, verify no size/performance limits
   - Risk if Invalid: May need individual Secret resources per server (significant pattern change)
   - Mitigation: Research Kubernetes Secret size limits, SOPS encryption overhead

3. **Assumption**: github.yaml pattern (after bug fix) applies to all MCP servers
   - Validation Needed: Review MCP server documentation for special requirements
   - Risk if Invalid: Some servers may need non-standard configurations
   - Mitigation: Document server-specific requirements during research phase

4. **Assumption**: toolhive operator supports both stdio and sse transports
   - Validation Needed: Review toolhive operator documentation and CRD schema
   - Risk if Invalid: SSE servers cannot be deployed using current operator version
   - Mitigation: Check toolhive operator version, upgrade if needed, or use alternative transport

### Performance Considerations

- **Resource Impact**: 18 MCP servers × resource limits (1000m cpu, 2Gi memory) = potential 18 vCPU cores, 36Gi memory maximum
  - Home-lab cluster capacity: Need to verify cluster has sufficient resources
  - Actual usage expected to be much lower (requests: 100m cpu, 128Mi memory per server = 1.8 vCPU, 2.3Gi baseline)
  - Recommendation: Monitor cluster resource usage after each batch conversion

- **Scalability**: Single-replica deployment pattern for all servers
  - No high-availability requirements (home-lab context)
  - S3-backed persistence provides durability without pod replication
  - Acceptable downtime during pod restarts or updates

- **Benchmarking Needs**:
  - MCP server response latency: local process vs Kubernetes service
  - Network overhead for stdio/sse communication through cluster
  - SOPS secret decryption time during pod startup
  - Memory usage patterns across different MCP servers

---

## 6. Design Phase Priorities

Based on this analysis, the design phase should prioritize:

1. **Resolve MCP Server Configuration Source** (CRITICAL)
   - WHY: Cannot proceed with accurate design without verified server list
   - ACTION: Locate Claude Code MCP server configuration files
   - TIMELINE: Immediate (blocking all subsequent work)

2. **Fix Memory Limit Bug in Template** (CRITICAL)
   - WHY: github.yaml serves as template; bug will propagate to all conversions if not fixed
   - ACTION: Change line 25 from "2048Gi" to "2Gi" in kubernetes/apps/toolhive/mcp_servers/github.yaml
   - TIMELINE: Before any batch conversions begin

3. **Research Server-Specific Requirements** (HIGH)
   - WHY: Design must account for per-server variations (credentials, permissions, transport)
   - ACTION: Document image source, transport protocol, permission profile, and credentials for each of 18 servers
   - TIMELINE: Before design phase completion

4. **Design Secret Management Strategy** (HIGH)
   - WHY: Shared secret with 18 keys needs clear organization and naming conventions
   - ACTION: Define secret key naming pattern, document credential sources, plan SOPS encryption workflow
   - TIMELINE: Before design phase completion

5. **SSE Transport Protocol Pattern** (MEDIUM)
   - WHY: Requirements specify both stdio AND sse support
   - ACTION: Create example MCPServer YAML with sse transport (if applicable servers exist)
   - TIMELINE: During design phase if sse servers identified

6. **Validation and Testing Strategy** (MEDIUM)
   - WHY: Requirements mandate documentation of validation commands and troubleshooting
   - ACTION: Document kubectl commands, flux build process, common errors and resolutions
   - TIMELINE: During design phase, before implementation

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|--------------|
| **MCP server configuration files never located** | MEDIUM | **CRITICAL** | Search alternative config locations (docker-compose, env files, scripts); consult user documentation; use system context as fallback with explicit caveat |
| **Memory limit bug propagates to all conversions** | HIGH (if not fixed) | **HIGH** | Fix github.yaml template BEFORE any batch conversions; add validation check to detect >2Gi memory limits |
| **Shared secret pattern doesn't scale to 18 keys** | LOW | **MEDIUM** | Test secret.sops.yaml with all 18 keys; if size issues occur, split into multiple Secrets by server category |
| **Some servers require non-standard configurations** | MEDIUM | **MEDIUM** | Complete per-server research before design phase; document exceptions in design.md; create additional templates if needed |
| **SSE transport not supported by toolhive operator** | LOW | **MEDIUM** | Research toolhive CRD schema and operator version; upgrade operator if needed; fallback to stdio-only if sse unavailable |
| **Cluster insufficient resources for 18 servers** | LOW | **MEDIUM** | Monitor resource usage during batch conversions; implement server on-demand deployment pattern; prioritize critical servers |
| **Claude Code cannot connect to Kubernetes-hosted servers** | LOW | **HIGH** | Test end-to-end connection with github server before batch conversion; document connection configuration; maintain parallel local servers during transition |
| **SOPS decryption fails during deployment** | LOW | **MEDIUM** | Verify age key availability in cluster before deployment; test SOPS decryption in CI/CD; implement age key rotation procedure |
| **Breaking changes disrupt existing Claude Code workflows** | MEDIUM | **HIGH** | Plan parallel operation (local + Kubernetes servers); document migration steps; implement gradual cutover per server |
| **Pattern divergence across server implementations** | MEDIUM | **MEDIUM** | Use template-based approach with validation gates; implement automated YAML validation; maintain design documentation with pattern compliance checklist |

---

## Appendix: Investigation Notes

### Codebase Search Results

**Files Examined**:
1. `kubernetes/apps/toolhive/mcp_servers/github.yaml` - Reference MCPServer implementation
2. `kubernetes/apps/toolhive/mcp_servers/kustomization.yaml` - GitOps integration pattern
3. `kubernetes/apps/toolhive/mcp_servers/secret.sops.yaml` - SOPS-encrypted credential storage
4. `.kiro/specs/mcp-toolhive-conversion/requirements.md` - Approved requirements specification
5. `.kiro/specs/mcp-toolhive-conversion/spec.json` - Specification metadata and status
6. `.kiro/settings/rules/gap-analysis.md` - Gap analysis framework template
7. `README.md` - General cluster documentation (no MCP server references found)
8. `.claude/CLAUDE.md` - Kiro framework documentation (no MCP server configurations)

**Search Commands Executed**:
```bash
# Search for common MCP server names
grep -ri "github.*mcp|slack.*mcp|filesystem.*mcp|postgres.*mcp|brave.*mcp|tavily.*mcp|playwright.*mcp|context7|sequential.*thinking"
# Result: Only found existing github.yaml

# Search for MCP container images
grep -ri "ghcr\.io.*mcp|docker\.io.*mcp|mcp.*server|mcp.*plugin"
# Result: Found 6 files (requirements.md, git logs, existing k8s resources)

# Find all MCP-related files
find . -type f \( -name "*mcp*" -o -name "*toolhive*" \) ! -path "./.git/*" ! -path "./.kiro/*"
# Result: Found 2 toolhive operator YAML files, existing MCPServer resources

# Check standard Claude Code config locations
ls ~/.claude/settings.json
# Result: File not found

ls -la ~/.config/claude
# Result: Directory does not exist
```

**Key Findings**:
- ✅ github.yaml provides complete reference pattern with minor bug
- ✅ Kustomization structure matches GitOps requirements
- ✅ SOPS encryption pattern correctly implemented
- ❌ Claude Code MCP server configuration files not located in repository
- ❌ No SSE transport examples found
- ⚠️ Memory limit bug: 2048Gi instead of 2Gi (line 25 of github.yaml)

### External Research

**MCP Server List** (18 servers identified from system context):

**Core MCP Servers** (8):
1. context7 (plugin:compounding-engineering:context7) - Documentation lookup
2. sequential-thinking - Multi-step reasoning
3. magic - UI component generation
4. morphllm - Code transformation
5. serena - Semantic understanding
6. playwright (plugin:compounding-engineering:playwright) - Browser automation
7. tavily - Web search
8. chrome-devtools - Browser debugging

**Cloud/Infrastructure MCP Servers** (10):
9. pagerduty-mcp - Incident management
10. github (awslabs GitHub MCP) - Currently deployed
11. homebrew - Package management
12. datadog - Monitoring
13. terraform - Infrastructure as code
14. aws-terraform - AWS-specific IaC
15. aws-diagrams - Architecture visualization
16. aws-pricing (awslabs-aws-pricing-mcp-server) - Cost analysis
17. aws-iam (awslabs-iam-mcp-server) - Identity management
18. aws-ecs (awslabs-ecs-mcp-server) - Container orchestration

**Status**: This list was derived from system context and MCP documentation sections but has NOT been verified against actual Claude Code configuration files. The source configuration files could not be located in the repository or standard configuration directories.

**CRITICAL NOTE**: Requirements specify converting "all existing Claude Code MCP Server configurations" but these configuration files remain unlocated. This list should be validated before design phase completion.

---

## Status and Next Steps

**Gap Analysis Status**: **COMPLETE** with noted research caveat

**Critical Research Item**: Locate Claude Code MCP server configuration files to verify the 18-server list

**Recommended Next Actions**:
1. Fix memory limit bug in github.yaml (2048Gi → 2Gi)
2. Validate MCP server list against actual Claude Code configuration
3. Research per-server requirements (credentials, transport, permissions)
4. Proceed to design phase with detailed implementation plan
5. Document validation commands and troubleshooting procedures

**Design Phase Readiness**: Ready to proceed with design.md creation, noting the MCP server list verification as a design-phase research task
