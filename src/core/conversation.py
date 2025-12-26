"""Conversation context building and windowing logic.

This module provides platform-agnostic conversation context management,
including message windowing (limiting to most recent messages) and token
estimation. All logic is pure computation with no I/O dependencies.
"""

from dataclasses import dataclass
from typing import Any

from src.core.providers import ChatMessage


@dataclass
class ConversationContext:
    """Built conversation context ready for AI provider consumption.

    Contains the windowed messages and metadata about the context.

    Attributes:
        messages: List of ChatMessage objects, windowed to fit limits.
            Messages are in chronological order (oldest first).
        total_tokens_estimate: Rough estimate of total tokens in the context.
            Uses ~4 characters per token heuristic.
    """

    messages: list[ChatMessage]
    total_tokens_estimate: int


class ContextBuilder:
    """Builds conversation context from message history with windowing.

    Applies limits to ensure the conversation fits within model context
    windows. Windowing is done from the most recent messages backward,
    preserving the most relevant context.

    This class is pure logic with no I/O dependencies, making it easy
    to test and use across different contexts.

    Attributes:
        max_messages: Maximum number of messages to include in context.
        max_tokens: Maximum estimated tokens to include in context.
    """

    def __init__(self, max_messages: int = 50, max_tokens: int = 100000) -> None:
        """Initialize the context builder with limits.

        Args:
            max_messages: Maximum number of messages to include. Defaults to 50.
            max_tokens: Maximum estimated tokens. Defaults to 100000.
        """
        self.max_messages = max_messages
        self.max_tokens = max_tokens

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
                (oldest first). The timestamp is preserved for ordering but
                not included in the output messages.
            system_prompt: Optional system prompt. If provided, its token
                estimate counts toward the max_tokens limit.

        Returns:
            ConversationContext with windowed messages and token estimate.
        """
        # Start with system prompt token budget if provided
        system_tokens = self.estimate_tokens(system_prompt) if system_prompt else 0

        # Convert history to ChatMessages (most recent first for windowing)
        reversed_history = list(reversed(history))

        windowed_messages: list[ChatMessage] = []
        total_tokens = system_tokens

        for role, content, _timestamp in reversed_history:
            if len(windowed_messages) >= self.max_messages:
                break

            message_tokens = self.estimate_tokens(content)
            if total_tokens + message_tokens > self.max_tokens:
                break

            windowed_messages.append(ChatMessage(role=role, content=content))
            total_tokens += message_tokens

        # Reverse back to chronological order (oldest first)
        windowed_messages.reverse()

        return ConversationContext(
            messages=windowed_messages,
            total_tokens_estimate=total_tokens,
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses a rough heuristic of ~4 characters per token. This is
        a reasonable approximation for English text with typical
        tokenizers (GPT, Claude, etc.).

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated token count (minimum of 1 for non-empty text).
        """
        if not text:
            return 0
        # ~4 characters per token is a reasonable heuristic
        return max(1, len(text) // 4)


def convert_context_to_messages(
    context: list[dict[str, Any]],
) -> tuple[list[ChatMessage], str | None]:
    """Convert database context to ChatMessage list and extract system prompt.

    Processes message history from the repository format into a list of
    ChatMessage objects suitable for AI providers. Behavior messages are
    extracted as the system prompt rather than included in the message list.

    Args:
        context: List of message dicts from the repository. Each dict should
            have 'message_type' and 'message_data' keys. Valid message_type
            values are 'behavior', 'prompt', and 'assistant'.

    Returns:
        Tuple of (chat_messages, system_prompt) where:
        - chat_messages: List of ChatMessage objects with role and content
        - system_prompt: The most recent behavior message content, or None
    """
    messages: list[ChatMessage] = []
    system_prompt: str | None = None

    # Find the most recent behavior message (system prompt)
    for row in reversed(context):
        if row["message_type"] == "behavior":
            system_prompt = row["message_data"]
            break

    # Convert non-behavior messages to ChatMessages
    for row in context:
        msg_type = row["message_type"]
        if msg_type == "behavior":
            continue  # Skip behavior messages - they become system prompt

        # Map message_type to ChatMessage role
        if msg_type == "prompt":
            role = "user"
        elif msg_type == "assistant":
            role = "assistant"
        else:
            continue  # Skip unknown types

        messages.append(ChatMessage(role=role, content=row["message_data"]))

    return messages, system_prompt
