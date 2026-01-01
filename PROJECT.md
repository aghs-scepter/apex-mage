# PROJECT.md - Apex Mage

> Internal reference document for AI assistants and developers

## Overview

**Apex Mage** is a self-hosted Discord bot providing AI chat and image generation capabilities. Users interact via slash commands in servers or DMs, with conversations persisted per-channel.

- **Author**: Kev Silver (aghs on Discord)
- **Repository**: `aghs-scepter/apex-mage`
- **Version**: v1.2.6
- **License**: Non-commercial use (custom)
- **Python**: 3.11+

---

## Architecture

```
apex-mage/
├── main.py                      # Discord bot entry point
├── api_main.py                  # FastAPI entry point (alternative)
├── src/
│   ├── clients/discord/         # Discord bot implementation
│   │   ├── bot.py               # DiscordBot class, lifecycle management
│   │   ├── commands/            # Slash command implementations
│   │   │   ├── chat.py          # /prompt, /clear, /summarize, behavior commands
│   │   │   └── image.py         # /create_image, /modify_image, /describe_this
│   │   ├── views/               # Discord UI components (embeds, buttons, modals)
│   │   │   ├── carousel.py      # Main view orchestration, image carousels
│   │   │   ├── ai_assist_views.py    # AI-powered prompt refinement
│   │   │   ├── edit_views.py         # Image edit prompts/previews
│   │   │   ├── google_search_views.py # Google Image search UI
│   │   │   ├── info_views.py         # Info embeds, confirmations
│   │   │   └── summarization_views.py # Summarize preview/confirm
│   │   ├── checks.py            # Ban check command tree
│   │   ├── decorators.py        # Command counting decorator
│   │   └── utils.py             # Embed helpers, text overflow
│   ├── providers/               # External API integrations
│   │   ├── anthropic_provider.py    # Claude Sonnet 4 for chat
│   │   ├── fal_provider.py          # Fal.AI nano-banana-pro for images
│   │   └── serpapi_provider.py      # Google Image search
│   ├── adapters/                # Data layer
│   │   ├── sqlite_repository.py     # SQLite implementation
│   │   ├── repository_compat.py     # RepositoryAdapter facade
│   │   ├── gcs_adapter.py           # Google Cloud Storage uploads
│   │   └── memory_repository.py     # In-memory (testing)
│   ├── core/                    # Business logic
│   │   ├── providers.py         # Protocol definitions (AIProvider, ImageProvider)
│   │   ├── conversation.py      # Context building, message conversion
│   │   ├── rate_limit.py        # Sliding window rate limiter
│   │   ├── haiku.py             # Claude Haiku utility (summarization, vision)
│   │   ├── image_utils.py       # Image compression, thumbnails
│   │   ├── image_variations.py  # Variation generation logic
│   │   ├── auto_summarization.py    # Token threshold monitoring
│   │   ├── token_counting.py        # tiktoken-based counting
│   │   ├── chart_utils.py           # Usage statistics charts
│   │   ├── health.py                # Health check system
│   │   ├── logging.py               # structlog configuration
│   │   └── prompts/                 # System prompts for AI features
│   ├── api/                     # FastAPI REST API
│   │   ├── app.py               # FastAPI application factory
│   │   ├── routes/              # API endpoints
│   │   │   ├── health.py        # /health endpoint
│   │   │   ├── auth.py          # API key management
│   │   │   ├── conversations.py # Conversation CRUD
│   │   │   ├── images.py        # Image generation endpoints
│   │   │   └── websocket.py     # WebSocket support
│   │   └── dependencies.py      # AppState singleton
│   └── ports/                   # Repository interfaces
│       └── repositories.py      # Protocol definitions
├── tests/                       # Test suite
├── data/                        # SQLite database location
├── .github/workflows/           # CI/CD
│   ├── ci.yml                   # Lint, typecheck, test
│   ├── container-build.yml      # Docker build
│   └── deploy.yml               # Deployment
└── Dockerfile                   # Container definition
```

---

## AI Providers

### Anthropic (Chat)
- **Model**: `claude-sonnet-4-20250514` (main), `claude-haiku-4-5-20251001` (utility)
- **Uses**: Chat completions, conversation summarization, image description, prompt refinement
- **Rate limit**: Configurable per-user (default: 30/hour)

### Fal.AI (Images)
- **Model**: `fal-ai/nano-banana-pro` (generation), `fal-ai/nano-banana-pro/edit` (modification)
- **Uses**: Text-to-image generation, image-to-image modification
- **Features**: Web search enabled, 16:9 aspect ratio, 1K resolution
- **Rate limit**: Configurable per-user (default: 8/hour)

### SerpAPI (Search)
- **Uses**: Google Image search for `/modify_image` and `/describe_this` workflows
- **Optional**: Only required if using Google search feature

---

## Discord Commands

### Chat Commands
| Command | Description |
|---------|-------------|
| `/prompt` | Chat with AI. Supports optional image upload. |
| `/clear` | Clear channel conversation history (with confirmation). |
| `/summarize` | Summarize conversation to reduce token usage. |

