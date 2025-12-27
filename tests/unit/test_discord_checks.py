"""Tests for Discord global checks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.checks import BanCheckCommandTree, register_global_checks


class TestBanCheckCommandTree:
    """Tests for the BanCheckCommandTree functionality."""

    @pytest.fixture
    def mock_bot(self) -> MagicMock:
        """Create a mock Discord bot."""
        bot = MagicMock()
        bot.repo = AsyncMock()
        # Clear any existing tree reference so we can create a new one
        bot._connection = MagicMock()
        bot._connection._command_tree = None
        return bot

    @pytest.fixture
    def mock_interaction(self, mock_bot: MagicMock) -> MagicMock:
        """Create a mock Discord interaction."""
        interaction = MagicMock()
        interaction.client = mock_bot
        interaction.user = MagicMock()
        interaction.user.name = "testuser"
        interaction.user.id = 123456789
        interaction.command = MagicMock()
        interaction.command.name = "test_command"
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        return interaction

    @pytest.fixture
    def command_tree(self, mock_bot: MagicMock) -> BanCheckCommandTree:
        """Create a BanCheckCommandTree with a mock bot."""
        with patch.object(BanCheckCommandTree, '__init__', lambda self, client: None):
            tree = object.__new__(BanCheckCommandTree)
            return tree

    def test_register_global_checks_is_noop(self, mock_bot: MagicMock) -> None:
        """Test that register_global_checks is a no-op (kept for backwards compatibility)."""
        # Should not raise any errors
        register_global_checks(mock_bot)

    # Whitelist tests

    @pytest.mark.asyncio
    async def test_non_whitelisted_user_is_denied(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that non-whitelisted users are denied access."""
        mock_bot.repo.is_user_whitelisted.return_value = False

        result = await command_tree.interaction_check(mock_interaction)

        # Should return False (deny access)
        assert result is False
        mock_bot.repo.is_user_whitelisted.assert_called_once_with(123456789)
        # Should NOT check ban status for non-whitelisted users
        mock_bot.repo.is_user_banned.assert_not_called()
        # Should send access denied message
        mock_interaction.response.send_message.assert_called_once_with(
            "Access denied. Contact @aghs",
            ephemeral=False,
        )

    @pytest.mark.asyncio
    async def test_whitelisted_non_banned_user_is_allowed(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that whitelisted, non-banned users are allowed to use commands."""
        mock_bot.repo.is_user_whitelisted.return_value = True
        mock_bot.repo.is_user_banned.return_value = False

        result = await command_tree.interaction_check(mock_interaction)

        # Should return True (allow command)
        assert result is True
        mock_bot.repo.is_user_whitelisted.assert_called_once_with(123456789)
        mock_bot.repo.is_user_banned.assert_called_once_with(123456789)
        mock_interaction.response.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitelisted_banned_user_is_blocked(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that whitelisted but banned users are blocked (ban takes precedence)."""
        mock_bot.repo.is_user_whitelisted.return_value = True
        mock_bot.repo.is_user_banned.return_value = True
        mock_bot.repo.get_ban_reason.return_value = "Spamming"

        result = await command_tree.interaction_check(mock_interaction)

        # Should return False (block command)
        assert result is False
        mock_bot.repo.is_user_whitelisted.assert_called_once_with(123456789)
        mock_bot.repo.is_user_banned.assert_called_once_with(123456789)
        mock_bot.repo.get_ban_reason.assert_called_once_with(123456789)

        # Should send a visible (not ephemeral) message with ban reason
        mock_interaction.response.send_message.assert_called_once_with(
            "You are banned from using this bot. Reason: Spamming",
            ephemeral=False,
        )

    @pytest.mark.asyncio
    async def test_ban_check_handles_no_reason(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that banned users without a reason get a default message."""
        mock_bot.repo.is_user_whitelisted.return_value = True
        mock_bot.repo.is_user_banned.return_value = True
        mock_bot.repo.get_ban_reason.return_value = None  # No reason provided

        result = await command_tree.interaction_check(mock_interaction)

        # Should return False (block command)
        assert result is False

        # Should send a message with default reason text
        mock_interaction.response.send_message.assert_called_once_with(
            "You are banned from using this bot. Reason: No reason provided",
            ephemeral=False,
        )

    @pytest.mark.asyncio
    async def test_whitelist_check_uses_user_id(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that the whitelist check uses the user's ID (not username)."""
        mock_bot.repo.is_user_whitelisted.return_value = True
        mock_bot.repo.is_user_banned.return_value = False

        # Set a different display_name vs username
        mock_interaction.user.name = "actual_username"
        mock_interaction.user.display_name = "Fancy Display Name"
        mock_interaction.user.id = 987654321

        await command_tree.interaction_check(mock_interaction)

        # Should use .id, not .name
        mock_bot.repo.is_user_whitelisted.assert_called_once_with(987654321)
        mock_bot.repo.is_user_banned.assert_called_once_with(987654321)

    # Exempt commands tests

    @pytest.mark.asyncio
    async def test_exempt_command_bypasses_whitelist_check(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that exempt commands (like my_status) bypass whitelist/ban checks."""
        # Set up as non-whitelisted user
        mock_bot.repo.is_user_whitelisted.return_value = False

        # Use an exempt command
        mock_interaction.command.name = "my_status"

        result = await command_tree.interaction_check(mock_interaction)

        # Should return True (allow command) without checking whitelist
        assert result is True
        mock_bot.repo.is_user_whitelisted.assert_not_called()
        mock_bot.repo.is_user_banned.assert_not_called()
        mock_interaction.response.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_exempt_command_bypasses_ban_check(
        self, mock_bot: MagicMock, mock_interaction: MagicMock, command_tree: BanCheckCommandTree
    ) -> None:
        """Test that banned users can still use exempt commands."""
        # Set up as banned user
        mock_bot.repo.is_user_whitelisted.return_value = True
        mock_bot.repo.is_user_banned.return_value = True

        # Use an exempt command
        mock_interaction.command.name = "my_status"

        result = await command_tree.interaction_check(mock_interaction)

        # Should return True (allow command) without checking whitelist/ban
        assert result is True
        mock_bot.repo.is_user_whitelisted.assert_not_called()
        mock_bot.repo.is_user_banned.assert_not_called()

    def test_exempt_commands_includes_my_status(self) -> None:
        """Test that EXEMPT_COMMANDS contains expected commands."""
        assert "my_status" in BanCheckCommandTree.EXEMPT_COMMANDS
