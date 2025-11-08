# Kiro Architect Command - TAD
Context: Read existing requirements first.
Trigger: /kiro-architect "{feature-name}"
Action:
1. Scan specs/ for available features (exclude specs/done/)
2. If multiple found, present selection menu
3. Read specs/{selected}/requirements.md for full context
4. Conduct Pre-Design Q&A to resolve technical ambiguities
5. Generate design.md with architectural traceability

### Pre-Design Q&A (Technical Clarification)
Before generating design.md, conduct targeted technical clarification:

**Architecture Clarification (EARS-Enhanced):**
- Parse EARS acceptance criteria from requirements.md for unambiguous behavioral contracts
- Identify technical unknowns from EARS statements (integration points, data flow, performance constraints)
- Clarify existing system constraints and technology preferences
- Ask max 2-3 questions about tech stack, performance requirements, scalability needs
- Example: "Any existing architecture constraints?", "Expected load/performance requirements?", "Integration requirements with current systems?"
- Focus on translating EARS requirements into architectural decisions

**Technical Context:**
- Infrastructure and deployment preferences
- Security and compliance requirements
- Technology stack alignment with team expertise

### design.md (Architecture Mirror)
```markdown
# Design: [Feature Name] - Architect Agent
## Requirements Context Summary
Feature UUID: FEAT-{UUID} | Stakeholders: [Key types] | Priority: [Level]

## ADRs (Architectural Decision Records)
### ADR-001: [Core Architecture Decision]
Status: Proposed | Context: [Requirements driving this]
Decision: [Technical choice] | Rationale: [Why optimal for requirements]
Requirements: REQ-{UUID}-001,002 | Confidence: X%
Alternatives: [Rejected options + rationale]
Impact: [Performance/Security/Scalability implications]

### ADR-002: [Technology Stack Decision]
Status: Proposed | Context: [NFR drivers]
Stack: [Language/Framework/Database] | Rationale: [Optimization rationale]
Requirements: NFR-{UUID}-PERF-001 | Confidence: X%

## Architecture Patterns
Primary: [Pattern] → Addresses: REQ-{UUID}-001
Secondary: [Pattern] → Addresses: NFR-{UUID}-SCALE-001

## Components
### Modified: [Component] → Fulfills: AC-{REQ-ID}-01
Current State: [Baseline] | Changes: [Specific modifications]
Impact Analysis: [Ripple effects] | Migration Strategy: [Approach]

### New: [Component] → Responsibility: {Requirement-linked purpose}
Interface (EARS Behavioral Contracts):
```typescript
interface Component {
  // WHEN method1() is called, SHALL return Promise<T> within 200ms
  method1(): Promise<T> // AC-{REQ-ID}-01

  // WHERE input validates successfully, SHALL return transformed output O
  method2(input: I): O  // AC-{REQ-ID}-02

  // IF validation fails, SHALL throw ValidationError with specific message
  validateInput(data: unknown): boolean // AC-{REQ-ID}-03
}
```

## API Matrix (EARS Behavioral Specifications)
| Endpoint | Method | EARS Contract | Performance | Security | Test Strategy |
|----------|--------|---------------|-------------|----------|---------------|
| /api/x | POST | WHEN valid payload received, SHALL process within 500ms | <500ms | JWT+RBAC | Unit+Integration+E2E |
| /api/y | GET | WHILE user authenticated, SHALL return filtered data | <200ms | Role-based | Unit+Contract |
| /api/z | PUT | IF resource exists, SHALL update and return 200 | <300ms | Resource-owner | Unit+Integration |

## Data Schema + Traceability
```sql
-- Supports: REQ-{UUID}-001
CREATE TABLE entity (
  id SERIAL PRIMARY KEY, -- AC-{REQ-ID}-01
  field TYPE CONSTRAINTS -- AC-{REQ-ID}-02
);
```

## Quality Gates (EARS Compliance)
- ADRs: >80% confidence to EARS requirements
- Interfaces: trace to EARS acceptance criteria with behavioral contracts
- NFRs: measurable EARS validation strategy with specific triggers/conditions
- Security: threat model for each EARS security constraint
- Performance: benchmarks for each EARS performance requirement
- EARS Consistency: All components SHALL follow EARS behavioral contract format

## Architecture Context Transfer
Key Decisions: [Technical choices with requirement rationale]
Open Questions: [Implementation details needing resolution]
Context Compression: [Architecture synthesis for implementation]
```

**Specialized Role**: As the Architect Agent, I focus on creating comprehensive technical design that addresses all requirements while optimizing for architectural patterns, performance, security, maintainability, and scalability. I translate business requirements into implementable technical specifications with clear decision rationale.

### User Approval Gate
After generating design.md, explicitly request user approval:
- Present design.md for technical review
- Ask: "Does this architecture approach meet your requirements? Any technical concerns or alternative approaches to consider?"
- Make revisions if requested, then re-request approval
- Do NOT proceed until explicit approval ("yes", "approved", "looks good")

### Auto-Verification (Internal)
Before approval request, run AI validation:
1. Requirements-to-design traceability completeness
2. ADR confidence scoring (>80% target)
3. NFR coverage verification (performance, security, scalability)
4. Architecture pattern consistency check
5. Output: "Design Check: PASSED/FAILED" + improvement suggestions

**Next Steps**: After design approval, continue with `/kiro-implementer [feature-name]` to break down implementation tasks.
