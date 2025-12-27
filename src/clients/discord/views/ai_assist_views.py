"""AI Assist views for Discord UI.

This module contains views for the AI-powered prompt refinement workflow.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

from src.clients.discord.constants import (
    EMBED_COLOR_ERROR,
    EMBED_COLOR_INFO,
    USER_INTERACTION_TIMEOUT,
)
from src.clients.discord.utils import get_user_info
from src.clients.discord.views.base_views import create_file_from_image
from src.core.haiku import HaikuError, haiku_complete
from src.core.logging import get_logger
from src.core.prompts.refinement import IMAGE_MODIFICATION_REFINEMENT_PROMPT

if TYPE_CHECKING:
    pass

__all__ = [
    "AIAssistModal",
    "AIAssistResultView",
    "AIAssistErrorView",
]

logger = get_logger(__name__)


class AIAssistModal(discord.ui.Modal, title="AI Assist - Describe Your Edit"):
    """Modal for entering a rough description that AI will refine into a detailed edit prompt."""

    def __init__(
        self,
        image_data: dict[str, str],
        user: dict[str, Any] | None,
        message: discord.Message | None,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=None)
        self.image_data = image_data
        self.user = user
        self.message = message
        self.on_select = on_select

        self.description: discord.ui.TextInput[AIAssistModal] = discord.ui.TextInput(
            label="Describe what changes you want:",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your desired changes (e.g., 'darker', 'sunset background')",
            required=True,
            max_length=500,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission by calling Haiku to refine the prompt."""
        # Import here to avoid circular imports
        from src.clients.discord.views.edit_views import EditPromptPreviewView

        await interaction.response.defer()

        rough_description = self.description.value

        # Call Haiku to refine the prompt with retry logic
        refined_prompt = None
        last_error = None

        for attempt in range(2):  # Try twice (initial + 1 retry)
            try:
                refined_prompt = await haiku_complete(
                    system_prompt=IMAGE_MODIFICATION_REFINEMENT_PROMPT,
                    user_message=rough_description,
                    max_tokens=256,
                )
                break  # Success, exit retry loop
            except HaikuError as e:
                last_error = e
                logger.warning(
                    "ai_assist_haiku_error",
                    view="AIAssistModal",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt == 0:
                    # Wait briefly before retry
                    await asyncio.sleep(1.0)
                continue

        if refined_prompt is None:
            # Both attempts failed, show error with fallback
            logger.error(
                "ai_assist_haiku_failed",
                view="AIAssistModal",
                error=str(last_error),
            )

            error_view = AIAssistErrorView(
                image_data=self.image_data,
                user=self.user,
                message=self.message,
                rough_description=rough_description,
                on_select=self.on_select,
            )
            await error_view.initialize(interaction)
            return

        # Show the edit preview directly with refined prompt
        preview_view = EditPromptPreviewView(
            interaction=interaction,
            image_data=self.image_data,
            edit_type="AI Assist",
            prompt=refined_prompt,
            user=self.user,
            message=self.message,
            on_select=self.on_select,
        )
        await preview_view.initialize(interaction)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        logger.error("modal_error", view="AIAssistModal", error=str(error))

        try:
            await interaction.response.send_message(
                "An error occurred while processing your request. Please try again.",
                ephemeral=True,
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send(
                "An error occurred while processing your request. Please try again.",
                ephemeral=True,
            )


class AIAssistResultView(discord.ui.View):
    """View to display refined prompt and allow user to use, edit, or cancel."""

    def __init__(
        self,
        image_data: dict[str, str],
        user: dict[str, Any] | None,
        message: discord.Message | None,
        rough_description: str,
        refined_prompt: str,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.image_data = image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.rough_description = rough_description
        self.refined_prompt = refined_prompt
        self.on_select = on_select
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Display the refined prompt to the user."""
        self.embed = discord.Embed(
            title="AI-Refined Edit Prompt",
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        self.embed.add_field(
            name="Your Description",
            value=self.rough_description[:1024],  # Discord field limit
            inline=False,
        )
        self.embed.add_field(
            name="Refined Prompt",
            value=self.refined_prompt[:1024],  # Discord field limit
            inline=False,
        )

        # Add image to embed as main image (not thumbnail)
        embed_image = await create_file_from_image(self.image_data)
        self.embed.set_image(url=f"attachment://{embed_image.filename}")

        if self.message:
            await self.message.edit(embed=self.embed, view=self, attachments=[embed_image])

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Use This", style=discord.ButtonStyle.success, row=0)
    async def use_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistResultView"]
    ) -> None:
        """Show preview view with the refined prompt."""
        # Import here to avoid circular imports
        from src.clients.discord.views.edit_views import EditPromptPreviewView

        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            await interaction.response.defer()
            self.stop()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)

            # Show preview view with refined prompt
            preview_view = EditPromptPreviewView(
                interaction=interaction,
                image_data=self.image_data,
                edit_type="Edit",
                prompt=self.refined_prompt,
                user=self.user,
                message=self.message,
                on_select=self.on_select,
                edit_count=0,
            )
            await preview_view.initialize(interaction)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.success, row=0)
    async def edit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistResultView"]
    ) -> None:
        """Open prompt modal with refined prompt pre-filled for editing."""
        # Import here to avoid circular imports
        from src.clients.discord.views.edit_views import ImageEditPromptModal

        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.stop()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)

            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Edit",
                user=self.user,
                message=self.message,
                initial_text=self.refined_prompt,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistResultView"]
    ) -> None:
        """Cancel and return to previous state."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.stop()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "AI Assist Cancelled"
            self.embed.description = "Prompt refinement was cancelled."
            self.embed.clear_fields()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Handle timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
            self.embed.clear_fields()
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except discord.NotFound:
                pass  # Message deleted, expected
            except discord.HTTPException as e:
                logger.warning("message_edit_failed", error=str(e))


class AIAssistErrorView(discord.ui.View):
    """View shown when AI assist fails, offering fallback to manual entry."""

    def __init__(
        self,
        image_data: dict[str, str],
        user: dict[str, Any] | None,
        message: discord.Message | None,
        rough_description: str,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.image_data = image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.rough_description = rough_description
        self.on_select = on_select
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Display the error message with fallback option."""
        self.embed = discord.Embed(
            title="AI Assist Unavailable",
            description=(
                "Unable to refine your prompt at this time. "
                "You can enter your edit instructions manually instead."
            ),
            color=EMBED_COLOR_ERROR,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        self.embed.add_field(
            name="Your Description",
            value=self.rough_description[:1024],
            inline=False,
        )

        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Enter Manually", style=discord.ButtonStyle.primary, row=0)
    async def enter_manually_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistErrorView"]
    ) -> None:
        """Open manual prompt entry modal with the rough description pre-filled."""
        # Import here to avoid circular imports
        from src.clients.discord.views.edit_views import ImageEditPromptModal

        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.stop()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)

            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Edit",
                user=self.user,
                message=self.message,
                initial_text=self.rough_description,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistErrorView"]
    ) -> None:
        """Cancel the operation."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.stop()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Image editing was cancelled."
            self.embed.clear_fields()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Handle timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
            self.embed.clear_fields()
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except discord.NotFound:
                pass  # Message deleted, expected
            except discord.HTTPException as e:
                logger.warning("message_edit_failed", error=str(e))
