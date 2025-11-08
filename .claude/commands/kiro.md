# Kiro Command - Traceable Agentic Development (TAD)

**Context:** Review `CLAUDE.md` for project context first.
**Trigger:** `/kiro "Feature Name"`
**Action:** Create `specs/{kebab-case-feature-name}/` with a semantic traceability chain.

---

## Phase 0: Mandatory Thinking Pass (🛑 Do Not Generate Yet)

> You must complete this **thinking-only** section **before** generating `requirements.md`, `design.md`, or `tasks.md`.
> If any item below is incomplete or uncertain, **STOP** and ask up to **3–5** focused questions (see Phase 1.0) before proceeding.
> If any section feels rushed or incomplete after first pass, revise until confident before proceeding.

### 0.A Problem Framing (1–2 sentences)
- **Core objective:**
- **Primary users & value:**
- **Out-of-scope / risks to avoid:**

### 0.B Assumptions (max 5; each with confidence %)
1. (…%)
2. (…%)

### 0.C Constraints (tech, org, time, compliance)
- …

### 0.D Solution Options (at least 2)
- **Option A** — summary, key pros, key cons
- **Option B** — summary, key pros, key cons
**Selection:** A | B — because …

### 0.E Test Strategy Sketch (tie to EARS AC groups)
- How will each **EARS** acceptance criterion be validated? (unit / integration / E2E / inspection)

### 0.F Go/No-Go Criteria
- Proceed only when **every AC group** has ≥1 validation idea **and** all critical ambiguities are resolved.

> **Gate:** If options < 2, AC validation is missing, or critical ambiguity remains → **STOP** and ask clarification questions (Phase 1.0).

---

## Phase 1: Generation Sequence

### 0. Pre-Generation Q&A (Ambiguity Resolution)
Before generating each document, conduct targeted clarification to minimize revision cycles:

**Requirements Clarification:**
- Analyze feature request for ambiguous user roles, success criteria, constraints
- Ask max 3–5 focused questions to resolve critical unknowns
- Example: "Who are primary users?", "What's the success metric?", "Any tech constraints?"

**Design Clarification:**
- Identify technical unknowns from requirements (architecture, integrations, data flow)
- Ask max 2–3 questions about tech stack, existing system integration
- Focus on decisions that significantly impact implementation

**Tasks Clarification:**
- Clarify scope boundaries, MVP vs full feature, resource constraints
- Ask about risk tolerance and timeline expectations
- Ensure clear understanding of what's in/out of scope

### 1. requirements.md (Semantic Anchor)
````markdown
# Requirements: [Feature Name]
## Meta-Context
- Feature UUID: FEAT-{8-char-hash}
- Parent Context: [CLAUDE.md links]
- Dependency Graph: [Auto-detected]

## Functional Requirements
### REQ-{UUID}-001: [Name]
Intent Vector: {AI semantic summary}
As a [User] I want [Goal] So that [Benefit]
Business Value: {1-10} | Complexity: {XS/S/M/L/XL}

Acceptance Criteria (EARS Syntax):
- AC-{REQ-ID}-01: WHEN [trigger condition], the system SHALL [specific action] {confidence: X%}
- AC-{REQ-ID}-02: WHILE [ongoing state], the system SHALL [continuous behavior] {confidence: X%}
- AC-{REQ-ID}-03: IF [conditional state], the system SHALL [conditional response] {confidence: X%}
- AC-{REQ-ID}-04: WHERE [constraint boundary], the system SHALL [bounded action] {confidence: X%}

EARS Examples:
- WHEN user submits valid login credentials, the system SHALL authenticate within 200ms
- WHILE user session is active, the system SHALL maintain authentication state
- IF login attempts exceed 3 failures, the system SHALL temporarily lock the account for 15 minutes
- WHERE user lacks required permissions, the system SHALL display "Access Denied" message

Validation Hooks: {EARS-to-BDD testable assertions}
Risk Factors: {auto-identified}

## Non-functional Requirements (EARS Format)
- NFR-{UUID}-PERF-001: WHEN [operation trigger], the system SHALL [perform action] within [time constraint]
- NFR-{UUID}-SEC-001: WHERE [security context], the system SHALL [enforce protection] using [method]
- NFR-{UUID}-UX-001: WHILE [user interaction], the system SHALL [provide feedback] within [response time]
- NFR-{UUID}-SCALE-001: IF [load condition], the system SHALL [maintain performance] up to [capacity limit]

