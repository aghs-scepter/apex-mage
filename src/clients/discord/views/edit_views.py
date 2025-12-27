"""Edit-related modals and views for Discord UI.

This module contains modals and views for image editing workflows,
including prompt entry, preview, and confirmation.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

from src.clients.discord.constants import EMBED_COLOR_INFO, USER_INTERACTION_TIMEOUT
from src.clients.discord.utils import get_user_info
from src.clients.discord.views.base_views import create_file_from_image
from src.core.image_utils import create_composite_thumbnail
from src.core.logging import get_logger

if TYPE_CHECKING:
    pass

__all__ = [
    "ImageEditPromptModal",
    "EditPromptEditModal",
    "EditPromptPreviewView",
]

logger = get_logger(__name__)


class ImageEditPromptModal(discord.ui.Modal, title="Image Edit Instructions"):
    """Modal for entering image edit prompt.

    Shows a preview screen after submission where user can revise the prompt
    up to 3 times before applying the edit.
    """

    def __init__(
        self,
        image_data: dict[str, str],
        edit_type: str,
        user: dict[str, Any] | None,
        message: discord.Message | None,
        initial_text: str = "",
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
        image_data_list: list[dict[str, str]] | None = None,
    ) -> None:
        # timeout=None ensures download button remains functional indefinitely
        super().__init__(timeout=None)
        self.image_data = image_data
        self.image_data_list = image_data_list or [image_data]
        self.edit_type = edit_type
        self.user = user
        self.message = message
        self.on_select = on_select

        self.prompt: discord.ui.TextInput[ImageEditPromptModal] = discord.ui.TextInput(
            label="Enter your prompt:",
            style=discord.TextStyle.paragraph,
            placeholder=(
                "Describe how you want to modify this image. "
                "NOTE: Closing this window will cancel your edit request."
            ),
            required=True,
            max_length=1000,
            default=initial_text,
        )
        self.add_item(self.prompt)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Show preview view instead of calling on_select directly."""
        if self.on_select:
            # Defer interaction and show preview view
            await interaction.response.defer()

            preview_view = EditPromptPreviewView(
                interaction=interaction,
                image_data=self.image_data,
                edit_type=self.edit_type,
                prompt=self.prompt.value,
                user=self.user,
                message=self.message,
                on_select=self.on_select,
                image_data_list=self.image_data_list,
                edit_count=0,
            )
            await preview_view.initialize(interaction)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        logger.error("modal_error", view="ImageEditPromptModal", error=str(error))

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


