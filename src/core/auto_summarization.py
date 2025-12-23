"""Auto-summarization trigger and state management.

This module manages the state and logic for automatic context summarization
when the token count exceeds a threshold. It tracks which channels have
pending summarization and provides the logic for triggering the summarization
flow.

The flow is:
1. Token count exceeds threshold during a message
2. Set pending_summarization flag, add warning prefix to response
3. On next message with flag set: summarize context, clear flag, add confirmation

Example usage:
    manager = AutoSummarizationManager()

    # Check if we should summarize on this message
    if manager.should_summarize(channel_id):
        # Perform summarization
        await summarize_and_replace_context(...)
        manager.clear_pending(channel_id)

    # After processing, check if threshold was exceeded
    if threshold_exceeded:
        manager.set_pending(channel_id)
"""

from __future__ import annotations

from typing import Any

from src.core.haiku import SummarizationError, haiku_summarize_conversation
from src.core.logging import get_logger
from src.core.token_counting import check_token_threshold

logger = get_logger(__name__)

# Warning message shown when threshold is exceeded
THRESHOLD_WARNING = (
    "*Note: Context is approaching limit. "
    "Your next message will trigger auto-summarization.*"
)

# Confirmation message shown after auto-summarization
SUMMARIZATION_CONFIRMATION = "*Context auto-summarized to maintain performance.*"


class AutoSummarizationManager:
    """Manages auto-summarization state per channel.

    This class tracks which channels have pending summarization and provides
    methods to check, set, and clear the pending state.

    The manager uses an in-memory dict for state tracking. This is appropriate
    because:
    - State is transient (only matters between consecutive messages)
    - If bot restarts, worst case is missing one auto-summarization
    - Avoids database overhead for every message

    Attributes:
        _pending: Dict mapping channel_id to pending summarization state.
    """

    def __init__(self) -> None:
        """Initialize the manager with empty state."""
        self._pending: dict[int, bool] = {}

    def should_summarize(self, channel_id: int) -> bool:
        """Check if this channel should perform auto-summarization.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            True if the channel has pending summarization, False otherwise.
        """
        return self._pending.get(channel_id, False)

    def set_pending(self, channel_id: int) -> None:
        """Mark a channel as having pending summarization.

        This should be called when the token threshold is exceeded.

        Args:
            channel_id: The Discord channel ID.
        """
        self._pending[channel_id] = True
        logger.info(
            "Auto-summarization pending",
            extra={"channel_id": channel_id},
        )

    def clear_pending(self, channel_id: int) -> None:
        """Clear the pending summarization flag for a channel.

        This should be called after summarization completes or if the
        channel history is cleared.

        Args:
            channel_id: The Discord channel ID.
        """
        self._pending.pop(channel_id, None)
        logger.info(
            "Auto-summarization cleared",
            extra={"channel_id": channel_id},
        )

    def is_pending(self, channel_id: int) -> bool:
        """Check if a channel has pending summarization.

        This is an alias for should_summarize for clarity.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            True if pending, False otherwise.
        """
        return self.should_summarize(channel_id)


# Global manager instance for the application
_manager: AutoSummarizationManager | None = None


def get_auto_summarization_manager() -> AutoSummarizationManager:
    """Get the global auto-summarization manager instance.

    Returns:
        The singleton AutoSummarizationManager instance.
    """
    global _manager
    if _manager is None:
        _manager = AutoSummarizationManager()
    return _manager


def check_threshold_for_summarization(
    system_prompt: str,
    messages: list[dict[str, Any]],
    current_prompt: str,
    threshold: int = 10000,
) -> tuple[int, bool]:
    """Check if token threshold is exceeded for auto-summarization.

    This is a convenience wrapper around check_token_threshold that uses
    the default summarization threshold.

    Args:
        system_prompt: The system prompt text.
        messages: List of message dictionaries with 'role' and 'content' keys.
        current_prompt: The current user prompt being processed.
        threshold: Token threshold for triggering summarization.
            Defaults to 10,000.

    Returns:
        Tuple of (total_token_count, threshold_exceeded).
    """
    return check_token_threshold(
        system_prompt=system_prompt,
        messages=messages,
        current_prompt=current_prompt,
        threshold=threshold,
    )


def convert_context_to_chat_messages(
    context: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Convert repository context to the format expected by haiku_summarize_conversation.

    Args:
        context: List of message dicts from the repository.

    Returns:
        List of message dicts with 'role' and 'content' keys.
    """
    messages: list[dict[str, str]] = []

    for row in context:
        msg_type = row.get("message_type", "")
        content = row.get("message_data", "")

        # Skip behavior messages and empty content
        if msg_type == "behavior" or not content:
            continue

        # Map message_type to role
        if msg_type == "prompt":
            role = "user"
        elif msg_type == "assistant":
            role = "assistant"
        else:
            continue

        messages.append({"role": role, "content": content})

    return messages


async def perform_summarization(
    messages: list[dict[str, str]],
    guidance: str | None = None,
) -> str:
    """Perform conversation summarization using Haiku.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        guidance: Optional focus area for the summary.

    Returns:
        The summary text.

    Raises:
        SummarizationError: If summarization fails.
    """
    logger.info(
        "Performing auto-summarization",
        extra={
            "message_count": len(messages),
            "has_guidance": guidance is not None,
        },
    )

    try:
        summary = await haiku_summarize_conversation(messages, guidance)
        logger.info(
            "Auto-summarization complete",
            extra={
                "summary_length": len(summary),
                "original_message_count": len(messages),
            },
        )
        return summary
    except SummarizationError:
        logger.error("Auto-summarization failed")
        raise
