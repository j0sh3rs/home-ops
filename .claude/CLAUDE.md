# Kiro Style Specification-Driven Development Template

This project adopts Kiro-style specification-driven development with EARS (Easy Approach to Requirements Syntax) hybrid implementation for enhanced precision and testability.

## Specification Files

- **specs/{feature-name}/requirements.md**: User stories with EARS acceptance criteria (WHEN/WHILE/IF/WHERE + SHALL)
- **specs/{feature-name}/design.md**: Technical architecture with EARS behavioral contracts
- **specs/{feature-name}/tasks.md**: Implementation tasks with EARS Definition of Done (DoD)
- **specs/debug-{issue-id}/requirements.md**: Issue definition with EARS expected resolution criteria
- **specs/debug-{issue-id}/design.md**: Debug strategy with EARS-compliant solution specifications
- **specs/debug-{issue-id}/tasks.md**: Investigation steps with EARS validation checkpoints

## Development Flow

1. Requirements Definition → Document in requirements.md
2. Design → Document in design.md
3. Task Division → Document in tasks.md
4. Implementation → Implement each task sequentially
5. Verification → Test build and resolve any errors
6. Archival → Move completed features to specs/done/

## Debugging Flow

1. Issue Detection → Document problem in requirements.md
2. Investigation → Analyze root causes and document in design.md
3. Solution Design → Create resolution strategy in design.md
4. Implementation → Apply fixes following tasks.md
5. Validation → Verify resolution without introducing new issues
6. Documentation → Update relevant specifications with insights gained

## Commands

- `/kiro`: Initialize specifications for a new feature
- Ask "Approve requirements.md" to confirm requirements
- Ask "Approve design.md" to confirm design
- Ask "Please implement Task X" for implementation
- Natural language debugging queries like "Investigate why [issue] is occurring"

## Development Rules

1. All features start with requirements definition
2. Proceed to design after approving requirements
3. Proceed to implementation after approving design
4. Tasks should be independently testable
5. Mark tasks as completed using `[x]` notation
6. All tasks must pass verification before archiving
7. Debugging follows the same spec-driven approach as feature development

## Task Completion

When a task is completed:

1. Update tasks.md by changing `[ ]` to `[x]`
2. Update the progress counter at the top of tasks.md
3. Proceed to the next task only after confirming current task works

## Agent Specialization with EARS Hybrid Implementation

This project supports specialized agent roles with EARS (Easy Approach to Requirements Syntax) integration:

### Agent Commands

- `/kiro [feature-name]` - Full TAD workflow with EARS integration
- `/kiro-researcher [feature-name]` - Requirements specialist with EARS acceptance criteria
- `/kiro-architect [feature-name]` - Design specialist with EARS behavioral contracts
- `/kiro-implementer [feature-name]` - Implementation specialist with EARS DoD
- Natural language debugging queries - Debugging specialist with EARS validation

### EARS-Enhanced Agent Workflow

1. **Researcher**: Create requirements.md with EARS syntax (WHEN/WHILE/IF/WHERE + SHALL)
2. **Architect**: Create design.md with EARS behavioral contracts for components
3. **Implementer**: Create tasks.md with EARS Definition of Done for each task
4. **Debugger**: Use EARS validation for systematic issue resolution

### EARS Hybrid Benefits

- **Eliminates Ambiguity**: "WHEN user clicks login, system SHALL authenticate within 200ms" vs "fast login"
- **Direct Test Translation**: EARS → BDD (Given/When/Then) mapping for automated testing
- **Behavioral Contracts**: Component interfaces specify exact behavioral expectations
- **Measurable Success**: Every requirement has specific triggers and measurable outcomes
- **Token Efficiency**: Dense, precise EARS statements reduce verbose explanations
- **Comprehensive Coverage**: Every acceptance criterion maps to testable conditions

## EARS-Enhanced Debugging Capabilities

The debugging system provides:

1. **Context-aware analysis** with EARS behavioral expectation validation
2. **Root cause identification** using EARS acceptance criteria mapping
3. **Solution design** with EARS-compliant resolution specifications
4. **Structured implementation** with EARS Definition of Done for debug tasks
5. **Comprehensive validation** using EARS success criteria measurement

Debugging with EARS precision:

- "WHEN user submits login, system SHALL respond within 200ms but currently takes 5s"
- "WHERE file size exceeds 10MB, system SHALL handle gracefully but currently crashes"
- "IF authentication token is invalid, system SHALL return 401 but returns 500"

EARS debugging creates measurable resolution criteria:

- **Issue Definition**: EARS format for exact problem specification
- **Expected Resolution**: EARS acceptance criteria for successful fix
- **Validation Steps**: EARS-to-BDD test scenarios for verification

## Responding to Specification Changes

When specifications change, update all related specification files (requirements.md, design.md, tasks.md) while maintaining consistency.

Examples:

- "I want to add user authentication functionality"
- "I want to change the database from PostgreSQL to MongoDB"
- "The dark mode feature is no longer needed, please remove it"

When changes occur, take the following actions:

1. Add/modify/delete requirements in requirements.md
2. Update design.md to match the requirements
3. Adjust tasks.md based on the design
4. Verify consistency between all files

## Integration Between Development and Debugging

When debugging reveals issues that require specification changes:

1. Complete the debugging process to resolve immediate issues
2. Document findings that impact specifications
3. Update original feature specifications to reflect new understanding
4. Create regression tests to prevent issue recurrence
5. Consider architectural implications of recurring issues

For detailed debugging information with EARS implementation, refer to the debugger.md documentation.

## EARS Hybrid Implementation Details

### EARS Syntax Format

- **WHEN** [trigger condition], the system **SHALL** [specific action]
- **WHILE** [ongoing state], the system **SHALL** [continuous behavior]
- **IF** [conditional state], the system **SHALL** [conditional response]
- **WHERE** [constraint boundary], the system **SHALL** [bounded action]

### EARS-to-BDD Translation

EARS requirements automatically translate to BDD scenarios:

- **EARS**: WHEN user submits valid form, system SHALL save data within 1 second
- **BDD**: GIVEN valid form data, WHEN user submits form, THEN system saves within 1 second

### Quality Assurance with EARS

- Every acceptance criterion includes confidence scoring
- All behavioral contracts specify measurable outcomes
- Component interfaces use EARS format for precise expectations
- Test coverage maps directly from EARS statements to automated tests

### Implementation Verification

- Definition of Done (DoD) written in EARS format
- Task completion verified against EARS acceptance criteria
- Progress tracking includes EARS compliance validation
- Archival process preserves EARS traceability relationships

## Project Architecture Patterns

### Infrastructure Overview

This is a home-lab Kubernetes cluster managed via GitOps with FluxCD. The cluster follows established patterns for deployment, storage, and monitoring.

### Deployment Patterns

- **GitOps with FluxCD**: All applications deployed via `HelmRelease` + `OCIRepository` pattern
- **Namespace Organization**: Applications grouped by function (monitoring, databases, network, services)
- **SOPS Encryption**: All secrets encrypted using SOPS with age keys before committing to Git
- **Kustomize Structure**: Each app follows pattern: `{app}/ks.yaml` + `{app}/app/kustomization.yaml` + `{app}/app/helmrelease.yaml`

### Storage Architecture

- **Primary Storage**: OpenEBS LocalPV Provisioner for dynamic persistent volume provisioning
- **Storage Classes**: `openebs-localpv-hostpath` (default), `openebs-localpv-device` (block devices)
- **Disaster Recovery**: Velero integration with S3-backed snapshots (daily at 02:00 UTC, 30-day retention)
- **Object Storage**: Local Minio S3-compatible endpoint at `https://s3.68cc.io`
- **Storage Strategy**: Hybrid approach with local volumes (OpenEBS) for performance + S3 snapshots (Velero) for durability
- **S3 Integration Pattern**: Applications use S3 for persistent data with dedicated buckets per service
- **Credential Management**: Separate SOPS-encrypted secrets per component: `{component}-s3-secret`
- **S3 Secret Format**: Contains `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT`, `S3_BUCKET`
- **S3 Backup Buckets**: `openebs-backups` (Velero snapshots), `loki-chunks`, `tempo-traces`, `mimir-blocks`
- **Examples**: CloudNative-PG uses S3 for backups, LGTM stack uses S3 for data persistence, all stateful workloads use OpenEBS LocalPV volumes

