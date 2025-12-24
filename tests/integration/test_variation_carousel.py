"""Integration tests for the Variation Carousel feature (Epic D).

These tests verify the end-to-end flows for image variation generation,
including transitions between views, button state management, and
error handling scenarios.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.clients.discord.views.carousel import (
    ImageEditResultView,
    ImageGenerationResultView,
    VariationCarouselView,
)
from src.core.image_variations import (
    RateLimitExceededError,
    VariationError,
)

# --- Test Fixtures ---


def create_mock_user() -> dict[str, Any]:
    """Create a mock user dict."""
    return {
        "name": "TestUser",
        "id": 12345,
        "pfp": "https://example.com/avatar.png",
    }


def create_mock_image_data(name: str = "test") -> dict[str, str]:
    """Create mock image data with a simple valid base64 image.

    Args:
        name: Optional name prefix for the filename.

    Returns:
        Dict with 'filename' and 'image' keys.
    """
    # Create a minimal valid base64 string (1x1 JPEG)
    # This is just "test" encoded, which is enough for testing
    fake_b64 = base64.b64encode(b"fake_image_data").decode()
    return {
        "filename": f"{name}.jpeg",
        "image": fake_b64,
    }


def create_mock_interaction(user_id: int = 12345, channel_id: int = 99999) -> MagicMock:
    """Create a mock Discord interaction.

    Args:
        user_id: The user ID for the interaction.
        channel_id: The channel ID for the interaction.

    Returns:
        A configured MagicMock for discord.Interaction.
    """
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.channel_id = channel_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def create_mock_message() -> MagicMock:
    """Create a mock Discord message.

    Returns:
        A configured MagicMock for discord.Message.
    """
    message = MagicMock(spec=discord.Message)
    message.edit = AsyncMock()
    return message


def create_mock_rate_limiter(allowed: bool = True, wait_seconds: float = 0.0) -> MagicMock:
    """Create a mock rate limiter.

    Args:
        allowed: Whether rate limiting allows the action.
        wait_seconds: Seconds until rate limit resets.

    Returns:
        A configured MagicMock for rate limiter.
    """
    rate_limiter = MagicMock()
    rate_check = MagicMock()
    rate_check.allowed = allowed
    rate_check.wait_seconds = wait_seconds
    rate_limiter.check = AsyncMock(return_value=rate_check)
    rate_limiter.record = AsyncMock()
    return rate_limiter


def create_mock_repo() -> MagicMock:
    """Create a mock repository adapter.

    Returns:
        A configured MagicMock for RepositoryAdapter.
    """
    repo = MagicMock()
    repo.create_channel = AsyncMock()
    repo.add_message_with_images = AsyncMock()
    return repo


def create_mock_image_provider(
    image_url: str = "data:image/jpeg;base64,dGVzdA==",
) -> MagicMock:
    """Create a mock image provider.

    Args:
        image_url: The URL to return for generated images.

    Returns:
        A configured MagicMock for ImageProvider.
    """
    provider = MagicMock()
    generated_image = MagicMock()
    generated_image.url = image_url
    generated_image.has_nsfw_content = False
    provider.generate = AsyncMock(return_value=[generated_image])
    return provider


# --- Test Classes ---


class TestVariationCarouselViewInitialization:
    """Tests for VariationCarouselView initialization and display."""

    @pytest.mark.asyncio
    async def test_view_initializes_with_original_image(self) -> None:
        """Test that the view initializes with the original image at position 0."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        original_image = create_mock_image_data("original")

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=original_image,
            prompt="A beautiful sunset",
            source_image=None,
        )

        assert view.original_image == original_image
        assert view.current_index == 0
        assert len(view.variations) == 0
        assert view._get_current_image() == original_image

    @pytest.mark.asyncio
    async def test_view_initializes_with_source_image_for_modify(self) -> None:
        """Test that source_image is stored for modify_image flows."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        original_image = create_mock_image_data("result")
        source_image = create_mock_image_data("source")

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=original_image,
            prompt="Add a hat",
            source_image=source_image,
        )

        assert view.source_image == source_image

    @pytest.mark.asyncio
    async def test_view_shows_correct_position_indicator(self) -> None:
        """Test that position indicator shows correctly for original."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        indicator = view._generate_position_indicator()
        assert "(Original)" in indicator
        # Should show filled dot for current position plus 3 empty for potential variations
        assert "\u25cf" in indicator  # Current position (filled)
        assert "\u25cb" in indicator  # Empty positions

    @pytest.mark.asyncio
    async def test_view_has_all_required_buttons(self) -> None:
        """Test that view has navigation, variation, and action buttons."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        button_labels = [
            child.label for child in view.children if hasattr(child, "label")
        ]
        assert "<" in button_labels  # Previous
        assert ">" in button_labels  # Next
        assert "Same Prompt" in button_labels
        assert "AI Remix" in button_labels
        assert "Add to Context" in button_labels
        assert "Cancel" in button_labels


class TestVariationCarouselNavigation:
    """Tests for carousel navigation functionality."""

    @pytest.mark.asyncio
    async def test_previous_button_disabled_at_start(self) -> None:
        """Test that previous button is disabled at index 0."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )
        view._update_buttons()

        assert view.previous_button.disabled is True
        assert view.next_button.disabled is True  # No variations yet

    @pytest.mark.asyncio
    async def test_navigation_with_variations(self) -> None:
        """Test navigation works correctly with variations."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data("original"),
            prompt="Test",
        )

        # Add a variation
        view.variations.append(create_mock_image_data("variation1"))
        view._update_buttons()

        # At position 0, can go forward
        assert view.previous_button.disabled is True
        assert view.next_button.disabled is False

        # Move to position 1
        view.current_index = 1
        view._update_buttons()

        # At last position, cannot go forward but can go back
        assert view.previous_button.disabled is False
        assert view.next_button.disabled is True

    @pytest.mark.asyncio
    async def test_previous_button_rejects_wrong_user(self) -> None:
        """Test that previous button rejects non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        await view.previous_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_next_button_rejects_wrong_user(self) -> None:
        """Test that next button rejects non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        await view.next_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True


class TestVariationGeneration:
    """Tests for variation generation functionality."""

    @pytest.mark.asyncio
    async def test_same_prompt_generates_variation(self) -> None:
        """Test that Same Prompt button generates a variation."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        rate_limiter = create_mock_rate_limiter()
        image_provider = create_mock_image_provider()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="A beautiful sunset",
            rate_limiter=rate_limiter,
            image_provider=image_provider,
        )

        with patch(
            "src.clients.discord.views.carousel.generate_variation_same_prompt",
            new_callable=AsyncMock,
            return_value=create_mock_image_data("variation"),
        ):
            await view.same_prompt_button.callback(interaction)

        # Should have one variation now
        assert len(view.variations) == 1
        # Should have navigated to the new variation
        assert view.current_index == 1

    @pytest.mark.asyncio
    async def test_ai_remix_generates_variation(self) -> None:
        """Test that AI Remix button generates a remixed variation."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        rate_limiter = create_mock_rate_limiter()
        image_provider = create_mock_image_provider()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="A beautiful sunset",
            rate_limiter=rate_limiter,
            image_provider=image_provider,
        )
        # Initialize embed for field updates
        view.embed = discord.Embed()
        view.embed.add_field(name="Prompt", value="A beautiful sunset")

        with patch(
            "src.clients.discord.views.carousel.generate_variation_remixed",
            new_callable=AsyncMock,
            return_value=("A gorgeous twilight", create_mock_image_data("variation")),
        ):
            await view.ai_remix_button.callback(interaction)

        # Should have one variation now
        assert len(view.variations) == 1
        # Should have navigated to the new variation
        assert view.current_index == 1

    @pytest.mark.asyncio
    async def test_max_variations_enforced(self) -> None:
        """Test that max 3 variations are enforced."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )

        # Add 3 variations (max)
        view.variations = [
            create_mock_image_data("v1"),
            create_mock_image_data("v2"),
            create_mock_image_data("v3"),
        ]
        view._update_buttons()

        # Variation buttons should be disabled
        assert view.same_prompt_button.disabled is True
        assert view.ai_remix_button.disabled is True

    @pytest.mark.asyncio
    async def test_same_prompt_rejects_when_at_max(self) -> None:
        """Test Same Prompt button shows message when at max variations."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )

        # Add 3 variations (max)
        view.variations = [
            create_mock_image_data("v1"),
            create_mock_image_data("v2"),
            create_mock_image_data("v3"),
        ]

        await view.same_prompt_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "Maximum number of variations" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_variation_buttons_reject_wrong_user(self) -> None:
        """Test that variation buttons reject non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )

        await view.same_prompt_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_variation_prevents_concurrent_generation(self) -> None:
        """Test that concurrent generation is prevented."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )

        # Simulate generation in progress
        view._generating = True

        await view.same_prompt_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "wait for the current generation" in call_args[0][0]


class TestRateLimitHandling:
    """Tests for rate limit error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error_during_same_prompt(self) -> None:
        """Test rate limit error handling for Same Prompt generation."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )
        # Initialize embed with content so it's truthy (empty Embed is falsy)
        view.embed = discord.Embed(title="Image Variations", description="Initial")

        with patch(
            "src.clients.discord.views.carousel.generate_variation_same_prompt",
            new_callable=AsyncMock,
            side_effect=RateLimitExceededError(retry_after=300.0),
        ):
            await view.same_prompt_button.callback(interaction)

        # Check that the embed was updated with rate limit message
        assert "Rate limit exceeded" in str(view.embed.description)
        assert "5 minute(s)" in str(view.embed.description)

    @pytest.mark.asyncio
    async def test_rate_limit_error_during_ai_remix(self) -> None:
        """Test rate limit error handling for AI Remix generation."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )
        # Initialize embed with content so it's truthy (empty Embed is falsy)
        view.embed = discord.Embed(title="Image Variations", description="Initial")

        with patch(
            "src.clients.discord.views.carousel.generate_variation_remixed",
            new_callable=AsyncMock,
            side_effect=RateLimitExceededError(retry_after=120.0),
        ):
            await view.ai_remix_button.callback(interaction)

        # Check that the embed was updated with rate limit message
        assert "Rate limit exceeded" in str(view.embed.description)
        assert "2 minute(s)" in str(view.embed.description)


