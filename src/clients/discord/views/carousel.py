"""Discord UI components for carousel and embed views."""

import asyncio
import base64
import io
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

from src.core.image_utils import compress_image, image_strip_headers
from src.core.providers import ImageRequest

if TYPE_CHECKING:
    from src.adapters.repository_compat import RepositoryAdapter
    from src.core.providers import ImageProvider
    from src.core.rate_limit import SlidingWindowRateLimiter

EMBED_COLOR_ERROR = 0xE91515
EMBED_COLOR_INFO = 0x3498DB


def get_user_info(user: dict | None) -> tuple[str, int, str]:
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


async def create_file_from_image(image_data: dict) -> discord.File:
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
        user: dict | None = None,
        title: str = "Default Title",
        description: str | None = None,
        is_error: bool = False,
        image_data: dict | None = None,
        notes: list[dict] | None = None,
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
        user: dict | None = None,
        on_select: (
            Callable[[discord.Interaction, dict | None, bool], Coroutine[Any, Any, None]]
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
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        self.hide_buttons()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        if self.on_select:
            await self.on_select(interaction, self.user, True)

    @discord.ui.button(label="Never Mind", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
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
        user: dict | None = None,
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
        if self.repo:
            has_recent_images = await self.repo.has_images_in_context(
                interaction.channel_id, "All Models"
            )

        self.update_buttons(has_previous_image, has_recent_images)
        logging.debug("ImageSelectionTypeModal embed created successfully.")

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )

        logging.debug("ImageSelectionTypeModal initialized successfully.")

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
        self, interaction: discord.Interaction, button: discord.ui.Button
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
        self, interaction: discord.Interaction, button: discord.ui.Button
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
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cancel selection."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        if self.on_select:
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)
            await self.on_select(interaction, "Cancel")


class ImageCarouselView(discord.ui.View):
    """A view that provides a simple image carousel."""

    def __init__(
        self,
        interaction: discord.Interaction,
        files: list[dict],
        user: dict | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[[discord.Interaction, dict | None], Coroutine[Any, Any, None]]
            | None
        ) = None,
    ) -> None:
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.files = files
        self.embed_image: discord.File | None = None
        self.current_index = (len(self.files) - 1) if self.files else 0
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
            logging.error(
                "No files provided to ImageCarouselView at startup; Error embed created."
            )
        else:
            self.embed, self.embed_image = await self.create_embed(interaction)
            self.update_buttons()
            logging.debug("ImageCarouselView embed created successfully.")

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
        logging.debug("ImageCarouselView initialized successfully.")

    def generate_image_chrono_bar(self, current_index: int, total: int) -> str:
        """Generate a visual position indicator for the carousel."""
        bar_icons = ""
        for i in range(total):
            bar_icons += "\u2b25" if i == current_index else "\u2b26"
        return f"(Oldest) {bar_icons} (Newest)"

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

    def get_current_file(self) -> dict:
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
        """Disable all buttons on timeout."""
        self.disable_buttons()
        self.hide_buttons()
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

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
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to previous image."""
        await interaction.response.defer()
        if self.current_index > 0:
            self.current_index -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to next image."""
        await interaction.response.defer()
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            await self.update_embed(interaction)

    @discord.ui.button(label="Select", style=discord.ButtonStyle.success)
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Accept current image selection."""
        selected_image = self.get_current_file()
        if self.on_select:
            self.disable_buttons()
            await self.on_select(interaction, selected_image)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cancel image selection."""
        if self.on_select:
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)
            await self.on_select(interaction, None)


class ImageEditTypeView(discord.ui.View):
    """A view that displays buttons for different image editing options."""

    def __init__(
        self,
        image_data: dict,
        user: dict | None = None,
        message: discord.Message | None = None,
        on_select: (
            Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__()
        self.image_data = image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message = message
        self.on_select = on_select
        logging.debug("ImageEditTypeView initialized")

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the view with the image and buttons."""
        self.embed = discord.Embed(
            title="Edit Image", description="Select an editing option:"
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        embed_image = await create_file_from_image(self.image_data)
        self.embed.set_image(url=f"attachment://{embed_image.filename}")

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )
        logging.debug("ImageEditTypeView embed created and displayed")

    def disable_buttons(self) -> None:
        """Disable all buttons in the view."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        logging.debug("All buttons disabled")

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()
        logging.debug("All buttons hidden")

    @discord.ui.button(label="Adjust", style=discord.ButtonStyle.primary, row=0)
    async def adjust_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
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
                edit_type="Adjust",
                user=self.user,
                message=self.message,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Redraw", style=discord.ButtonStyle.primary, row=0)
    async def redraw_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
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
                edit_type="Redraw",
                user=self.user,
                message=self.message,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(
        label="Random (disabled)",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=0,
    )
    async def random_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
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
                edit_type="Random",
                user=self.user,
                message=self.message,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
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
            await self.on_select(interaction, "Cancel", "")


class ImageEditPromptModal(discord.ui.Modal, title="Image Edit Instructions"):
    """Modal for entering image edit prompt."""

    def __init__(
        self,
        image_data: dict,
        edit_type: str,
        user: dict | None,
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

        self.prompt = discord.ui.TextInput(
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

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        logging.error(f"Error in ImageEditPromptModal: {error}")

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
    """A view that handles performing an image edit operation."""

    def __init__(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
        user: dict | None,
        image_data: dict,
        edit_type: str,
        prompt: str = "`placeholder`",
        on_complete: (
            Callable[[discord.Interaction, dict], Coroutine[Any, Any, None]] | None
        ) = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        image_provider: "ImageProvider | None" = None,
    ) -> None:
        super().__init__()
        self.interaction = interaction
        self.prompt = prompt
        self.message = message
        self.user = user
        self.image_data = image_data
        self.edit_type = edit_type
        self.on_complete = on_complete
        self.rate_limiter = rate_limiter
        self.image_provider = image_provider
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the initial 'processing' embed."""
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

            guidance_scale = 0.0
            if self.edit_type == "Adjust":
                guidance_scale = 10.0
            elif self.edit_type == "Redraw":
                guidance_scale = 1.5

            # Perform the image modification
            if not self.image_provider:
                raise RuntimeError("Image provider not initialized")

            modified_images = await self.image_provider.modify(
                ImageRequest(
                    prompt=prompt,
                    image_data=self.image_data["image"],
                    guidance_scale=guidance_scale,
                )
            )
            modified_image = modified_images[0]

            # Process the response
            result_image_data = image_strip_headers(modified_image.url, "jpeg")
            result_image_data = await asyncio.to_thread(compress_image, result_image_data)
            image_return = {"filename": "image.jpeg", "image": result_image_data}

            # Record the request after successful operation
            if self.rate_limiter:
                await self.rate_limiter.record(self.interaction.user.id, "image")

            # Call completion callback
            if self.on_complete:
                await self.on_complete(self.interaction, image_return)

        except Exception as ex:
            logging.error(f"Error in image edit: {ex}")
            error_data = {
                "error": True,
                "message": f"An error occurred while modifying the image: {ex}",
            }
            if self.on_complete:
                await self.on_complete(self.interaction, error_data)
