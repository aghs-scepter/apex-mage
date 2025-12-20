"""Discord UI components for carousel and embed views."""

import asyncio
import base64
import io
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

from src.core.image_utils import (
    compress_image,
    create_composite_thumbnail,
    image_strip_headers,
)
from src.core.logging import get_logger
from src.core.providers import ImageModifyRequest

if TYPE_CHECKING:
    from src.adapters.repository_compat import RepositoryAdapter
    from src.core.providers import ImageProvider
    from src.core.rate_limit import SlidingWindowRateLimiter

logger = get_logger(__name__)

EMBED_COLOR_ERROR = 0xE91515
EMBED_COLOR_INFO = 0x3498DB


def get_user_info(user: dict[str, Any] | None) -> tuple[str, int, str]:
    """Get username, user ID, and avatar from a user dict.

    Args:
        user: Dict with name, id, and pfp keys, or None.

    Returns:
        Tuple of (username, user_id, avatar_url).
    """
    if user:
        return user["name"], user["id"], user["pfp"]
    return (
        "System",
        0,
        "https://github.com/aghs-scepter/apex-mage/raw/main/assets/default_pfp.png",
    )


async def create_file_from_image(image_data: dict[str, str]) -> discord.File:
    """Create a discord.File object from base64 image data.

    Args:
        image_data: Dict with 'filename' and 'image' (base64) keys.

    Returns:
        A discord.File ready for attachment.
    """
    file_data = io.BytesIO(base64.b64decode(image_data["image"]))
    file_data.seek(0)
    return discord.File(file_data, filename=image_data["filename"], spoiler=False)


