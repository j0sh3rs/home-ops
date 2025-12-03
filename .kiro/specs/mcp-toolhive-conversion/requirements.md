# Requirements: MCP Toolhive Conversion

**Status**: Requirements Generated
**Created**: 2025-12-02T00:00:00Z
**Updated**: 2025-12-02T00:00:00Z
**Phase**: Requirements Definition

## Project Description

Convert all of the existing Claude Code MCP Server configurations into ones that are deployable using the toolhive pattern defined in kubernetes/apps/toolhive/mcp_servers

## Requirements Overview

This specification covers the conversion of Claude Code MCP Server configurations to Kubernetes-native MCPServer custom resources following the toolhive deployment pattern. Key requirement areas include:

- **Configuration Discovery**: Identify and catalog all existing MCP server configurations
- **Resource Generation**: Create MCPServer CRDs for each identified server
- **Secret Management**: Implement SOPS-encrypted secrets for credentials
- **GitOps Integration**: Ensure Flux compatibility with kustomization structure
- **Validation**: Verify deployments follow cluster standards

---

## Requirement 1: MCP Server Configuration Discovery

### User Story

As a cluster operator, I want to identify all existing Claude Code MCP server configurations so that I can systematically convert them to Kubernetes deployments.

### Acceptance Criteria (EARS Format)

1. **Configuration Identification**
    - The system SHALL identify all MCP servers referenced in project documentation
    - **Measurable Success**: Complete list of MCP servers with names and purposes documented

2. **Configuration Analysis**
    - WHEN analyzing each MCP server, the system SHALL document its container image, environment variables, and resource requirements
    - **Measurable Success**: Each server has documented image source, required env vars, and credential needs

3. **Server Catalog**
    - The system SHALL create a catalog listing all identified MCP servers with their current configuration details
    - **Measurable Success**: Catalog includes server name, image, transport protocol, secrets, and environment variables

### Priority

High

### Dependencies

- Access to project documentation and MCP server references
- Understanding of toolhive MCPServer CRD schema

---

## Requirement 2: MCPServer Resource Generation

### User Story

As a cluster operator, I want each MCP server converted to a Kubernetes MCPServer resource so that they can be deployed via GitOps.

### Acceptance Criteria (EARS Format)

1. **MCPServer CRD Creation**
    - WHEN generating resources, the system SHALL create one MCPServer YAML file per server
    - **Measurable Success**: Each server has a corresponding `{server-name}.yaml` file in `kubernetes/apps/toolhive/mcp_servers/`

2. **Required Metadata**
    - The MCPServer resource SHALL include name and namespace matching the toolhive-system pattern
    - **Measurable Success**: All resources have `metadata.name` and `metadata.namespace: toolhive-system`

3. **Image Specification**
    - The MCPServer resource SHALL specify the correct container image for each server
    - **Measurable Success**: `spec.image` field contains valid container image reference

4. **Transport Configuration**
    - The MCPServer resource SHALL specify transport protocol as `stdio` WHEN applicable
    - The MCPServer resource SHALL specify transport protocol as `sse` WHEN applicable
    - **Measurable Success**: `spec.transport: stdio` is set for all servers using stdio; `spec.transport: sse` for those using SSE

5. **Permission Profiles**
    - WHEN a server requires network access, the system SHALL configure appropriate permission profiles
    - **Measurable Success**: `spec.permissionProfile` is set based on server requirements (network, filesystem, or none)

### Priority

High

### Dependencies

- Requirement 1 (Configuration Discovery) completed
- Understanding of each server's permission requirements

---

## Requirement 3: Secret Management

### User Story

As a security-conscious operator, I want all MCP server credentials stored as SOPS-encrypted secrets so that sensitive data is protected in Git.

### Acceptance Criteria (EARS Format)

1. **Secret Resource Creation**
    - WHERE servers require credentials, the system SHALL create or update the `secret.sops.yaml` file
    - **Measurable Success**: `secret.sops.yaml` exists with all required credential keys

2. **SOPS Encryption**
    - The secret file SHALL be encrypted using the cluster's age key before committing
    - **Measurable Success**: `stringData` fields are encrypted with SOPS age encryption

3. **Secret Reference**
    - WHEN a server requires credentials, the MCPServer resource SHALL reference the secret correctly
    - **Measurable Success**: `spec.secrets` array maps secret keys to environment variables

4. **Secret Key Format**
    - The system SHALL use consistent naming for secret keys (UPPERCASE_WITH_UNDERSCORES)
    - **Measurable Success**: All secret keys follow the pattern `{SERVER}_TOKEN` or `{SERVER}_API_KEY`

### Priority

High

### Dependencies

