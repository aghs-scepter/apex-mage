"""Unit tests for conversation summarization functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.haiku import (
    SummarizationError,
    _format_conversation_for_summary,
    haiku_summarize_conversation,
)
from src.core.prompts.summarization import (
    GUIDANCE_TEMPLATE,
    SUMMARIZATION_PROMPT,
    build_summarization_prompt,
)


class TestBuildSummarizationPrompt:
    """Tests for the build_summarization_prompt function."""

    def test_returns_base_prompt_without_guidance(self) -> None:
        """Test that base prompt is returned when no guidance provided."""
        result = build_summarization_prompt()
        # Should have empty guidance section
        assert "{guidance_section}" not in result
        assert "PRIORITY ORDER FOR PRESERVATION" in result
        assert "Summarize the following conversation:" in result

    def test_includes_guidance_when_provided(self) -> None:
        """Test that guidance is included in prompt when provided."""
        result = build_summarization_prompt("the authentication bug")
        assert "SPECIFIC FOCUS:" in result
        assert "the authentication bug" in result

    def test_preserves_priority_order(self) -> None:
        """Test that priority order is preserved in prompt."""
        result = build_summarization_prompt()
        assert "1. Key facts and explicit decisions" in result
        assert "2. Current active task or request" in result
        assert "3. User preferences" in result
        assert "4. Technical details" in result
        assert "5. Recent context over older context" in result

    def test_prompt_specifies_25_percent_target(self) -> None:
        """Test that prompt specifies 25% compression target."""
        result = build_summarization_prompt()
        assert "25%" in result

    def test_prompt_specifies_output_format(self) -> None:
        """Test that prompt specifies output format."""
        result = build_summarization_prompt()
        assert 'Begin with: "Summary of conversation:"' in result


class TestFormatConversationForSummary:
    """Tests for the _format_conversation_for_summary function."""

    def test_formats_user_message(self) -> None:
        """Test formatting of a single user message."""
        messages = [{"role": "user", "content": "Hello"}]
        result = _format_conversation_for_summary(messages)
        assert result == "User: Hello"

    def test_formats_assistant_message(self) -> None:
        """Test formatting of a single assistant message."""
        messages = [{"role": "assistant", "content": "Hi there!"}]
        result = _format_conversation_for_summary(messages)
        assert result == "Assistant: Hi there!"

    def test_formats_multiple_messages(self) -> None:
        """Test formatting of multiple messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]
        result = _format_conversation_for_summary(messages)
        assert "User: Hello" in result
        assert "Assistant: Hi!" in result
        assert "User: How are you?" in result
        # Check messages are separated by double newlines
        assert "\n\n" in result

    def test_handles_empty_list(self) -> None:
        """Test formatting of empty message list."""
        result = _format_conversation_for_summary([])
        assert result == ""

    def test_handles_missing_role(self) -> None:
        """Test handling of message with missing role."""
        messages = [{"content": "Hello"}]
        result = _format_conversation_for_summary(messages)
        assert result == "Unknown: Hello"

    def test_handles_missing_content(self) -> None:
        """Test handling of message with missing content."""
        messages = [{"role": "user"}]
        result = _format_conversation_for_summary(messages)
        assert result == "User: "


