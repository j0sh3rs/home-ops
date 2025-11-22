# EARS Format Rules

EARS (Easy Approach to Requirements Syntax) provides unambiguous, testable requirement statements.

## EARS Syntax Patterns

### 1. Ubiquitous Requirements (always active)
**Format**: The {system} SHALL {action}

**Example**: The system SHALL log all authentication attempts

### 2. Event-Driven Requirements
**Format**: WHEN {trigger condition}, the {system} SHALL {action}

**Example**: WHEN a user submits a form, the system SHALL validate input within 200ms

### 3. State-Driven Requirements
**Format**: WHILE {ongoing state}, the {system} SHALL {action}

**Example**: WHILE processing requests, the system SHALL maintain response time under 100ms

### 4. Optional Feature Requirements
**Format**: WHERE {feature is enabled}, the {system} SHALL {action}

**Example**: WHERE debug mode is enabled, the system SHALL output detailed trace logs

### 5. Conditional Requirements
**Format**: IF {condition}, THEN the {system} SHALL {action}

**Example**: IF authentication fails, THEN the system SHALL return HTTP 401

## Key Principles

1. **Measurable**: Every requirement must have verifiable success criteria
2. **Unambiguous**: Single interpretation only
3. **Testable**: Can be validated through automated or manual testing
4. **Traceable**: Maps directly to test cases and design elements

## Usage Guidelines

- Use "SHALL" for mandatory requirements (not "should", "must", "will")
- Specify exact system/component name as subject
- Include measurable criteria (timeouts, limits, counts)
- Avoid implementation details (focus on WHAT, not HOW)
