"""Unit tests for Discord chat commands (chat.py).

These tests verify the behavior of chat-related slash commands including:
- /help command
- /prompt command
- /clear command
- /set_behavior custom and preset commands
- /behavior_preset CRUD commands
- /summarize command
- /ban_user and /unban_user commands
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.commands.chat import (
    BehaviorPresetGroup,
    SetBehaviorGroup,
    register_chat_commands,
)

# --- Test Fixtures ---


def create_mock_user(
    user_id: int = 12345,
    name: str = "TestUser",
    display_name: str = "TestUser",
    is_admin: bool = False,
) -> MagicMock:
    """Create a mock Discord user."""
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.display_name = display_name
    user.avatar = "https://example.com/avatar.png"
    if is_admin:
        user.guild_permissions = MagicMock()
        user.guild_permissions.administrator = True
    else:
        # Explicitly remove guild_permissions so hasattr returns False
        del user.guild_permissions
    return user


def create_mock_interaction(
    user: MagicMock | None = None,
    channel_id: int = 99999,
    guild_id: int | None = 88888,
    message: MagicMock | None = None,
) -> MagicMock:
    """Create a mock Discord interaction."""
    if user is None:
        user = create_mock_user()

    interaction = MagicMock()
    interaction.user = user
    interaction.channel_id = channel_id
    interaction.guild_id = guild_id
    interaction.message = message or MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def create_mock_bot() -> MagicMock:
    """Create a mock Discord bot with required dependencies."""
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.tree.command = MagicMock(return_value=lambda f: f)
    bot.tree.add_command = MagicMock()

    # Mock repository
    bot.repo = AsyncMock()
    bot.repo.create_channel = AsyncMock()
    bot.repo.add_message = AsyncMock()
    bot.repo.add_message_with_images = AsyncMock()
    bot.repo.get_visible_messages = AsyncMock(return_value=[])
    bot.repo.clear_messages = AsyncMock()
    bot.repo.deactivate_old_messages = AsyncMock()
    bot.repo.is_user_banned = AsyncMock(return_value=False)
    bot.repo.add_ban = AsyncMock()
    bot.repo.remove_ban = AsyncMock()
    bot.repo.get_ban_reason = AsyncMock(return_value=None)
    bot.repo.is_user_whitelisted = AsyncMock(return_value=False)
    bot.repo.add_to_whitelist = AsyncMock()
    bot.repo.remove_from_whitelist = AsyncMock()
    bot.repo.list_whitelist = AsyncMock(return_value=[])
    bot.repo.list_presets = AsyncMock(return_value=[])
    bot.repo.get_preset = AsyncMock(return_value=None)
    bot.repo.create_preset = AsyncMock()
    bot.repo.update_preset = AsyncMock()
    bot.repo.delete_preset = AsyncMock()
    bot.repo.count_presets = AsyncMock(return_value=0)

    # Mock AI provider
    bot.ai_provider = AsyncMock()
    bot.ai_provider.chat = AsyncMock(
        return_value=MagicMock(content="Mock AI response")
    )

    # Mock rate limiter
    bot.rate_limiter = AsyncMock()
    bot.rate_limiter.check = AsyncMock(
        return_value=MagicMock(allowed=True, wait_seconds=0)
    )
    bot.rate_limiter.record = AsyncMock()

    # Mock GCS adapter
    bot.gcs_adapter = MagicMock()
    bot.gcs_adapter.upload_text = MagicMock(return_value="https://storage.example.com/text")

    return bot


def get_command_callback(group: Any, command_name: str) -> Any:
    """Get the callback function from a command in a group.

    Args:
        group: The command group instance.
        command_name: The name of the command method.

    Returns:
        The underlying callback function.
    """
    cmd = getattr(group, command_name)
    # discord.py app_commands wraps the function in a Command object
    if hasattr(cmd, "callback"):
        return cmd.callback
    if hasattr(cmd, "_callback"):
        return cmd._callback
    return cmd


# --- SetBehaviorGroup Tests ---


class TestSetBehaviorGroup:
    """Tests for /set_behavior command group."""

    @pytest.fixture
    def group(self) -> SetBehaviorGroup:
        """Create a SetBehaviorGroup with mock bot."""
        bot = create_mock_bot()
        return SetBehaviorGroup(bot)

    @pytest.mark.asyncio
    async def test_custom_sets_behavior_prompt(self, group: SetBehaviorGroup) -> None:
        """Test that /set_behavior custom stores the behavior prompt."""
        interaction = create_mock_interaction()
        prompt = "You are a helpful pirate assistant"

        callback = get_command_callback(group, "custom")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(group, interaction, prompt)

            # Verify channel was created
            group.bot.repo.create_channel.assert_called_once_with(
                interaction.channel_id
            )

            # Verify behavior message was added
            group.bot.repo.add_message.assert_any_call(
                interaction.channel_id,
                "Anthropic",
                "behavior",
                False,
                prompt,
            )

    @pytest.mark.asyncio
    async def test_custom_handles_timeout(self, group: SetBehaviorGroup) -> None:
        """Test that /set_behavior custom handles timeout gracefully."""
        interaction = create_mock_interaction()
        prompt = "Test prompt"

        callback = get_command_callback(group, "custom")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            # Use a very short timeout to trigger timeout error
            with patch("asyncio.timeout", side_effect=TimeoutError()):
                await callback(group, interaction, prompt, timeout=0.001)

            # Verify error view was shown
            mock_view_class.assert_called()
            call_kwargs = mock_view_class.call_args.kwargs
            assert call_kwargs["is_error"] is True
            assert "timed out" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_preset_shows_no_presets_message_when_empty(
        self, group: SetBehaviorGroup
    ) -> None:
        """Test that /set_behavior preset shows message when no presets exist."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = []

        callback = get_command_callback(group, "preset")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(group, interaction)

            mock_view_class.assert_called()
            call_kwargs = mock_view_class.call_args.kwargs
            assert "No Presets Available" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_preset_shows_selection_when_presets_exist(
        self, group: SetBehaviorGroup
    ) -> None:
        """Test that /set_behavior preset shows PresetSelectView with presets."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = [
            {"name": "Pirate", "description": "Talk like a pirate", "created_by": "TestUser"}
        ]

        callback = get_command_callback(group, "preset")

        with patch(
            "src.clients.discord.commands.chat.PresetSelectView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(group, interaction)

            mock_view_class.assert_called()


# --- BehaviorPresetGroup Tests ---


class TestBehaviorPresetGroup:
    """Tests for /behavior_preset command group."""

    @pytest.fixture
    def group(self) -> BehaviorPresetGroup:
        """Create a BehaviorPresetGroup with mock bot."""
        bot = create_mock_bot()
        return BehaviorPresetGroup(bot)

    @pytest.mark.asyncio
    async def test_create_requires_guild(self, group: BehaviorPresetGroup) -> None:
        """Test that /behavior_preset create requires guild context."""
        interaction = create_mock_interaction(guild_id=None)

        callback = get_command_callback(group, "create")
        await callback(
            group,
            interaction,
            name="TestPreset",
            description="A test preset",
            prompt="You are helpful",
        )

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "server" in call_args.args[0].lower()
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_create_enforces_preset_limit(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset create enforces max preset limit."""
        interaction = create_mock_interaction()
        group.bot.repo.count_presets.return_value = 15  # At limit

        callback = get_command_callback(group, "create")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(
                group,
                interaction,
                name="NewPreset",
                description="Desc",
                prompt="Prompt",
            )

            call_kwargs = mock_view_class.call_args.kwargs
            assert "Limit Reached" in call_kwargs["title"]
            assert call_kwargs["is_error"] is True

    @pytest.mark.asyncio
    async def test_create_handles_duplicate_name(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset create handles duplicate name error."""
        interaction = create_mock_interaction()
        group.bot.repo.create_preset.side_effect = sqlite3.IntegrityError()

        callback = get_command_callback(group, "create")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(
                group,
                interaction,
                name="ExistingPreset",
                description="Desc",
                prompt="Prompt",
            )

            call_kwargs = mock_view_class.call_args.kwargs
            assert "Duplicate" in call_kwargs["title"]
            assert call_kwargs["is_error"] is True

    @pytest.mark.asyncio
    async def test_create_success(self, group: BehaviorPresetGroup) -> None:
        """Test successful preset creation."""
        interaction = create_mock_interaction()

        callback = get_command_callback(group, "create")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(
                group,
                interaction,
                name="NewPreset",
                description="A new preset",
                prompt="You are a friendly assistant",
            )

            group.bot.repo.create_preset.assert_called_once()
            call_kwargs = mock_view_class.call_args.kwargs
            assert "Created" in call_kwargs["title"]
            assert call_kwargs["is_error"] is False

    @pytest.mark.asyncio
    async def test_edit_requires_permission(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset edit requires appropriate permission."""
        # User who is not owner, creator, or admin
        user = create_mock_user(name="RandomUser", is_admin=False)
        interaction = create_mock_interaction(user=user)

        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "created_by": "OriginalCreator",
            "description": "Desc",
            "prompt_text": "Prompt",
        }

        callback = get_command_callback(group, "edit")
        await callback(
            group,
            interaction,
            name="TestPreset",
            description="New description",
        )

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "permission" in call_args.args[0].lower()
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_edit_allows_creator(self, group: BehaviorPresetGroup) -> None:
        """Test that preset creator can edit their preset."""
        user = create_mock_user(name="OriginalCreator")
        interaction = create_mock_interaction(user=user)

        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "created_by": "OriginalCreator",
            "description": "Desc",
            "prompt_text": "Prompt",
        }

        callback = get_command_callback(group, "edit")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(
                group,
                interaction,
                name="TestPreset",
                description="Updated description",
            )

            group.bot.repo.update_preset.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_allows_admin(self, group: BehaviorPresetGroup) -> None:
        """Test that server admin can edit any preset."""
        user = create_mock_user(name="AdminUser", is_admin=True)
        interaction = create_mock_interaction(user=user)

        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "created_by": "SomeoneElse",
            "description": "Desc",
            "prompt_text": "Prompt",
        }

        callback = get_command_callback(group, "edit")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(
                group,
                interaction,
                name="TestPreset",
                description="Admin update",
            )

            group.bot.repo.update_preset.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_requires_permission(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset delete requires permission."""
        user = create_mock_user(name="RandomUser", is_admin=False)
        interaction = create_mock_interaction(user=user)

        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "created_by": "OriginalCreator",
        }

        callback = get_command_callback(group, "delete")
        await callback(group, interaction, name="TestPreset")

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "permission" in call_args.args[0].lower()
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, group: BehaviorPresetGroup) -> None:
        """Test that /behavior_preset delete handles non-existent preset."""
        interaction = create_mock_interaction()
        group.bot.repo.get_preset.return_value = None

        callback = get_command_callback(group, "delete")
        await callback(group, interaction, name="NonExistent")

        interaction.response.send_message.assert_called_once()
        assert "not found" in interaction.response.send_message.call_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_list_shows_empty_message(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset list shows message when empty."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = []

        callback = get_command_callback(group, "list_presets")

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await callback(group, interaction)

            call_kwargs = mock_view_class.call_args.kwargs
            assert "No behavior presets found" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_list_shows_presets(self, group: BehaviorPresetGroup) -> None:
        """Test that /behavior_preset list shows all presets."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = [
            {"name": "Pirate", "description": "Talks like a pirate", "created_by": "User1"},
            {"name": "Formal", "description": "Very formal tone", "created_by": "User2"},
        ]

        callback = get_command_callback(group, "list_presets")
        await callback(group, interaction)

        interaction.followup.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_view_shows_preset_details(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that /behavior_preset view shows full preset details."""
        interaction = create_mock_interaction()
        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "description": "A test preset",
            "prompt_text": "You are a helpful assistant",
            "created_by": "TestUser",
            "created_at": "2024-01-01 12:00:00",
        }

        callback = get_command_callback(group, "view")
        await callback(group, interaction, name="TestPreset")

        interaction.followup.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_view_not_found(self, group: BehaviorPresetGroup) -> None:
        """Test that /behavior_preset view handles non-existent preset."""
        interaction = create_mock_interaction()
        group.bot.repo.get_preset.return_value = None

        callback = get_command_callback(group, "view")
        await callback(group, interaction, name="NonExistent")

        interaction.response.send_message.assert_called_once()
        assert "not found" in interaction.response.send_message.call_args.args[0].lower()


# --- Command Registration Tests ---


class TestRegisterChatCommands:
    """Tests for register_chat_commands function."""

    def test_registers_command_groups(self) -> None:
        """Test that command groups are registered with the bot."""
        bot = create_mock_bot()

        register_chat_commands(bot)

        # Should add SetBehaviorGroup and BehaviorPresetGroup
        assert bot.tree.add_command.call_count == 2

    def test_registers_help_command(self) -> None:
        """Test that /help command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_chat_commands(bot)

        assert "help" in registered_commands

    def test_registers_prompt_command(self) -> None:
        """Test that /prompt command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_chat_commands(bot)

        assert "prompt" in registered_commands

    def test_registers_clear_command(self) -> None:
        """Test that /clear command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_chat_commands(bot)

        assert "clear" in registered_commands

    def test_registers_summarize_command(self) -> None:
        """Test that /summarize command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_chat_commands(bot)

        assert "summarize" in registered_commands


# --- Input Validation Tests ---


class TestInputValidation:
    """Tests for input validation in chat commands."""

    @pytest.fixture
    def group(self) -> BehaviorPresetGroup:
        """Create a BehaviorPresetGroup with mock bot."""
        bot = create_mock_bot()
        return BehaviorPresetGroup(bot)

    @pytest.mark.asyncio
    async def test_edit_requires_at_least_one_field(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that edit requires either description or prompt."""
        user = create_mock_user(name="OriginalCreator")
        interaction = create_mock_interaction(user=user)

        group.bot.repo.get_preset.return_value = {
            "name": "TestPreset",
            "created_by": "OriginalCreator",
        }

        callback = get_command_callback(group, "edit")
        await callback(
            group,
            interaction,
            name="TestPreset",
            description=None,
            prompt=None,
        )

        interaction.response.send_message.assert_called_once()
        assert "at least one field" in interaction.response.send_message.call_args.args[0].lower()


# --- Prompt Command Tests ---


class TestPromptCommand:
    """Tests for /prompt command."""

    @pytest.fixture
    def prompt_func(self) -> tuple:
        """Get the prompt command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("prompt"), bot

    @pytest.mark.asyncio
    async def test_prompt_defers_response(self, prompt_func: tuple) -> None:
        """Test that prompt command defers response first."""
        func, _bot = prompt_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction, prompt="Hello")

            interaction.response.defer.assert_called_once()


# --- Clear Command Tests ---


class TestClearCommand:
    """Tests for /clear command."""

    @pytest.fixture
    def clear_func(self) -> tuple:
        """Get the clear command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("clear"), bot

    @pytest.mark.asyncio
    async def test_clear_shows_confirmation_view(self, clear_func: tuple) -> None:
        """Test that clear command shows confirmation view."""
        func, _bot = clear_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.ClearHistoryConfirmationView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction)

            mock_view_class.assert_called_once()
            call_kwargs = mock_view_class.call_args.kwargs
            assert "on_select" in call_kwargs