class EditPromptEditModal(discord.ui.Modal, title="Edit Prompt"):
    """Modal for editing the edit prompt during cycling.

    Allows users to revise their edit prompt before applying.
    Limited to 1000 characters to match ImageEditPromptModal.
    """

    def __init__(
        self,
        current_prompt: str,
        on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the edit prompt modal.

        Args:
            current_prompt: The current prompt text to edit.
            on_submit: Callback when the modal is submitted with the new prompt.
        """
        super().__init__()
        self.on_submit_callback = on_submit

        self.prompt: discord.ui.TextInput[EditPromptEditModal] = discord.ui.TextInput(
            label="Edit your prompt:",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=current_prompt,
            placeholder="Describe how you want to modify the image...",
        )
        self.add_item(self.prompt)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await self.on_submit_callback(interaction, self.prompt.value)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle errors during modal submission."""
        logger.error("modal_error", view="EditPromptEditModal", error=str(error))

        try:
            await interaction.response.send_message(
                "An error occurred while processing your edit. Please try again.",
                ephemeral=True,
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send(
                "An error occurred while processing your edit. Please try again.",
                ephemeral=True,
            )


class EditPromptPreviewView(discord.ui.View):
    """View for previewing an edit prompt before applying.

    Shows the edit prompt in an embed with action buttons to apply, edit, or cancel.
    Supports prompt cycling with up to 3 edits total.

    Button layout: Apply Edit (green), Edit Prompt (blurple), X (red)

    Edit Prompt allows up to 3 edits total. After the 2nd edit, a warning is shown
    that only one more edit is allowed.
    """

    MAX_EDITS = 3

    def __init__(
        self,
        interaction: discord.Interaction,
        image_data: dict[str, str],
        edit_type: str,
        prompt: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
        image_data_list: list[dict[str, str]] | None = None,
        edit_count: int = 0,
    ) -> None:
        """Initialize the edit prompt preview view.

        Args:
            interaction: The Discord interaction that triggered this view.
            image_data: Dict with 'filename' and 'image' (base64) keys.
            edit_type: The type of edit ("Edit" or "AI Assist").
            prompt: The edit prompt to preview.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional existing message to update.
            on_select: Callback when user confirms the edit.
            image_data_list: List of all selected images for multi-image edits.
            edit_count: Number of edits already made (for cycling).
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.interaction = interaction
        self.image_data = image_data
        self.image_data_list = image_data_list or [image_data]
        self.edit_type = edit_type
        self.prompt = prompt
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.on_select = on_select
        self.edit_count = edit_count
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Display the preview embed with action buttons.

        Args:
            interaction: The Discord interaction.
        """
        await self._display_preview(interaction)

    async def _display_preview(self, interaction: discord.Interaction) -> None:
        """Display the prompt preview with action buttons.

        Args:
            interaction: The Discord interaction.
        """
        # Build prompt text with optional warning
        prompt_text = self.prompt
        if self.edit_count == self.MAX_EDITS - 1:
            # After 2nd edit (edit_count=2), show warning before 3rd edit
            prompt_text = (
                f"{self.prompt}\n\n"
                "**You can edit the prompt one more time before further editing is disabled.**"
            )

        num_images = len(self.image_data_list)
        title = "Edit Preview" if num_images == 1 else f"Edit Preview ({num_images} images)"

        self.embed = discord.Embed(
            title=title,
            description=prompt_text,
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Create thumbnail: composite for 2+ images, single for 1 image
        if num_images > 1:
            image_strings = [img["image"] for img in self.image_data_list]
            composite_b64 = await asyncio.to_thread(
                create_composite_thumbnail, image_strings
            )
            display_image_data = {"filename": "composite.jpeg", "image": composite_b64}
        else:
            display_image_data = self.image_data

        embed_image = await create_file_from_image(display_image_data)
        self.embed.set_thumbnail(url=f"attachment://{embed_image.filename}")

        # Set button states
        self.apply_button.disabled = False
        self.edit_prompt_button.disabled = self.edit_count >= self.MAX_EDITS

        # Update the message
        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )
        elif interaction.response.is_done():
            self.message = await interaction.edit_original_response(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )
        else:
            self.message = await interaction.followup.send(
                embed=self.embed,
                file=embed_image,
                view=self,
                wait=True,
            )

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    async def _handle_edit_submit(
        self, interaction: discord.Interaction, new_prompt: str
    ) -> None:
        """Handle edit prompt modal submission - cycle back to same view.

        Args:
            interaction: The Discord interaction from the modal.
            new_prompt: The new prompt text.
        """
        # Increment edit count and cycle back to this view with new prompt
        new_edit_count = self.edit_count + 1

        # Create new view with updated prompt and edit count
        new_view = EditPromptPreviewView(
            interaction=interaction,
            image_data=self.image_data,
            edit_type=self.edit_type,
            prompt=new_prompt,
            user=self.user,
            message=self.message,
            on_select=self.on_select,
            image_data_list=self.image_data_list,
            edit_count=new_edit_count,
        )

        # Respond to modal and initialize new view
        await interaction.response.defer()
        self.stop()
        await new_view.initialize(interaction)

    @discord.ui.button(label="Apply Edit", style=discord.ButtonStyle.success, row=0)
    async def apply_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptPreviewView"],
    ) -> None:
        """Apply the edit with the current prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.stop()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)
            await self.on_select(interaction, self.edit_type, self.prompt)

    @discord.ui.button(label="Edit Prompt", style=discord.ButtonStyle.primary, row=0)
    async def edit_prompt_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptPreviewView"],
    ) -> None:
        """Open modal to edit the prompt, then cycle back to same view."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can edit this.",
                ephemeral=True,
            )
            return

        if self.edit_count >= self.MAX_EDITS:
            await interaction.response.send_message(
                "Maximum number of edits reached.",
                ephemeral=True,
            )
            return

        modal = EditPromptEditModal(
            current_prompt=self.prompt,
            on_submit=self._handle_edit_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptPreviewView"],
    ) -> None:
        """Cancel the edit flow."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can cancel this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()

        if self.embed:
            self.embed.title = "Edit Cancelled"
            self.embed.description = "Image editing was cancelled."
            self.embed.set_thumbnail(url=None)

        if self.message:
            await self.message.edit(embed=self.embed, attachments=[], view=self)

        if self.on_select:
            await self.on_select(interaction, "Cancel", "")

        self.stop()

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
            self.embed.set_thumbnail(url=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            except discord.NotFound:
                pass  # Message deleted, expected
            except discord.HTTPException as e:
                logger.warning("message_edit_failed", error=str(e))