class TestVariationErrors:
    """Tests for variation error handling."""

    @pytest.mark.asyncio
    async def test_variation_error_during_generation(self) -> None:
        """Test VariationError handling during generation."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            rate_limiter=create_mock_rate_limiter(),
            image_provider=create_mock_image_provider(),
        )
        # Initialize embed with content so it's truthy (empty Embed is falsy)
        view.embed = discord.Embed(title="Image Variations", description="Initial")

        with patch(
            "src.clients.discord.views.carousel.generate_variation_same_prompt",
            new_callable=AsyncMock,
            side_effect=VariationError("Image generation timed out"),
        ):
            await view.same_prompt_button.callback(interaction)

        # Check that the embed was updated with error message
        assert "Failed to generate variation" in str(view.embed.description)

    @pytest.mark.asyncio
    async def test_missing_image_provider_shows_message(self) -> None:
        """Test that missing image provider shows appropriate message."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            image_provider=None,  # No provider
        )

        await view.same_prompt_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "not available" in call_args[0][0]


class TestAddToContext:
    """Tests for Add to Context functionality."""

    @pytest.mark.asyncio
    async def test_add_to_context_stores_current_image(self) -> None:
        """Test that Add to Context stores the currently selected image."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        repo = create_mock_repo()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data("original"),
            prompt="Test",
            repo=repo,
        )
        view.embed = discord.Embed()

        await view.add_to_context_button.callback(interaction)

        # Check that repo methods were called
        repo.create_channel.assert_called_once_with(99999)
        repo.add_message_with_images.assert_called_once()
        assert view.added_to_context is True

    @pytest.mark.asyncio
    async def test_add_to_context_uses_selected_variation(self) -> None:
        """Test that Add to Context uses the currently navigated variation."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        repo = create_mock_repo()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data("original"),
            prompt="Test",
            repo=repo,
        )
        view.embed = discord.Embed()

        # Add a variation and navigate to it
        variation = create_mock_image_data("variation1")
        view.variations.append(variation)
        view.current_index = 1

        await view.add_to_context_button.callback(interaction)

        # Check that the variation image was stored
        repo.add_message_with_images.assert_called_once()
        call_args = repo.add_message_with_images.call_args[0]
        # The images are passed as a JSON string
        assert "variation1" in call_args[5]  # images parameter

    @pytest.mark.asyncio
    async def test_add_to_context_rejects_wrong_user(self) -> None:
        """Test that Add to Context rejects non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        await view.add_to_context_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True


class TestCancelWithoutSelection:
    """Tests for cancel behavior."""

    @pytest.mark.asyncio
    async def test_cancel_does_not_add_to_context(self) -> None:
        """Test that cancel button does not add image to context."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        repo = create_mock_repo()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
            repo=repo,
        )
        view.embed = discord.Embed()

        await view.cancel_button.callback(interaction)

        # Repo should not be called for adding images
        repo.add_message_with_images.assert_not_called()
        assert view.added_to_context is False

    @pytest.mark.asyncio
    async def test_cancel_updates_embed(self) -> None:
        """Test that cancel updates the embed appropriately."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )
        # Initialize embed with content so it's truthy (empty Embed is falsy)
        view.embed = discord.Embed(title="Image Variations", description="Initial")

        await view.cancel_button.callback(interaction)

        assert view.embed.title == "Operation Cancelled"
        assert "no image was added to context" in str(view.embed.description).lower()

    @pytest.mark.asyncio
    async def test_cancel_removes_buttons(self) -> None:
        """Test that cancel removes all buttons."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )
        view.embed = discord.Embed()

        # Initially should have buttons
        assert len(view.children) > 0

        await view.cancel_button.callback(interaction)

        # After cancel, should have no buttons
        assert len(view.children) == 0

    @pytest.mark.asyncio
    async def test_cancel_rejects_wrong_user(self) -> None:
        """Test that cancel button rejects non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        await view.cancel_button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True


class TestSourceThumbnailPersistence:
    """Tests for source thumbnail in modify_image flows."""

    @pytest.mark.asyncio
    async def test_source_image_available_for_modify_flow(self) -> None:
        """Test that source_image is accessible during navigation."""
        interaction = create_mock_interaction()
        message = create_mock_message()
        source_image = create_mock_image_data("source")

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data("result"),
            prompt="Add a hat",
            source_image=source_image,
        )

        # Add variations and navigate
        view.variations.append(create_mock_image_data("v1"))
        view.current_index = 1

        # Source image should still be accessible
        assert view.source_image is not None
        assert view.source_image["filename"] == "source.jpeg"

    @pytest.mark.asyncio
    async def test_no_source_image_for_create_flow(self) -> None:
        """Test that create_image flow has no source_image."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data("generated"),
            prompt="A sunset",
            source_image=None,  # No source for create_image
        )

        assert view.source_image is None


