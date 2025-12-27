"""Unit tests for Discord image commands (image.py).

These tests verify the behavior of image-related slash commands including:
- /upload_image command
- /create_image command
- /modify_image command
- /describe_this command
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.commands.image import register_image_commands
from src.core.providers import GeneratedImage

# --- Test Fixtures ---


def create_mock_user(
    user_id: int = 12345,
    name: str = "TestUser",
    display_name: str = "TestUser",
) -> MagicMock:
    """Create a mock Discord user."""
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.display_name = display_name
    user.avatar = "https://example.com/avatar.png"
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


def create_mock_attachment(
    filename: str = "test.png",
    content: bytes | None = None,
) -> MagicMock:
    """Create a mock Discord attachment."""
    attachment = MagicMock()
    attachment.filename = filename
    attachment.read = AsyncMock(return_value=content or b"fake_image_data")
    attachment.to_file = AsyncMock()
    return attachment


def create_mock_bot() -> MagicMock:
    """Create a mock Discord bot with required dependencies."""
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.tree.command = MagicMock(return_value=lambda f: f)

    # Mock repository
    bot.repo = AsyncMock()
    bot.repo.create_channel = AsyncMock()
    bot.repo.add_message = AsyncMock()
    bot.repo.add_message_with_images = AsyncMock()
    bot.repo.get_visible_messages = AsyncMock(return_value=[])
    bot.repo.get_images = AsyncMock(return_value=[])
    bot.repo.clear_messages = AsyncMock()

    # Mock image provider
    bot.image_provider = AsyncMock()
    bot.image_provider.generate = AsyncMock(
        return_value=[
            GeneratedImage(
                url="data:image/jpeg;base64,/9j/fake",
                width=1024,
                height=1024,
                seed=12345,
                content_type="image/jpeg",
            )
        ]
    )
    bot.image_provider.modify = AsyncMock(
        return_value=[
            GeneratedImage(
                url="data:image/jpeg;base64,/9j/modified",
                width=1024,
                height=1024,
                seed=12346,
                content_type="image/jpeg",
            )
        ]
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
    bot.gcs_adapter.upload_generated_image = MagicMock(
        return_value="https://storage.example.com/image.jpeg"
    )

    return bot


# --- Command Registration Tests ---


class TestRegisterImageCommands:
    """Tests for register_image_commands function."""

    def test_registers_upload_image_command(self) -> None:
        """Test that /upload_image command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_image_commands(bot)

        assert "upload_image" in registered_commands

    def test_registers_create_image_command(self) -> None:
        """Test that /create_image command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_image_commands(bot)

        assert "create_image" in registered_commands

    def test_registers_modify_image_command(self) -> None:
        """Test that /modify_image command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_image_commands(bot)

        assert "modify_image" in registered_commands

    def test_registers_describe_this_command(self) -> None:
        """Test that /describe_this command is registered."""
        bot = create_mock_bot()
        registered_commands: list[str] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                registered_commands.append(func.__name__)
                return func
            return lambda f: (registered_commands.append(f.__name__), f)[1]

        bot.tree.command = capture_command

        register_image_commands(bot)

        assert "describe_this" in registered_commands


# --- Upload Image Tests ---


