# Apex Mage - Project Guide

> **Note**: This project uses [bd (beads)](https://github.com/steveyegge/beads) for issue tracking. See AGENTS.md for workflow details.

## Project Overview

AI-powered conversational assistant with multi-channel support. Currently a Discord bot; refactoring toward platform-agnostic backend with multiple frontends (Discord, web).

**Current Tech Stack:**
- Python 3.11, discord.py v2.x
- SQLite3 database
- Docker containerized
- APIs: Anthropic (Claude), Fal.AI (images), Google Cloud Storage

## Architecture Principles

- **Backend/Frontend Separation**: Core conversation logic must not depend on any specific client
- **Observability First**: Structured logs and metrics. Ask: "How will I know this worked?"
- **Explicit Data Model**: Schema defined in `docs/data-model.md`
- **Test Coverage**: Target 80% for business logic, 60% overall

## File Conventions

| Path | Purpose |
|------|---------|
| `src/core/` | Platform-agnostic business logic (target) |
| `src/clients/` | Client adapters - discord, web (target) |
| `src/db/` | Database access, migrations (target) |
| `docs/data-model.md` | Canonical schema definition |
| `docs/beads/` | Bead specifications |
| `.github/workflows/` | CI/CD pipelines |
| `history/` | AI-generated planning documents |

### Current Structure (pre-refactor)

```
├── main.py              # Discord bot core, slash commands
├── ai.py                # API integrations (Anthropic, Fal.AI, GCS)
├── mem.py               # Database operations, rate limiting
├── carousel.py          # Discord UI components
├── allowed_vendors.json # Model configuration
├── db/                  # SQL schema and queries
└── Dockerfile           # Container definition
```

## Code Standards

- Python with type hints (mypy strict)
- Async-first for I/O operations
- Dependency injection for testability
- No hardcoded credentials; use environment variables
- Structured logging (JSON format)

## Build & Run

```bash
./install.sh              # Initial setup
./start.sh                # Start container
docker build -t apex-mage . && ./start.sh  # Rebuild
./update_keys.sh          # Update API keys
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `FAL_KEY` | Yes | Fal.AI API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | Path to GCP auth JSON |
| `ANTHROPIC_RATE_LIMIT` | No | Max text requests/hour (default: 30) |
| `FAL_RATE_LIMIT` | No | Max image requests/hour (default: 8) |

## Testing

```bash
pytest                                    # Run all tests
pytest --cov=src --cov-report=term-missing  # With coverage
pytest tests/core/                        # Specific module
```

## Quick Reference

```bash
ruff check src/           # Lint
mypy src/                 # Type check
repomix bundle -o ctx.md  # Generate context bundle
bd ready --json           # Find ready work
```
