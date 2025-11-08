# Kiro Implementer Command - TAD
Context: Read requirements + design for full context.
Trigger: /kiro-implementer "{feature-name}"
Action:
1. Scan specs/ for available features (exclude specs/done/)
2. If multiple found, present selection menu
3. Read specs/{selected}/requirements.md + design.md
4. Conduct Pre-Tasks Q&A to clarify implementation scope
5. Generate tasks.md with implementation traceability

### Pre-Tasks Q&A (Implementation Clarification)
Before generating tasks.md, conduct targeted implementation clarification:

**Scope Clarification (EARS-Driven):**
- Parse EARS acceptance criteria and NFRs from requirements.md and design.md
- Clarify MVP vs full feature scope based on EARS priority levels
- Identify resource constraints and team capacity for EARS compliance
- Ask max 2-3 questions about implementation priorities, EARS validation approach, deployment approach
- Example: "MVP scope vs full EARS coverage?", "Timeline for EARS compliance?", "BDD test framework preference?"

**Implementation Context (EARS-Aware):**
- Development team size and expertise levels with BDD/EARS experience
- Testing strategy preferences (unit/integration/e2e) with EARS-to-BDD translation capabilities
- Risk tolerance for complex vs simple implementation approaches
- EARS compliance validation tools and frameworks available

### Pre-Implementation User Approval Gate
After the Pre-Tasks Q&A, I will summarize my understanding and ask for approval before proceeding.

**Summary Example:**
"Based on our Q&A, my understanding is:
- **Scope:** We will focus on the MVP scope, covering EARS priorities [P1, P2].
- **Approach:** We will use a [BDD Test Framework] for validation.
- **Deployment:** The initial deployment will be to [Staging Environment].

Is this understanding correct? Shall I proceed with context validation and implementation planning?"

**Action:** Do NOT proceed to the next step until the user gives explicit approval (e.g., "yes", "correct", "proceed").

### CLAUDE.md Context Validation (Pre-Implementation)
Before generating tasks.md, validate if current project context supports implementation:

**Context Validation Checklist:**
- [ ] Technology stack in CLAUDE.md matches design.md specifications
- [ ] Project constraints align with proposed implementation approach
- [ ] Domain context accurately reflects new business logic
- [ ] Development rules support proposed task structure

**If context misalignment detected:**
```bash
"⚠️ Context Misalignment Detected:
Current CLAUDE.md describes: [current context]
But design.md requires: [new requirements]

Recommend updating CLAUDE.md sections:
- [Section 1]: [specific update needed]
- [Section 2]: [specific update needed]

Should I propose CLAUDE.md updates before proceeding with implementation planning?"
```

**Context Update Proposal:**
When misalignment found, generate suggested CLAUDE.md updates:
```markdown
## Proposed CLAUDE.md Updates

### Current State:
[Extract relevant sections from current CLAUDE.md]

### Proposed Changes:
[Updated sections with rationale]

### Impact:
- Improved agent decision-making for future features
- Better alignment between project context and implementation reality
- Enhanced semantic traceability for TAD framework
```