class TestUploadImageCommand:
    """Tests for /upload_image command."""

    @pytest.fixture
    def upload_image_func(self) -> Any:
        """Get the upload_image command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_image_commands(bot)

        # Return both the function and the bot for testing
        return commands.get("upload_image"), bot

    @pytest.mark.asyncio
    async def test_upload_valid_png_image(self, upload_image_func: tuple) -> None:
        """Test uploading a valid PNG image."""
        func, bot = upload_image_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="test.png")

        with patch(
            "src.clients.discord.commands.image.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            with patch(
                "src.clients.discord.commands.image.compress_image",
                return_value="compressed_base64",
            ):
                await func(interaction, attachment)

            # Verify image was stored
            bot.repo.add_message_with_images.assert_called_once()

            # Verify success view was shown
            call_kwargs = mock_view_class.call_args.kwargs
            assert "successful" in call_kwargs["title"].lower()
            assert call_kwargs["is_error"] is False

    @pytest.mark.asyncio
    async def test_upload_valid_jpeg_image(self, upload_image_func: tuple) -> None:
        """Test uploading a valid JPEG image."""
        func, bot = upload_image_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="photo.jpeg")

        with patch(
            "src.clients.discord.commands.image.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            with patch(
                "src.clients.discord.commands.image.compress_image",
                return_value="compressed_base64",
            ):
                await func(interaction, attachment)

            bot.repo.add_message_with_images.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_invalid_file_format(self, upload_image_func: tuple) -> None:
        """Test uploading an invalid file format."""
        func, _bot = upload_image_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="document.pdf")

        with patch(
            "src.clients.discord.commands.image.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction, attachment)

            # Verify error view was shown
            call_kwargs = mock_view_class.call_args.kwargs
            assert "error" in call_kwargs["title"].lower()
            assert call_kwargs["is_error"] is True
            assert "valid image format" in call_kwargs["description"]


# --- Create Image Tests ---


class TestCreateImageCommand:
    """Tests for /create_image command."""

    @pytest.fixture
    def create_image_func(self) -> tuple:
        """Get the create_image command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_image_commands(bot)

        return commands.get("create_image"), bot

    @pytest.mark.asyncio
    async def test_create_image_shows_refinement_view(
        self, create_image_func: tuple
    ) -> None:
        """Test that create_image shows prompt refinement view first."""
        func, _bot = create_image_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.image.PromptRefinementView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction, prompt="A beautiful sunset")

            mock_view_class.assert_called_once()
            call_kwargs = mock_view_class.call_args.kwargs
            assert call_kwargs["prompt"] == "A beautiful sunset"


# --- Modify Image Tests ---


class TestModifyImageCommand:
    """Tests for /modify_image command."""

    @pytest.fixture
    def modify_image_func(self) -> tuple:
        """Get the modify_image command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_image_commands(bot)

        return commands.get("modify_image"), bot

    @pytest.mark.asyncio
    async def test_modify_image_shows_selection_view(
        self, modify_image_func: tuple
    ) -> None:
        """Test that modify_image shows image selection view."""
        func, _bot = modify_image_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.image.ImageSelectionTypeView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction)

            mock_view_class.assert_called_once()


# --- Describe This Tests ---


class TestDescribeThisCommand:
    """Tests for /describe_this command."""

    @pytest.fixture
    def describe_this_func(self) -> tuple:
        """Get the describe_this command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_image_commands(bot)

        return commands.get("describe_this"), bot

    @pytest.mark.asyncio
    async def test_describe_this_with_attachment_processes_directly(
        self, describe_this_func: tuple
    ) -> None:
        """Test that describe_this processes attached image directly."""
        func, bot = describe_this_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="photo.jpg")

        with patch(
            "src.clients.discord.commands.image.DescriptionDisplayView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            with patch(
                "src.clients.discord.commands.image.compress_image",
                return_value="compressed_base64",
            ):
                await func(interaction, image=attachment)

            # Should show description display view
            mock_view_class.assert_called_once()

            # Should add image to context
            bot.repo.add_message_with_images.assert_called_once()

    @pytest.mark.asyncio
    async def test_describe_this_without_attachment_shows_selection(
        self, describe_this_func: tuple
    ) -> None:
        """Test that describe_this shows selection view when no attachment."""
        func, _bot = describe_this_func
        interaction = create_mock_interaction()

        with patch(
            "src.clients.discord.commands.image.DescribeImageSourceView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction, image=None)

            mock_view_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_describe_this_rejects_invalid_format(
        self, describe_this_func: tuple
    ) -> None:
        """Test that describe_this rejects invalid file formats."""
        func, _bot = describe_this_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="document.gif")

        with patch(
            "src.clients.discord.commands.image.InfoEmbedView"
        ) as mock_view_class:
            mock_view = MagicMock()
            mock_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_view

            await func(interaction, image=attachment)

            # Verify error view was shown
            call_kwargs = mock_view_class.call_args.kwargs
            assert "error" in call_kwargs["title"].lower()
            assert call_kwargs["is_error"] is True


