# Agent Operating Guide

## Issue Tracking with bd (beads)

**CRITICAL**: Use **bd** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?
- Dependency-aware with blocker relationships
- Git-friendly via `.beads/issues.jsonl` auto-sync
- Agent-optimized with JSON output and ready work detection

### Core Commands

```bash
# Find ready work
bd ready --json

# Create issues
bd create "Title" -t bug|feature|task|epic|chore -p 0-4 --json
bd create "Found during work" --deps discovered-from:bd-123 --json
bd create "Subtask" --parent <epic-id> --json

# Work on issues
bd update bd-42 --status in_progress --json
bd close bd-42 --reason "Completed" --json
```

### Priorities
- `0` Critical (security, data loss, broken builds)
- `1` High (major features, important bugs)
- `2` Medium (default)
- `3` Low (polish)
- `4` Backlog

### Agent Workflow
1. `bd ready --json` to find unblocked work
2. `bd update <id> --status in_progress` to claim
3. Implement, test, document
4. Discover new work? `bd create "..." --deps discovered-from:<id>`
5. `bd close <id> --reason "Done"`
6. **Always commit `.beads/issues.jsonl` with code changes**

### MCP Server
If available, prefer `mcp__beads__*` functions over CLI.

### Planning Documents
Store AI-generated planning docs (PLAN.md, DESIGN.md, etc.) in `history/` directory, not repo root.

### Rules
- Always use `--json` flag for programmatic use
- Run `bd <cmd> --help` to discover flags
- Do NOT create markdown TODO lists
- Do NOT duplicate tracking systems

---

## Session Types

### Initializer Agent
Runs once per bead to establish context and plan.

**Startup sequence:**
1. Read `docs/beads/<bead-id>.md` for requirements
2. Read `docs/data-model.md` if data changes involved
3. Run `git log --oneline -10` to understand recent changes
4. Run `pytest -x --tb=short` to verify baseline health
5. Create `docs/beads/<bead-id>-plan.md` with implementation steps

**Output:**
- Implementation plan with specific files to modify
- Test scenarios to implement
- Acceptance criteria checklist

**Do NOT:**
- Write implementation code
- Modify existing files
- Make commits

---

### Coding Agent
Executes planned work incrementally.

**Startup sequence:**
1. Read `docs/beads/<bead-id>-plan.md`
2. Read `docs/beads/<bead-id>-progress.md` if exists
3. Run `pytest -x --tb=short` to verify baseline
4. Select next incomplete task from plan

**Work loop:**
1. Implement ONE task from plan
2. Run relevant tests
3. If tests pass: commit with `[BD-<id>] <description>`
4. Update `docs/beads/<bead-id>-progress.md`
5. If tests fail: fix or revert, do not proceed

**Session end:**
- Ensure all changes committed or reverted
- Update progress file with session summary
- Note any blockers or questions

---

## Context Management

### Token Efficiency
- Do NOT re-read files already in context
- Use `repomix bundle` output when provided
- Prefer targeted file reads over broad searches
- State assumptions explicitly rather than re-verifying

### Recovery Protocol
If you encounter unexpected state:
1. `git status` - check for uncommitted changes
2. `git diff` - review pending changes
3. `pytest -x` - verify test health
4. If broken: `git checkout .` and restart from last good commit

---

## Decision Framework

### Before Modifying Code
Ask:
1. Is this in the plan? If not, update plan first.
2. How will I test this?
3. Does this touch the data model? Update `docs/data-model.md` first.
4. Will this break existing clients? Consider migration path.

### Observability Checklist
For any new feature:
- [ ] Structured log at operation start/end
- [ ] Error logging with context
- [ ] Metric/counter for success/failure rates
- [ ] Health check endpoint if applicable

### Test Requirements
- Unit tests for pure functions
- Integration tests for database operations
- Client tests can mock core services
- No mocking within the module under test

---

## Bead Lifecycle

```
DRAFT -> PLANNED -> IN_PROGRESS -> REVIEW -> DONE
```

1. **DRAFT**: Requirements captured in `docs/beads/<id>.md`
2. **PLANNED**: Initializer agent created `-plan.md`
3. **IN_PROGRESS**: Coding agent working, `-progress.md` tracking
4. **REVIEW**: PR open, awaiting human review
5. **DONE**: Merged to main

---

## Communication

### Progress Updates
Write to `docs/beads/<bead-id>-progress.md`:
```markdown
## Session: YYYY-MM-DD HH:MM

### Completed
- Task description

### Blocked
- Blocker description (if any)

### Next
- Next task to tackle
```

### Asking Questions
If blocked or uncertain, write question to progress file and STOP.
Do not guess or make assumptions that could require significant rework.

---

## Anti-Patterns

- Starting implementation without reading the plan
- Making multiple unrelated changes in one session
- Skipping tests to "move faster"
- Modifying data model without updating docs
- Hardcoding values that should be configurable
- Adding features not in the bead spec
