# Apex Mage - Project Guide

## ⚠️ MANDATORY WORKFLOW (READ FIRST)

**You operate as one of three agent roles. You MUST follow this structure.**

| Role | Does | Does NOT |
|------|------|----------|
| **Initializer** | Analyzes, plans, creates beads, spawns agents | Write or modify code |
| **Coding** | Implements per bead spec, iterates on feedback | Approve own work |
| **Reviewer** | Validates, approves or returns with feedback | Implement fixes |

### Session Start (EVERY session, after /clear or /compact)
```bash
bd ready --json                         # Available work
bd list --status in_progress --json     # Active work
bd show <bead-id>                       # Read context before starting
```

**Resume from bead notes.** They contain full context from previous sessions.

### Default Behavior
- **No existing beads?** → You are **Initializer**. Analyze request, create beads, delegate.
- **Beads exist with status `in_progress`?** → Check bead notes for which role to resume as.
- **User gives new request?** → You are **Initializer**. Plan first, then delegate.

### The Implementation Loop (MANDATORY)
```
CODING → REVIEWER → CODING → REVIEWER → ... → APPROVED
```
This loop repeats until reviewer approves. Single-pass is NOT acceptable. Initializer waits and does not intervene with code.

### Agent Boundaries (STRICT)
- **Initializer NEVER writes code.** Creates beads, delegates, waits.
- **Reviewer NEVER implements fixes.** Documents issues, returns to coding.
- **Coding NEVER approves own work.** Implements, hands to reviewer.

### Anti-Patterns (DO NOT DO)
- ❌ Initializer writes "just a small fix"
- ❌ Single coding→reviewer pass assumed sufficient
- ❌ Reviewer implements changes instead of returning
- ❌ Skipping reviewer for "simple changes"
- ❌ Proceeding without beads for non-trivial work

---

## Bead Documentation (CRITICAL)

Beads are persistent memory. Context is temporary. **Write bead notes assuming /clear could happen any moment.**

### What MUST Be In Bead Notes
```
STATUS: investigating|implementing|review|needs-changes|approved
ITERATION: <N> (which coding↔reviewer round)
COMPLETED: <what's done, specific>
CURRENT: <exact state, where you stopped>
NEXT: <literal next action to take>
FILES: <paths modified>
DECISIONS: <decision>: <rationale>
BLOCKERS: <if any>
```

### Checkpoint Triggers
Update bead notes:
- After completing any significant step
- Before switching to another bead
- Every 15-20 tool calls
- Between coding↔reviewer handoffs
- When task is taking long (mid-task checkpoint)

### Before /compact or /clear
If context is getting long:
1. **STOP immediately**
2. **Checkpoint ALL in-progress beads** with exact resume point
3. **Push uncommitted code** to branch
4. **Confirm:** "Checkpointed. Safe to /compact."

### Documentation Style
- **Concise.** No fluff. No filler.
- **Technical.** File paths, line numbers, commit hashes.
- **Actionable.** "NEXT: Add error handling to foo.py:45" not "NEXT: Continue work"

Bad: "Made good progress on the auth module today"
Good: "Implemented JWT refresh in auth/tokens.py:23-45. Added 24h expiry. Commit: a1b2c3d"

---

## Release Discipline

```
Push to main → WAIT for container build to succeed → THEN create release
```
Check Actions tab or `gh run list`. Never release while build is running.

---

## Project Overview

AI-powered conversational assistant with multi-channel support. Currently a Discord bot; refactoring toward platform-agnostic backend with multiple frontends.

**Tech Stack:**
- Python 3.11, discord.py v2.x
- SQLite3 database
- Docker containerized
- APIs: Anthropic (Claude), Fal.AI (images), Google Cloud Storage

## Architecture Principles

- **Backend/Frontend Separation**: Core logic must not depend on specific client
- **Observability First**: Structured logs and metrics
- **Explicit Data Model**: Schema in `docs/data-model.md`
- **Test Coverage**: Target 80% business logic, 60% overall

## File Structure

| Path | Purpose |
|------|---------|
| `src/core/` | Platform-agnostic business logic |
| `src/clients/` | Client adapters (discord, web) |
| `src/db/` | Database access, migrations |
| `docs/data-model.md` | Canonical schema |
| `docs/deployment.md` | Deployment guide |
| `.claude/agents/` | Agent definitions |
| `.github/workflows/` | CI/CD pipelines |

## Code Standards

- Python with type hints (mypy strict)
- Async-first for I/O operations
- Dependency injection for testability
- No hardcoded credentials
- Structured logging (JSON format)

## Build & Run

```bash
./install.sh              # Initial setup
./start.sh                # Start container
docker build -t apex-mage . && ./start.sh  # Rebuild
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `FAL_KEY` | Yes | Fal.AI API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | GCP auth JSON path |

## Testing

```bash
pytest                    # Run all tests
pytest --cov=src         # With coverage
ruff check src/          # Lint
mypy src/                # Type check
```

## Quick Reference

```bash
bd ready --json          # Find ready work
bd show <id> --json      # Read bead context
bd update <id> --notes   # Update bead notes
bd comment <id> "..."    # Add bead comment
bd close <id>            # Close completed bead
```
