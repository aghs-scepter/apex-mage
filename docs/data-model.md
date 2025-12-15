# Data Model

> Single source of truth for all persistent entities. Update this document BEFORE implementing schema changes.

## Entities

### Conversation
A thread of messages between a user and the AI, scoped to a specific channel.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| channel_id | string | External channel identifier (platform-specific) |
| platform | enum | Source platform: `discord`, `web` |
| created_at | timestamp | When conversation started |
| updated_at | timestamp | Last activity |
| behavior | text | Custom system prompt, nullable |
| is_active | boolean | Soft delete flag |

### Message
A single exchange within a conversation.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| conversation_id | UUID | FK to Conversation |
| role | enum | `user`, `assistant`, `system` |
| content | text | Message text |
| images | jsonb | Array of image references |
| created_at | timestamp | When sent |
| token_count | integer | Tokens used, nullable |

### Vendor
API provider configuration.

| Field | Type | Description |
|-------|------|-------------|
| id | string | Provider identifier: `anthropic`, `fal` |
| is_enabled | boolean | Whether provider is active |
| rate_limit | jsonb | Rate limiting configuration |

---

## Relationships

```
Conversation 1--* Message
```

---

## Indexes

- `conversation_channel_platform_idx` on Conversation(channel_id, platform)
- `message_conversation_created_idx` on Message(conversation_id, created_at DESC)

---

## Migration Notes

When modifying this schema:
1. Update this document first
2. Create migration file in `src/db/migrations/`
3. Test migration up AND down
4. Update any affected queries in `src/db/queries/`