class TestHaikuSummarizeConversation:
    """Tests for the haiku_summarize_conversation function."""

    @pytest.mark.asyncio
    async def test_returns_summary_response(self) -> None:
        """Test that summarization returns the API response."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary of conversation: Test")]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Hello"}]
                )

            assert result == "Summary of conversation: Test"

    @pytest.mark.asyncio
    async def test_passes_formatted_conversation(self) -> None:
        """Test that conversation is formatted and passed to API."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_summarize_conversation(
                    messages=[
                        {"role": "user", "content": "Question"},
                        {"role": "assistant", "content": "Answer"},
                    ]
                )

            call_kwargs = mock_create.call_args.kwargs
            # The user message should contain the formatted conversation
            assert "User: Question" in call_kwargs["messages"][0]["content"]
            assert "Assistant: Answer" in call_kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_uses_summarization_prompt(self) -> None:
        """Test that summarization prompt is used as system prompt."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Test"}]
                )

            call_kwargs = mock_create.call_args.kwargs
            # Check that system prompt contains summarization instructions
            assert "PRIORITY ORDER FOR PRESERVATION" in call_kwargs["system"]
            assert "Summarize the following conversation:" in call_kwargs["system"]

    @pytest.mark.asyncio
    async def test_includes_guidance_in_prompt(self) -> None:
        """Test that guidance is included in system prompt when provided."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Test"}],
                    guidance="the authentication bug",
                )

            call_kwargs = mock_create.call_args.kwargs
            assert "SPECIFIC FOCUS:" in call_kwargs["system"]
            assert "the authentication bug" in call_kwargs["system"]

    @pytest.mark.asyncio
    async def test_raises_on_empty_messages(self) -> None:
        """Test that empty message list raises SummarizationError."""
        with pytest.raises(SummarizationError) as exc_info:
            await haiku_summarize_conversation(messages=[])

        assert "empty conversation" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_on_empty_content(self) -> None:
        """Test that messages with only empty content raises error."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with pytest.raises(SummarizationError) as exc_info:
                await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": ""}]
                )

            assert "no content" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_result(self) -> None:
        """Test that result is stripped of leading/trailing whitespace."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="  Summary with spaces  \n")]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Test"}]
                )

            assert result == "Summary with spaces"

    @pytest.mark.asyncio
    async def test_raises_on_api_key_error(self) -> None:
        """Test that missing API key raises SummarizationError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SummarizationError) as exc_info:
                await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Test"}]
                )

        assert "api_key" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        """Test that timeout raises SummarizationError."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=TimeoutError())
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                with pytest.raises(SummarizationError) as exc_info:
                    await haiku_summarize_conversation(
                        messages=[{"role": "user", "content": "Test"}]
                    )

            assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_uses_adequate_max_tokens(self) -> None:
        """Test that max_tokens is set high enough for summaries."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_summarize_conversation(
                    messages=[{"role": "user", "content": "Test"}]
                )

            call_kwargs = mock_create.call_args.kwargs
            # Should use higher max_tokens for summaries (at least 1024)
            assert call_kwargs["max_tokens"] >= 1024


class TestSummarizationPromptContent:
    """Tests for the content of the summarization prompt."""

    def test_prompt_has_priority_weighting(self) -> None:
        """Test that prompt includes priority weighting as per C7 decision."""
        assert "PRIORITY ORDER FOR PRESERVATION" in SUMMARIZATION_PROMPT
        assert "highest to lowest" in SUMMARIZATION_PROMPT

    def test_prompt_specifies_output_format(self) -> None:
        """Test that prompt specifies Summary of conversation format."""
        assert "Summary of conversation:" in SUMMARIZATION_PROMPT

    def test_prompt_targets_25_percent(self) -> None:
        """Test that prompt targets ~25% compression as per C6 decision."""
        assert "25%" in SUMMARIZATION_PROMPT

    def test_guidance_template_format(self) -> None:
        """Test that guidance template has correct format."""
        assert "SPECIFIC FOCUS:" in GUIDANCE_TEMPLATE
        assert "{guidance}" in GUIDANCE_TEMPLATE


class TestSummarizationWithSampleConversation:
    """Integration-style tests with sample conversation data."""

    @pytest.fixture
    def sample_conversation(self) -> list[dict[str, str]]:
        """Sample conversation for testing."""
        return [
            {
                "role": "user",
                "content": "I'm having trouble with the authentication system. Users "
                "are getting logged out after about 5 minutes.",
            },
            {
                "role": "assistant",
                "content": "That sounds like a session timeout issue. Let me help you "
                "debug this. First, can you tell me what session management "
                "library you're using?",
            },
            {
                "role": "user",
                "content": "We're using express-session with Redis as the store. "
                "The cookie maxAge is set to 24 hours.",
            },
            {
                "role": "assistant",
                "content": "I see. The 5-minute timeout doesn't match your 24-hour "
                "maxAge. This could be caused by Redis TTL settings overriding "
                "the cookie expiration. Can you check your Redis session store "
                "configuration for a 'ttl' option?",
            },
            {
                "role": "user",
                "content": "Found it! The ttl was set to 300 seconds. I'll change it "
                "to match the cookie maxAge.",
            },
        ]

    @pytest.mark.asyncio
    async def test_summarizes_sample_conversation(
        self, sample_conversation: list[dict[str, str]]
    ) -> None:
        """Test that sample conversation is summarized correctly."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(
                    text="Summary of conversation: User debugging session timeout "
                    "issue. Users logged out after 5 minutes despite 24-hour cookie "
                    "maxAge. Root cause: Redis TTL set to 300 seconds. Solution: "
                    "Update Redis TTL to match cookie maxAge."
                )
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await haiku_summarize_conversation(sample_conversation)

            assert result.startswith("Summary of conversation:")
            # The mock response contains key facts
            assert "session timeout" in result.lower()
            assert "redis" in result.lower()

    @pytest.mark.asyncio
    async def test_guidance_focuses_summary(
        self, sample_conversation: list[dict[str, str]]
    ) -> None:
        """Test that guidance focuses the summary on specific aspects."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Summary")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_summarize_conversation(
                    sample_conversation,
                    guidance="Redis configuration",
                )

            call_kwargs = mock_create.call_args.kwargs
            assert "Redis configuration" in call_kwargs["system"]
