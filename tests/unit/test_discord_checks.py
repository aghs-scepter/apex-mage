"""Tests for Discord global checks."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGlobalBanCheck:
    """Tests for the global ban check functionality."""

    @pytest.fixture
    def mock_bot(self) -> MagicMock:
        """Create a mock Discord bot."""
        bot = MagicMock()
        bot.tree = MagicMock()
        bot.tree.interaction_check = MagicMock()
        bot.repo = AsyncMock()
        return bot

    @pytest.fixture
    def mock_interaction(self) -> MagicMock:
        """Create a mock Discord interaction."""
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.name = "testuser"
        interaction.user.id = 123456789
        interaction.command = MagicMock()
        interaction.command.name = "test_command"
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        return interaction

    def test_register_global_checks_decorates_tree(
        self, mock_bot: MagicMock
    ) -> None:
        """Test that register_global_checks sets up the interaction_check decorator."""
        from src.clients.discord.checks import register_global_checks

        register_global_checks(mock_bot)

        # The interaction_check decorator should have been called
        mock_bot.tree.interaction_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_ban_check_allows_non_banned_user(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that non-banned users are allowed to use commands."""
        from src.clients.discord.checks import register_global_checks

        # Set up the mock to capture the check function
        captured_check = None

        def capture_decorator(func: object) -> object:
            nonlocal captured_check
            captured_check = func
            return func

        mock_bot.tree.interaction_check = capture_decorator
        mock_bot.repo.is_user_banned.return_value = False

        # Register checks to capture the function
        register_global_checks(mock_bot)

        # Run the captured check
        assert captured_check is not None
        result = await captured_check(mock_interaction)

        # Should return True (allow command)
        assert result is True
        mock_bot.repo.is_user_banned.assert_called_once_with("testuser")
        mock_interaction.response.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_ban_check_blocks_banned_user(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that banned users are blocked from using commands."""
        from src.clients.discord.checks import register_global_checks

        # Set up the mock to capture the check function
        captured_check = None

        def capture_decorator(func: object) -> object:
            nonlocal captured_check
            captured_check = func
            return func

        mock_bot.tree.interaction_check = capture_decorator
        mock_bot.repo.is_user_banned.return_value = True
        mock_bot.repo.get_ban_reason.return_value = "Spamming"

        # Register checks to capture the function
        register_global_checks(mock_bot)

        # Run the captured check
        assert captured_check is not None
        result = await captured_check(mock_interaction)

        # Should return False (block command)
        assert result is False
        mock_bot.repo.is_user_banned.assert_called_once_with("testuser")
        mock_bot.repo.get_ban_reason.assert_called_once_with("testuser")

        # Should send a visible (not ephemeral) message
        mock_interaction.response.send_message.assert_called_once_with(
            "You are banned from using this bot. Reason: Spamming",
            ephemeral=False,
        )

    @pytest.mark.asyncio
    async def test_ban_check_handles_no_reason(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that banned users without a reason get a default message."""
        from src.clients.discord.checks import register_global_checks

        # Set up the mock to capture the check function
        captured_check = None

        def capture_decorator(func: object) -> object:
            nonlocal captured_check
            captured_check = func
            return func

        mock_bot.tree.interaction_check = capture_decorator
        mock_bot.repo.is_user_banned.return_value = True
        mock_bot.repo.get_ban_reason.return_value = None  # No reason provided

        # Register checks to capture the function
        register_global_checks(mock_bot)

        # Run the captured check
        assert captured_check is not None
        result = await captured_check(mock_interaction)

        # Should return False (block command)
        assert result is False

        # Should send a message with default reason text
        mock_interaction.response.send_message.assert_called_once_with(
            "You are banned from using this bot. Reason: No reason provided",
            ephemeral=False,
        )

    @pytest.mark.asyncio
    async def test_ban_check_uses_username_not_display_name(
        self, mock_bot: MagicMock, mock_interaction: MagicMock
    ) -> None:
        """Test that the check uses the user's username (not display name)."""
        from src.clients.discord.checks import register_global_checks

        # Set up the mock to capture the check function
        captured_check = None

        def capture_decorator(func: object) -> object:
            nonlocal captured_check
            captured_check = func
            return func

        mock_bot.tree.interaction_check = capture_decorator
        mock_bot.repo.is_user_banned.return_value = False

        # Set a different display_name vs username
        mock_interaction.user.name = "actual_username"
        mock_interaction.user.display_name = "Fancy Display Name"

        # Register checks to capture the function
        register_global_checks(mock_bot)

        # Run the captured check
        assert captured_check is not None
        await captured_check(mock_interaction)

        # Should use .name, not .display_name
        mock_bot.repo.is_user_banned.assert_called_once_with("actual_username")
