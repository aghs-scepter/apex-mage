"""Anthropic Claude AI provider implementation.

This module provides an implementation of the AIProvider protocol
for Anthropic's Claude API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from anthropic import APIError, AsyncAnthropic

from src.core.providers import AIProvider, ChatMessage, ChatResponse


logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Claude API provider implementing AIProvider protocol.

    This provider wraps the Anthropic Python SDK to provide chat completion
    functionality via the Claude model family. It supports both standard
    completions and streaming responses.

    The API key is injected via the constructor to support dependency
    injection and avoid direct environment variable access.

    Attributes:
        _client: The AsyncAnthropic client instance.
        _default_model: The default model to use for completions.
        _max_retries: Maximum retry attempts for transient errors.
        _backoff_factor: Exponential backoff multiplier for retries.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-20250514",
        max_retries: int = 4,
        backoff_factor: float = 2.0,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            api_key: The Anthropic API key for authentication.
            default_model: The default model to use for completions.
                Defaults to "claude-sonnet-4-20250514".
            max_retries: Maximum number of retries for transient errors.
                Defaults to 4.
            backoff_factor: Base for exponential backoff between retries.
                Defaults to 2.0 (so delays are 1, 2, 4, 8 seconds).
        """
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

    def _convert_messages(
        self, messages: list[ChatMessage]
    ) -> list[dict[str, str]]:
        """Convert ChatMessage list to Anthropic API format.

        Anthropic's API expects messages as a list of dicts with 'role'
        and 'content' keys. System messages should be passed separately
        via the system parameter, not in the messages list.

        Args:
            messages: List of ChatMessage objects to convert.

        Returns:
            List of dicts in Anthropic message format, excluding system
            messages (those should be passed to the system parameter).
        """
        anthropic_messages = []
        for msg in messages:
            # Skip system messages - they should be passed via system_prompt
            if msg.role == "system":
                continue
            anthropic_messages.append({
                "role": msg.role,
                "content": msg.content,
            })
        return anthropic_messages

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Generate a chat completion from a conversation.

        Sends the conversation history to Anthropic's Claude API and
        returns the generated response. Implements retry logic with
        exponential backoff for transient errors (e.g., 529 overloaded).

        Args:
            messages: The conversation history as a list of ChatMessage
                objects. Should be in chronological order (oldest first).
            system_prompt: Optional system prompt that sets Claude's behavior.
                This is passed as a separate parameter per Anthropic's API.
            max_tokens: Maximum tokens to generate. Defaults to 4096.

        Returns:
            A ChatResponse containing the generated text, model identifier,
            and token usage statistics.

        Raises:
            APIError: If the API call fails after all retries.
        """
        anthropic_messages = self._convert_messages(messages)

        for retry in range(self._max_retries):
            try:
                # Build kwargs for the API call
                kwargs: dict = {
                    "model": self._default_model,
                    "max_tokens": max_tokens,
                    "messages": anthropic_messages,
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                response = await self._client.messages.create(**kwargs)

                # Extract content - Anthropic returns a list of content blocks
                content = ""
                if response.content:
                    content = response.content[0].text

                return ChatResponse(
                    content=content,
                    model=response.model,
                    usage={
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                )

            except APIError as ex:
                # Anthropic throws 529 when servers are overloaded
                if ex.status_code == 529:
                    sleep_time = self._backoff_factor**retry
                    logger.warning(
                        "Anthropic API returned 529 (overloaded). "
                        "Retrying in %.2f seconds...",
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    # Re-raise non-retryable errors immediately
                    raise

        # All retries exhausted
        raise APIError(
            message="Max retries exceeded for Anthropic API call",
            request=None,  # type: ignore[arg-type]
            body=None,
        )

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
            system_prompt: Optional system prompt that sets Claude's behavior.

        Yields:
            String chunks of the generated response as they become available.

        Raises:
            APIError: If the API call fails.
        """
        anthropic_messages = self._convert_messages(messages)

        # Build kwargs for the API call
        kwargs: dict = {
            "model": self._default_model,
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


# Protocol compliance verification
def _verify_protocol_compliance() -> None:
    """Verify that AnthropicProvider implements AIProvider protocol.

    This function is not called at runtime but serves as a static
    type check to ensure protocol compliance.
    """
    _: AIProvider = AnthropicProvider(api_key="test")  # noqa: F841