NFR Examples:
- WHEN user requests dashboard data, the system SHALL load results within 500ms
- WHERE sensitive data is accessed, the system SHALL require multi-factor authentication
- WHILE form validation occurs, the system SHALL display real-time feedback within 100ms
- IF concurrent users exceed 1000, the system SHALL maintain 99% uptime with <2s response times

## Traceability Manifest
Upstream: [dependencies] | Downstream: [impact] | Coverage: [AI-calculated]
````

### 2. design.md (Architecture Mirror)
````markdown
# Design: [Feature Name]
## ADRs (Architectural Decision Records)
### ADR-001: [Decision]
Status: Proposed | Context: [background] | Decision: [what] | Rationale: [why]
Requirements: REQ-{UUID}-001,002 | Confidence: X% | Alternatives: [rejected options]

## Components
### Modified: [Component] → Fulfills: AC-{REQ-ID}-01
Changes: [specific modifications]

### New: [Component] → Responsibility: {requirement-linked purpose}
Interface (EARS Behavioral Contracts):
```typescript
interface Component {
  // WHEN method1() is called, SHALL return Promise<T> within 200ms
  method1(): Promise<T> // AC-{REQ-ID}-01

  // WHERE input validates successfully, SHALL return transformed output O
  method2(input: I): O  // AC-{REQ-ID}-02

  // IF validation fails, SHALL throw ValidationError with details
  validateInput(data: unknown): boolean // AC-{REQ-ID}-03
}
```

## API Matrix (EARS Behavioral Specifications)
| Endpoint | Method | EARS Contract | Performance | Security | Test Strategy |
|----------|--------|---------------|-------------|----------|---------------|
| /api/x | POST | WHEN valid payload received, SHALL process within 500ms | <500ms | JWT+RBAC | Unit+Integration+E2E |
| /api/y | GET | WHILE user authenticated, SHALL return filtered data | <200ms | Role-based | Unit+Contract |

## Data Flow + Traceability
1. Input Validation → NFR-{UUID}-SEC-001
2. Business Logic → REQ-{UUID}-001
3. Output → AC-{REQ-ID}-01

## Quality Gates
- ADRs: >80% confidence to requirements
- Interfaces: trace to acceptance criteria
- NFRs: measurable test plans
````

### 3. tasks.md (Execution Blueprint)
````markdown
# Tasks: [Feature Name]
## Metadata
Complexity: {AI-calc} | Critical Path: {sequence} | Risk: {score} | Timeline: {estimate}

## Progress: 0/X Complete, 0 In Progress, 0 Not Started, 0 Blocked

## Phase 1: Foundation
- [ ] TASK-{UUID}-001: [Name]
  Trace: REQ-{UUID}-001 | Design: NewComponent | AC: AC-{REQ-ID}-01
  DoD (EARS Format): WHEN task completed, SHALL satisfy AC-{REQ-ID}-01 with 100% test coverage
  Risk: Low | Deps: None | Effort: 2pts

- [ ] TASK-{UUID}-002: [Name]
  Trace: REQ-{UUID}-001,002 | Design: method1() | AC: AC-{REQ-ID}-01,02
  DoD (EARS Format): WHEN implementation finished, SHALL pass integration tests AND WHILE method executes, SHALL complete within performance requirements
  Risk: Medium | Deps: TASK-001 | Effort: 5pts

## Phase 2: Integration
- [ ] TASK-{UUID}-003: API Implementation
  Trace: REQ-{UUID}-002 | Design: POST /api/x | AC: AC-{REQ-ID}-02
  DoD (EARS Format): WHEN endpoint deployed, SHALL handle requests per EARS contract AND WHERE error conditions occur, SHALL return appropriate HTTP status codes
  Risk: Low | Deps: TASK-002 | Effort: 3pts

## Phase 3: QA
- [ ] TASK-{UUID}-004: Test Suite
  Trace: ALL AC-* | Design: Test impl | AC: 100% coverage + NFR validation
  DoD (EARS Format): WHEN tests execute, SHALL validate every EARS acceptance criterion AND IF any test fails, SHALL provide actionable error messages
  Risk: Medium | Deps: All prev | Effort: 4pts

