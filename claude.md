# Apex Mage - Claude Code Configuration

## Project Overview

AI-powered conversational assistant with multi-channel support. Backend is platform-agnostic; frontends include Discord bot and web interface.

## Architecture Principles

- **Backend/Frontend Separation**: Core conversation logic must not depend on any specific client (Discord, web, etc.)
- **Observability First**: All operations should emit structured logs and metrics. Ask: "How will I know this worked?"
- **Explicit Data Model**: Schema defined in `docs/data-model.md`, single source of truth
- **Test Coverage**: Target 80% for business logic, 60% overall. No PR without tests for changed code.

## Workflow

### Tools
- **bd (beads)**: Issue-based work management. One bead = one atomic, testable change.
- **repomix**: Context bundling for AI sessions.

### Git Discipline
- Branch per bead: `bd/<bead-id>-short-description`
- Commit messages: `[BD-<id>] <imperative description>`
- Squash merge to main via PR

### CI/CD
- All automation via GitHub Actions in `.github/workflows/`
- Required checks: lint, test, build
- Deploy on merge to main

## File Conventions

| Path | Purpose |
|------|---------|
| `src/core/` | Platform-agnostic business logic |
| `src/clients/` | Client adapters (discord, web) |
| `src/api/` | HTTP API layer |
| `src/db/` | Database access, migrations |
| `docs/data-model.md` | Canonical schema definition |
| `docs/beads/` | Bead specifications |
| `.github/workflows/` | CI/CD pipelines |

## Code Standards

- Python with type hints (mypy strict)
- Async-first for I/O operations
- Dependency injection for testability
- No hardcoded credentials; use environment variables
- Structured logging (JSON format)

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=term-missing

# Specific module
pytest tests/core/
```

## Quick Reference

```bash
# Start dev environment
./scripts/dev.sh

# Run linter
ruff check src/

# Type check
mypy src/

# Generate context bundle
repomix bundle --output context.md
```
