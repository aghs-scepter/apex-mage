"""Unit tests for the auto-summarization module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.core.auto_summarization import (
    SUMMARIZATION_CONFIRMATION,
    THRESHOLD_WARNING,
    AutoSummarizationManager,
    check_threshold_for_summarization,
    convert_context_to_chat_messages,
    get_auto_summarization_manager,
    perform_summarization,
)
from src.core.haiku import SummarizationError


class TestAutoSummarizationManager:
    """Tests for AutoSummarizationManager class."""

    def test_initial_state_is_empty(self) -> None:
        """Test that manager starts with no pending channels."""
        manager = AutoSummarizationManager()
        assert not manager.should_summarize(12345)

    def test_set_pending(self) -> None:
        """Test setting a channel as pending."""
        manager = AutoSummarizationManager()
        channel_id = 12345

        manager.set_pending(channel_id)

        assert manager.should_summarize(channel_id)

    def test_clear_pending(self) -> None:
        """Test clearing the pending state."""
        manager = AutoSummarizationManager()
        channel_id = 12345

        manager.set_pending(channel_id)
        manager.clear_pending(channel_id)

        assert not manager.should_summarize(channel_id)

    def test_clear_pending_when_not_set(self) -> None:
        """Test that clearing a non-pending channel does not error."""
        manager = AutoSummarizationManager()
        channel_id = 12345

        # Should not raise
        manager.clear_pending(channel_id)

        assert not manager.should_summarize(channel_id)

    def test_is_pending_alias(self) -> None:
        """Test that is_pending is an alias for should_summarize."""
        manager = AutoSummarizationManager()
        channel_id = 12345

        assert manager.is_pending(channel_id) == manager.should_summarize(channel_id)

        manager.set_pending(channel_id)

        assert manager.is_pending(channel_id) == manager.should_summarize(channel_id)
        assert manager.is_pending(channel_id) is True

    def test_multiple_channels_independent(self) -> None:
        """Test that different channels have independent pending states."""
        manager = AutoSummarizationManager()
        channel_1 = 12345
        channel_2 = 67890

        manager.set_pending(channel_1)

        assert manager.should_summarize(channel_1)
        assert not manager.should_summarize(channel_2)

        manager.set_pending(channel_2)

        assert manager.should_summarize(channel_1)
        assert manager.should_summarize(channel_2)

        manager.clear_pending(channel_1)

        assert not manager.should_summarize(channel_1)
        assert manager.should_summarize(channel_2)


class TestGetAutoSummarizationManager:
    """Tests for get_auto_summarization_manager function."""

    def test_returns_manager(self) -> None:
        """Test that get_auto_summarization_manager returns a manager."""
        manager = get_auto_summarization_manager()
        assert isinstance(manager, AutoSummarizationManager)

    def test_returns_singleton(self) -> None:
        """Test that get_auto_summarization_manager returns the same instance."""
        manager1 = get_auto_summarization_manager()
        manager2 = get_auto_summarization_manager()
        assert manager1 is manager2


class TestCheckThresholdForSummarization:
    """Tests for check_threshold_for_summarization function."""

    def test_returns_tuple(self) -> None:
        """Test that the function returns a tuple."""
        result = check_threshold_for_summarization(
            system_prompt="You are helpful.",
            messages=[],
            current_prompt="Hello",
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_uses_default_threshold(self) -> None:
        """Test that default threshold of 10000 is used."""
        count, exceeded = check_threshold_for_summarization(
            system_prompt="",
            messages=[],
            current_prompt="Hello",
        )
        assert not exceeded  # Small text should not exceed 10k

    def test_threshold_exceeded_with_long_text(self) -> None:
        """Test that threshold is exceeded with very long text."""
        # Generate text that exceeds 10k tokens
        long_text = "word " * 3000  # ~3000 tokens per message
        messages = [
            {"role": "user", "content": long_text},
            {"role": "assistant", "content": long_text},
            {"role": "user", "content": long_text},
            {"role": "assistant", "content": long_text},
        ]

        _, exceeded = check_threshold_for_summarization(
            system_prompt="",
            messages=messages,
            current_prompt="",
        )
        assert exceeded


class TestConvertContextToChatMessages:
    """Tests for convert_context_to_chat_messages function."""

    def test_converts_prompt_to_user(self) -> None:
        """Test that 'prompt' message type becomes 'user' role."""
        context = [{"message_type": "prompt", "message_data": "Hello"}]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_converts_assistant(self) -> None:
        """Test that 'assistant' message type becomes 'assistant' role."""
        context = [{"message_type": "assistant", "message_data": "Hi there!"}]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Hi there!"

    def test_skips_behavior_messages(self) -> None:
        """Test that 'behavior' message type is skipped."""
        context = [
            {"message_type": "behavior", "message_data": "You are helpful."},
            {"message_type": "prompt", "message_data": "Hello"},
        ]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_skips_empty_content(self) -> None:
        """Test that messages with empty content are skipped."""
        context = [
            {"message_type": "prompt", "message_data": ""},
            {"message_type": "assistant", "message_data": "Hi"},
        ]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"

    def test_skips_unknown_message_types(self) -> None:
        """Test that unknown message types are skipped."""
        context = [
            {"message_type": "unknown", "message_data": "Something"},
            {"message_type": "prompt", "message_data": "Hello"},
        ]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_empty_context(self) -> None:
        """Test that empty context returns empty list."""
        result = convert_context_to_chat_messages([])
        assert result == []

    def test_preserves_order(self) -> None:
        """Test that message order is preserved."""
        context = [
            {"message_type": "prompt", "message_data": "First"},
            {"message_type": "assistant", "message_data": "Second"},
            {"message_type": "prompt", "message_data": "Third"},
        ]
        result = convert_context_to_chat_messages(context)
        assert len(result) == 3
        assert result[0]["content"] == "First"
        assert result[1]["content"] == "Second"
        assert result[2]["content"] == "Third"


class TestPerformSummarization:
    """Tests for perform_summarization function."""

    @pytest.mark.asyncio
    async def test_calls_haiku_summarize(self) -> None:
        """Test that perform_summarization calls haiku_summarize_conversation."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        with patch(
            "src.core.auto_summarization.haiku_summarize_conversation"
        ) as mock_summarize:
            mock_summarize.return_value = "Summary of conversation: Brief exchange."

            result = await perform_summarization(messages)

            mock_summarize.assert_called_once_with(messages, None)
            assert result == "Summary of conversation: Brief exchange."

    @pytest.mark.asyncio
    async def test_passes_guidance(self) -> None:
        """Test that guidance is passed to haiku_summarize_conversation."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch(
            "src.core.auto_summarization.haiku_summarize_conversation"
        ) as mock_summarize:
            mock_summarize.return_value = "Summary focused on greetings."

            await perform_summarization(messages, guidance="greetings")

            mock_summarize.assert_called_once_with(messages, "greetings")

    @pytest.mark.asyncio
    async def test_raises_on_error(self) -> None:
        """Test that SummarizationError is raised on failure."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch(
            "src.core.auto_summarization.haiku_summarize_conversation"
        ) as mock_summarize:
            mock_summarize.side_effect = SummarizationError("API error")

            with pytest.raises(SummarizationError):
                await perform_summarization(messages)


class TestConstants:
    """Tests for module constants."""

    def test_threshold_warning_is_italic(self) -> None:
        """Test that the warning message uses italic formatting."""
        assert THRESHOLD_WARNING.startswith("*")
        assert THRESHOLD_WARNING.endswith("*")

    def test_summarization_confirmation_is_italic(self) -> None:
        """Test that the confirmation message uses italic formatting."""
        assert SUMMARIZATION_CONFIRMATION.startswith("*")
        assert SUMMARIZATION_CONFIRMATION.endswith("*")

    def test_warning_mentions_auto_summarization(self) -> None:
        """Test that the warning mentions auto-summarization."""
        assert "auto-summarization" in THRESHOLD_WARNING.lower()

    def test_confirmation_mentions_auto_summarized(self) -> None:
        """Test that the confirmation mentions auto-summarized."""
        assert "auto-summarized" in SUMMARIZATION_CONFIRMATION.lower()