# --- Help Command Tests ---


class TestHelpCommand:
    """Tests for /help command."""

    @pytest.fixture
    def help_func(self) -> tuple:
        """Get the help command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("help"), bot

    @pytest.mark.asyncio
    async def test_help_shows_info_view(self, help_func: tuple) -> None:
        """Test that help command shows info view with help text."""
        func, _bot = help_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction)

            mock_view_class.assert_called_once()
            call_kwargs = mock_view_class.call_args.kwargs
            assert call_kwargs["title"] == "/help"
            assert "/prompt" in call_kwargs["description"]
            assert "/create_image" in call_kwargs["description"]


# --- Ban Command Tests ---


class TestBanCommands:
    """Tests for /ban_user and /unban_user commands."""

    @pytest.fixture
    def ban_funcs(self) -> tuple:
        """Get the ban command functions."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(description=None, **kwargs):
            def decorator(func):
                commands[func.__name__] = func
                return func
            return decorator

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("ban_user"), commands.get("unban_user"), bot

    @pytest.mark.asyncio
    async def test_ban_user_requires_owner(self, ban_funcs: tuple) -> None:
        """Test that /ban_user requires bot owner (aghs)."""
        ban_func, _unban_func, _bot = ban_funcs
        invoker = create_mock_user(name="NotAghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="someuser", user_id=999)

        await ban_func(interaction, user=target_user, reason="spam")

        interaction.response.send_message.assert_called_once()
        assert "aghs" in interaction.response.send_message.call_args.args[0].lower()
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_ban_user_succeeds_for_owner(self, ban_funcs: tuple) -> None:
        """Test that /ban_user works for bot owner."""
        ban_func, _unban_func, bot = ban_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="spammer", user_id=999)

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await ban_func(interaction, user=target_user, reason="spam")

            bot.repo.add_ban.assert_called_once_with(999, "spammer", "spam", "aghs")

    @pytest.mark.asyncio
    async def test_unban_user_requires_owner(self, ban_funcs: tuple) -> None:
        """Test that /unban_user requires bot owner (aghs)."""
        _ban_func, unban_func, _bot = ban_funcs
        invoker = create_mock_user(name="NotAghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="someuser", user_id=999)

        await unban_func(interaction, user=target_user)

        interaction.response.send_message.assert_called_once()
        assert "aghs" in interaction.response.send_message.call_args.args[0].lower()


# --- Summarize Command Tests ---


class TestSummarizeCommand:
    """Tests for /summarize command."""

    @pytest.fixture
    def summarize_func(self) -> tuple:
        """Get the summarize command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, description=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("summarize"), bot

    @pytest.mark.asyncio
    async def test_summarize_handles_empty_context(
        self, summarize_func: tuple
    ) -> None:
        """Test that summarize shows message when nothing to summarize."""
        func, bot = summarize_func
        interaction = create_mock_interaction()

        # Empty context - nothing to summarize
        bot.repo.get_visible_messages.return_value = []

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction)

            mock_view_class.assert_called()
            call_kwargs = mock_view_class.call_args.kwargs
            assert "Nothing to Summarize" in call_kwargs["title"]


# --- Autocomplete Tests ---


class TestAutocomplete:
    """Tests for autocomplete handlers."""

    @pytest.fixture
    def group(self) -> BehaviorPresetGroup:
        """Create a BehaviorPresetGroup with mock bot."""
        bot = create_mock_bot()
        return BehaviorPresetGroup(bot)

    @pytest.mark.asyncio
    async def test_preset_name_autocomplete_filters_by_input(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that autocomplete filters presets by input."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = [
            {"name": "Pirate"},
            {"name": "Formal"},
            {"name": "Playful"},
        ]

        results = await group._preset_name_autocomplete(interaction, "P")

        # Should return Pirate and Playful (case-insensitive match)
        names = [r.name for r in results]
        assert "Pirate" in names
        assert "Playful" in names
        assert "Formal" not in names

    @pytest.mark.asyncio
    async def test_preset_name_autocomplete_limits_to_25(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that autocomplete limits results to 25."""
        interaction = create_mock_interaction()
        group.bot.repo.list_presets.return_value = [
            {"name": f"Preset{i}"} for i in range(30)
        ]

        results = await group._preset_name_autocomplete(interaction, "")

        assert len(results) <= 25

    @pytest.mark.asyncio
    async def test_preset_name_autocomplete_handles_no_guild(
        self, group: BehaviorPresetGroup
    ) -> None:
        """Test that autocomplete returns empty for non-guild context."""
        interaction = create_mock_interaction(guild_id=None)

        results = await group._preset_name_autocomplete(interaction, "")

        assert results == []


# --- Whitelist Command Tests ---


class TestWhitelistCommands:
    """Tests for /whitelist_add, /whitelist_remove, and /whitelist_list commands."""

    @pytest.fixture
    def whitelist_funcs(self) -> tuple:
        """Get the whitelist command functions."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, description=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return (
            commands.get("whitelist_add"),
            commands.get("whitelist_remove"),
            commands.get("whitelist_list"),
            bot,
        )

    @pytest.mark.asyncio
    async def test_whitelist_add_requires_owner(self, whitelist_funcs: tuple) -> None:
        """Test that /whitelist_add requires bot owner (aghs)."""
        add_func, _remove_func, _list_func, _bot = whitelist_funcs
        invoker = create_mock_user(name="NotAghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="someuser", user_id=999)

        await add_func(interaction, user=target_user, notes=None)

        interaction.response.send_message.assert_called_once()
        assert "aghs" in interaction.response.send_message.call_args.args[0].lower()
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_whitelist_add_succeeds_for_owner(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_add works for bot owner."""
        add_func, _remove_func, _list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="newuser", user_id=999)

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await add_func(interaction, user=target_user, notes="Test notes")

            bot.repo.add_to_whitelist.assert_called_once_with(
                999, "newuser", "aghs", "Test notes"
            )

    @pytest.mark.asyncio
    async def test_whitelist_add_already_whitelisted(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_add handles already whitelisted user."""
        add_func, _remove_func, _list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="existinguser", user_id=999)

        bot.repo.is_user_whitelisted.return_value = True

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await add_func(interaction, user=target_user, notes=None)

            # Should not call add_to_whitelist
            bot.repo.add_to_whitelist.assert_not_called()
            # Should show already whitelisted message
            call_kwargs = mock_view_class.call_args.kwargs
            assert "already whitelisted" in call_kwargs["description"].lower()

    @pytest.mark.asyncio
    async def test_whitelist_remove_requires_owner(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_remove requires bot owner (aghs)."""
        _add_func, remove_func, _list_func, _bot = whitelist_funcs
        invoker = create_mock_user(name="NotAghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="someuser", user_id=999)

        await remove_func(interaction, user=target_user)

        interaction.response.send_message.assert_called_once()
        assert "aghs" in interaction.response.send_message.call_args.args[0].lower()
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_whitelist_remove_succeeds_for_owner(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_remove works for bot owner."""
        _add_func, remove_func, _list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="existinguser", user_id=999)

        bot.repo.is_user_whitelisted.return_value = True

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await remove_func(interaction, user=target_user)

            bot.repo.remove_from_whitelist.assert_called_once_with(999)

    @pytest.mark.asyncio
    async def test_whitelist_remove_not_whitelisted(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_remove handles non-whitelisted user."""
        _add_func, remove_func, _list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)
        target_user = create_mock_user(name="unknownuser", user_id=999)

        bot.repo.is_user_whitelisted.return_value = False

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await remove_func(interaction, user=target_user)

            # Should not call remove_from_whitelist
            bot.repo.remove_from_whitelist.assert_not_called()
            # Should show not whitelisted message
            call_kwargs = mock_view_class.call_args.kwargs
            assert "not currently whitelisted" in call_kwargs["description"].lower()

    @pytest.mark.asyncio
    async def test_whitelist_list_requires_owner(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_list requires bot owner (aghs)."""
        _add_func, _remove_func, list_func, _bot = whitelist_funcs
        invoker = create_mock_user(name="NotAghs")
        interaction = create_mock_interaction(user=invoker)

        await list_func(interaction)

        interaction.response.send_message.assert_called_once()
        assert "aghs" in interaction.response.send_message.call_args.args[0].lower()
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_whitelist_list_shows_empty_message(
        self, whitelist_funcs: tuple
    ) -> None:
        """Test that /whitelist_list shows message when whitelist is empty."""
        _add_func, _remove_func, list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)

        bot.repo.list_whitelist.return_value = []

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await list_func(interaction)

            call_kwargs = mock_view_class.call_args.kwargs
            assert "no users" in call_kwargs["description"].lower()

    @pytest.mark.asyncio
    async def test_whitelist_list_shows_users(self, whitelist_funcs: tuple) -> None:
        """Test that /whitelist_list shows whitelisted users."""
        _add_func, _remove_func, list_func, bot = whitelist_funcs
        invoker = create_mock_user(name="aghs")
        interaction = create_mock_interaction(user=invoker)

        bot.repo.list_whitelist.return_value = [
            {
                "user_id": 123,
                "username": "User1",
                "added_by": "aghs",
                "added_at": "2024-01-01 12:00:00",
                "notes": "Test note",
            },
            {
                "user_id": 456,
                "username": "User2",
                "added_by": "aghs",
                "added_at": "2024-01-02 12:00:00",
                "notes": None,
            },
        ]

        await list_func(interaction)

        interaction.followup.send.assert_called_once()
        # Check that an embed was sent
        call_kwargs = interaction.followup.send.call_args.kwargs
        assert "embed" in call_kwargs


# --- My Status Command Tests ---


class TestMyStatusCommand:
    """Tests for /my_status command."""

    @pytest.fixture
    def my_status_func(self) -> tuple:
        """Get the my_status command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, description=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("my_status"), bot

    @pytest.mark.asyncio
    async def test_my_status_shows_banned_with_reason(
        self, my_status_func: tuple
    ) -> None:
        """Test that /my_status shows banned status with reason."""
        func, bot = my_status_func
        user = create_mock_user(user_id=123)
        interaction = create_mock_interaction(user=user)

        bot.repo.is_user_banned.return_value = True
        bot.repo.get_ban_reason.return_value = "Spamming"

        await func(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "Banned" in call_args.args[0]
        assert "Spamming" in call_args.args[0]
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_my_status_shows_banned_no_reason(
        self, my_status_func: tuple
    ) -> None:
        """Test that /my_status shows banned status with default reason."""
        func, bot = my_status_func
        user = create_mock_user(user_id=123)
        interaction = create_mock_interaction(user=user)

        bot.repo.is_user_banned.return_value = True
        bot.repo.get_ban_reason.return_value = None

        await func(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "Banned" in call_args.args[0]
        assert "No reason provided" in call_args.args[0]
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_my_status_shows_whitelisted(self, my_status_func: tuple) -> None:
        """Test that /my_status shows whitelisted status."""
        func, bot = my_status_func
        user = create_mock_user(user_id=123)
        interaction = create_mock_interaction(user=user)

        bot.repo.is_user_banned.return_value = False
        bot.repo.is_user_whitelisted.return_value = True

        await func(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "Whitelisted" in call_args.args[0]
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_my_status_shows_not_whitelisted(
        self, my_status_func: tuple
    ) -> None:
        """Test that /my_status shows not whitelisted status."""
        func, bot = my_status_func
        user = create_mock_user(user_id=123)
        interaction = create_mock_interaction(user=user)

        bot.repo.is_user_banned.return_value = False
        bot.repo.is_user_whitelisted.return_value = False

        await func(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "Not whitelisted" in call_args.args[0]
        assert "@aghs" in call_args.args[0]
        assert call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_my_status_uses_correct_user_id(
        self, my_status_func: tuple
    ) -> None:
        """Test that /my_status uses the interaction user's ID."""
        func, bot = my_status_func
        user = create_mock_user(user_id=42)
        interaction = create_mock_interaction(user=user)

        bot.repo.is_user_banned.return_value = False
        bot.repo.is_user_whitelisted.return_value = True

        await func(interaction)

        bot.repo.is_user_banned.assert_called_once_with(42)
        bot.repo.is_user_whitelisted.assert_called_once_with(42)


# --- Show Usage Command Tests ---


class TestShowUsageCommand:
    """Tests for /show_usage command."""

    @pytest.fixture
    def show_usage_func(self) -> tuple:
        """Get the show_usage command function."""
        bot = create_mock_bot()
        # Add get_top_users_by_usage mock
        bot.repo.get_top_users_by_usage = AsyncMock(return_value=[])
        commands: dict[str, Any] = {}

        def capture_command(description=None, **kwargs):
            def decorator(func):
                commands[func.__name__] = func
                return func
            return decorator

        bot.tree.command = capture_command
        register_chat_commands(bot)

        return commands.get("show_usage"), bot

    @pytest.mark.asyncio
    async def test_show_usage_defers_response(self, show_usage_func: tuple) -> None:
        """Test that /show_usage defers response first."""
        func, _bot = show_usage_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"  # PNG header

            await func(interaction)

            interaction.response.defer.assert_called_once()

    @pytest.mark.asyncio
    async def test_show_usage_uses_guild_id_when_server_only(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage passes guild_id when server_only=True."""
        func, bot = show_usage_func
        interaction = create_mock_interaction(guild_id=12345)

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction, server_only=True)

            bot.repo.get_top_users_by_usage.assert_called_once_with(12345, limit=5)

    @pytest.mark.asyncio
    async def test_show_usage_uses_none_when_not_server_only(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage passes None when server_only=False."""
        func, bot = show_usage_func
        interaction = create_mock_interaction(guild_id=12345)

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction, server_only=False)

            bot.repo.get_top_users_by_usage.assert_called_once_with(None, limit=5)

    @pytest.mark.asyncio
    async def test_show_usage_generates_chart(self, show_usage_func: tuple) -> None:
        """Test that /show_usage calls generate_usage_chart with stats."""
        func, bot = show_usage_func
        mock_stats = [
            {"user_id": 123, "username": "Alice", "image_count": 10, "text_count": 50, "score": 100}
        ]
        bot.repo.get_top_users_by_usage.return_value = mock_stats
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction)

            mock_chart.assert_called_once()
            call_args = mock_chart.call_args
            # Stats are transformed from raw SQL (score) to UserStats (total_score)
            expected_stats = [
                {"user_id": 123, "username": "Alice", "image_count": 10, "text_count": 50, "total_score": 100}
            ]
            assert call_args[0][0] == expected_stats

    @pytest.mark.asyncio
    async def test_show_usage_sends_embed_with_file(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage sends embed with file attachment."""
        func, _bot = show_usage_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction)

            interaction.followup.send.assert_called_once()
            call_kwargs = interaction.followup.send.call_args.kwargs
            assert "embed" in call_kwargs
            assert "file" in call_kwargs

    @pytest.mark.asyncio
    async def test_show_usage_handles_error(self, show_usage_func: tuple) -> None:
        """Test that /show_usage handles errors gracefully."""
        func, bot = show_usage_func
        bot.repo.get_top_users_by_usage.side_effect = Exception("Database error")
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction)

            mock_view_class.assert_called()
            call_kwargs = mock_view_class.call_args.kwargs
            assert call_kwargs["is_error"] is True
            assert "Usage Stats Error" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_show_usage_default_is_server_only(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage defaults to server_only=True."""
        func, bot = show_usage_func
        interaction = create_mock_interaction(guild_id=99999)

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            # Call without server_only argument
            await func(interaction)

            # Should use guild_id since server_only defaults to True
            bot.repo.get_top_users_by_usage.assert_called_once_with(99999, limit=5)

    @pytest.mark.asyncio
    async def test_show_usage_embed_has_correct_title(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage embed has correct title."""
        func, _bot = show_usage_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction)

            call_kwargs = interaction.followup.send.call_args.kwargs
            embed = call_kwargs["embed"]
            assert embed.title == "Usage Statistics"

    @pytest.mark.asyncio
    async def test_show_usage_embed_has_scope_footer(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage embed has scope in footer."""
        func, _bot = show_usage_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction, server_only=True)

            call_kwargs = interaction.followup.send.call_args.kwargs
            embed = call_kwargs["embed"]
            assert "This server only" in embed.footer.text

    @pytest.mark.asyncio
    async def test_show_usage_all_servers_scope_footer(
        self, show_usage_func: tuple
    ) -> None:
        """Test that /show_usage shows all servers scope in footer."""
        func, _bot = show_usage_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.chat.generate_usage_chart"
        ) as mock_chart:
            mock_chart.return_value = b"\x89PNG\r\n\x1a\n"

            await func(interaction, server_only=False)

            call_kwargs = interaction.followup.send.call_args.kwargs
            embed = call_kwargs["embed"]
            assert "All servers" in embed.footer.text
