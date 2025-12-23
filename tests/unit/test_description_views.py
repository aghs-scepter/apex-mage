"""Unit tests for Description Display views in carousel.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.views.carousel import (
    DescriptionDisplayView,
    DescriptionEditModal,
)
from src.core.haiku import ImageDescriptionError


def create_mock_user() -> dict[str, Any]:
    """Create a mock user dict."""
    return {
        "name": "TestUser",
        "id": 12345,
        "pfp": "https://example.com/avatar.png",
    }


def create_mock_image_data() -> dict[str, str]:
    """Create mock image data."""
    return {
        "filename": "test.jpg",
        "image": "base64encodedimage",
    }


class TestDescriptionEditModal:
    """Tests for DescriptionEditModal class."""

    @pytest.mark.asyncio
    async def test_modal_initializes_with_correct_title(self) -> None:
        """Test that the modal has the correct title."""
        mock_callback = AsyncMock()
        modal = DescriptionEditModal(
            current_description="Test description",
            on_submit=mock_callback,
        )
        assert modal.title == "Edit Description"

    @pytest.mark.asyncio
    async def test_modal_has_description_text_input(self) -> None:
        """Test that the modal has a description text input."""
        mock_callback = AsyncMock()
        modal = DescriptionEditModal(
            current_description="Test description",
            on_submit=mock_callback,
        )
        assert hasattr(modal, "description")
        assert modal.description.label == "Edit the description:"

    @pytest.mark.asyncio
    async def test_modal_text_input_max_length(self) -> None:
        """Test that the text input has appropriate max length (1000 chars)."""
        mock_callback = AsyncMock()
        modal = DescriptionEditModal(
            current_description="Test description",
            on_submit=mock_callback,
        )
        assert modal.description.max_length == 1000

    @pytest.mark.asyncio
    async def test_modal_prefills_current_description(self) -> None:
        """Test that the modal is pre-filled with current description."""
        mock_callback = AsyncMock()
        current = "Digital art style, vibrant colors. A cat sitting on a chair."
        modal = DescriptionEditModal(
            current_description=current,
            on_submit=mock_callback,
        )
        assert modal.description.default == current

    @pytest.mark.asyncio
    async def test_on_submit_calls_callback_with_new_description(self) -> None:
        """Test that on_submit calls the callback with the new description."""
        mock_callback = AsyncMock()
        mock_interaction = MagicMock()

        modal = DescriptionEditModal(
            current_description="Original description",
            on_submit=mock_callback,
        )
        modal.description._value = "New edited description"

        await modal.on_submit(mock_interaction)

        mock_callback.assert_called_once_with(mock_interaction, "New edited description")


class TestDescriptionDisplayView:
    """Tests for DescriptionDisplayView class."""

    @pytest.mark.asyncio
    async def test_view_initializes_with_correct_user_info(self) -> None:
        """Test that the view extracts correct user info."""
        mock_interaction = MagicMock()
        user = create_mock_user()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=user,
            message=None,
        )

        assert view.username == "TestUser"
        assert view.user_id == 12345
        assert view.pfp == "https://example.com/avatar.png"

    @pytest.mark.asyncio
    async def test_view_stores_image_data(self) -> None:
        """Test that the view stores the image data for later use."""
        mock_interaction = MagicMock()
        image_data = create_mock_image_data()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=image_data,
            user=create_mock_user(),
            message=None,
        )

        assert view.image_data == image_data

    @pytest.mark.asyncio
    async def test_view_has_three_buttons(self) -> None:
        """Test that the view has edit, use this, and cancel buttons."""
        mock_interaction = MagicMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )

        # Get button labels
        button_labels = [item.label for item in view.children if hasattr(item, "label")]
        assert "Edit Description" in button_labels
        assert "Use This" in button_labels
        assert "X" in button_labels

    @pytest.mark.asyncio
    async def test_edit_button_rejects_wrong_user(self) -> None:
        """Test that edit button rejects interactions from wrong user."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different from user_id 12345
        mock_interaction.response.send_message = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )

        await view.edit_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Only the original requester" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_use_this_button_rejects_wrong_user(self) -> None:
        """Test that use this button rejects interactions from wrong user."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different from user_id 12345
        mock_interaction.response.send_message = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )

        await view.use_this_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Only the original requester" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_cancel_button_rejects_wrong_user(self) -> None:
        """Test that cancel button rejects interactions from wrong user."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different from user_id 12345
        mock_interaction.response.send_message = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )

        await view.cancel_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Only the original requester" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_edit_button_opens_modal(self) -> None:
        """Test that edit button opens the description edit modal."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345  # Same as user_id
        mock_interaction.response.send_modal = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )
        view.description = "Test description to edit"
        view._generating = False

        await view.edit_button.callback(mock_interaction)

        mock_interaction.response.send_modal.assert_called_once()
        modal = mock_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal, DescriptionEditModal)

    @pytest.mark.asyncio
    async def test_edit_button_blocked_during_generation(self) -> None:
        """Test that edit button is blocked during description generation."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345  # Same as user_id
        mock_interaction.response.send_message = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )
        view._generating = True  # Simulating generation in progress

        await view.edit_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "wait for the description to finish" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_use_this_button_blocked_during_generation(self) -> None:
        """Test that use this button is blocked during description generation."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345  # Same as user_id
        mock_interaction.response.send_message = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )
        view._generating = True  # Simulating generation in progress

        await view.use_this_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "wait for the description to finish" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_initialize_generates_description(self) -> None:
        """Test that initialize calls haiku_describe_image."""
        mock_interaction = MagicMock()
        mock_interaction.response.is_done.return_value = True
        mock_interaction.edit_original_response = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
        )

        with (
            patch(
                "src.clients.discord.views.carousel.haiku_describe_image",
                new_callable=AsyncMock,
                return_value="Digital art style. A cat on a chair.",
            ) as mock_describe,
            patch(
                "src.clients.discord.views.carousel.create_file_from_image",
                new_callable=AsyncMock,
            ),
        ):
            await view.initialize(mock_interaction)

            mock_describe.assert_called_once()
            assert view.description == "Digital art style. A cat on a chair."

    @pytest.mark.asyncio
    async def test_initialize_handles_description_error(self) -> None:
        """Test that initialize handles ImageDescriptionError gracefully."""
        mock_interaction = MagicMock()
        mock_interaction.response.is_done.return_value = True
        mock_interaction.edit_original_response = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
        )

        with (
            patch(
                "src.clients.discord.views.carousel.haiku_describe_image",
                new_callable=AsyncMock,
                side_effect=ImageDescriptionError("Failed to describe image: API error"),
            ),
            patch(
                "src.clients.discord.views.carousel.create_file_from_image",
                new_callable=AsyncMock,
            ),
        ):
            await view.initialize(mock_interaction)

            # View should show error state
            assert view.embed is not None
            assert view.embed.title == "Description Generation Failed"
            assert "Failed to describe image" in str(view.embed.description)

    @pytest.mark.asyncio
    async def test_update_description_updates_embed(self) -> None:
        """Test that _update_description updates the embed and message."""
        mock_interaction = MagicMock()
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
        )
        view.embed = MagicMock()

        with patch(
            "src.clients.discord.views.carousel.create_file_from_image",
            new_callable=AsyncMock,
        ):
            await view._update_description(mock_interaction, "New edited description")

        assert view.description == "New edited description"
        assert view.embed.description == "New edited description"
        mock_message.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_button_updates_embed_and_stops_view(self) -> None:
        """Test that cancel button updates embed and stops the view."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345  # Same as user_id
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
        )
        view.embed = MagicMock()

        await view.cancel_button.callback(mock_interaction)

        assert view.embed.title == "Operation Cancelled"
        assert view.embed.description == "Image description was cancelled."
        mock_message.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_hide_buttons_clears_items(self) -> None:
        """Test that hide_buttons removes all buttons from view."""
        mock_interaction = MagicMock()

        view = DescriptionDisplayView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
        )

        # Initially should have 3 buttons
        assert len(view.children) == 3

        view.hide_buttons()

        # After hiding, should have 0 items
        assert len(view.children) == 0