class TestImageGenerationResultViewTransition:
    """Tests for ImageGenerationResultView -> VariationCarouselView transition."""

    @pytest.mark.asyncio
    async def test_create_variations_button_exists(self) -> None:
        """Test that Create Variations button exists on result view."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = ImageGenerationResultView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            image_data=create_mock_image_data(),
            prompt="A sunset",
        )

        button_labels = [
            child.label for child in view.children if hasattr(child, "label")
        ]
        assert "Create Variations" in button_labels

    @pytest.mark.asyncio
    async def test_create_variations_rejects_without_dependencies(self) -> None:
        """Test Create Variations button rejects when dependencies missing."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = ImageGenerationResultView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            image_data=create_mock_image_data(),
            prompt="A sunset",
            image_provider=None,
            rate_limiter=None,
        )

        # Find the create variations button
        button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Create Variations"
        )

        await button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "not available" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_variations_rejects_wrong_user(self) -> None:
        """Test Create Variations button rejects non-original users."""
        interaction = create_mock_interaction(user_id=99999)  # Different user
        message = create_mock_message()

        view = ImageGenerationResultView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),  # user_id = 12345
            image_data=create_mock_image_data(),
            prompt="A sunset",
        )

        # Find the create variations button
        button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Create Variations"
        )

        await button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs["ephemeral"] is True


