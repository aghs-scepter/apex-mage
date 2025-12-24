"""Unit tests for AI Assist views in carousel.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.discord.views.carousel import (
    AIAssistErrorView,
    AIAssistModal,
    AIAssistResultView,
    ImageEditTypeView,
)
from src.core.haiku import HaikuError


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


class TestAIAssistModal:
    """Tests for AIAssistModal class."""

    @pytest.mark.asyncio
    async def test_modal_initializes_with_correct_title(self) -> None:
        """Test that the modal has the correct title."""
        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=None,
        )
        assert modal.title == "AI Assist - Describe Your Edit"

    @pytest.mark.asyncio
    async def test_modal_has_description_text_input(self) -> None:
        """Test that the modal has a description text input."""
        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=None,
        )
        assert hasattr(modal, "description")
        assert modal.description.label == "Describe what changes you want:"

    @pytest.mark.asyncio
    async def test_modal_text_input_max_length(self) -> None:
        """Test that the text input has appropriate max length."""
        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=None,
        )
        assert modal.description.max_length == 500

    @pytest.mark.asyncio
    async def test_on_submit_calls_haiku_complete(self) -> None:
        """Test that on_submit calls haiku_complete with correct args."""
        mock_interaction = MagicMock()
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        mock_on_select = AsyncMock()

        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            on_select=mock_on_select,
        )
        modal.description._value = "make it darker"

        with patch(
            "src.clients.discord.views.carousel.haiku_complete",
            new_callable=AsyncMock,
            return_value="Reduce brightness by 40%, increase contrast",
        ) as mock_haiku:
            await modal.on_submit(mock_interaction)

            mock_haiku.assert_called_once()
            call_kwargs = mock_haiku.call_args.kwargs
            assert call_kwargs["user_message"] == "make it darker"

    @pytest.mark.asyncio
    async def test_on_submit_shows_result_view_on_success(self) -> None:
        """Test that on_submit shows AIAssistResultView on success."""
        mock_interaction = MagicMock()
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            on_select=AsyncMock(),
        )
        modal.description._value = "make it darker"

        with patch(
            "src.clients.discord.views.carousel.haiku_complete",
            new_callable=AsyncMock,
            return_value="Reduce brightness by 40%",
        ):
            await modal.on_submit(mock_interaction)

            # The message.edit should be called with the result view
            mock_message.edit.assert_called()

    @pytest.mark.asyncio
    async def test_on_submit_retries_on_failure(self) -> None:
        """Test that on_submit retries once on Haiku failure."""
        mock_interaction = MagicMock()
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            on_select=AsyncMock(),
        )
        modal.description._value = "make it darker"

        # First call fails, second succeeds
        with patch(
            "src.clients.discord.views.carousel.haiku_complete",
            new_callable=AsyncMock,
            side_effect=[
                HaikuError("API Error"),
                "Reduce brightness by 40%",
            ],
        ) as mock_haiku:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await modal.on_submit(mock_interaction)

            assert mock_haiku.call_count == 2

    @pytest.mark.asyncio
    async def test_on_submit_shows_error_view_after_retry_failures(self) -> None:
        """Test that on_submit shows AIAssistErrorView after all retries fail."""
        mock_interaction = MagicMock()
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        modal = AIAssistModal(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            on_select=AsyncMock(),
        )
        modal.description._value = "make it darker"

        # Both calls fail
        with patch(
            "src.clients.discord.views.carousel.haiku_complete",
            new_callable=AsyncMock,
            side_effect=HaikuError("API Error"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await modal.on_submit(mock_interaction)

            # Should show error view
            mock_message.edit.assert_called()


class TestAIAssistResultView:
    """Tests for AIAssistResultView class."""

    @pytest.mark.asyncio
    async def test_view_initializes_with_correct_data(self) -> None:
        """Test that the view initializes with correct data."""
        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=None,
        )
        assert view.rough_description == "make it darker"
        assert view.refined_prompt == "Reduce brightness by 40%"

    @pytest.mark.asyncio
    async def test_view_has_three_buttons(self) -> None:
        """Test that the view has Use This, Edit, and Cancel buttons."""
        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=None,
        )
        button_labels = [
            child.label
            for child in view.children
            if hasattr(child, "label")
        ]
        assert "Use This" in button_labels
        assert "Edit" in button_labels
        assert "X" in button_labels  # Cancel button is labeled "X"

    @pytest.mark.asyncio
    async def test_use_button_calls_on_select_with_refined_prompt(self) -> None:
        """Test that Use This button calls on_select with refined prompt."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()
        mock_on_select = AsyncMock()

        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=mock_on_select,
        )

        # Find and call the use button
        use_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Use This"
        )
        await use_button.callback(mock_interaction)

        mock_on_select.assert_called_once_with(
            mock_interaction, "Edit", "Reduce brightness by 40%"
        )

    @pytest.mark.asyncio
    async def test_edit_button_opens_prompt_modal(self) -> None:
        """Test that Edit button opens ImageEditPromptModal with pre-filled text."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.send_modal = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=AsyncMock(),
        )

        # Find and call the edit button
        edit_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Edit"
        )
        await edit_button.callback(mock_interaction)

        mock_interaction.response.send_modal.assert_called_once()
        modal = mock_interaction.response.send_modal.call_args[0][0]
        assert modal.prompt.default == "Reduce brightness by 40%"

    @pytest.mark.asyncio
    async def test_cancel_button_stops_view(self) -> None:
        """Test that Cancel button properly cancels the operation."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.defer = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=AsyncMock(),
        )

        # Find and call the cancel button
        cancel_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "X"
        )
        await cancel_button.callback(mock_interaction)

        mock_message.edit.assert_called()

    @pytest.mark.asyncio
    async def test_buttons_reject_wrong_user(self) -> None:
        """Test that buttons reject interactions from non-original users."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different user
        mock_interaction.response.send_message = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()
        mock_on_select = AsyncMock()

        view = AIAssistResultView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),  # user_id = 12345
            message=mock_message,
            rough_description="make it darker",
            refined_prompt="Reduce brightness by 40%",
            on_select=mock_on_select,
        )

        # Find and call the use button
        use_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Use This"
        )
        await use_button.callback(mock_interaction)

        # Should send ephemeral rejection message
        mock_interaction.response.send_message.assert_called_once()
        call_kwargs = mock_interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True
        # on_select should NOT be called
        mock_on_select.assert_not_called()


class TestAIAssistErrorView:
    """Tests for AIAssistErrorView class."""

    @pytest.mark.asyncio
    async def test_view_initializes_with_rough_description(self) -> None:
        """Test that the view stores the rough description."""
        view = AIAssistErrorView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            rough_description="make it darker",
            on_select=None,
        )
        assert view.rough_description == "make it darker"

    @pytest.mark.asyncio
    async def test_view_has_enter_manually_and_cancel_buttons(self) -> None:
        """Test that the view has Enter Manually and Cancel buttons."""
        view = AIAssistErrorView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            rough_description="make it darker",
            on_select=None,
        )
        button_labels = [
            child.label
            for child in view.children
            if hasattr(child, "label")
        ]
        assert "Enter Manually" in button_labels
        assert "X" in button_labels  # Cancel button is labeled "X"

    @pytest.mark.asyncio
    async def test_enter_manually_opens_modal_with_prefilled_text(self) -> None:
        """Test that Enter Manually opens modal with rough description pre-filled."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.send_modal = AsyncMock()
        mock_message = MagicMock()
        mock_message.edit = AsyncMock()

        view = AIAssistErrorView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=mock_message,
            rough_description="make it darker",
            on_select=AsyncMock(),
        )

        # Find and call the enter manually button
        enter_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Enter Manually"
        )
        await enter_button.callback(mock_interaction)

        mock_interaction.response.send_modal.assert_called_once()
        modal = mock_interaction.response.send_modal.call_args[0][0]
        assert modal.prompt.default == "make it darker"


