# Coding Conventions

This document describes the coding conventions used in the apex-mage codebase.

## Error Handling

### Error Hierarchy

Use domain-specific custom errors for recoverable conditions:

```python
# Define in module where error originates
class VariationError(Exception):
    """Base error for image variation operations."""

class RateLimitExceededError(VariationError):
    """Raised when variation rate limit is exceeded."""
```

### When to Use Each Error Type

| Error Type | Use Case | Example |
|------------|----------|---------|
| Custom domain error | Recoverable, caller can handle | `VariationError`, `HaikuError`, `AuthError` |
| `HTTPException` | FastAPI routes, return to client | Rate limits, auth failures, bad requests |
| `RuntimeError` | Programming errors, should never happen | Missing required config at startup |
| Built-in errors | Standard Python semantics | `ValueError` for bad args, `KeyError` for missing keys |

### Error Classification (Transient vs Permanent)

Use `src/core/errors.py` for retry logic:

```python
from src.core.errors import classify_error, is_retryable, TransientError

try:
    result = await api_call()
except Exception as ex:
    if is_retryable(classify_error(ex)):
        # Retry with backoff
        pass
    else:
        raise PermanentError.from_exception(ex)
```

Transient (retryable): `RATE_LIMIT`, `TIMEOUT`, `NETWORK`, `SERVICE_UNAVAILABLE`, `OVERLOADED`
Permanent (fail fast): `INVALID_INPUT`, `AUTH_FAILURE`, `NOT_FOUND`, `CONFIGURATION`, `UNKNOWN`

### HTTPException Pattern

Always include structured detail:

```python
raise HTTPException(
    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    detail={
        "error": "Rate limit exceeded",
        "code": "RATE_LIMIT_EXCEEDED",
        "retry_after": rate_check.retry_after,
    },
)
```

---

## Logging

### Setup

Use structlog via `src/core/logging.py`:

```python
from src.core.logging import get_logger

logger = get_logger(__name__)
```

### Log Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed diagnostic info, not for production |
| `INFO` | Normal operations, significant events |
| `WARNING` | Recoverable issues (auth failures, rate limits) |
| `ERROR` | Errors that need attention but don't crash |
| `EXCEPTION` | Use `logger.exception()` when catching exceptions |

### Structured Format

Always use keyword arguments for structured data:

```python
# Good - structured, searchable
logger.info("image_generated", user_id=user.id, prompt_length=len(prompt))
logger.warning("rate_limit_hit", user_id=user.id, retry_after=30)
logger.exception("api_call_failed", provider="anthropic", error=str(ex))

# Bad - unstructured string interpolation
logger.info(f"Generated image for user {user.id}")
```

### Event Naming

Use snake_case for event names:
- `image_generated`, `auth_failed`, `rate_limit_hit`
- Start with noun (what) or verb (action)

### Context Variables

For request-scoped context (correlation IDs, user info):

```python
from src.core.logging import bind_contextvars, clear_contextvars

bind_contextvars(correlation_id="abc-123", user_id=456)
# All subsequent logs include these fields
logger.info("processing")  # Includes correlation_id and user_id
clear_contextvars()  # Clean up at request end
```

---

## Type Hints

### Syntax

Use modern Python 3.10+ syntax:

```python
# Good - modern union syntax
def process(data: str | None = None) -> list[str]:
    ...

# Avoid - old typing module syntax
from typing import Optional, List
def process(data: Optional[str] = None) -> List[str]:
    ...
```

### Avoid `Any`

Prefer specific types or generics:

```python
# Good - specific type
def get_config(key: str) -> str | int | bool:
    ...

# Good - generic when truly dynamic
T = TypeVar("T")
def get_item(container: Container[T], index: int) -> T:
    ...

# Avoid - loses type safety
def get_config(key: str) -> Any:
    ...
```

### Protocol for Duck Typing

Use `Protocol` for interface definitions:

```python
from typing import Protocol

class AIProvider(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
    ) -> ChatResponse:
        ...
```

### TYPE_CHECKING for Circular Imports

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.providers import ImageProvider
```

---

## Docstrings

Use Google-style docstrings with Args, Returns, Raises:

```python
def build_context(
    self,
    history: list[tuple[str, str, str]],
    system_prompt: str | None = None,
) -> ConversationContext:
    """Build conversation context from message history.

    Windows messages to fit within the configured limits, keeping
    the most recent messages. If a system prompt is provided, its
    tokens count toward the max_tokens limit.

    Args:
        history: List of (role, content, timestamp) tuples representing
            the conversation history. Should be in chronological order
            (oldest first).
        system_prompt: Optional system prompt. If provided, its token
            estimate counts toward the max_tokens limit.

    Returns:
        ConversationContext with windowed messages and token estimate.

    Raises:
        ValueError: If history contains invalid role values.
    """