# --- Rate Limiting Tests ---


class TestImageCommandRateLimiting:
    """Tests for rate limiting in image commands."""

    @pytest.fixture
    def create_image_with_callback(self) -> tuple:
        """Get the create_image command with ability to invoke callback."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}
        captured_callbacks: list[Any] = []

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command

        # Capture the on_generate callback
        original_view_class: Any = None

        def capture_refinement_view(**kwargs: Any) -> MagicMock:
            nonlocal original_view_class
            if "on_generate" in kwargs:
                captured_callbacks.append(kwargs["on_generate"])
            mock = MagicMock()
            mock.initialize = AsyncMock()
            return mock

        register_image_commands(bot)

        return commands.get("create_image"), bot, captured_callbacks, capture_refinement_view

    @pytest.mark.asyncio
    async def test_create_image_rate_limit_blocks(
        self, create_image_with_callback: tuple
    ) -> None:
        """Test that create_image respects rate limits."""
        func, bot, callbacks, view_factory = create_image_with_callback
        interaction = create_mock_interaction()

        # Set rate limiter to deny
        bot.rate_limiter.check.return_value = MagicMock(
            allowed=False, wait_seconds=60
        )

        with patch(
            "src.clients.discord.commands.image.PromptRefinementView",
            side_effect=view_factory,
        ):
            await func(interaction, prompt="A test image")

            # Get the captured callback and invoke it
            if callbacks:
                callback = callbacks[0]

                with patch(
                    "src.clients.discord.commands.image.InfoEmbedView"
                ) as error_view_class:
                    error_view = MagicMock()
                    error_view.initialize = AsyncMock()
                    error_view_class.return_value = error_view

                    await callback(interaction, "A test image")

                    # Verify rate limit error was shown
                    call_kwargs = error_view_class.call_args.kwargs
                    assert call_kwargs["is_error"] is True
                    assert "rate-limited" in call_kwargs["description"]


# --- Error Handling Tests ---


class TestImageCommandErrorHandling:
    """Tests for error handling in image commands."""

    @pytest.fixture
    def upload_image_func(self) -> tuple:
        """Get the upload_image command function."""
        bot = create_mock_bot()
        commands: dict[str, Any] = {}

        def capture_command(func=None, **kwargs):
            if func is not None:
                commands[func.__name__] = func
                return func
            return lambda f: (commands.update({f.__name__: f}), f)[1]

        bot.tree.command = capture_command
        register_image_commands(bot)

        return commands.get("upload_image"), bot

    @pytest.mark.asyncio
    async def test_upload_handles_read_error(self, upload_image_func: tuple) -> None:
        """Test that upload handles attachment read errors gracefully."""
        func, _bot = upload_image_func
        interaction = create_mock_interaction()
        attachment = create_mock_attachment(filename="test.png")
        attachment.read.side_effect = Exception("Network error")

        # Should not raise - should handle gracefully
        with pytest.raises(Exception, match="Network error"):
            await func(interaction, attachment)


# --- Utility Function Tests ---


class TestImageCommandUtilities:
    """Tests for utility functions used in image commands."""

    def test_constants_are_defined(self) -> None:
        """Test that timeout constants are properly defined."""
        from src.clients.discord.commands.image import (
            DEFAULT_API_TIMEOUT,
            DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT,
            DEFAULT_IMAGE_TIMEOUT,
            DEFAULT_USER_INTERACTION_TIMEOUT,
        )

        assert DEFAULT_API_TIMEOUT > 0
        assert DEFAULT_USER_INTERACTION_TIMEOUT > 0
        assert DEFAULT_IMAGE_TIMEOUT > 0
        assert DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT > DEFAULT_USER_INTERACTION_TIMEOUT
