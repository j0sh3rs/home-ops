# Kiro Project Initialization

Initialize a new project with Kiro-style specification-driven development template.

## Usage

```
/kiro-init
```

## What this command does

1. Copies the Kiro CLAUDE.md template to the current project
2. Creates the .claude/commands directory structure
3. Sets up the specs/ directory for future feature development
4. Runs initialization while preserving existing CLAUDE.md content

## Instructions

You are a project initialization specialist focused on setting up Kiro-style specification-driven development workflow.

When this command is executed:

1. **Check for existing CLAUDE.md**:
   - If exists, read it first to understand current project setup
   - Preserve any existing content when merging with Kiro template

2. **Copy Kiro template**:
   - Copy the Kiro CLAUDE.md template from `~/.claude/templates/kiro-template.md`
   - If existing CLAUDE.md exists, merge intelligently without overwriting valuable project-specific information

3. **Create directory structure**:
   ```
   .claude/
   └── commands/
       ├── kiro.md
       ├── kiro-researcher.md
       ├── kiro-architect.md
       ├── kiro-implementer.md
       └── debugger.md
   specs/
   ```

4. **Copy Kiro commands**:
   - Copy all Kiro commands from global `~/.claude/commands/` to local `.claude/commands/`
   - Only copy kiro-*.md and debugger.md files

5. **Run standard initialization**:
   - Execute: "Please run initialization while preserving the existing CLAUDE.md content. Add project structure details without overwriting the Kiro workflow information."

6. **Confirmation**:
   - Confirm that all Kiro commands are available: /kiro, /kiro-researcher, /kiro-architect, /kiro-implementer, /debugger
   - Verify the project is ready for Kiro-style development

## Success Criteria

- CLAUDE.md contains Kiro workflow information
- All Kiro commands are available locally
- Directory structure is properly set up
- Project initialization is complete without losing existing content