```

### Class Docstrings

Include Attributes section:

```python
class TransientError(Exception):
    """Error that is temporary and can be retried.

    Attributes:
        category: The specific type of transient error.
        retry_after: Suggested wait time before retry (seconds), if known.
        original_error: The underlying exception that was classified.
    """
```

### Module Docstrings

Include purpose, example usage:

```python
"""Structured logging configuration using structlog.

This module provides a centralized logging configuration that supports both
development (pretty-printed) and production (JSON) output formats.

Usage:
    from src.core.logging import get_logger, configure_logging

    configure_logging(development=True)
    logger = get_logger(__name__)
    logger.info("message", key="value")
"""
```

---

## Import Organization

Organize imports in three groups with blank lines between:

```python
# 1. Standard library
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

# 2. Third-party packages
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# 3. Local imports
from src.core.errors import classify_error
from src.core.logging import get_logger
from src.core.providers import ChatMessage
```

### Import Style

- Prefer `from x import y` for specific items
- Use `import x` for namespacing when helpful (`import asyncio`)
- Sort alphabetically within each group (ruff handles this)
- Use `from __future__ import annotations` for forward references

---

## Naming Conventions

### General Rules

| Item | Convention | Example |
|------|------------|---------|
| Functions/methods | `snake_case` | `get_logger`, `build_context` |
| Variables | `snake_case` | `user_id`, `max_tokens` |
| Classes | `PascalCase` | `ContextBuilder`, `TransientError` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `DEFAULT_MODEL` |
| Private | Leading underscore | `_client`, `_convert_messages` |
| Type variables | Single uppercase or `PascalCase` | `T`, `ResponseT` |

### Async Functions

Prefix with action verb, no special async naming:

```python
# Good - clear action
async def generate_image(...):
async def fetch_messages(...):

# Avoid - redundant async prefix
async def async_generate_image(...):
```

### Boolean Variables/Parameters

Use `is_`, `has_`, `can_`, `should_` prefixes:

```python
is_valid: bool
has_nsfw_content: bool
can_retry: bool
should_compress: bool
```

---

## Test Structure

### File Naming

- `test_<module>.py` for unit tests
- `test_<feature>_integration.py` for integration tests

### Test Class/Function Naming

```python
class TestContextBuilder:
    """Tests for ContextBuilder class."""

    def test_empty_history_returns_empty_context(self):
        """Empty history should produce empty context."""
        ...

    def test_windows_to_max_messages(self):
        """Should limit to max_messages, keeping most recent."""
        ...
```

### Test Organization

Group related tests in classes:

```python
class TestVariationCarouselNavigation:
    """Navigation button tests."""

    def test_previous_button_disabled_at_start(self):
        ...

    def test_navigation_with_variations(self):
        ...


class TestVariationGeneration:
    """Variation generation tests."""

    def test_same_prompt_generates_variation(self):
        ...
```

### Fixtures

Define in `conftest.py` for shared fixtures:

```python
@pytest.fixture
def mock_ai_provider() -> MockAIProvider:
    """Provide a mock AI provider for testing.

    Returns a MockAIProvider with default settings. For tests requiring
    specific responses, create the mock directly with custom responses.

    Returns:
        MockAIProvider: A mock AI provider instance.
    """
    return MockAIProvider()
```

### When to Mock

| Mock | Don't Mock |
|------|------------|
| External APIs (Anthropic, Fal.AI) | Pure logic functions |
| Database I/O | Data structures |
| Network requests | Business rules |
| Time-dependent operations | Calculations |

### Async Tests

pytest-asyncio handles async tests automatically:

```python
async def test_chat_returns_response(self):
    """Should return ChatResponse from API."""
    provider = AnthropicProvider(api_key="test")
    response = await provider.chat([...])
    assert response.content == "expected"
```

---

## Async Patterns

### Use `async`/`await` for I/O

```python
# Good - async I/O
async def fetch_image(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.read()

# Avoid - blocking I/O in async context
def fetch_image(url: str) -> bytes:
    return requests.get(url).content  # Blocks event loop!
```

### Concurrent Operations

Use `asyncio.gather` for independent operations:

```python
results = await asyncio.gather(
    fetch_user(user_id),
    fetch_settings(user_id),
    return_exceptions=True,
)
```

---

## Pydantic Models

### Schema Definitions

```python
class ImageGenerateRequest(BaseModel):
    """Request schema for image generation."""

    prompt: str = Field(..., min_length=1, max_length=10000)
    width: int | None = Field(None, ge=256, le=2048)
    height: int | None = Field(None, ge=256, le=2048)

    model_config = {
        "json_schema_extra": {
            "example": {
                "prompt": "A serene mountain landscape",
                "width": 1024,
                "height": 1024,
            }
        }
    }
```

---

## Dependency Injection

Prefer constructor injection:

```python
class AnthropicProvider:
    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
```

For FastAPI, use `Depends()`:

```python
async def generate_image(
    request: ImageGenerateRequest,
    image_provider: ImageProvider = Depends(get_image_provider),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
) -> ImageResponse:
    ...
```