### Observability Stack (LGTM Architecture)

- **Logs**: Loki with S3 backend (`loki-chunks` bucket) in simple scalable mode
- **Traces**: Tempo with S3 backend (`tempo-traces` bucket) in monolithic mode with OTLP receiver
- **Metrics**: Mimir with S3 backend (`mimir-blocks` bucket) in monolithic mode for long-term storage
- **Visualization**: Grafana with datasources for Prometheus, Loki, Tempo, and Mimir
- **Metrics Collection**: kube-prometheus-stack with Prometheus remote-write to Mimir

### Resource Sizing Strategy

- **Home-Lab Philosophy**: Single-replica deployments with S3 providing durability
- **Memory Limits**: Stateful services typically <2Gi per pod to conserve resources
- **Storage Strategy**: Prefer S3 backend over local PVCs for cost and durability
- **Scaling Approach**: Vertical scaling preferred over horizontal for resource efficiency

### Monitoring Namespace Components

- **kube-prometheus-stack**: Prometheus, Alertmanager, Grafana Operator, ServiceMonitors
- **Grafana**: Central visualization with multiple datasources
- **Loki**: Log aggregation with S3 persistence
- **Tempo**: Distributed tracing with S3 persistence
- **Mimir**: Long-term metrics storage with S3 persistence
- **netdata**: System monitoring
- **unpoller**: UniFi network monitoring

### Security Patterns

- **Secrets Management**: SOPS encryption mandatory for all credentials
- **Network Security**: Internal ingress for services, Cloudflare tunnel for external access
- **Credential Isolation**: Dedicated S3 credentials per component to limit blast radius
- **HTTPS Enforcement**: All S3 connections use HTTPS endpoint

### Service Discovery

- **DNS Pattern**: Services accessible via `{service-name}.{namespace}.svc.cluster.local`
- **Port Conventions**: Follow Helm chart defaults for consistency
- **Ingress**: Internal ingress controller with Cloudflare DNS integration

### Key Architectural Decisions

1. **FluxCD over ArgoCD**: Simpler for home-lab, native Kubernetes CRDs
2. **Single Replica Services**: S3 provides durability without pod replication overhead
3. **Minio S3 over Cloud**: Local control, cost savings, sufficient for home-lab scale
4. **LGTM Stack**: Unified Grafana observability (Loki/Tempo/Mimir) over separate vendor tools
5. **Monolithic Modes**: LGTM components in monolithic deployment mode for resource efficiency

## Bear V2 Agentic Agent Integration

Bear V2 enhances the Kiro framework with adaptive planning, persistent memory, and reflexive learning:

### Bear Commands

- `/bear [task-description]` - Full adaptive workflow with complexity triage
- `/bear-fast [simple-task]` - Fast Track for well-defined tasks
- `/bear-deep [complex-task]` - Deep Dive for complex projects
- `/bear-memory [query]` - Search persistent memory system

### Integration Benefits

- **Adaptive Workflows**: Automatic complexity assessment and workflow selection
- **Persistent Memory**: Learn from every project and maintain knowledge across sessions
- **Performance Optimization**: Agent selection based on historical effectiveness
- **Reflexive Learning**: Deep analysis and prevention of repeated errors
- **Enhanced Kiro**: Bear's memory system enhances specification-driven development

### Combined Usage

- Start with `/bear [feature]` for planning, then use `/kiro-implementer` for execution
- Use `/bear-memory` to find relevant specifications and past solutions
- Bear's Deep Dive workflow incorporates Kiro's EARS-driven specifications
- All Bear learnings feed back into improved Kiro specification quality
