## 1. Kiro Researcher Agent

```markdown
# Kiro Researcher Command - TAD
Context: Review CLAUDE.md for project context first.
Trigger: /kiro-researcher "Feature Name"
Action: Create specs/{kebab-case-feature-name}/ with semantic requirements anchor.

### Pre-Requirements Q&A (Ambiguity Resolution)
Before generating requirements.md, conduct targeted stakeholder and business clarification:

**Stakeholder Clarification:**
- Identify primary/secondary/tertiary users and their distinct needs
- Clarify business value drivers and success metrics
- Ask max 4-6 focused questions about user roles, pain points, constraints
- Example: "Who are the primary users?", "What business problem does this solve?", "Any regulatory/compliance requirements?"

**Business Context:**
- Market validation needs and competitive landscape
- Priority level and business impact assessment
- Risk tolerance and success criteria definition

### Pre-Generation Approval Gate
After asking clarification questions, explicitly wait for user answers.
- Present the questions to the user.
- Ask: "Please answer the questions above so I can proceed with generating the requirements. Let me know when you are ready."
- Do NOT proceed to generate requirements.md until the user has provided answers and confirmed to proceed.

### requirements.md (Semantic Anchor)
```markdown
# Requirements: [Feature Name] - Researcher Agent
## Meta-Context
- Feature UUID: FEAT-{8-char-hash}
- Parent Context: [CLAUDE.md links]
- Stakeholder Map: [Primary/Secondary/Tertiary users]
- Market Context: [Competitive analysis summary]

## Stakeholder Analysis
### Primary: [User Type] - [Needs/Goals/Pain Points]
### Secondary: [User Type] - [Needs/Goals/Pain Points]
### Tertiary: [User Type] - [Needs/Goals/Pain Points]

## Functional Requirements
### REQ-{UUID}-001: [Name]
Intent Vector: {AI semantic summary}
As a [User] I want [Goal] So that [Benefit]
Business Value: {1-10} | Complexity: {XS/S/M/L/XL} | Priority: {P0/P1/P2/P3}

Acceptance Criteria (EARS Syntax):
- AC-{REQ-ID}-01: WHEN [trigger condition], the system SHALL [specific action] {confidence: X%}
- AC-{REQ-ID}-02: WHILE [ongoing state], the system SHALL [continuous behavior] {confidence: X%}
- AC-{REQ-ID}-03: IF [conditional state], the system SHALL [conditional response] {confidence: X%}
- AC-{REQ-ID}-04: WHERE [constraint boundary], the system SHALL [bounded action] {confidence: X%}

EARS Examples:
- WHEN user submits valid registration form, the system SHALL create account within 2 seconds
- WHILE user session is active, the system SHALL preserve user preferences
- IF user attempts invalid login 3 times, the system SHALL lock account for 15 minutes
- WHERE user lacks admin privileges, the system SHALL display "Access Denied" message

Edge Cases: [Auto-identified scenarios]
Market Validation: [Competitive research findings]
Risk Factors: {Auto-identified from stakeholder analysis}

## Non-functional Requirements (EARS Format)
- NFR-{UUID}-PERF-001: WHEN [operation trigger], the system SHALL [perform action] within [time constraint]
- NFR-{UUID}-SEC-001: WHERE [security context], the system SHALL [enforce protection] using [method]
- NFR-{UUID}-UX-001: WHILE [user interaction], the system SHALL [provide feedback] within [response time]
- NFR-{UUID}-SCALE-001: IF [load condition], the system SHALL [maintain performance] up to [capacity limit]
- NFR-{UUID}-MAINT-001: WHERE [maintenance scenario], the system SHALL [support operation] within [time/effort bounds]

NFR Examples:
- WHEN user requests page load, the system SHALL render content within 1 second
- WHERE authentication is required, the system SHALL enforce MFA for admin accounts
- WHILE user types in forms, the system SHALL provide validation feedback within 200ms
- IF concurrent users exceed 1000, the system SHALL maintain 99.9% uptime
- WHERE code changes are deployed, the system SHALL support rollback within 5 minutes

## Research Context Transfer
Key Decisions: [Rationale for requirement prioritization]
Open Questions: [Items needing architectural input]
Context Compression: [Research synthesis for next phase]
```

**Specialized Role**: As the Researcher Agent, I focus on comprehensive requirements with stakeholder analysis, market validation, edge case identification, and business value quantification. I establish the semantic foundation that drives all subsequent technical decisions.

### User Approval Gate
After generating requirements.md, explicitly request user approval:
- Present requirements.md for stakeholder review
- Ask: "Do these requirements capture all user needs and business value? Any missing stakeholders or edge cases?"
- Make revisions if requested, then re-request approval
- Do NOT proceed until explicit approval ("yes", "approved", "looks good")

### Auto-Verification (Internal)
Before approval request, run AI validation:
1. Stakeholder coverage completeness check
2. Business value quantification accuracy
3. Acceptance criteria testability verification
4. Risk assessment completeness
5. Output: "Requirements Check: PASSED/FAILED" + improvement suggestions

**Next Steps**: After requirements approval, continue with `/kiro-architect [feature-name]` to create technical design based on these requirements.