- SOPS configuration (`.sops.yaml`) present in repository
- Age encryption key available for the cluster

---

## Requirement 4: Resource Configuration

### User Story

As a platform engineer, I want each MCP server to have appropriate resource limits and environment variables so that they run efficiently within cluster constraints.

### Acceptance Criteria (EARS Format)

1. **Resource Limits**
    - The MCPServer resource SHALL specify CPU and memory limits appropriate for home-lab constraints
    - **Measurable Success**: `spec.resources.limits` set with cpu ≤ 1000m and memory ≤ 2Gi per server

2. **Resource Requests**
    - The MCPServer resource SHALL specify conservative resource requests for scheduling
    - **Measurable Success**: `spec.resources.requests` set with cpu ≥ 100m and memory ≥ 128Mi

3. **Environment Variables**
    - WHEN a server requires configuration, the system SHALL provide environment variables via `spec.env`
    - **Measurable Success**: Non-secret configuration values in `spec.env` array

4. **Port Configuration**
    - WHERE applicable, the MCPServer resource SHALL specify the service port
    - **Measurable Success**: `spec.port` field configured for servers requiring network access

### Priority

Medium

### Dependencies

- Understanding of each server's runtime requirements
- Cluster resource availability knowledge

---

## Requirement 5: Kustomization Integration

### User Story

As a GitOps practitioner, I want all MCPServer resources integrated into the kustomization structure so that Flux can deploy them automatically.

### Acceptance Criteria (EARS Format)

1. **Kustomization Resource List**
    - WHEN adding a new MCPServer, the system SHALL update `kustomization.yaml` to include it
    - **Measurable Success**: `kustomization.yaml` resources list includes all `{server-name}.yaml` files

2. **Namespace Consistency**
    - The kustomization SHALL declare `namespace: toolhive-system` for all resources
    - **Measurable Success**: `kustomization.yaml` has `namespace: toolhive-system` field

3. **Secret Inclusion**
    - The kustomization SHALL include `secret.sops.yaml` in resources list
    - **Measurable Success**: `./secret.sops.yaml` is first item in resources array

4. **GitOps Compatibility**
    - The kustomization structure SHALL be compatible with Flux reconciliation
    - **Measurable Success**: `flux build kustomize kubernetes/apps/toolhive/mcp_servers` succeeds

### Priority

High

### Dependencies

- Flux installed in cluster
- Kustomize binary available for validation

---

## Requirement 6: Documentation and Validation

### User Story

As a future maintainer, I want clear documentation of the conversion process and validation steps so that I can troubleshoot or extend the deployment.

### Acceptance Criteria (EARS Format)

1. **Conversion Documentation**
    - The system SHALL document which MCP servers were converted and their configuration
    - **Measurable Success**: README or documentation file lists all converted servers with deployment status

2. **Validation Commands**
    - The system SHALL provide commands to validate the MCPServer resources before deployment
    - **Measurable Success**: Documentation includes `kubectl apply --dry-run` and `flux build` validation steps

3. **Deployment Verification**
    - WHEN resources are deployed, the system SHALL provide commands to verify MCPServer pod status
    - **Measurable Success**: Documentation includes `kubectl get mcpserver -n toolhive-system` and pod status checks

4. **Troubleshooting Guide**
    - The system SHALL document common issues and their resolutions
    - **Measurable Success**: Documentation includes troubleshooting section with log access and common errors

### Priority

Medium

### Dependencies

- Access to Kubernetes cluster for testing
- Flux and kubectl CLI tools available

---

## Non-Functional Requirements

### Performance

- The conversion process SHALL complete analysis and generation for all MCP servers within 5 minutes

### Security

- The system SHALL NEVER commit unencrypted secrets to Git
- All secret values SHALL be encrypted with SOPS before any Git operations

### Reliability

- The MCPServer resources SHALL be compatible with Kubernetes API version `toolhive.stacklok.dev/v1alpha1`
- The generated YAML SHALL pass Kubernetes schema validation

### Maintainability

- The MCPServer YAML files SHALL follow consistent formatting (2-space indentation, sorted keys)
- Secret keys SHALL use consistent naming conventions across all servers

---

## Out of Scope

Items explicitly excluded from this specification:

- Deploying toolhive operator itself (assumed to be already installed)
- Modifying existing Claude Code configurations (only converting, not changing)
- Creating custom MCP server images (using existing published images)
- Implementing custom permission profiles (using builtin profiles only)
- Migrating away from Claude Code to native toolhive clients (conversion only, not replacement)

---

## Approval

- [ ] Requirements reviewed and approved
- [ ] Ready to proceed to design phase

**Approved by**: ******\_******
**Date**: ******\_******
