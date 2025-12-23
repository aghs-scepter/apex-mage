"""Token counting utility for prompt pipeline.

This module provides functions to count tokens and check if the total
token count exceeds a configured threshold. Token counting is used to
determine when auto-summarization should be triggered.

Uses tiktoken with cl100k_base encoding as a fast approximation for Claude
models (accurate within ~15%).

Example usage:
    # Count tokens in text
    count = count_tokens("Hello, world!")

    # Check if threshold exceeded
    total, exceeded = check_token_threshold(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "Hi"}],
        current_prompt="How are you?",
        threshold=10000,
    )
"""

from __future__ import annotations

from typing import Any

import tiktoken

from src.core.logging import get_logger

logger = get_logger(__name__)

# Use cl100k_base encoding (GPT-4/Claude approximation)
# This is cached by tiktoken after first load
_ENCODING_NAME = "cl100k_base"

# Default threshold for triggering auto-summarization
DEFAULT_THRESHOLD = 10000


def _get_encoding() -> tiktoken.Encoding:
    """Get the tiktoken encoding (cached after first call).

    Returns:
        The cl100k_base encoding for token counting.
    """
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken cl100k_base.

    This provides a fast approximation of token count that is
    accurate within ~15% for Claude models.

    Args:
        text: The text to count tokens in.

    Returns:
        The number of tokens in the text.
    """
    if not text:
        return 0

    encoding = _get_encoding()
    tokens = encoding.encode(text)
    return len(tokens)


def _extract_message_content(message: dict[str, Any]) -> str:
    """Extract text content from a message dictionary.

    Handles both simple string content and complex content lists
    (e.g., messages with images and text).

    Args:
        message: A message dictionary with 'role' and 'content' keys.

    Returns:
        The text content from the message.
    """
    content = message.get("content", "")

    # Simple string content
    if isinstance(content, str):
        return content

    # Complex content (list of content blocks)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                # Skip image blocks - they don't contribute to text token count
                # in the same way (images have their own token counting)
            elif isinstance(block, str):
                text_parts.append(block)
        return " ".join(text_parts)

    return ""


def check_token_threshold(
    system_prompt: str,
    messages: list[dict[str, Any]],
    current_prompt: str,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[int, bool]:
    """Check if total tokens exceed threshold.

    Counts tokens from the system prompt, all message history, and
    the current user prompt to determine if auto-summarization
    should be triggered.

    Args:
        system_prompt: The system prompt text.
        messages: List of message dictionaries with 'role' and 'content' keys.
        current_prompt: The current user prompt being processed.
        threshold: Token threshold for triggering summarization.
            Defaults to 10,000.

    Returns:
        Tuple of (total_token_count, threshold_exceeded) where:
        - total_token_count: The total number of tokens counted
        - threshold_exceeded: True if total exceeds threshold
    """
    total_tokens = 0

    # Count system prompt tokens
    system_tokens = count_tokens(system_prompt)
    total_tokens += system_tokens

    # Count message history tokens
    message_tokens = 0
    for message in messages:
        content = _extract_message_content(message)
        message_tokens += count_tokens(content)
    total_tokens += message_tokens

    # Count current prompt tokens
    current_tokens = count_tokens(current_prompt)
    total_tokens += current_tokens

    threshold_exceeded = total_tokens > threshold

    logger.debug(
        "Token count check",
        extra={
            "system_tokens": system_tokens,
            "message_tokens": message_tokens,
            "current_tokens": current_tokens,
            "total_tokens": total_tokens,
            "threshold": threshold,
            "exceeded": threshold_exceeded,
        },
    )

    return total_tokens, threshold_exceeded