class TestImageEditResultViewTransition:
    """Tests for ImageEditResultView -> VariationCarouselView transition."""

    @pytest.mark.asyncio
    async def test_create_variations_button_exists(self) -> None:
        """Test that Create Variations button exists on edit result view."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = ImageEditResultView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            result_image_data=create_mock_image_data("result"),
            source_image_data_list=[create_mock_image_data("source")],
            prompt="Add a hat",
        )

        button_labels = [
            child.label for child in view.children if hasattr(child, "label")
        ]
        assert "Create Variations" in button_labels

    @pytest.mark.asyncio
    async def test_create_variations_rejects_without_dependencies(self) -> None:
        """Test Create Variations button rejects when dependencies missing."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = ImageEditResultView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            result_image_data=create_mock_image_data("result"),
            source_image_data_list=[create_mock_image_data("source")],
            prompt="Add a hat",
            image_provider=None,
            rate_limiter=None,
        )

        # Find the create variations button
        button = next(
            child for child in view.children
            if hasattr(child, "label") and child.label == "Create Variations"
        )

        await button.callback(interaction)

        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "not available" in call_args[0][0]


class TestButtonStateManagement:
    """Tests for button enable/disable state management."""

    @pytest.mark.asyncio
    async def test_buttons_disabled_during_generation(self) -> None:
        """Test that all buttons are disabled during generation."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        view._disable_all_buttons()

        for child in view.children:
            if isinstance(child, discord.ui.Button) and not child.url:
                assert child.disabled is True

    @pytest.mark.asyncio
    async def test_buttons_update_after_variation_added(self) -> None:
        """Test that button states update correctly after adding variation."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        # Initially at index 0 with no variations
        view._update_buttons()
        assert view.previous_button.disabled is True
        assert view.next_button.disabled is True

        # Add variation and move to it
        view.variations.append(create_mock_image_data("v1"))
        view.current_index = 1
        view._update_buttons()

        # Now can go back but not forward
        assert view.previous_button.disabled is False
        assert view.next_button.disabled is True

    @pytest.mark.asyncio
    async def test_variation_buttons_disabled_at_max(self) -> None:
        """Test variation buttons are disabled at max variations."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )

        # Initially enabled
        view._update_buttons()
        assert view.same_prompt_button.disabled is False
        assert view.ai_remix_button.disabled is False

        # Add 3 variations (max)
        view.variations = [
            create_mock_image_data("v1"),
            create_mock_image_data("v2"),
            create_mock_image_data("v3"),
        ]
        view._update_buttons()

        # Now disabled
        assert view.same_prompt_button.disabled is True
        assert view.ai_remix_button.disabled is True


class TestTimeoutBehavior:
    """Tests for view timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_without_selection_shows_error(self) -> None:
        """Test that timeout without selection shows error state."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )
        # Initialize embed with content so it's truthy (empty Embed is falsy)
        view.embed = discord.Embed(title="Image Variations", description="Initial")

        # Simulate timeout without adding to context
        await view.on_timeout()

        assert "timed out" in str(view.embed.description).lower()
        assert "NOT added to context" in view.embed.description

    @pytest.mark.asyncio
    async def test_timeout_after_selection_preserves_state(self) -> None:
        """Test that timeout after Add to Context preserves success state."""
        interaction = create_mock_interaction()
        message = create_mock_message()

        view = VariationCarouselView(
            interaction=interaction,
            message=message,
            user=create_mock_user(),
            original_image=create_mock_image_data(),
            prompt="Test",
        )
        view.embed = discord.Embed()
        view.added_to_context = True

        await view.on_timeout()

        # Should not show error message since image was added
        assert "NOT added to context" not in str(view.embed.description or "")