class InfoEmbedView(discord.ui.View):
    """A view that displays an informational or error message in an embed."""

    def __init__(
        self,
        message: discord.Message | None = None,
        user: dict[str, Any] | None = None,
        title: str = "Default Title",
        description: str | None = None,
        is_error: bool = False,
        image_data: dict[str, str] | None = None,
        notes: list[dict[str, str]] | None = None,
        full_response_url: str | None = None,
        full_prompt_url: str | None = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.title = title
        self.message = message
        self.description = description
        self.is_error = is_error
        self.image_data = image_data
        self.notes = notes
        self.full_response_url = full_response_url
        self.full_prompt_url = full_prompt_url
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the embed."""
        self.embed = discord.Embed(
            title=self.title,
            color=EMBED_COLOR_ERROR if self.is_error else EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        if self.description:
            self.embed.description = self.description

        if self.notes:
            for note in self.notes:
                self.embed.add_field(
                    name=note["name"],
                    value=note["value"],
                    inline=False,
                )

        # Add view full response button if URL is provided
        if self.full_response_url:
            self.add_item(
                discord.ui.Button(
                    label="View Full Response",
                    url=self.full_response_url,
                    style=discord.ButtonStyle.link,
                )
            )

        # Add view full prompt button if URL is provided
        if self.full_prompt_url:
            self.add_item(
                discord.ui.Button(
                    label="View Full Prompt",
                    url=self.full_prompt_url,
                    style=discord.ButtonStyle.link,
                )
            )

        if self.image_data:
            embed_image = await create_file_from_image(self.image_data)
            self.embed.set_image(url=f"attachment://{embed_image.filename}")

            if interaction.response.is_done():
                await interaction.edit_original_response(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            else:
                await interaction.followup.send(
                    embed=self.embed,
                    file=embed_image,
                    view=self,
                )
        else:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    attachments=[],
                    embed=self.embed,
                    view=self,
                )
            else:
                await interaction.followup.send(
                    embed=self.embed,
                    view=self,
                )


class UnauthorizedModal(discord.ui.Modal):
    """Modal shown when unauthorized user tries to interact."""

    def init(self) -> None:
        super().__init__(title="Not Allowed")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class ClearHistoryConfirmationView(discord.ui.View):
    """View for confirming history clear operation."""

    def __init__(
        self,
        interaction: discord.Interaction,
        user: dict[str, Any] | None = None,
        on_select: (
            Callable[[discord.Interaction, dict[str, Any] | None, bool], Coroutine[Any, Any, None]]
            | None
        ) = None,
    ) -> None:
        super().__init__(timeout=60.0)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None
        self.on_select = on_select

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the confirmation embed."""
        self.embed = discord.Embed(
            title="Clear history confirmation",
            description=(
                "Are you sure you want to clear the bot's history in this channel? "
                "All prior messages and images will be forgotten and you will not "
                "be able to access them."
            ),
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )

    def disable_buttons(self) -> None:
        """Disable all buttons in the view."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ClearHistoryConfirmationView"]
    ) -> None:
        await interaction.response.defer()
        self.hide_buttons()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        if self.on_select:
            await self.on_select(interaction, self.user, True)

    @discord.ui.button(label="Never Mind", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ClearHistoryConfirmationView"]
    ) -> None:
        await interaction.response.defer()
        self.hide_buttons()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        if self.on_select:
            await self.on_select(interaction, self.user, False)


class ImageSelectionTypeView(discord.ui.View):
    """View for selecting how to choose an image for a request."""

    def __init__(
        self,
        interaction: discord.Interaction,
        user: dict[str, Any] | None = None,
        on_select: (
            Callable[[discord.Interaction, str], Coroutine[Any, Any, None]] | None
        ) = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None
        self.on_select = on_select
        self.repo = repo

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the image selection type modal."""
        self.embed = discord.Embed(
            title="Image Selection Type",
            description="Select an option to choose an image for your request.",
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Check if the channel has recent images
        has_previous_image = False
        has_recent_images = False
        if self.repo and interaction.channel_id is not None:
            has_recent_images = await self.repo.has_images_in_context(
                interaction.channel_id, "All Models"
            )

        self.update_buttons(has_previous_image, has_recent_images)
        logger.debug("embed_created", view="ImageSelectionTypeModal")

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )

        logger.debug("view_initialized", view="ImageSelectionTypeModal")

    def update_buttons(
        self, has_previous_image: bool, has_recent_images: bool
    ) -> None:
        """Update button states based on available images."""
        self.last_image_button.disabled = not has_previous_image
        self.recent_images_button.disabled = not has_recent_images

    def disable_buttons(self) -> None:
        """Disable all selection buttons."""
        self.last_image_button.disabled = True
        self.recent_images_button.disabled = True
        self.cancel_button.disabled = True

    def hide_buttons(self) -> None:
        """Remove all selection buttons."""
        self.clear_items()

    async def disable_embed(self, interaction: discord.Interaction) -> None:
        """Disable further interaction with the embed."""
        if self.embed:
            self.embed.description = f"Command cancelled by {self.username}."

        self.hide_buttons()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(
        label="Google (disabled)", style=discord.ButtonStyle.primary, disabled=True
    )
    async def last_image_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageSelectionTypeView"]
    ) -> None:
        """Use most recently selected or uploaded image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.hide_buttons()
            await self.on_select(interaction, "My Last Image")

    @discord.ui.button(label="Recent Images", style=discord.ButtonStyle.primary)
    async def recent_images_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageSelectionTypeView"]
    ) -> None:
        """Select a recent image from a carousel."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.hide_buttons()
            await self.on_select(interaction, "Recent Images")

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageSelectionTypeView"]
    ) -> None:
        """Cancel selection."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            await interaction.response.defer()
            self.hide_buttons()
            if self.embed:
                self.embed.title = "Operation Cancelled"
                self.embed.description = "Image modification was cancelled."
            if self.message:
                await self.message.edit(embed=self.embed, view=self)
            await self.on_select(interaction, "Cancel")

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class ImageCarouselView(discord.ui.View):
    """A view that provides a simple image carousel."""

    def __init__(
        self,
        interaction: discord.Interaction,
        files: list[dict[str, str]],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[[discord.Interaction, dict[str, str] | None], Coroutine[Any, Any, None]]
            | None
        ) = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.files = files
        self.embed_image: discord.File | None = None
        self.current_index = 0
        self.on_select = on_select
        self.message = message
        self.healthy = bool(self.files)

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the image carousel view."""
        if not self.healthy:
            self.embed, self.embed_image = await self.create_error_embed(
                interaction,
                "ERROR: There are no images in context. "
                "Add or generate an image to use this feature.",
            )
            self.hide_buttons()
            logger.error("carousel_no_files", view="ImageCarouselView")
        else:
            self.embed, self.embed_image = await self.create_embed(interaction)
            self.update_buttons()
            logger.debug("embed_created", view="ImageCarouselView")

        if self.message:
            if self.embed_image:
                await self.message.edit(
                    attachments=[self.embed_image],
                    embed=self.embed,
                    view=self,
                )
            else:
                await self.message.edit(
                    embed=self.embed,
                    view=self,
                )
        logger.debug("view_initialized", view="ImageCarouselView")

    def generate_image_chrono_bar(self, current_index: int, total: int) -> str:
        """Generate a visual position indicator for the carousel."""
        bar_icons = ""
        for i in range(total):
            bar_icons += "\u2b25" if i == current_index else "\u2b26"
        return f"(Newest) {bar_icons} (Oldest)"

    async def create_error_embed(
        self, interaction: discord.Interaction, error_message: str
    ) -> tuple[discord.Embed, None]:
        """Create an error embed."""
        embed = discord.Embed(title="Error Message", description=error_message)
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        return embed, None

    def get_current_file(self) -> dict[str, str]:
        """Return the image file data of the currently shown image."""
        return self.files[self.current_index]

    def disable_buttons(self) -> None:
        """Disable all navigation and selection buttons."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def hide_buttons(self) -> None:
        """Remove all navigation and selection buttons."""
        self.clear_items()

    def update_buttons(self) -> None:
        """Update button states for navigation bounds."""
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= len(self.files) - 1

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.disable_buttons()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
            self.embed.set_image(url=None)
        try:
            if self.message:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
        except Exception:
            pass  # Message may have been deleted

    async def create_embed(
        self, interaction: discord.Interaction
    ) -> tuple[discord.Embed, discord.File]:
        """Create the carousel embed with current image."""
        embed_image = await create_file_from_image(self.files[self.current_index])

        embed = discord.Embed(
            title="Select an Image",
            description=self.generate_image_chrono_bar(
                self.current_index, len(self.files)
            ),
        )
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        embed.set_image(url=f"attachment://{embed_image.filename}")

        return embed, embed_image

    async def disable_embed(self, interaction: discord.Interaction) -> None:
        """Disable further interaction with the embed."""
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        if self.embed:
            self.embed.description = "Image selection closed."
            self.embed.set_image(url=f"attachment://{self.embed_image.filename}")

        self.hide_buttons()
        if self.message:
            await self.message.edit(
                attachments=[self.embed_image],
                embed=self.embed,
                view=self,
            )

    async def update_embed(self, interaction: discord.Interaction) -> None:
        """Update the embed with the current image after navigation."""
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        if self.embed:
            self.embed.description = self.generate_image_chrono_bar(
                self.current_index, len(self.files)
            )
            self.embed.set_image(url=f"attachment://{self.embed_image.filename}")

        self.update_buttons()

        if self.message:
            await self.message.edit(
                attachments=[self.embed_image],
                embed=self.embed,
                view=self,
            )

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageCarouselView"]
    ) -> None:
        """Navigate to previous image."""
        await interaction.response.defer()
        if self.current_index > 0:
            self.current_index -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageCarouselView"]
    ) -> None:
        """Navigate to next image."""
        await interaction.response.defer()
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            await self.update_embed(interaction)

    @discord.ui.button(label="Select", style=discord.ButtonStyle.success)
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageCarouselView"]
    ) -> None:
        """Accept current image selection."""
        if self.on_select:
            await interaction.response.defer()
            selected_image = self.get_current_file()
            self.disable_buttons()
            await self.on_select(interaction, selected_image)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageCarouselView"]
    ) -> None:
        """Cancel image selection."""
        if self.on_select:
            await interaction.response.defer()
            self.hide_buttons()
            if self.embed:
                self.embed.title = "Selection Cancelled"
                self.embed.description = "Image selection was cancelled."
                self.embed.set_image(url=None)
            if self.message:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            await self.on_select(interaction, None)


class ImageEditTypeView(discord.ui.View):
    """A view that displays buttons for different image editing options.

    Supports both single-image and multi-image display. When image_data_list
    contains 2+ images, displays a composite thumbnail instead of a single image.
    """

    def __init__(
        self,
        image_data: dict[str, str],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
        image_data_list: list[dict[str, str]] | None = None,
        on_back: (
            Callable[[discord.Interaction], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__()
        self.image_data = image_data
        self.image_data_list = image_data_list or [image_data]
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message = message
        self.on_select = on_select
        self.on_back = on_back
        logger.debug("view_initialized", view="ImageEditTypeView")

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the view with the image and buttons.

        If multiple images are selected, displays a composite thumbnail.
        Otherwise displays the single selected image.
        """
        num_images = len(self.image_data_list)
        title = "Edit Image" if num_images == 1 else f"Edit Images ({num_images})"

        # Build description with optional multi-image instructions
        description = "Choose how to modify your images, or go back to change your selection."
        if num_images > 1:
            description += (
                "\n\nReference images by description (e.g., 'the sunset photo'), "
                "not by position—the AI sees them together without a specific order."
            )

        self.embed = discord.Embed(title=title, description=description)
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
        self.embed.set_image(url=f"attachment://{embed_image.filename}")

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )
        logger.debug("embed_displayed", view="ImageEditTypeView")

    def disable_buttons(self) -> None:
        """Disable all buttons in the view."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        logger.debug("buttons_disabled", view="ImageEditTypeView")

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()
        logger.debug("buttons_hidden", view="ImageEditTypeView")

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, row=0)
    async def edit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageEditTypeView"]
    ) -> None:
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.",
                    ephemeral=True,
                )
                return

            self.disable_buttons()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)

            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Edit",
                user=self.user,
                message=self.message,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageEditTypeView"]
    ) -> None:
        """Return to the image selection carousel."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_back:
            await interaction.response.defer()
            self.hide_buttons()
            await self.on_back(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageEditTypeView"]
    ) -> None:
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer()
            self.disable_buttons()
            self.hide_buttons()
            if self.embed:
                self.embed.title = "Edit Cancelled"
                self.embed.description = "Image editing was cancelled."
                self.embed.set_image(url=None)
            if self.message:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            await self.on_select(interaction, "Cancel", "")

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
            self.embed.set_image(url=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            except Exception:
                pass  # Message may have been deleted


class ImageEditPromptModal(discord.ui.Modal, title="Image Edit Instructions"):
    """Modal for entering image edit prompt."""

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
    ) -> None:
        super().__init__()
        self.image_data = image_data
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
        if self.on_select:
            await self.on_select(interaction, self.edit_type, self.prompt.value)

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