class TestImageEditTypeViewAIAssistButton:
    """Tests for AI Assist button in ImageEditTypeView."""

    @pytest.mark.asyncio
    async def test_ai_assist_button_exists(self) -> None:
        """Test that AI Assist button exists in ImageEditTypeView."""
        view = ImageEditTypeView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=None,
        )
        button_labels = [
            child.label
            for child in view.children
            if hasattr(child, "label")
        ]
        assert "AI Assist" in button_labels

    @pytest.mark.asyncio
    async def test_ai_assist_button_is_success_style(self) -> None:
        """Test that AI Assist button uses success (green) style."""
        import discord

        view = ImageEditTypeView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=None,
        )
        ai_assist_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "AI Assist"
        )
        assert ai_assist_button.style == discord.ButtonStyle.success

    @pytest.mark.asyncio
    async def test_ai_assist_button_opens_modal(self) -> None:
        """Test that AI Assist button opens the AIAssistModal."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 12345
        mock_interaction.response.send_modal = AsyncMock()

        view = ImageEditTypeView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),
            message=None,
            on_select=AsyncMock(),
        )

        ai_assist_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "AI Assist"
        )
        await ai_assist_button.callback(mock_interaction)

        mock_interaction.response.send_modal.assert_called_once()
        modal = mock_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal, AIAssistModal)

    @pytest.mark.asyncio
    async def test_ai_assist_button_rejects_wrong_user(self) -> None:
        """Test that AI Assist button rejects wrong user."""
        mock_interaction = MagicMock()
        mock_interaction.user.id = 99999  # Different user
        mock_interaction.response.send_message = AsyncMock()

        view = ImageEditTypeView(
            image_data=create_mock_image_data(),
            user=create_mock_user(),  # user_id = 12345
            message=None,
            on_select=AsyncMock(),
        )

        ai_assist_button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "AI Assist"
        )
        await ai_assist_button.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_kwargs = mock_interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True
