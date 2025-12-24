"""Unit tests for EditPromptPreviewView and EditPromptEditModal."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.views.carousel import (
    EditPromptEditModal,
    EditPromptPreviewView,
)


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
        "filename": "test.jpeg",
        "image": "base64encodedimagedata",
    }


class TestEditPromptEditModal:
    """Tests for EditPromptEditModal."""

    @pytest.mark.asyncio
    async def test_modal_initializes_with_correct_title(self) -> None:
        """Test that modal has correct title."""
        modal = EditPromptEditModal(
            current_prompt="test prompt",
            on_submit=AsyncMock(),
        )
        assert modal.title == "Edit Prompt"

    @pytest.mark.asyncio
    async def test_modal_has_prompt_text_input(self) -> None:
        """Test that modal has a prompt text input."""
        modal = EditPromptEditModal(
            current_prompt="test prompt",
            on_submit=AsyncMock(),
        )
        assert hasattr(modal, "prompt")
        assert modal.prompt.label == "Edit your prompt:"

    @pytest.mark.asyncio
    async def test_modal_text_input_max_length(self) -> None:
        """Test that text input has max length of 1000."""
        modal = EditPromptEditModal(
            current_prompt="test prompt",
            on_submit=AsyncMock(),
        )
        assert modal.prompt.max_length == 1000

    @pytest.mark.asyncio
    async def test_modal_text_input_has_default_value(self) -> None:
        """Test that text input has the current prompt as default."""
        modal = EditPromptEditModal(
            current_prompt="my current prompt",
            on_submit=AsyncMock(),
        )
        assert modal.prompt.default == "my current prompt"

    @pytest.mark.asyncio
    async def test_on_submit_calls_callback(self) -> None:
        """Test that on_submit calls the callback with new prompt."""
        mock_callback = AsyncMock()
        modal = EditPromptEditModal(
            current_prompt="old prompt",
            on_submit=mock_callback,
        )
        modal.prompt._value = "new edited prompt"

        mock_interaction = MagicMock()
        await modal.on_submit(mock_interaction)

        mock_callback.assert_called_once_with(mock_interaction, "new edited prompt")


class TestEditPromptPreviewView:
    """Tests for EditPromptPreviewView."""

    @pytest.mark.asyncio
    async def test_view_initializes_with_correct_data(self) -> None:
        """Test that view initializes with provided parameters."""
        mock_interaction = MagicMock()
        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="test prompt",
            user=create_mock_user(),
            message=MagicMock(),
            on_select=AsyncMock(),
        )
        assert view.prompt == "test prompt"
        assert view.edit_type == "Edit"
        assert view.edit_count == 0

    @pytest.mark.asyncio
    async def test_view_has_three_buttons(self) -> None:
        """Test that view has Apply Edit, Edit Prompt, and X buttons."""
        mock_interaction = MagicMock()
        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="test prompt",
            user=create_mock_user(),
        )
        button_labels = [
            child.label
            for child in view.children
            if hasattr(child, "label")
        ]
        assert "Apply Edit" in button_labels
        assert "Edit Prompt" in button_labels
        assert "X" in button_labels

    def test_max_edits_constant(self) -> None:
        """Test that MAX_EDITS is set to 3."""
        assert EditPromptPreviewView.MAX_EDITS == 3

    @pytest.mark.asyncio
    async def test_apply_button_calls_on_select(self) -> None:
        """Test that Apply Edit button calls on_select with prompt."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()
        mock_on_select = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="my edit prompt",
            user=create_mock_user(),
            message=mock_message,
            on_select=mock_on_select,
        )

        apply_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Apply Edit"
        )
        await apply_button.callback(mock_interaction)

        mock_on_select.assert_called_once_with(
            mock_interaction, "Edit", "my edit prompt"
        )

    @pytest.mark.asyncio
    async def test_edit_prompt_button_opens_modal(self) -> None:
        """Test that Edit Prompt button opens the edit modal."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.send_modal = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="original prompt",
            user=create_mock_user(),
            edit_count=0,
        )

        edit_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Edit Prompt"
        )
        await edit_button.callback(mock_interaction)

        mock_interaction.response.send_modal.assert_called_once()
        modal = mock_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal, EditPromptEditModal)
        assert modal.prompt.default == "original prompt"

    @pytest.mark.asyncio
    async def test_edit_prompt_button_disabled_after_max_edits(self) -> None:
        """Test that Edit Prompt button rejects when edit_count >= MAX_EDITS."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.send_message = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="original prompt",
            user=create_mock_user(),
            edit_count=3,  # At max edits
        )

        edit_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Edit Prompt"
        )
        await edit_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        assert "Maximum number of edits reached" in str(
            mock_interaction.response.send_message.call_args
        )

    @pytest.mark.asyncio
    async def test_cancel_button_calls_on_select_with_cancel(self) -> None:
        """Test that X button calls on_select with Cancel."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()
        mock_on_select = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="test prompt",
            user=create_mock_user(),
            message=mock_message,
            on_select=mock_on_select,
        )

        cancel_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "X"
        )
        await cancel_button.callback(mock_interaction)

        mock_on_select.assert_called_once_with(mock_interaction, "Cancel", "")

    @pytest.mark.asyncio
    async def test_buttons_reject_wrong_user(self) -> None:
        """Test that buttons reject interactions from wrong user."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different user
        mock_interaction.response.send_message = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="test prompt",
            user=create_mock_user(),  # user_id=12345
        )

        for child in view.children:
            if hasattr(child, "callback"):
                await child.callback(mock_interaction)
                mock_interaction.response.send_message.assert_called()
                assert "Only the original requester" in str(
                    mock_interaction.response.send_message.call_args
                )
                mock_interaction.response.send_message.reset_mock()

    @pytest.mark.asyncio
    async def test_edit_cycling_increments_count(self) -> None:
        """Test that edit cycling creates new view with incremented count."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.defer = AsyncMock()
        mock_interaction.response.is_done.return_value = True
        mock_interaction.edit_original_response = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="original prompt",
            user=create_mock_user(),
            message=mock_message,
            on_select=AsyncMock(),
            edit_count=1,
        )

        with patch(
            "src.clients.discord.views.carousel.EditPromptPreviewView"
        ) as mock_view_class:
            mock_new_view = MagicMock()
            mock_new_view.initialize = AsyncMock()
            mock_view_class.return_value = mock_new_view

            await view._handle_edit_submit(mock_interaction, "new prompt")

            # Verify new view was created with edit_count=2
            call_kwargs = mock_view_class.call_args.kwargs
            assert call_kwargs["edit_count"] == 2
            assert call_kwargs["prompt"] == "new prompt"


class TestEditPromptPreviewViewWarning:
    """Tests for warning display at 2nd edit."""

    @pytest.mark.asyncio
    async def test_warning_shown_after_second_edit(self) -> None:
        """Test that warning is shown when edit_count=2."""
        mock_interaction = MagicMock()
        mock_interaction.response.is_done.return_value = True
        mock_interaction.edit_original_response = AsyncMock()

        view = EditPromptPreviewView(
            interaction=mock_interaction,
            image_data=create_mock_image_data(),
            edit_type="Edit",
            prompt="test prompt",
            user=create_mock_user(),
            edit_count=2,  # After 2nd edit
        )

        with patch(
            "src.clients.discord.views.carousel.create_file_from_image"
        ) as mock_create_file:
            mock_file = MagicMock()
            mock_file.filename = "test.jpeg"
            mock_create_file.return_value = mock_file

            await view._display_preview(mock_interaction)

            # Check that embed description contains warning
            assert view.embed is not None
            assert "one more time" in view.embed.description.lower()
            assert "editing is disabled" in view.embed.description.lower()
