# CLAUDE.md - Apex Mage Project Guide

**Note**: This project uses [bd (beads)](https://github.com/steveyegge/beads)
   for issue tracking. Use `bd` commands instead of markdown TODOs.
   See AGENTS.md for workflow details.

## Project Overview

Apex Mage is a self-hosted Discord bot providing AI chat and image capabilities. It integrates with Anthropic (Claude Opus 4.5) for text, Fal.AI (Flux Pro) for images, and Google Cloud Storage for overflow response storage.

## Tech Stack

- **Language:** Python 3.11
- **Framework:** discord.py v2.x
- **Database:** SQLite3
- **Deployment:** Docker containerized
- **APIs:** Anthropic, Fal.AI, Google Cloud Storage

## Project Structure

```
├── main.py          # Discord bot core, slash command handlers
├── ai.py            # API integrations (Anthropic, Fal.AI, GCS)
├── mem.py           # Database operations, rate limiting, memory management
├── carousel.py      # Discord UI components, embeds, views
├── allowed_vendors.json  # Model configuration
├── db/              # SQL schema and query files (parameterized)
├── Dockerfile       # Container definition
├── install.sh       # Setup script
└── start.sh         # Docker startup script
```

## Key Architectural Patterns

### Async-First Design
All operations use async/await. Use `asyncio.to_thread()` for blocking operations (Fal.AI API, image compression).

### Command Handler Pattern
```python
@client.tree.command()
async def command_name(interaction: discord.Interaction, param: str):
    await interaction.response.defer()  # Prevent 3-second Discord timeout
    # Process command
```

### Database Layer
- SQL queries stored in `/db/*.sql` files (parameterized)
- Operations wrapped in Python methods in `mem.py`
- Foreign keys enabled, soft deletion (visible flag)
- Context window: 35 messages per channel

### Rate Limiting
- Per-channel rate limits for text (`ANTHROPIC_RATE_LIMIT`) and image (`FAL_RATE_LIMIT`) requests
- Counts recent requests within hourly window

## Build & Run Commands

```bash
# Install and start
./install.sh

# Start existing container
./start.sh

# Rebuild and start
docker build -t apex-mage . && ./start.sh

# Update API keys
./update_keys.sh
```

## Environment Variables

- `DISCORD_BOT_TOKEN` - Required
- `ANTHROPIC_API_KEY` - Required
- `FAL_KEY` - Required
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to GCP auth JSON
- `ANTHROPIC_RATE_LIMIT` - Max requests/hour (default: 30)
- `FAL_RATE_LIMIT` - Max image requests/hour (default: 8)
- `IMAGE_CONTEXT_SIZE` - Images to keep in context (default: 5)

## Discord Commands

- `/prompt` - Text generation with optional image input
- `/create_image` - Image generation from text
- `/upload_image` - Store image for later use
- `/modify_image` - Edit images using Fal.AI Canny model
- `/behavior` - Change bot personality/system prompt
- `/clear` - Reset channel context
- `/help` - Display command documentation

## Development Guidelines

1. **Always defer interactions** - Discord has a 3-second response window
2. **Maintain async patterns** - Never block the event loop
3. **Use parameterized SQL** - All queries in `/db/*.sql` files
4. **Handle timeouts** - Use `asyncio.timeout()` context managers
5. **Compress images** - Max 512x512, JPEG quality=75 for token efficiency
6. **Check rate limits** - Query `mem.py` before API calls
7. **Environment variables only** - Never hardcode API keys

## Database Schema

Three main tables:
- `channels` - Discord channel/DM storage (channel_id, discord_id)
- `vendors` - AI service providers (vendor_id, vendor_name, vendor_model_name)
- `channel_messages` - Chat history with images as base64 JSON arrays

## Error Handling

- Retry logic for Anthropic 529 errors (exponential backoff)
- Text overflow (>1024 chars) uploads to GCS with graceful fallback
- NSFW detection with SPOILER_ prefix for images

## Testing

No automated tests currently. Manual testing via Discord commands:
```
/prompt prompt:hello world!
```

Important reminders:
   • Use bd for ALL task tracking - NO markdown TODO lists
   • Always use --json flag for programmatic bd commands
   • Link discovered work with discovered-from dependencies
   • Check bd ready before asking "what should I work on?"