## Verification Checklist (EARS Compliance)
- [ ] Every REQ-* → implementing task with EARS DoD
- [ ] Every EARS AC → BDD test coverage (Given/When/Then)
- [ ] Every NFR-* → measurable EARS validation criteria
- [ ] All design EARS contracts → implementation tasks
- [ ] Risk mitigation for Medium+ risks with EARS success criteria
- [ ] EARS-to-BDD test translation completeness check
````

### 4. Internal Review Gate (before User Approval)

Complete and show this **filled** section **before** asking the user to approve any document:

**Traceability Quick-check**
- Every REQ-* maps to ≥1 task? □ Yes / □ No
- Every EARS AC has a validation hook? □ Yes / □ No
- NFRs measurable & linked to design choices? □ Yes / □ No

**Reviewer Rubric (0–3 each)**
- Clarity __ / Correctness __ / Safety __ / Testability __ / Simplicity __

> **Rule:** If any checkbox is **No** or any score < **2** → **REVISE**. Do **not** request approval.

### 5. User Approval Gates

After generating/updating each document, explicitly request user approval:

**Requirements Approval:**
- Present `requirements.md` for review
- Ask: "Do these requirements capture your vision? Any critical gaps or changes needed?"
- Make revisions if requested, then re-request approval
- Do **NOT** proceed to design until explicit approval ("yes", "approved", "looks good")

**Design Approval:**
- Present `design.md` for review
- Ask: "Does this design approach work? Any architectural concerns?"
- Make revisions if requested, then re-request approval
- Do **NOT** proceed to tasks until explicit approval

**Tasks Approval:**
- Present `tasks.md` for review
- Ask: "Is this implementation plan actionable? Any scope adjustments needed?"
- Make revisions if requested, then re-request approval
- Mark workflow complete only after explicit approval

### 6. Auto-Verification (Internal)

Before each approval request, run AI validation:
1. Forward/Backward/Bi-directional traceability check
2. Gap analysis (missing coverage, orphaned elements)
3. Confidence scoring (requirements: X%, design: X%, tasks: X%)
4. Risk assessment and recommendations
5. Output: "**Traceability Check: PASSED/FAILED**" + improvement suggestions

### 7. CLAUDE.md Update Assessment (Post-Generation)

After generating all three files, analyze if major architectural changes require `CLAUDE.md` updates:

**Triggers for CLAUDE.md Update:**
- New technology stack (framework, database, architecture pattern)
- Major architectural decisions that change project direction
- New domain concepts or business logic that affects project context
- Significant changes to development approach or constraints

**Assessment Process:**
1. Compare generated `design.md` ADRs against current `CLAUDE.md` project context
2. Identify semantic gaps between new requirements and existing project description
3. Check if new NFRs introduce constraints not reflected in `CLAUDE.md`

**If update needed:**
```bash
"The generated specifications introduce significant architectural changes.
Should I update CLAUDE.md to reflect:
- [Specific change 1]
- [Specific change 2]
- [Specific change 3]

This will improve future agent decisions and maintain project context accuracy."
```

**If no update needed:**
```bash
"CLAUDE.md context remains accurate for this feature. No updates required."
```

---

## Phase 2: Lifecycle Management

**Execution Rules:**
- ALWAYS read `requirements.md`, `design.md`, `tasks.md` before executing any task
- Execute **ONLY one task at a time** — stop after completion for user review
- Do **NOT** automatically proceed to next task without explicit user request
- If a task has sub-tasks, start with sub-tasks first
- Verify implementation against specific **AC** references in task details

**Task Updates**: Change `[ ]` to `[x]`, update progress count; monitor scope drift/timeline deviation

**Smart Completion** (100% progress):
1. Auto-validate acceptance criteria vs implementation
2. Execute full test suite against original requirements
3. Generate requirement satisfaction + quality metrics report
4. Archive: Create `specs/done/`, move `specs/{feature}/`, rename `DONE_{date}_{hash}_filename.md`
5. Generate retrospective + update semantic knowledge base

**Learning Loop**: Pattern recognition for estimates, risk prediction, process optimization

---

## Resume Command

`/kiro resume "{feature-name}"`
**Action:**
1. Read `specs/{feature-name}/requirements.md` for full requirement context
2. Read `specs/{feature-name}/design.md` for architectural decisions + rationale
3. Read `specs/{feature-name}/tasks.md` for current progress state
4. Reconstruct semantic traceability graph from all three documents
5. Continue with full TAD framework context maintained

> This ensures AI agents understand **WHY** decisions were made, not just **WHAT** needs to be done.