class ImageEditPerformView(discord.ui.View):
    """A view that handles performing an image edit operation.

    Supports both single-image and multi-image modification. When image_data_list
    is provided, all images are sent to the API; otherwise only image_data is used.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
        user: dict[str, Any] | None,
        image_data: dict[str, str],
        edit_type: str,
        prompt: str = "`placeholder`",
        on_complete: (
            Callable[[discord.Interaction, dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        image_provider: "ImageProvider | None" = None,
        image_data_list: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.interaction = interaction
        self.prompt = prompt
        self.message = message
        self.user = user
        self.image_data = image_data
        self.image_data_list = image_data_list or [image_data]
        self.edit_type = edit_type
        self.on_complete = on_complete
        self.rate_limiter = rate_limiter
        self.image_provider = image_provider
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the initial 'processing' embed.

        If multiple images are selected, displays a composite thumbnail.
        Otherwise displays the single selected image.
        """
        num_images = len(self.image_data_list)
        image_count_text = f" ({num_images} image{'s' if num_images != 1 else ''})"

        self.embed = discord.Embed(
            title="Image modification in progress",
            description=(
                f"Modifying your image{image_count_text}... "
                "(This may take up to 180 seconds)"
            ),
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

        await self.message.edit(
            embed=self.embed,
            attachments=[embed_image],
            view=self,
        )

        await self.perform_edit(self.prompt)

    async def on_timeout(self) -> None:
        """Update the embed with a timeout message."""
        if self.embed:
            self.embed.title = "Edit Timed Out"
            self.embed.description = (
                "The image edit operation timed out. Please try again."
            )
            self.embed.color = EMBED_COLOR_ERROR

        try:
            await self.message.edit(
                attachments=[],
                embed=self.embed,
                view=None,
            )
        except Exception:
            pass

    async def perform_edit(self, prompt: str) -> None:
        """Perform the actual image modification using the AI service."""
        try:
            # Check rate limits
            if self.rate_limiter:
                rate_check = await self.rate_limiter.check(
                    self.interaction.user.id, "image"
                )
                if not rate_check.allowed:
                    wait_msg = (
                        f" Try again in {int(rate_check.wait_seconds)} seconds."
                        if rate_check.wait_seconds
                        else ""
                    )
                    error_data = {
                        "error": True,
                        "message": (
                            "Rate limit exceeded. "
                            f"Please wait before requesting more image edits.{wait_msg}"
                        ),
                    }
                    if self.on_complete:
                        await self.on_complete(self.interaction, error_data)
                    return

            # Perform the image modification
            # Note: guidance_scale is no longer used by nano-banana-pro/edit API
            if not self.image_provider:
                raise RuntimeError("Image provider not initialized")

            # Extract base64 image data from all selected images
            image_data_strings = [img["image"] for img in self.image_data_list]

            modified_images = await self.image_provider.modify(
                ImageModifyRequest(
                    prompt=prompt,
                    image_data=image_data_strings[0],  # For backward compatibility
                    image_data_list=image_data_strings,  # All images for multi-image
                    guidance_scale=0.0,  # Not used by nano-banana-pro/edit
                )
            )
            modified_image = modified_images[0]

            # Process the response
            if modified_image.url is None:
                raise ValueError("Modified image has no URL")
            result_image_data = image_strip_headers(modified_image.url, "jpeg")
            result_image_data = await asyncio.to_thread(compress_image, result_image_data)
            image_return = {
                "filename": "image.jpeg",
                "image": result_image_data,
                "prompt": prompt,
            }

            # Record the request after successful operation
            if self.rate_limiter:
                await self.rate_limiter.record(self.interaction.user.id, "image")

            # Call completion callback
            if self.on_complete:
                await self.on_complete(self.interaction, image_return)

        except Exception as ex:
            logger.error("image_edit_error", error=str(ex))
            error_data = {
                "error": True,
                "message": f"An error occurred while modifying the image: {ex}",
            }
            if self.on_complete:
                await self.on_complete(self.interaction, error_data)


class MultiImageCarouselView(discord.ui.View):
    """A view that provides a multi-image selection carousel.

    Allows users to select up to 3 images from a carousel of available images.
    Selected images can be used for multi-image modification operations.
    """

    MAX_SELECTIONS = 3

    def __init__(
        self,
        interaction: discord.Interaction,
        files: list[dict[str, str]],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[
                [discord.Interaction, list[dict[str, str]]],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        initial_selections: list[int] | None = None,
    ) -> None:
        """Initialize the multi-image carousel view.

        Args:
            interaction: The Discord interaction that triggered this view.
            files: List of image file dicts with 'filename' and 'image' keys.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional message to edit when updating the view.
            on_select: Callback when user confirms selection. Receives the
                interaction and list of selected image dicts. Empty list
                indicates cancellation.
            initial_selections: Optional list of pre-selected image indices
                for restoring state when navigating back.
        """
        super().__init__(timeout=180.0)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.files = files
        self.embed_image: discord.File | None = None
        self.current_index = 0
        self.selected_indices: list[int] = (
            list(initial_selections) if initial_selections else []
        )
        self.on_select = on_select
        self.message = message
        self.healthy = bool(self.files)

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the multi-image carousel view."""
        if not self.healthy:
            self.embed, self.embed_image = await self.create_error_embed(
                interaction,
                "ERROR: There are no images in context. "
                "Add or generate an image to use this feature.",
            )
            self.hide_buttons()
            logger.error("carousel_no_files", view="MultiImageCarouselView")
        else:
            self.embed, self.embed_image = await self.create_embed(interaction)
            self.update_buttons()
            logger.debug("embed_created", view="MultiImageCarouselView")

        if self.message:
            if self.embed_image:
                await self.message.edit(
                    attachments=[self.embed_image],
                    embed=self.embed,
                    view=self,
                )
            else:
                await self.message.edit(
                    embed=self.embed,
                    view=self,
                )
        logger.debug("view_initialized", view="MultiImageCarouselView")

    def is_current_selected(self) -> bool:
        """Check if the current image is in the selection."""
        return self.current_index in self.selected_indices

    def get_selected_images(self) -> list[dict[str, str]]:
        """Get the list of selected image data dicts."""
        return [self.files[i] for i in self.selected_indices]

    def generate_image_chrono_bar(self, current_index: int, total: int) -> str:
        """Generate a visual position indicator for the carousel.

        Uses two-line display format:
        - Position line: temporal labels with filled circle for current, empty for others
        - Selection line: checkmark for selected, ring for unselected (aligned)

        Example (viewing image 2, images 1 and 2 selected of 4 total):
            (Newest) ○ ● ○ ○ (Oldest)
                     ✓ ✓ ∘ ∘
        """
        position_symbols = []
        selected_symbols = []

        for i in range(total):
            # Position indicator: filled circle for current, empty for others
            if i == current_index:
                position_symbols.append("●")  # Black circle (U+25CF)
            else:
                position_symbols.append("○")  # White circle (U+25CB)

            # Selection indicator: checkmark for selected, ring for unselected
            if i in self.selected_indices:
                selected_symbols.append("✓")  # Checkmark (U+2713)
            else:
                selected_symbols.append("∘")  # Ring operator (U+2218)

        position_line = "(Newest) " + " ".join(position_symbols) + " (Oldest)"
        # Add 9 spaces to align selection symbols under position symbols
        selected_line = "         " + " ".join(selected_symbols)

        return f"{position_line}\n{selected_line}"

    async def create_error_embed(
        self, interaction: discord.Interaction, error_message: str
    ) -> tuple[discord.Embed, None]:
        """Create an error embed."""
        embed = discord.Embed(title="Error Message", description=error_message)
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        return embed, None

    async def create_embed(
        self, interaction: discord.Interaction
    ) -> tuple[discord.Embed, discord.File]:
        """Create the carousel embed with current image and selection status."""
        embed_image = await create_file_from_image(self.files[self.current_index])

        embed = discord.Embed(
            title="Select Images (up to 3)",
            description=self.generate_image_chrono_bar(
                self.current_index, len(self.files)
            ),
        )
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        embed.set_image(url=f"attachment://{embed_image.filename}")

        return embed, embed_image

    def disable_buttons(self) -> None:
        """Disable all navigation and selection buttons."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def hide_buttons(self) -> None:
        """Remove all navigation and selection buttons."""
        self.clear_items()

    def update_buttons(self) -> None:
        """Update button states based on current position and selection."""
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= len(self.files) - 1

        # Update toggle button based on current selection state
        if self.is_current_selected():
            self.toggle_button.label = "Remove"
            self.toggle_button.style = discord.ButtonStyle.danger
            self.toggle_button.disabled = False
        else:
            self.toggle_button.label = "Add"
            self.toggle_button.style = discord.ButtonStyle.success
            # Disable add if at max selections
            self.toggle_button.disabled = (
                len(self.selected_indices) >= self.MAX_SELECTIONS
            )

        # Continue button enabled when at least one image selected
        self.continue_button.disabled = len(self.selected_indices) == 0

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.disable_buttons()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
            self.embed.set_image(url=None)
            self.embed.clear_fields()
        try:
            if self.message:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
        except Exception:
            pass  # Message may have been deleted

    async def update_embed(self, interaction: discord.Interaction) -> None:
        """Update the embed with the current image after navigation or selection."""
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        if self.embed:
            self.embed.description = self.generate_image_chrono_bar(
                self.current_index, len(self.files)
            )
            self.embed.set_image(url=f"attachment://{self.embed_image.filename}")

        self.update_buttons()

        if self.message:
            await self.message.edit(
                attachments=[self.embed_image],
                embed=self.embed,
                view=self,
            )

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["MultiImageCarouselView"],
    ) -> None:
        """Navigate to previous image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if self.current_index > 0:
            self.current_index -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["MultiImageCarouselView"],
    ) -> None:
        """Navigate to next image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            await self.update_embed(interaction)

    @discord.ui.button(label="Add", style=discord.ButtonStyle.success)
    async def toggle_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["MultiImageCarouselView"],
    ) -> None:
        """Toggle selection of current image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if self.is_current_selected():
            self.selected_indices.remove(self.current_index)
        else:
            if len(self.selected_indices) < self.MAX_SELECTIONS:
                self.selected_indices.append(self.current_index)
        await self.update_embed(interaction)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["MultiImageCarouselView"],
    ) -> None:
        """Confirm selection and continue."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        if self.on_select:
            await interaction.response.defer()
            selected = self.get_selected_images()
            self.hide_buttons()
            await self.on_select(interaction, selected)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["MultiImageCarouselView"],
    ) -> None:
        """Cancel image selection."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        if self.on_select:
            await interaction.response.defer()
            self.hide_buttons()
            if self.embed:
                self.embed.title = "Selection Cancelled"
                self.embed.description = "Image selection was cancelled."
                self.embed.set_image(url=None)
                self.embed.clear_fields()
            if self.message:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            await self.on_select(interaction, [])  # Empty list = cancelled
