# Kiro Specification-Driven Development

This project uses Kiro-style spec-driven development. Features are developed through a 3-phase approval workflow before any implementation begins.

## Spec File Layout

```
.kiro/specs/{feature-name}/
├── requirements.md   # User stories with EARS acceptance criteria
├── design.md         # Technical architecture and behavioral contracts
└── tasks.md          # Implementation tasks with Definition of Done
```

## Workflow

```
/kiro:spec-init "description"   → create spec
/kiro:spec-requirements {feat}  → define requirements (EARS format)
/kiro:spec-design {feat}        → technical design
/kiro:spec-tasks {feat}         → task breakdown
/kiro:spec-impl {feat} [tasks]  → implement
/kiro:spec-status {feat}        → check progress
```

Human approval required at each phase. Use `-y` only to intentionally skip a review gate.

## EARS Acceptance Criteria Format

Requirements use EARS syntax for unambiguous, testable criteria:

- `WHEN [trigger], the system SHALL [action]`
- `WHILE [state], the system SHALL [behavior]`
- `IF [condition], the system SHALL [response]`
- `WHERE [constraint], the system SHALL [bounded action]`

EARS statements map directly to BDD test scenarios (Given/When/Then).

## Development Rules

1. All features start with requirements definition — no code before approved requirements
2. Design must be approved before tasks are written
3. Tasks must be approved before implementation starts
4. Mark tasks complete with `[x]` only after verifying they work
5. Debugging follows the same spec flow: requirements → design → tasks → validate
6. Completed specs move to `.kiro/specs/done/`