### Image Commands
| Command | Description |
|---------|-------------|
| `/create_image` | Generate image from text prompt. Shows refinement UI. |
| `/modify_image` | Edit images from recent context or Google search. Multi-image support (up to 3). |
| `/describe_this` | Get AI description of an image. Supports direct upload or selection. |
| `/upload_image` | Upload image to conversation context. |

### Behavior Commands
| Command | Description |
|---------|-------------|
| `/set_behavior custom` | Set custom system prompt for AI. |
| `/set_behavior preset` | Select saved preset from dropdown. |
| `/behavior_preset create` | Create new server preset. |
| `/behavior_preset edit` | Edit existing preset (owner/creator/admin only). |
| `/behavior_preset delete` | Delete preset (owner/creator/admin only). |
| `/behavior_preset list` | List all server presets. |
| `/behavior_preset view` | View preset details. |

### User Commands
| Command | Description |
|---------|-------------|
| `/my_status` | Check access status (whitelisted/banned). |
| `/show_usage` | View usage statistics chart (top 5 users). |
| `/help` | Display command reference. |

### Admin Commands (Owner Only)
| Command | Description |
|---------|-------------|
| `/ban_user` | Ban user from using bot. |
| `/unban_user` | Remove user ban. |
| `/whitelist_add` | Add user to whitelist. |
| `/whitelist_remove` | Remove from whitelist. |
| `/whitelist_list` | List all whitelisted users. |

---

## Key Features

### Conversation Management
- Per-channel context isolation
- Configurable context window (default: 50 messages)
- Auto-summarization when token threshold exceeded
- Manual summarization via `/summarize`

### Image Workflows
1. **Generation**: `/create_image` -> prompt refinement UI -> generate -> result view with "Add to Context", "Download", "Create Variation" options
2. **Modification**: `/modify_image` -> source selection (Recent/Google) -> multi-image carousel -> edit type selection -> AI Assist or manual prompt -> result
3. **Description**: `/describe_this` -> source selection -> AI vision analysis -> edit/accept description

### Access Control
- Whitelist-based access (optional)
- Ban system with history tracking
- Per-user rate limiting

### Persistence
- SQLite database (`data/app.db`)
- Tables: channels, vendors, channel_messages, api_keys, bans, ban_history, whitelist, whitelist_history, behavior_presets, command_usage
- GCS for generated image storage (download URLs)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | - | Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | - | Anthropic API key |
| `FAL_KEY` | Yes | - | Fal.AI API key |
| `ANTHROPIC_RATE_LIMIT` | No | 30 | Chat requests per hour |
| `FAL_RATE_LIMIT` | No | 8 | Image requests per hour |
| `IMAGE_CONTEXT_SIZE` | No | 5 | Images kept in context |
| `SYNC_COMMANDS` | No | false | Sync commands on startup |
| `HEALTH_ENABLED` | No | true | Enable health endpoint |
| `HEALTH_PORT` | No | 8080 | Health server port |
| `SERPAPI_KEY` | No | - | Google Image search |
| `GCS_BUCKET` | No | - | GCS bucket for uploads |
| `DATABASE_PATH` | No | data/app.db | SQLite path |

---

## Development

### Setup
```bash
# Clone and setup
git clone https://github.com/aghs-scepter/apex-mage.git
cd apex-mage
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env  # Edit with your keys

# Run
python main.py
```

### Testing
```bash
pytest                    # Run all tests
pytest --cov=src          # With coverage
ruff check src/           # Lint
mypy src/                 # Type check
```

### CI/CD
- **Lint**: ruff check on push/PR
- **Typecheck**: mypy on push/PR
- **Test**: pytest with coverage on push/PR
- **Build**: Docker image to GHCR on release

---

## Deployment

### Docker (Recommended)
```bash
# Via install script (prompts for keys)
sudo bash install.sh

# Manual
docker pull ghcr.io/aghs-scepter/apex-mage:latest
docker run -d \
  -e DISCORD_BOT_TOKEN=xxx \
  -e ANTHROPIC_API_KEY=xxx \
  -e FAL_KEY=xxx \
  -v /appdata:/app/data \
  ghcr.io/aghs-scepter/apex-mage:latest
```

### Hosting
- Designed for low-resource VMs (tested on GCP e2-micro)
- SQLite is sufficient for typical Discord bot usage
- Health endpoint available at `:8080/health`

---

## Recent Changes (v1.2.x)

- v1.2.6: Fix embed field length error for AI Assist with character preservation
- v1.2.5: Reference image support for variation consistency
- v1.2.4: Fix AI Assist timeout bug
- v1.2.3: Wider image generation (16:9)
- v1.2.2: Help command update
- v1.2.1: Character preservation toggle for AI Assist
- v1.2.0: Multi-image modification support (up to 3 reference images)

---

## Known Limitations

1. **Single API key per provider**: All requests use the same API keys (by design for billing consolidation)
2. **SQLite only**: No distributed database support
3. **Discord-only client**: REST API exists but is secondary to Discord bot
4. **English prompts**: AI prompts optimized for English

---

## Contact

- **Discord**: [aghs](https://discord.com/users/833494957024870401)
- **GitHub**: [aghs-scepter/apex-mage](https://github.com/aghs-scepter/apex-mage)