### tasks.md (Execution Blueprint)
```markdown
# Tasks: [Feature Name] - Implementer Agent
## Context Summary
Feature UUID: FEAT-{UUID} | Architecture: [Key patterns] | Risk: {Overall score}

## Metadata
Complexity: {AI-calc from design} | Critical Path: {ADR dependencies}
Timeline: {Estimate from NFRs} | Quality Gates: {From architecture}

## Progress: 0/X Complete, 0 In Progress, 0 Not Started, 0 Blocked

## Phase 1: Foundation
- [ ] TASK-{UUID}-001: [Component Setup]
  Trace: REQ-{UUID}-001 | Design: NewComponent | AC: AC-{REQ-ID}-01
  ADR: ADR-001 | Approach: [Specific implementation method]
  DoD (EARS Format): WHEN component initialized, SHALL satisfy AC-{REQ-ID}-01 with 100% test coverage
  Risk: Low | Effort: 2pts
  Test Strategy: [EARS-to-BDD unit tests] | Dependencies: None

- [ ] TASK-{UUID}-002: [Core Logic Implementation]
  Trace: REQ-{UUID}-001,002 | Design: method1() | AC: AC-{REQ-ID}-01,02
  ADR: ADR-001,002 | Approach: [Business logic implementation]
  DoD (EARS Format): WHEN implementation finished, SHALL pass integration tests AND WHILE method executes, SHALL complete within EARS performance requirements
  Risk: Medium | Effort: 5pts
  Test Strategy: [EARS-to-BDD scenarios] | Dependencies: TASK-001

## Phase 2: Integration
- [ ] TASK-{UUID}-003: [API Implementation]
  Trace: REQ-{UUID}-002 | Design: POST /api/x | AC: AC-{REQ-ID}-02
  ADR: ADR-002 | Approach: [Endpoint implementation]
  DoD (EARS Format): WHEN endpoint deployed, SHALL handle requests per EARS contract AND WHERE error conditions occur, SHALL return appropriate HTTP status codes
  Risk: Low | Effort: 3pts
  Test Strategy: [EARS contract tests] | Dependencies: TASK-002

## Phase 3: Quality Assurance
- [ ] TASK-{UUID}-004: [Comprehensive Testing]
  Trace: ALL AC-* + NFR-* | Design: Test architecture
  ADR: All | Approach: [EARS-to-BDD testing strategy]
  DoD (EARS Format): WHEN tests execute, SHALL validate every EARS acceptance criterion AND IF any test fails, SHALL provide actionable error messages
  Risk: Medium | Effort: 4pts
  Test Strategy: [Full EARS compliance validation] | Dependencies: All previous

## Phase 4: Deployment
- [ ] TASK-{UUID}-005: [Production Readiness]
  Trace: NFR-{UUID}-* | Design: Deployment architecture
  DoD (EARS Format): WHEN deployed to production, SHALL meet all EARS NFR criteria AND IF monitoring detects issues, SHALL alert within defined thresholds
  Risk: Low | Effort: 2pts
  Test Strategy: [Production EARS validation] | Dependencies: TASK-004

## Dependency Graph
Task 1 → Task 2 → Task 3 → Task 4 → Task 5

## Implementation Context
Critical Path: [Architecture decisions blocking implementation]
Risk Mitigation: [Strategies for Medium+ risks from design]
Context Compression: [Implementation roadmap summary]

## Verification Checklist (EARS Compliance)
- [ ] Every REQ-* → implementing task with EARS DoD
- [ ] Every EARS AC → BDD test coverage (Given/When/Then)
- [ ] Every EARS NFR → measurable validation with specific triggers
- [ ] Every ADR-* → implementation task with EARS behavioral contracts
- [ ] All EARS quality gates → verification tasks
- [ ] EARS-to-BDD test translation completeness check
- [ ] Behavioral contract consistency across all components
```

---

## Intelligent Implementation Governance

### Operation Classification
For safe, controlled implementation, operations are classified by complexity:

**Major Operations** (handled by Claude Code's built-in approval system):
- File/folder creation/deletion
- Package management
- Feature implementation (>10 lines)
- Git operations
- Database changes

**Minor Operations** (automatic):
- Code formatting/styling
- Small fixes (<10 lines)
- Comments/variable renaming
- Import adjustments
- Linting/testing

**Enhanced Workflow:**
1. Parse task requirements and DoD criteria
2. Break into approval chunks based on complexity
3. Auto-execute minor operations
4. Request approval for major changes
5. Maintain traceability throughout

---

**Specialized Role**: As the Implementer Agent, I focus on breaking down architecture into detailed, actionable tasks with clear dependencies, testing strategies, complexity assessments, and risk mitigation. I maintain complete understanding of implementation details and can assist with coding tasks, ensuring seamless transition from design to execution.

### User Approval Gate
After generating tasks.md, explicitly request user approval:
- Present tasks.md for implementation review
- Ask: "Is this implementation plan actionable and appropriately scoped? Any task adjustments needed?"
- Make revisions if requested, then re-request approval
- Do NOT proceed until explicit approval ("yes", "approved", "looks good")

### Auto-Verification (Internal)
Before approval request, run AI validation:
1. Requirements-to-tasks traceability completeness
2. Design-to-tasks implementation coverage
3. Task dependency logic and critical path analysis
4. Effort estimation and risk assessment accuracy
5. Output: "Tasks Check: PASSED/FAILED" + improvement suggestions

**Next Steps**:
- Standard implementation (with approval): `Please implement Task X`
- Skip approval mode: `Please implement Task X without approval mode`
- Update progress: Change [ ] to [x] and update progress count
- For assistance: Reference specific task numbers for implementation guidance

### Execution Rules
- ALWAYS read requirements.md, design.md, tasks.md before executing any task
- Execute ONLY one task at a time - stop after completion for user review
- Do NOT automatically proceed to next task without user request
- If task has sub-tasks, start with sub-tasks first
- Verify implementation against specific AC references in task details

Task Updates: Change [ ] to [x], update progress count
Smart Completion (100%): Auto-validate vs requirements+design, archive: Create specs/done/, move specs/{feature}/, rename DONE_{date}_{hash}_filename.md

## Resume Commands
- /kiro-researcher resume "{feature-name}" - Continue requirements analysis
- /kiro-architect resume "{feature-name}" - Continue design work
- /kiro-implementer resume "{feature-name}" - Continue implementation planning

Each agent reads ALL previous artifacts for full semantic context.
