"""AI Provider protocols for text and image generation.

This module defines the interfaces (Protocols) for AI provider operations.
Implementations can use Anthropic, OpenAI, or any other AI service backend.
All types are platform-agnostic (no Discord, Slack, or other client types).
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ChatMessage:
    """Represents a single message in a conversation.

    This is a platform-agnostic representation of a chat message that can be
    used with any AI provider.

    Attributes:
        role: The role of the message sender. One of "user", "assistant", or
            "system". Note that some providers handle system messages via a
            separate parameter rather than in the message list.
        content: The text content of the message.
    """

    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class ChatResponse:
    """Represents a response from an AI chat completion.

    Contains the generated text along with metadata about the request.

    Attributes:
        content: The generated text response from the AI.
        model: The model identifier that generated the response (e.g.,
            "claude-3-sonnet-20240229").
        usage: Token usage statistics for the request. Typically contains
            "input_tokens" and "output_tokens" keys.
    """

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


# =============================================================================
# Provider Protocols
# =============================================================================


class AIProvider(Protocol):
    """Protocol for AI chat completion providers.

    Defines the interface for AI services that can generate text responses
    from conversations. Implementations should handle provider-specific
    details like API authentication, rate limiting, and error handling.

    This protocol intentionally excludes:
    - Image generation (see ImageProvider)
    - Embeddings
    - Fine-tuning operations

    Implementations are expected to be async-first for I/O efficiency.
    """

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Generate a chat completion from a conversation.

        Sends the conversation history to the AI provider and returns
        the generated response.

        Args:
            messages: The conversation history as a list of ChatMessage
                objects. Should be in chronological order (oldest first).
            system_prompt: Optional system prompt that sets the AI's behavior
                and context. How this is handled varies by provider (e.g.,
                Anthropic uses a separate system parameter, while OpenAI
                includes it in the messages list).
            max_tokens: Maximum number of tokens to generate in the response.
                Defaults to 4096.

        Returns:
            A ChatResponse containing the generated text, model identifier,
            and token usage statistics.

        Raises:
            ProviderError: If the API call fails (network error, rate limit,
                invalid request, etc.). Implementations should wrap
                provider-specific exceptions.
        """
        ...

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Generate a streaming chat completion.

        Similar to chat(), but yields response chunks as they are generated.
        This allows for real-time display of responses in interactive
        applications.

        Args:
            messages: The conversation history as a list of ChatMessage
                objects. Should be in chronological order (oldest first).
            system_prompt: Optional system prompt that sets the AI's behavior.

        Yields:
            String chunks of the generated response as they become available.

        Raises:
            ProviderError: If the API call fails.

        Example:
            >>> provider = AnthropicProvider(api_key="...")
            >>> async for chunk in provider.chat_stream(messages):
            ...     print(chunk, end="", flush=True)
        """
        ...
