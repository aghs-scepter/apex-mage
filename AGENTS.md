# Agent Operating Guide

## Issue Tracking with bd (beads)

**CRITICAL**: Use **bd** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?
- Dependency-aware with blocker relationships
- Git-friendly via `.beads/issues.jsonl` auto-sync
- Agent-optimized with JSON output and ready work detection

### Core Commands

```bash
bd ready --json                                    # Find unblocked work
bd create "Title" -t bug|feature|task|epic|chore -p 0-4 --json
bd create "Found during work" --deps discovered-from:bd-123 --json
bd create "Subtask" --parent <epic-id> --json      # Hierarchical
bd update bd-42 --status in_progress --json
bd close bd-42 --reason "Completed" --json
```

### Priorities
- `0` Critical (security, data loss, broken builds)
- `1` High (major features, important bugs)
- `2` Medium (default)
- `3` Low (polish)
- `4` Backlog

### MCP Server
If available, prefer `mcp__beads__*` functions over CLI.

### Rules
- Always use `--json` flag for programmatic use
- Always commit `.beads/issues.jsonl` with code changes
- Run `bd <cmd> --help` to discover flags
- Store AI planning docs in `history/` directory
- Do NOT create markdown TODO lists or duplicate trackers

---

## Session Types

### Initializer Agent
Runs once per bead to establish context and plan. **Read-only.**

**Startup:**
1. `bd ready --json` - identify target bead
2. Read `docs/data-model.md` if data changes involved
3. `git log --oneline -10` - understand recent changes
4. `pytest -x --tb=short` - verify baseline health
5. Create `history/<bead-id>-plan.md` with implementation steps

**Output:** Implementation plan, test scenarios, acceptance criteria.

**Do NOT:** Write code, modify files, or commit.

---

### Coding Agent
Executes planned work incrementally.

**Startup:**
1. Read `history/<bead-id>-plan.md`
2. Read `history/<bead-id>-progress.md` if exists
3. `pytest -x --tb=short` - verify baseline
4. Select next incomplete task

**Work loop:**
1. Implement ONE task
2. Run relevant tests
3. Pass? Commit with `[BD-<id>] <description>`
4. Update `history/<bead-id>-progress.md`
5. Fail? Fix or revert, do not proceed

**Session end:** All changes committed or reverted, progress updated.

---

## Context Management

### Token Efficiency
- Do NOT re-read files already in context
- Use `repomix bundle` output when provided
- Prefer targeted reads over broad searches
- State assumptions explicitly

### Recovery Protocol
If unexpected state:
1. `git status` - uncommitted changes?
2. `git diff` - review pending changes
3. `pytest -x` - test health
4. If broken: `git checkout .` and restart

---

## Decision Framework

### Before Modifying Code
1. Is this in the plan? If not, update plan first.
2. How will I test this?
3. Does this touch data model? Update `docs/data-model.md` first.
4. Will this break existing clients?

### Observability Checklist
For new features:
- [ ] Structured log at operation start/end
- [ ] Error logging with context
- [ ] Metric/counter for success/failure
- [ ] Health check endpoint if applicable

### Test Requirements
- Unit tests for pure functions
- Integration tests for DB operations
- Client tests can mock core services
- No mocking within module under test

---

## Session Ending Protocol

1. **File issues for remaining work**
   - Create issues for discovered bugs/TODOs
   - Close completed, update in-progress

2. **Run quality gates** (if code changed)
   - Tests, linters, builds
   - P0 issue if build broken

3. **Sync issue tracker**
   - Commit `.beads/issues.jsonl` with changes
   - Handle conflicts carefully

4. **Verify clean state**
   - All changes committed
   - No untracked files

5. **Document next steps**
   - Update progress file
   - Note blockers or questions

---

## Anti-Patterns

- Starting implementation without reading the plan
- Multiple unrelated changes in one session
- Skipping tests to "move faster"
- Modifying data model without updating docs
- Hardcoding configurable values
- Adding features not in bead spec
- Guessing when blocked (ask instead)
