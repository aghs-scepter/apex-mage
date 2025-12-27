"""Tests for Discord command decorators."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.clients.discord.decorators import (
    IMAGE_COMMANDS,
    TEXT_COMMANDS,
    _classify_exception,
    _get_command_type,
    _log_usage,
    count_command,
)


class TestCommandClassification:
    """Tests for command type classification."""

    def test_image_commands_contains_expected(self) -> None:
        """Test that IMAGE_COMMANDS contains the expected commands."""
        assert "create_image" in IMAGE_COMMANDS
        assert "modify_image" in IMAGE_COMMANDS
        assert "describe_this" in IMAGE_COMMANDS
        assert "upload_image" in IMAGE_COMMANDS

    def test_text_commands_contains_expected(self) -> None:
        """Test that TEXT_COMMANDS contains the expected commands."""
        assert "prompt" in TEXT_COMMANDS
        assert "summarize" in TEXT_COMMANDS
        assert "clear" in TEXT_COMMANDS
        assert "help" in TEXT_COMMANDS

    def test_get_command_type_image(self) -> None:
        """Test that image commands return 'image' type."""
        assert _get_command_type("create_image") == "image"
        assert _get_command_type("modify_image") == "image"
        assert _get_command_type("describe_this") == "image"

    def test_get_command_type_text(self) -> None:
        """Test that text commands return 'text' type."""
        assert _get_command_type("prompt") == "text"
        assert _get_command_type("summarize") == "text"
        assert _get_command_type("clear") == "text"

    def test_get_command_type_unknown(self) -> None:
        """Test that unknown commands return None."""
        assert _get_command_type("unknown_command") is None
        assert _get_command_type("ban") is None
        assert _get_command_type("whitelist") is None


class TestExceptionClassification:
    """Tests for exception classification."""

    def test_classify_timeout_error(self) -> None:
        """Test that TimeoutError is classified as 'timeout'."""
        assert _classify_exception(TimeoutError("timeout")) == "timeout"

    def test_classify_asyncio_timeout(self) -> None:
        """Test that asyncio.TimeoutError is classified as 'timeout'."""
        assert _classify_exception(TimeoutError()) == "timeout"

    def test_classify_cancelled_error(self) -> None:
        """Test that CancelledError is classified as 'cancelled'."""
        assert _classify_exception(asyncio.CancelledError()) == "cancelled"

    def test_classify_rate_limit_by_message(self) -> None:
        """Test that exceptions with 'rate limit' in message are classified."""
        assert _classify_exception(Exception("Rate limit exceeded")) == "rate_limited"
        assert _classify_exception(ValueError("rate limit hit")) == "rate_limited"

    def test_classify_rate_limit_by_429(self) -> None:
        """Test that 429 errors are classified as rate_limited."""
        assert _classify_exception(Exception("HTTP 429 error")) == "rate_limited"
        assert _classify_exception(Exception("too many requests")) == "rate_limited"

    def test_classify_rate_limit_exceeded_error(self) -> None:
        """Test that RateLimitExceededError is classified correctly."""

        class RateLimitExceededError(Exception):
            pass

        assert _classify_exception(RateLimitExceededError()) == "rate_limited"

    def test_classify_generic_error(self) -> None:
        """Test that generic exceptions are classified as 'error'."""
        assert _classify_exception(ValueError("some error")) == "error"
        assert _classify_exception(RuntimeError("failed")) == "error"
        assert _classify_exception(Exception("unexpected")) == "error"


class TestLogUsage:
    """Tests for the _log_usage function."""

    @pytest.fixture
    def mock_bot(self) -> MagicMock:
        """Create a mock Discord bot."""
        bot = MagicMock()
        bot.repo = AsyncMock()
        bot.repo.is_user_whitelisted = AsyncMock(return_value=True)
        bot.repo.is_user_banned = AsyncMock(return_value=False)
        bot.repo.log_command_usage = AsyncMock()
        return bot

    @pytest.fixture
    def mock_interaction(self, mock_bot: MagicMock) -> MagicMock:
        """Create a mock Discord interaction."""
        interaction = MagicMock()
        interaction.client = mock_bot
        interaction.user = MagicMock()
        interaction.user.id = 123456789
        interaction.user.name = "testuser"
        interaction.guild_id = 987654321
        return interaction

    @pytest.mark.asyncio
    async def test_logs_usage_for_whitelisted_user(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that usage is logged for whitelisted, non-banned users."""
        await _log_usage(mock_interaction, "prompt", "success")

        mock_bot.repo.log_command_usage.assert_called_once_with(
            user_id=123456789,
            username="testuser",
            guild_id=987654321,
            command_name="prompt",
            command_type="text",
            outcome="success",
        )

    @pytest.mark.asyncio
    async def test_skips_logging_for_non_whitelisted_user(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that usage is not logged for non-whitelisted users."""
        mock_bot.repo.is_user_whitelisted.return_value = False

        await _log_usage(mock_interaction, "prompt", "success")

        mock_bot.repo.log_command_usage.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_logging_for_banned_user(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that usage is not logged for banned users."""
        mock_bot.repo.is_user_banned.return_value = True

        await _log_usage(mock_interaction, "prompt", "success")

        mock_bot.repo.log_command_usage.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_logging_for_untracked_command(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that usage is not logged for untracked commands."""
        await _log_usage(mock_interaction, "ban", "success")

        mock_bot.repo.log_command_usage.assert_not_called()
        # Should not even check whitelist for untracked commands
        mock_bot.repo.is_user_whitelisted.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_image_command_type(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that image commands are logged with 'image' type."""
        await _log_usage(mock_interaction, "create_image", "success")

        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["command_type"] == "image"

    @pytest.mark.asyncio
    async def test_logs_various_outcomes(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that various outcomes are logged correctly."""
        outcomes = ["success", "error", "timeout", "cancelled", "rate_limited"]

        for outcome in outcomes:
            mock_bot.repo.log_command_usage.reset_mock()
            await _log_usage(mock_interaction, "prompt", outcome)

            call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
            assert call_kwargs["outcome"] == outcome

    @pytest.mark.asyncio
    async def test_handles_logging_failure_gracefully(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that logging failures don't raise exceptions."""
        mock_bot.repo.log_command_usage.side_effect = Exception("DB error")

        # Should not raise
        await _log_usage(mock_interaction, "prompt", "success")


class TestCountCommandDecorator:
    """Tests for the count_command decorator."""

    @pytest.fixture
    def mock_bot(self) -> MagicMock:
        """Create a mock Discord bot."""
        bot = MagicMock()
        bot.repo = AsyncMock()
        bot.repo.is_user_whitelisted = AsyncMock(return_value=True)
        bot.repo.is_user_banned = AsyncMock(return_value=False)
        bot.repo.log_command_usage = AsyncMock()
        return bot

    @pytest.fixture
    def mock_interaction(self, mock_bot: MagicMock) -> MagicMock:
        """Create a mock Discord interaction."""
        interaction = MagicMock()
        interaction.client = mock_bot
        interaction.user = MagicMock()
        interaction.user.id = 123456789
        interaction.user.name = "testuser"
        interaction.guild_id = 987654321
        interaction.channel_id = 111222333
        return interaction

    @pytest.mark.asyncio
    async def test_successful_command_logs_success(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that successful commands log 'success' outcome."""

        @count_command
        async def prompt(interaction: MagicMock) -> str:
            return "result"

        result = await prompt(mock_interaction)

        assert result == "result"
        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["outcome"] == "success"
        assert call_kwargs["command_name"] == "prompt"

    @pytest.mark.asyncio
    async def test_failed_command_logs_error(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that failed commands log 'error' outcome."""

        @count_command
        async def prompt(interaction: MagicMock) -> str:
            raise ValueError("Something went wrong")

        with pytest.raises(ValueError):
            await prompt(mock_interaction)

        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["outcome"] == "error"

    @pytest.mark.asyncio
    async def test_timeout_command_logs_timeout(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that timed out commands log 'timeout' outcome."""

        @count_command
        async def prompt(interaction: MagicMock) -> str:
            raise TimeoutError("Request timed out")

        with pytest.raises(TimeoutError):
            await prompt(mock_interaction)

        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["outcome"] == "timeout"

    @pytest.mark.asyncio
    async def test_cancelled_command_logs_cancelled(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that cancelled commands log 'cancelled' outcome."""

        @count_command
        async def prompt(interaction: MagicMock) -> str:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await prompt(mock_interaction)

        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["outcome"] == "cancelled"

    @pytest.mark.asyncio
    async def test_rate_limited_command_logs_rate_limited(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that rate limited commands log 'rate_limited' outcome."""

        class RateLimitError(RuntimeError):
            """Custom rate limit error for testing."""

            pass

        @count_command
        async def prompt(interaction: MagicMock) -> str:
            raise RateLimitError("Rate limit exceeded")

        with pytest.raises(RateLimitError):
            await prompt(mock_interaction)

        mock_bot.repo.log_command_usage.assert_called_once()
        call_kwargs = mock_bot.repo.log_command_usage.call_args.kwargs
        assert call_kwargs["outcome"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self) -> None:
        """Test that the decorator preserves function metadata."""

        @count_command
        async def my_command(interaction: MagicMock) -> str:
            """My docstring."""
            return "test"

        assert my_command.__name__ == "my_command"
        assert my_command.__doc__ == "My docstring."

    @pytest.mark.asyncio
    async def test_untracked_command_does_not_log(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that untracked commands don't log usage."""

        @count_command
        async def ban(interaction: MagicMock) -> str:
            return "banned"

        await ban(mock_interaction)

        # Untracked command - should not log
        mock_bot.repo.log_command_usage.assert_not_called()
