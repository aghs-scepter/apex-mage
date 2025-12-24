"""Discord UI components for carousel and embed views."""

import asyncio
import base64
import io
import json
from collections.abc import Callable, Coroutine
from os import getenv
from typing import TYPE_CHECKING, Any

import aiohttp
import discord

from src.core.haiku import (
    HaikuError,
    ImageDescriptionError,
    haiku_complete,
    haiku_describe_image,
)
from src.core.image_utils import (
    compress_image,
    create_composite_thumbnail,
    image_strip_headers,
)
from src.core.image_variations import (
    RateLimitExceededError,
    VariationError,
    generate_variation_remixed,
    generate_variation_same_prompt,
)
from src.core.logging import get_logger
from src.core.prompts.refinement import IMAGE_MODIFICATION_REFINEMENT_PROMPT
from src.core.providers import ImageModifyRequest, ImageRequest

if TYPE_CHECKING:
    from src.adapters.gcs_adapter import GCSAdapter
    from src.adapters.repository_compat import RepositoryAdapter
    from src.core.providers import ImageProvider
    from src.core.rate_limit import SlidingWindowRateLimiter

logger = get_logger(__name__)

EMBED_COLOR_ERROR = 0xE91515
EMBED_COLOR_INFO = 0x3498DB

# Timeout constants (seconds)
# User interaction timeout (how long user has to click/submit)
USER_INTERACTION_TIMEOUT = 300.0  # 5 minutes
# Extended timeout for result views where user may take time to decide
RESULT_VIEW_TIMEOUT = 600.0  # 10 minutes
# API timeout for image generation calls
API_TIMEOUT_SECONDS = 180


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
        download_url: str | None = None,
    ) -> None:
        # timeout=None ensures download button remains functional indefinitely
        super().__init__(timeout=None)
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
        self.download_url = download_url
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

        # Add download image button if URL is provided
        if self.download_url:
            self.add_item(
                discord.ui.Button(
                    label="Download Image",
                    url=self.download_url,
                    style=discord.ButtonStyle.link,
                )
            )

        if self.image_data:
            embed_image = await create_file_from_image(self.image_data)
            self.embed.set_image(url=f"attachment://{embed_image.filename}")

            # Use self.message.edit() when message is provided (e.g., modal callbacks)
            # This ensures we update the existing message rather than creating a new response
            if self.message is not None:
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            elif interaction.response.is_done():
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
            # Use self.message.edit() when message is provided (e.g., modal callbacks)
            if self.message is not None:
                await self.message.edit(
                    attachments=[],
                    embed=self.embed,
                    view=self,
                )
            elif interaction.response.is_done():
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


class GoogleSearchModal(discord.ui.Modal, title="Google Image Search"):
    """Modal for entering Google Image search query."""

    def __init__(
        self,
        on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__()
        self.on_submit_callback = on_submit

        self.query: discord.ui.TextInput[GoogleSearchModal] = discord.ui.TextInput(
            label="Enter your search query:",
            style=discord.TextStyle.short,
            max_length=200,
            required=True,
            placeholder="e.g., sunset over mountains",
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await self.on_submit_callback(interaction, self.query.value)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle errors during modal submission."""
        logger.error("modal_error", view="GoogleSearchModal", error=str(error))

        try:
            await interaction.response.send_message(
                "An error occurred while processing your search. Please try again.",
                ephemeral=True,
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send(
                "An error occurred while processing your search. Please try again.",
                ephemeral=True,
            )


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

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
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
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        image_provider: "ImageProvider | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
    ) -> None:
        # User has 5 minutes to make a selection
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None
        self.on_select = on_select
        self.repo = repo
        self.rate_limiter = rate_limiter
        self.image_provider = image_provider
        self.gcs_adapter = gcs_adapter

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
        # Google search is always enabled
        self.google_search_button.disabled = False
        self.recent_images_button.disabled = not has_recent_images

    def disable_buttons(self) -> None:
        """Disable all selection buttons."""
        self.google_search_button.disabled = True
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

    @discord.ui.button(label="Google Search", style=discord.ButtonStyle.primary)
    async def google_search_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageSelectionTypeView"],
    ) -> None:
        """Open Google Image search."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        # Show the GoogleSearchModal
        modal = GoogleSearchModal(on_submit=self._handle_google_search)
        await interaction.response.send_modal(modal)

    async def _handle_google_search(
        self, interaction: discord.Interaction, query: str
    ) -> None:
        """Handle Google search query submission.

        This method orchestrates the full Google Image search flow:
        1. Show processing message
        2. Screen the query via Haiku content screening
        3. If rejected: log to database and show error
        4. If approved: execute SerpAPI search
        5. Display results in GoogleResultsCarouselView

        Args:
            interaction: The Discord interaction from the modal submit.
            query: The search query entered by the user.
        """
        from src.core.content_screening import screen_search_query
        from src.providers.serpapi_provider import SerpAPIError, search_google_images

        await interaction.response.defer()

        # 1. Show processing message
        if self.embed:
            self.embed.title = "Google Image Search"
            self.embed.description = f"Searching for: {query}... Processing"
        if self.message:
            await self.message.edit(embed=self.embed, view=None)

        # 2. Screen the query via Haiku
        try:
            screening_result = await screen_search_query(query)
        except Exception as e:
            logger.error(
                "content_screening_error",
                view="ImageSelectionTypeView",
                query=query,
                error=str(e),
            )
            # Fail closed - treat screening errors as rejections
            if self.embed:
                self.embed.title = "Search Blocked"
                self.embed.description = (
                    "Content screening service is unavailable. Please try again later."
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        if not screening_result.allowed:
            # Log rejection to database
            if self.repo and interaction.channel_id is not None:
                guild_id = interaction.guild_id if interaction.guild else None
                await self.repo.log_search_rejection(
                    user_id=interaction.user.id,
                    channel_id=interaction.channel_id,
                    guild_id=guild_id,
                    query_text=query,
                    rejection_reason=screening_result.reason or "Content policy violation",
                )
                logger.info(
                    "search_query_rejected",
                    view="ImageSelectionTypeView",
                    user_id=interaction.user.id,
                    channel_id=interaction.channel_id,
                    query=query,
                    reason=screening_result.reason,
                )

            # Show rejection message
            if self.embed:
                self.embed.title = "Search Blocked"
                self.embed.description = (
                    f"Your search for **{query}** was blocked.\n\n"
                    f"Reason: {screening_result.reason or 'Content policy violation'}"
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        # 3. Execute SerpAPI search
        try:
            results = await search_google_images(query, num_results=10)
        except ValueError as e:
            # API key not configured
            logger.error(
                "serpapi_config_error",
                view="ImageSelectionTypeView",
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Search Error"
                self.embed.description = (
                    "Google Image Search is not configured. "
                    "Please contact the bot administrator."
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return
        except SerpAPIError as e:
            logger.error(
                "serpapi_search_error",
                view="ImageSelectionTypeView",
                query=query,
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Search Error"
                self.embed.description = "Search failed, please try again."
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        if not results:
            if self.embed:
                self.embed.title = "No Results"
                self.embed.description = f"No images found for: {query}"
                self.embed.color = EMBED_COLOR_INFO
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        # 4. Convert results to the format expected by GoogleResultsCarouselView
        result_dicts = [
            {
                "url": r.url,
                "thumbnail_url": r.thumbnail_url or "",
                "title": r.title or "",
                "source_url": r.source_url or "",
            }
            for r in results
        ]

        # 5. Create return callback
        async def on_return(
            return_interaction: discord.Interaction, view: GoogleResultsCarouselView
        ) -> None:
            """Handle return from GoogleResultsCarouselView to ImageSelectionTypeView."""
            # Re-create ImageSelectionTypeView
            new_view = ImageSelectionTypeView(
                interaction=return_interaction,
                user=self.user,
                on_select=self.on_select,
                repo=self.repo,
                rate_limiter=self.rate_limiter,
                image_provider=self.image_provider,
                gcs_adapter=self.gcs_adapter,
            )
            # Re-initialize the view with the return interaction
            # First respond to the interaction
            await return_interaction.response.defer()
            # Update the message content
            new_view.message = self.message
            new_view.embed = discord.Embed(
                title="Image Selection Type",
                description="Select an option to choose an image for your request.",
            )
            new_view.embed.set_author(
                name=f"{self.username} (via Apex Mage)",
                url="https://github.com/aghs-scepter/apex-mage",
                icon_url=self.pfp,
            )
            # Check for recent images
            has_recent_images = False
            if self.repo and return_interaction.channel_id is not None:
                has_recent_images = await self.repo.has_images_in_context(
                    return_interaction.channel_id, "All Models"
                )
            new_view.update_buttons(False, has_recent_images)
            if new_view.message:
                await new_view.message.edit(embed=new_view.embed, view=new_view)

        # 6. Stop this view's timeout before transitioning to GoogleResultsCarouselView
        self.stop()

        # Create and show GoogleResultsCarouselView
        carousel = GoogleResultsCarouselView(
            interaction=interaction,
            results=result_dicts,
            query=query,
            user=self.user,
            message=self.message,
            repo=self.repo,
            on_return=on_return,
            rate_limiter=self.rate_limiter,
            image_provider=self.image_provider,
            gcs_adapter=self.gcs_adapter,
            on_edit_complete=self._on_edit_complete,
        )
        await carousel.initialize(interaction)

    async def _on_edit_complete(
        self, interaction: discord.Interaction, result_data: dict[str, Any]
    ) -> None:
        """Handle image edit errors from GoogleResultsCarouselView.

        Note: Success cases are now handled by ImageEditResultView directly.
        This callback is only invoked for error cases (rate limit, timeout, etc.).

        Args:
            interaction: The Discord interaction.
            result_data: Error data containing 'error' and 'message' keys.
        """
        error_msg = result_data.get("message")
        error_view = InfoEmbedView(
            message=interaction.message,
            user=self.user,
            title="Image edit error!",
            description=str(error_msg) if error_msg else "An error occurred during image editing.",
            is_error=True,
            image_data=None,
        )
        await error_view.initialize(interaction)

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
            self.stop()  # Stop timeout before transitioning to next view
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
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        # User has 5 minutes to make a selection
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.files = files
        self.embed_image: discord.File | None = None
        self.current_index = 0
        self.on_select = on_select
        self.message = message
        self.healthy = bool(self.files)
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.repo = repo

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
            self.stop()  # Stop timeout before transitioning to next view
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

    @discord.ui.button(label="Describe", style=discord.ButtonStyle.primary)
    async def describe_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageCarouselView"]
    ) -> None:
        """Generate a description of the current image using Haiku vision."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Stop this view's timeout before transitioning
        self.stop()

        # Get the current image
        current_image = self.get_current_file()

        # Transition to DescriptionDisplayView
        description_view = DescriptionDisplayView(
            interaction=interaction,
            image_data=current_image,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        await description_view.initialize(interaction)


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
            placeholder=(
                "Enter a rough description of the edit you want "
                "(e.g., 'make it darker', 'add a sunset background'). "
                "AI will help refine this into a detailed prompt."
            ),
            required=True,
            max_length=500,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission by calling Haiku to refine the prompt."""
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

        # Show the result view with refined prompt
        result_view = AIAssistResultView(
            image_data=self.image_data,
            user=self.user,
            message=self.message,
            rough_description=rough_description,
            refined_prompt=refined_prompt,
            on_select=self.on_select,
        )
        await result_view.initialize(interaction)

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

        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Use This", style=discord.ButtonStyle.success, row=0)
    async def use_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["AIAssistResultView"]
    ) -> None:
        """Show preview view with the refined prompt."""
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
            except Exception:
                pass


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
            except Exception:
                pass


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
        # User has 5 minutes to make a selection
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
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

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.success, row=0)
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

            self.stop()  # Stop timeout - user is committing to edit action
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
                image_data_list=self.image_data_list,
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="AI Assist", style=discord.ButtonStyle.success, row=0)
    async def ai_assist_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ImageEditTypeView"]
    ) -> None:
        """Open AI Assist modal for prompt refinement."""
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.",
                    ephemeral=True,
                )
                return

            # Show the AI Assist modal
            modal = AIAssistModal(
                image_data=self.image_data,
                user=self.user,
                message=self.message,
                on_select=self.on_select,
            )
            await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.primary, row=0)
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

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=0)
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
            except Exception:
                pass  # Message may have been deleted


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
        gcs_adapter: "GCSAdapter | None" = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        # timeout=None ensures download button remains functional indefinitely
        super().__init__(timeout=None)
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
        self.gcs_adapter = gcs_adapter
        self.repo = repo
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

            # Wrap API call with timeout to distinguish from View timeout
            async with asyncio.timeout(API_TIMEOUT_SECONDS):
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

            # Upload to GCS for download button (optional - may fail if not configured)
            if self.gcs_adapter and self.interaction.channel_id is not None:
                try:
                    cloud_url = await asyncio.to_thread(
                        self.gcs_adapter.upload_modified_image,
                        self.interaction.channel_id,
                        result_image_data,
                    )
                    image_return["cloud_url"] = cloud_url
                    logger.debug(
                        "gcs_upload_success",
                        cloud_url=cloud_url,
                        channel_id=self.interaction.channel_id,
                    )
                except Exception as gcs_ex:
                    # Log but don't fail - image still works without GCS upload
                    logger.warning(
                        "gcs_upload_failed",
                        error=str(gcs_ex),
                        channel_id=self.interaction.channel_id,
                    )

            # Transition to ImageEditResultView for explicit context addition
            result_view = ImageEditResultView(
                interaction=self.interaction,
                message=self.message,
                user=self.user,
                result_image_data=image_return,
                source_image_data_list=self.image_data_list,
                prompt=prompt,
                download_url=image_return.get("cloud_url"),
                repo=self.repo,
                image_provider=self.image_provider,
                rate_limiter=self.rate_limiter,
                gcs_adapter=self.gcs_adapter,
            )
            await result_view.initialize(self.interaction)

        except TimeoutError:
            # API timeout - distinct from View's on_timeout (user interaction timeout)
            logger.error("image_generation_timeout", timeout_seconds=API_TIMEOUT_SECONDS)
            error_data = {
                "error": True,
                "message": "Image generation timed out. Please try again.",
            }
            if self.on_complete:
                await self.on_complete(self.interaction, error_data)

        except Exception as ex:
            logger.error("image_edit_error", error=str(ex))
            error_data = {
                "error": True,
                "message": f"An error occurred while modifying the image: {ex}",
            }
            if self.on_complete:
                await self.on_complete(self.interaction, error_data)




class ImageEditResultView(discord.ui.View):
    """A view that displays the result of an image edit operation.

    Shows the modified image with the source image(s) as a thumbnail for comparison.
    Provides buttons for adding to context, creating variations, and downloading.

    This view does NOT auto-add the modified image to context - the user must
    explicitly click Add to Context to store the result.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
        user: dict[str, Any] | None,
        result_image_data: dict[str, str],
        source_image_data_list: list[dict[str, str]],
        prompt: str,
        download_url: str | None = None,
        repo: "RepositoryAdapter | None" = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
    ) -> None:
        """Initialize the image edit result view.

        Args:
            interaction: The Discord interaction.
            message: The message to update with the result.
            user: User dict with name, id, and pfp keys.
            result_image_data: The modified image data with filename and image keys.
            source_image_data_list: List of source images used for the edit.
            prompt: The prompt used for the edit.
            download_url: Optional cloud URL for download button.
            repo: Repository adapter for storing images to context.
            image_provider: Image provider for generating variations.
            rate_limiter: Rate limiter for image generation.
            gcs_adapter: GCS adapter for uploading images.
        """
        super().__init__(timeout=RESULT_VIEW_TIMEOUT)
        self.interaction = interaction
        self.message = message
        self.user = user
        self.result_image_data = result_image_data
        self.source_image_data_list = source_image_data_list
        self.prompt = prompt
        self.download_url = download_url
        self.repo = repo
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.added_to_context = False

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the result embed with source thumbnail."""
        desc_line1 = "Your image was modified successfully."
        desc_line2 = "Click **Add to Context** to use this image in future commands."
        self.embed = discord.Embed(
            title="Image Modified",
            description=desc_line1 + chr(10) + desc_line2,
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Add prompt as a field
        if self.prompt:
            self.embed.add_field(
                name="Prompt",
                value=self.prompt,
                inline=False,
            )

        # Create the result image file for the main image
        result_file = await create_file_from_image(self.result_image_data)
        self.embed.set_image(url=f"attachment://{result_file.filename}")

        # Create source thumbnail (composite if multiple, single if one)
        num_sources = len(self.source_image_data_list)
        if num_sources > 1:
            # Create composite thumbnail for multiple source images
            source_strings = [img["image"] for img in self.source_image_data_list]
            composite_b64 = await asyncio.to_thread(
                create_composite_thumbnail, source_strings
            )
            source_display = {"filename": "source_composite.jpeg", "image": composite_b64}
        else:
            source_display = self.source_image_data_list[0]

        # Use a unique filename to avoid conflicts
        source_file = discord.File(
            io.BytesIO(base64.b64decode(source_display["image"])),
            filename="source_thumbnail.jpeg",
        )
        self.embed.set_thumbnail(url="attachment://source_thumbnail.jpeg")

        # Add footer indicating source
        plural_s = "s" if num_sources > 1 else ""
        source_label = f"Source: {num_sources} image{plural_s}"
        self.embed.set_footer(text=source_label)

        # Add download button if URL is provided
        if self.download_url:
            self.add_item(
                discord.ui.Button(
                    label="Download",
                    url=self.download_url,
                    style=discord.ButtonStyle.link,
                    row=1,
                )
            )

        await self.message.edit(
            embed=self.embed,
            attachments=[result_file, source_file],
            view=self,
        )

    async def on_timeout(self) -> None:
        """Update the embed when the view times out."""
        if self.embed:
            if not self.added_to_context:
                self.embed.description = (
                    "This interaction has timed out. "
                    "The image was NOT added to context."
                )
            self.embed.color = EMBED_COLOR_ERROR if not self.added_to_context else EMBED_COLOR_INFO

        # Disable all buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button) and not child.url:
                child.disabled = True

        try:
            await self.message.edit(embed=self.embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Add to Context", style=discord.ButtonStyle.success, row=0)
    async def add_to_context_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageEditResultView"],
    ) -> None:
        """Add the modified image to the channel context."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Store the image in context
        if self.repo and interaction.channel_id is not None:
            try:
                await self.repo.create_channel(interaction.channel_id)
                images = [self.result_image_data]
                str_images = json.dumps(images)
                await self.repo.add_message_with_images(
                    interaction.channel_id,
                    "Fal.AI",
                    "prompt",
                    False,
                    "Modified Image",
                    str_images,
                    is_image_only_context=True,
                )
                self.added_to_context = True
                logger.info(
                    "image_edit_result_added_to_context",
                    view="ImageEditResultView",
                    channel_id=interaction.channel_id,
                )
            except Exception as e:
                logger.error(
                    "image_edit_result_add_failed",
                    view="ImageEditResultView",
                    error=str(e),
                )
                if self.embed:
                    self.embed.description = f"Failed to add image to context: {e}"
                    self.embed.color = EMBED_COLOR_ERROR
                await self.message.edit(embed=self.embed, view=self)
                return

        # Update button to show success
        button.label = "Added to Context"
        button.disabled = True
        button.style = discord.ButtonStyle.secondary

        # Update embed description
        if self.embed:
            self.embed.description = (
                "Image added to context successfully!" + chr(10) +
                "You can use it for future /describe_this and /modify_image commands."
            )

        await self.message.edit(embed=self.embed, view=self)

    @discord.ui.button(label="Create Variations", style=discord.ButtonStyle.primary, row=0)
    async def create_variations_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageEditResultView"],
    ) -> None:
        """Create variations of the modified image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Check if we have the required dependencies for variations
        if self.image_provider is None or self.rate_limiter is None:
            await interaction.response.send_message(
                "Variation generation is not available. Missing required dependencies.",
                ephemeral=True,
            )
            return

        # Disable button to prevent re-entry
        button.disabled = True
        button.label = "Creating Variations..."
        await interaction.response.defer()

        # Update message to show button is disabled
        await self.message.edit(view=self)

        # Stop this view's timeout before transitioning
        self.stop()

        # Create source image for carousel comparison
        # For modify_image, the source is the original image(s) before editing
        num_sources = len(self.source_image_data_list)
        if num_sources > 1:
            # Create composite for multiple source images
            source_strings = [img["image"] for img in self.source_image_data_list]
            composite_b64 = await asyncio.to_thread(
                create_composite_thumbnail, source_strings
            )
            source_for_carousel = {"filename": "source_composite.jpeg", "image": composite_b64}
        else:
            source_for_carousel = self.source_image_data_list[0]

        # Transition to VariationCarouselView
        # Variations are of the EDIT RESULT (result_image_data), not the source
        # Source image is passed for reference comparison
        carousel = VariationCarouselView(
            interaction=interaction,
            message=self.message,
            user=self.user,
            original_image=self.result_image_data,
            prompt=self.prompt,
            source_image=source_for_carousel,  # Source for comparison
            repo=self.repo,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
        )
        await carousel.initialize(interaction)

    @discord.ui.button(label="Describe", style=discord.ButtonStyle.primary, row=0)
    async def describe_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageEditResultView"],
    ) -> None:
        """Generate a description of the image using Haiku vision."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Stop this view's timeout before transitioning
        self.stop()

        # Transition to DescriptionDisplayView
        description_view = DescriptionDisplayView(
            interaction=interaction,
            image_data=self.result_image_data,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        await description_view.initialize(interaction)


class ImageGenerationResultView(discord.ui.View):
    """A view that displays the result of an image generation operation.

    Shows the generated image with buttons for adding to context, creating
    variations, and downloading.

    This view does NOT auto-add the generated image to context - the user must
    explicitly click Add to Context to store the result.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        message: discord.Message | None,
        user: dict[str, Any] | None,
        image_data: dict[str, str],
        prompt: str,
        download_url: str | None = None,
        repo: "RepositoryAdapter | None" = None,
        full_prompt_url: str | None = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
    ) -> None:
        """Initialize the image generation result view.

        Args:
            interaction: The Discord interaction.
            message: The message to update with the result (may be None for followup).
            user: User dict with name, id, and pfp keys.
            image_data: The generated image data with filename and image keys.
            prompt: The prompt used for generation.
            download_url: Optional cloud URL for download button.
            repo: Repository adapter for storing images to context.
            full_prompt_url: Optional URL for viewing the full prompt.
            image_provider: Image provider for generating variations.
            rate_limiter: Rate limiter for image generation.
            gcs_adapter: GCS adapter for uploading images.
        """
        super().__init__(timeout=RESULT_VIEW_TIMEOUT)
        self.interaction = interaction
        self.message = message
        self.user = user
        self.image_data = image_data
        self.prompt = prompt
        self.download_url = download_url
        self.repo = repo
        self.full_prompt_url = full_prompt_url
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.added_to_context = False

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the result embed."""
        desc_line1 = "Your image was created successfully."
        desc_line2 = "Click **Add to Context** to use this image in future commands."
        self.embed = discord.Embed(
            title="Image Generation Successful",
            description=desc_line1 + chr(10) + desc_line2,
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Add prompt as a field (truncated if too long)
        if self.prompt:
            display_prompt = self.prompt
            if len(display_prompt) > 1024:
                display_prompt = display_prompt[:1021] + "..."
            self.embed.add_field(
                name="Prompt",
                value=display_prompt,
                inline=False,
            )

        # Create the result image file
        result_file = await create_file_from_image(self.image_data)
        self.embed.set_image(url=f"attachment://{result_file.filename}")

        # Add download button if URL is provided (link button, row 1)
        if self.download_url:
            self.add_item(
                discord.ui.Button(
                    label="Download",
                    url=self.download_url,
                    style=discord.ButtonStyle.link,
                    row=1,
                )
            )

        # Add view full prompt button if URL is provided (link button, row 1)
        if self.full_prompt_url:
            self.add_item(
                discord.ui.Button(
                    label="View Full Prompt",
                    url=self.full_prompt_url,
                    style=discord.ButtonStyle.link,
                    row=1,
                )
            )

        # Use self.message.edit() when message is provided
        if self.message is not None:
            await self.message.edit(
                embed=self.embed,
                attachments=[result_file],
                view=self,
            )
        elif interaction.response.is_done():
            await interaction.edit_original_response(
                embed=self.embed,
                attachments=[result_file],
                view=self,
            )
        else:
            await interaction.followup.send(
                embed=self.embed,
                file=result_file,
                view=self,
            )

    async def on_timeout(self) -> None:
        """Update the embed when the view times out."""
        if self.embed:
            if not self.added_to_context:
                self.embed.description = (
                    "This interaction has timed out. "
                    "The image was NOT added to context."
                )
            self.embed.color = EMBED_COLOR_ERROR if not self.added_to_context else EMBED_COLOR_INFO

        # Disable all non-link buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button) and not child.url:
                child.disabled = True

        try:
            if self.message:
                await self.message.edit(embed=self.embed, view=self)
        except Exception:
            pass  # Message may have been deleted

    @discord.ui.button(label="Add to Context", style=discord.ButtonStyle.success, row=0)
    async def add_to_context_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageGenerationResultView"],
    ) -> None:
        """Add the generated image to the channel context."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Store the image in context
        if self.repo and interaction.channel_id is not None:
            try:
                await self.repo.create_channel(interaction.channel_id)
                images = [self.image_data]
                str_images = json.dumps(images)
                await self.repo.add_message_with_images(
                    interaction.channel_id,
                    "Fal.AI",
                    "prompt",
                    False,
                    "Image",
                    str_images,
                    is_image_only_context=True,
                )
                self.added_to_context = True
                logger.info(
                    "image_generation_result_added_to_context",
                    view="ImageGenerationResultView",
                    channel_id=interaction.channel_id,
                )
            except Exception as e:
                logger.error(
                    "image_generation_result_add_failed",
                    view="ImageGenerationResultView",
                    error=str(e),
                )
                if self.embed:
                    self.embed.description = f"Failed to add image to context: {e}"
                    self.embed.color = EMBED_COLOR_ERROR
                if self.message:
                    await self.message.edit(embed=self.embed, view=self)
                return

        # Update button to show success
        button.label = "Added to Context"
        button.disabled = True
        button.style = discord.ButtonStyle.secondary

        # Update embed description
        if self.embed:
            self.embed.description = (
                "Image added to context successfully!" + chr(10) +
                "You can use it for future /describe_this and /modify_image commands."
            )

        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    @discord.ui.button(label="Create Variations", style=discord.ButtonStyle.primary, row=0)
    async def create_variations_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageGenerationResultView"],
    ) -> None:
        """Create variations of the generated image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Check if we have the required dependencies for variations
        if self.image_provider is None or self.rate_limiter is None:
            await interaction.response.send_message(
                "Variation generation is not available. Missing required dependencies.",
                ephemeral=True,
            )
            return

        # Disable button to prevent re-entry
        button.disabled = True
        button.label = "Creating Variations..."
        await interaction.response.defer()

        # Check that we have a message to update
        if self.message is None:
            logger.error(
                "create_variations_no_message",
                view="ImageGenerationResultView",
            )
            return

        # Update message to show button is disabled
        await self.message.edit(view=self)

        # Stop this view's timeout before transitioning
        self.stop()

        # Transition to VariationCarouselView
        # Note: source_image is None for create_image (no source to compare)
        carousel = VariationCarouselView(
            interaction=interaction,
            message=self.message,
            user=self.user,
            original_image=self.image_data,
            prompt=self.prompt,
            source_image=None,  # No source for create_image
            repo=self.repo,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
        )
        await carousel.initialize(interaction)

    @discord.ui.button(label="Describe", style=discord.ButtonStyle.primary, row=0)
    async def describe_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ImageGenerationResultView"],
    ) -> None:
        """Generate a description of the image using Haiku vision."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Stop this view's timeout before transitioning
        self.stop()

        # Transition to DescriptionDisplayView
        description_view = DescriptionDisplayView(
            interaction=interaction,
            image_data=self.image_data,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        await description_view.initialize(interaction)


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
        # User has 5 minutes to make selections
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
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

    def generate_image_chrono_bar(self) -> str:
        """Generate a single-line chronological bar showing position and selection.

        Uses bold brackets to indicate current position:
        - \u25cb = not selected, not current
        - \u2713 = selected, not current
        - **[(**\u25cb**)]** = current position, not selected (bold brackets)
        - **[(**\u2713**)]** = current position, selected (bold brackets)

        Example (viewing image 3, images 2 and 5 selected of 5 total):
            (Newest) \u25cb \u2713 **[(**\u25cb**)]** \u25cb \u2713 (Oldest)
        """
        symbols = []
        for i in range(len(self.files)):
            is_current = i == self.current_index
            is_selected = i in self.selected_indices

            if is_selected:
                symbol = "\u2713"  # Checkmark
            else:
                symbol = "\u25cb"  # White circle

            if is_current:
                symbol = f"**[(**{symbol}**)]**"

            symbols.append(symbol)

        return "(Newest) " + " ".join(symbols) + " (Oldest)"

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
            description=self.generate_image_chrono_bar(),
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
            self.embed.description = self.generate_image_chrono_bar()
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
            self.stop()  # Stop timeout before transitioning to next view
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


class PresetSelect(discord.ui.Select["PresetSelectView"]):
    """Custom select menu for behavior presets."""

    def __init__(self, presets: list[dict[str, Any]]) -> None:
        """Initialize the preset select.

        Args:
            presets: List of preset dicts with name, description, prompt_text.
        """
        # Build select options
        options = [
            discord.SelectOption(
                label="Default",
                description="Use default AI behavior (no system prompt)",
                value="__default__",
            )
        ]
        for preset in presets[:14]:  # Leave room for default (15 max)
            description = preset.get("description", "") or "No description"
            # Truncate description to 100 chars (Discord limit)
            if len(description) > 100:
                description = description[:97] + "..."
            options.append(
                discord.SelectOption(
                    label=preset["name"],
                    description=description,
                    value=preset["name"],
                )
            )

        super().__init__(
            placeholder="Choose a behavior preset...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle preset selection."""
        view = self.view
        if view is None:
            return

        if interaction.user.id != view.user_id:
            await interaction.response.send_message(
                f"Only the original requester ({view.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if self.values:
            selected_value = self.values[0]
            if selected_value == "__default__":
                await view.on_select_callback(interaction, None, None)
            else:
                await view.on_select_callback(interaction, selected_value, None)


class PresetSelectView(discord.ui.View):
    """A view that displays a select menu for choosing behavior presets."""

    def __init__(
        self,
        presets: list[dict[str, Any]],
        user: dict[str, Any] | None,
        channel_id: int,
        on_select: Callable[
            [discord.Interaction, str | None, str | None], Coroutine[Any, Any, None]
        ],
        timeout: float = 60.0,
    ) -> None:
        """Initialize the preset select view.

        Args:
            presets: List of preset dicts with name, description, prompt_text.
            user: The user who invoked the command.
            channel_id: The channel ID where the preset will be applied.
            on_select: Callback that receives (interaction, preset_name, prompt_text).
                       preset_name is None for default, prompt_text is None for default.
            timeout: View timeout in seconds.
        """
        super().__init__(timeout=timeout)
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.user = user
        self.channel_id = channel_id
        self.on_select_callback = on_select
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None

        # Add the select component
        self.add_item(PresetSelect(presets))

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the preset selection embed."""
        self.embed = discord.Embed(
            title="Select Behavior Preset",
            description="Choose a preset to apply to this channel:",
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        await interaction.followup.send(embed=self.embed, view=self)
        self.message = await interaction.original_response()


class GoogleResultsCarouselView(discord.ui.View):
    """Carousel view for displaying Google Image search results.

    Displays one image at a time from search results with navigation
    and action buttons. Images are displayed from URLs rather than
    base64 data.

    Supports adding images to context with URL-based deduplication.
    When an image URL is already in context, the Add to Context button
    is disabled with "Already in Context" label.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        results: list[dict[str, str]],
        query: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        repo: "RepositoryAdapter | None" = None,
        on_add_to_context: (
            Callable[
                [discord.Interaction, dict[str, str], "GoogleResultsCarouselView"],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        on_edit_image: (
            Callable[
                [discord.Interaction, dict[str, str], "GoogleResultsCarouselView"],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        on_return: (
            Callable[
                [discord.Interaction, "GoogleResultsCarouselView"],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        image_provider: "ImageProvider | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
        on_edit_complete: (
            Callable[
                [discord.Interaction, dict[str, Any]],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
    ) -> None:
        """Initialize the Google results carousel view.

        Args:
            interaction: The Discord interaction that triggered this view.
            results: List of image result dicts with 'url' and optional 'title' keys.
            query: The search query that produced these results.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional message to edit when updating the view.
            repo: Repository adapter for storing images to context.
            on_add_to_context: Callback when user clicks Add to Context.
                Receives interaction, current result dict, and this view.
            on_edit_image: Callback when user clicks Edit This Image.
                Receives interaction, current result dict, and this view.
            on_return: Callback when user clicks Return.
                Receives interaction and this view.
            rate_limiter: Rate limiter for image edits.
            image_provider: Image provider for calling the modification API.
            gcs_adapter: GCS adapter for uploading results.
            on_edit_complete: Callback when image edit completes.
                Receives interaction and result_data dict.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)  # 5 minutes
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.results = results
        self.query = query
        self.current_index = 0
        self.message = message
        self.repo = repo
        self.on_add_to_context = on_add_to_context
        self.on_edit_image = on_edit_image
        self.on_return = on_return
        self.rate_limiter = rate_limiter
        self.image_provider = image_provider
        self.gcs_adapter = gcs_adapter
        self.on_edit_complete = on_edit_complete
        self.healthy = bool(self.results)
        # Track URLs added to context during this session
        self.added_urls: set[str] = set()
        # Track URLs already in context (populated on initialization)
        self.existing_context_urls: set[str] = set()

    def generate_chrono_bar(self) -> str:
        """Generate a visual position indicator for the carousel.

        Uses bold brackets to indicate current position:
        - Circle = image position
        - **[(**circle**)]** = current position (bold brackets)

        Example (viewing image 2 of 5):
            (1) circle **[(**circle**)]** circle circle circle (5)
        """
        symbols = []
        for i in range(len(self.results)):
            is_current = i == self.current_index
            symbol = "\u25cb"  # White circle

            if is_current:
                symbol = f"**[(**{symbol}**)]**"

            symbols.append(symbol)

        return f"(1) {' '.join(symbols)} ({len(self.results)})"

    async def create_embed(self) -> discord.Embed:
        """Create the carousel embed with current image."""
        current_result = self.results[self.current_index]
        image_url = current_result.get("url", "")
        image_title = current_result.get("title", "")

        embed = discord.Embed(
            title=f"Searching for: {self.query}",
            description=self.generate_chrono_bar(),
        )
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Set image from URL
        if image_url:
            embed.set_image(url=image_url)

        # Add title as footer if available
        if image_title:
            embed.set_footer(text=image_title)

        return embed

    async def create_error_embed(self, error_message: str) -> discord.Embed:
        """Create an error embed."""
        embed = discord.Embed(
            title="Search Error",
            description=error_message,
            color=EMBED_COLOR_ERROR,
        )
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        return embed

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the Google results carousel view."""
        # Load existing context URLs for deduplication
        if self.repo and interaction.channel_id is not None:
            self.existing_context_urls = await self.repo.get_image_source_urls_in_context(
                interaction.channel_id
            )
            logger.debug(
                "loaded_existing_urls",
                view="GoogleResultsCarouselView",
                count=len(self.existing_context_urls),
            )

        if not self.healthy:
            self.embed = await self.create_error_embed(
                f"No images found for: {self.query}"
            )
            self.hide_buttons()
            logger.error("carousel_no_results", view="GoogleResultsCarouselView")
        else:
            self.embed = await self.create_embed()
            self.update_buttons()
            logger.debug("embed_created", view="GoogleResultsCarouselView")

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[],  # Clear any previous attachments
                view=self,
            )
        else:
            # Send as new message via followup
            self.message = await interaction.followup.send(
                embed=self.embed,
                view=self,
                wait=True,
            )
        logger.debug("view_initialized", view="GoogleResultsCarouselView")

    def update_buttons(self) -> None:
        """Update button states based on current position and context status."""
        # Navigation buttons
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= len(self.results) - 1

        # Add to Context button - check if current image is already in context
        current_url = self.get_current_result().get("url", "")
        is_in_context = (
            current_url in self.added_urls or current_url in self.existing_context_urls
        )

        if is_in_context:
            self.add_to_context_button.label = "Already in Context"
            self.add_to_context_button.disabled = True
            self.add_to_context_button.style = discord.ButtonStyle.secondary
        else:
            self.add_to_context_button.label = "Add to Context"
            self.add_to_context_button.disabled = False
            self.add_to_context_button.style = discord.ButtonStyle.success

    def disable_buttons(self) -> None:
        """Disable all navigation and action buttons."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    async def update_embed(self) -> None:
        """Update the embed with the current image after navigation."""
        self.embed = await self.create_embed()
        self.update_buttons()

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[],
                view=self,
            )

    def get_current_result(self) -> dict[str, str]:
        """Get the current image result dict."""
        return self.results[self.current_index]

    # Row 0: Navigation buttons
    @discord.ui.button(label="\u25c0", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
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
            await self.update_embed()

    @discord.ui.button(label="\u25b6", style=discord.ButtonStyle.primary, row=0)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
    ) -> None:
        """Navigate to next image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if self.current_index < len(self.results) - 1:
            self.current_index += 1
            await self.update_embed()

    # Row 1: Action buttons
    @discord.ui.button(label="Add to Context", style=discord.ButtonStyle.success, row=1)
    async def add_to_context_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
    ) -> None:
        """Add current image to context.

        Downloads the image from URL, converts to base64, and stores it
        in the channel's image context. Updates button state to show
        "Added" confirmation, then "Already in Context" for future views.
        """
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        current_result = self.get_current_result()
        image_url = current_result.get("url", "")

        # Check if already in context (shouldn't happen if button is disabled, but be safe)
        if image_url in self.added_urls or image_url in self.existing_context_urls:
            logger.debug(
                "image_already_in_context",
                view="GoogleResultsCarouselView",
                url=image_url,
            )
            return

        # Call callback if provided (for custom handling)
        if self.on_add_to_context:
            await self.on_add_to_context(interaction, current_result, self)

        # Only proceed with storage if we have a repo and channel_id
        if self.repo and interaction.channel_id is not None:
            try:
                # Download image and convert to base64
                image_b64 = await self._download_image_as_base64(image_url)

                # Compress the image
                image_b64 = await asyncio.to_thread(compress_image, image_b64)

                # Generate filename from URL or use default
                filename = self._generate_filename_from_url(image_url)

                # Create image data dict with source_url for deduplication
                image_data = {
                    "filename": filename,
                    "image": image_b64,
                    "source_url": image_url,
                }
                images = [image_data]
                str_images = json.dumps(images)

                # Ensure channel exists and add image to context
                await self.repo.create_channel(interaction.channel_id)
                await self.repo.add_message_with_images(
                    interaction.channel_id,
                    "Anthropic",
                    "prompt",
                    False,
                    "Google Image Search Result",
                    str_images,
                    is_image_only_context=True,
                )

                # Track this URL as added
                self.added_urls.add(image_url)

                logger.info(
                    "image_added_to_context",
                    view="GoogleResultsCarouselView",
                    url=image_url,
                    channel_id=interaction.channel_id,
                )

                # Update button to show "Added" confirmation
                button.label = "Added \u2713"
                button.disabled = True
                button.style = discord.ButtonStyle.secondary

                # Update the view
                if self.message:
                    await self.message.edit(view=self)

            except aiohttp.ClientError as e:
                logger.error(
                    "image_download_failed",
                    view="GoogleResultsCarouselView",
                    url=image_url,
                    error=str(e),
                )
                # Show error to user
                await interaction.followup.send(
                    f"Failed to download image: {e}",
                    ephemeral=True,
                )
            except Exception as e:
                logger.error(
                    "add_to_context_failed",
                    view="GoogleResultsCarouselView",
                    url=image_url,
                    error=str(e),
                )
                await interaction.followup.send(
                    "Failed to add image to context. Please try again.",
                    ephemeral=True,
                )
        else:
            logger.debug(
                "add_to_context_no_repo",
                view="GoogleResultsCarouselView",
                result=current_result,
            )

    async def _download_image_as_base64(self, url: str) -> str:
        """Download an image from URL and convert to base64.

        Args:
            url: The URL of the image to download.

        Returns:
            Base64-encoded image data.

        Raises:
            aiohttp.ClientError: If the download fails.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                data = await response.read()
                return base64.b64encode(data).decode("utf-8")

    def _generate_filename_from_url(self, url: str) -> str:
        """Generate a filename from a URL.

        Attempts to extract the filename from the URL path. Falls back to
        a default filename if extraction fails.

        Args:
            url: The URL to extract filename from.

        Returns:
            A filename ending in .jpeg
        """
        try:
            # Extract path from URL and get the last component
            from urllib.parse import urlparse

            parsed = urlparse(url)
            path = parsed.path
            if path:
                # Get the last component of the path
                filename = path.split("/")[-1]
                # Remove any query parameters that might be in the filename
                filename = filename.split("?")[0]
                # Ensure it has an extension
                if filename and "." in filename:
                    # Replace extension with .jpeg for consistency
                    name_without_ext = filename.rsplit(".", 1)[0]
                    return f"{name_without_ext}.jpeg"
        except Exception:
            pass
        # Default filename
        return "google_image.jpeg"

    @discord.ui.button(label="Edit This Image", style=discord.ButtonStyle.primary, row=1)
    async def edit_image_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
    ) -> None:
        """Edit current image (add to context then open edit flow).

        This handler:
        1. Downloads the image and adds it to context (if not already there)
        2. Opens the ImageEditPromptModal for the user to enter edit instructions
        3. On modal submit, performs the image edit via ImageEditPerformView
        4. Stores the result in channel context via on_edit_complete callback
        """
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        current_result = self.get_current_result()
        image_url = current_result.get("url", "")

        # Download and prepare image for editing
        try:
            image_b64 = await self._download_image_as_base64(image_url)
            image_b64 = await asyncio.to_thread(compress_image, image_b64)
            filename = self._generate_filename_from_url(image_url)
        except aiohttp.ClientError as e:
            logger.error(
                "edit_image_download_failed",
                view="GoogleResultsCarouselView",
                url=image_url,
                error=str(e),
            )
            await interaction.response.send_message(
                f"Failed to download image for editing: {e}",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.error(
                "edit_image_prepare_failed",
                view="GoogleResultsCarouselView",
                url=image_url,
                error=str(e),
            )
            await interaction.response.send_message(
                "Failed to prepare image for editing. Please try again.",
                ephemeral=True,
            )
            return

        # Add to context if not already there
        if image_url not in self.added_urls and image_url not in self.existing_context_urls:
            if self.repo and interaction.channel_id is not None:
                try:
                    # Create image data dict with source_url for deduplication
                    context_image_data = {
                        "filename": filename,
                        "image": image_b64,
                        "source_url": image_url,
                    }
                    images = [context_image_data]
                    str_images = json.dumps(images)

                    await self.repo.create_channel(interaction.channel_id)
                    await self.repo.add_message_with_images(
                        interaction.channel_id,
                        "Anthropic",
                        "prompt",
                        False,
                        "Google Image Search Result",
                        str_images,
                        is_image_only_context=True,
                    )

                    self.added_urls.add(image_url)
                    logger.info(
                        "edit_image_added_to_context",
                        view="GoogleResultsCarouselView",
                        url=image_url,
                        channel_id=interaction.channel_id,
                    )
                except Exception as e:
                    logger.error(
                        "edit_image_context_failed",
                        view="GoogleResultsCarouselView",
                        url=image_url,
                        error=str(e),
                    )
                    # Continue with edit even if context add fails

        # Create image data for the edit flow
        image_data: dict[str, str] = {
            "filename": filename,
            "image": image_b64,
        }

        # Define the callback for when the modal is submitted
        async def on_modal_submit(
            modal_interaction: discord.Interaction,
            edit_type: str,
            prompt: str,
        ) -> None:
            """Handle modal submission - perform the image edit."""
            if edit_type == "Cancel" or not prompt:
                return

            await modal_interaction.response.defer()

            # Stop this view's timeout - user has committed to the edit action
            self.stop()

            if modal_interaction.message is None:
                logger.error(
                    "edit_image_no_message",
                    view="GoogleResultsCarouselView",
                )
                return

            # Create and run ImageEditPerformView
            perform_view = ImageEditPerformView(
                interaction=modal_interaction,
                message=modal_interaction.message,
                user=self.user,
                image_data=image_data,
                image_data_list=[image_data],
                edit_type=edit_type,
                prompt=prompt,
                on_complete=self.on_edit_complete,
                rate_limiter=self.rate_limiter,
                image_provider=self.image_provider,
                gcs_adapter=self.gcs_adapter,
                repo=self.repo,
            )
            await perform_view.initialize(modal_interaction)

        # Open the edit modal (must be the response, cannot defer first)
        prompt_modal = ImageEditPromptModal(
            image_data=image_data,
            edit_type="Edit",
            user=self.user,
            message=self.message,
            on_select=on_modal_submit,
        )
        await interaction.response.send_modal(prompt_modal)

        # Call custom callback if provided (for additional handling after modal opens)
        if self.on_edit_image:
            await self.on_edit_image(interaction, current_result, self)

    @discord.ui.button(label="Describe", style=discord.ButtonStyle.primary, row=1)
    async def describe_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
    ) -> None:
        """Generate a description of the current image using Haiku vision."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        current_result = self.get_current_result()
        image_url = current_result.get("url", "")

        # Download and prepare image for description
        try:
            image_b64 = await self._download_image_as_base64(image_url)
            image_b64 = await asyncio.to_thread(compress_image, image_b64)
            filename = self._generate_filename_from_url(image_url)
        except aiohttp.ClientError as e:
            logger.error(
                "describe_image_download_failed",
                view="GoogleResultsCarouselView",
                url=image_url,
                error=str(e),
            )
            await interaction.response.send_message(
                f"Failed to download image for description: {e}",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.error(
                "describe_image_prepare_failed",
                view="GoogleResultsCarouselView",
                url=image_url,
                error=str(e),
            )
            await interaction.response.send_message(
                "Failed to prepare image for description. Please try again.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Stop this view's timeout before transitioning
        self.stop()

        # Create image data for the description flow
        image_data: dict[str, str] = {
            "filename": filename,
            "image": image_b64,
        }

        # Transition to DescriptionDisplayView
        description_view = DescriptionDisplayView(
            interaction=interaction,
            image_data=image_data,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        await description_view.initialize(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger, row=1)
    async def return_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["GoogleResultsCarouselView"],
    ) -> None:
        """Return to the initial embed (ImageSelectionTypeView).

        Calls the on_return callback if provided, then stops this view
        to clear the search state. Images previously added to context
        are already persisted in the database and will remain.
        """
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Call the callback if provided (handles navigation logic)
        if self.on_return:
            await self.on_return(interaction, self)
        else:
            # Default behavior: just acknowledge
            await interaction.response.defer()
            logger.debug(
                "return_no_callback",
                view="GoogleResultsCarouselView",
            )

        # Stop this view (clears search state)
        self.stop()

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This search session has timed out. Please start again."
            self.embed.set_image(url=None)
            self.embed.set_footer(text=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, attachments=[], view=self)
            except Exception:
                pass  # Message may have been deleted


class SummarizePreviewView(discord.ui.View):
    """View for previewing and confirming conversation summarization.

    This view displays a summary preview with token count comparison
    and allows the user to confirm or cancel the summarization.
    """

    def __init__(
        self,
        user: dict[str, Any] | None = None,
        summary_text: str = "",
        original_tokens: int = 0,
        summary_tokens: int = 0,
        on_confirm: (
            Callable[[discord.Interaction], Coroutine[Any, Any, None]] | None
        ) = None,
        on_cancel: (
            Callable[[discord.Interaction], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        """Initialize the summarize preview view.

        Args:
            user: The user who initiated the command.
            summary_text: The generated summary text to preview.
            original_tokens: Approximate token count of original context.
            summary_tokens: Approximate token count of the summary.
            on_confirm: Callback when user confirms summarization.
            on_cancel: Callback when user cancels.
        """
        # 5 minute timeout for user interaction
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.summary_text = summary_text
        self.original_tokens = original_tokens
        self.summary_tokens = summary_tokens
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the summary preview embed."""
        # Truncate summary for display if too long (Discord embed limit)
        display_summary = self.summary_text
        if len(display_summary) > 4000:
            display_summary = display_summary[:3997] + "..."

        self.embed = discord.Embed(
            title="Conversation Summary Preview",
            description=display_summary,
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Add token count comparison in footer
        self.embed.set_footer(
            text=f"Original: ~{self.original_tokens} tokens -> Summary: ~{self.summary_tokens} tokens"
        )

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Summarize", style=discord.ButtonStyle.primary)
    async def summarize_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["SummarizePreviewView"],
    ) -> None:
        """Confirm and apply the summarization."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        if self.on_confirm:
            await self.on_confirm(interaction)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["SummarizePreviewView"],
    ) -> None:
        """Cancel the summarization."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Summarization Cancelled"
            self.embed.description = "No changes were made to your context."
            self.embed.set_footer(text=None)
        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        if self.on_cancel:
            await self.on_cancel(interaction)

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This summarization session has timed out. No changes were made."
            self.embed.set_footer(text=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class DescribeImageSourceView(discord.ui.View):
    """View for selecting an image source for the /describe_this command.

    Provides options to select an image from recent images, Google search,
    or upload directly via the command. The selected image will be sent
    to B3 (description display) for processing.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        user: dict[str, Any] | None = None,
        on_image_selected: (
            Callable[
                [discord.Interaction, dict[str, str]],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        """Initialize the describe image source view.

        Args:
            interaction: The Discord interaction that triggered this view.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            on_image_selected: Callback when an image is selected.
                Receives the interaction and image data dict with
                'filename' and 'image' (base64) keys.
            repo: Repository adapter for fetching recent images.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message: discord.Message | None = None
        self.on_image_selected = on_image_selected
        self.repo = repo
        self.carousel_files: list[dict[str, str]] = []

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the describe image source view."""
        self.embed = discord.Embed(
            title="Describe an Image",
            description=(
                "Select how you want to choose an image to describe.\n\n"
                "**Tip:** You can also run `/describe_this` with an image "
                "attachment to describe it directly."
            ),
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Check if the channel has recent images
        has_recent_images = False
        if self.repo and interaction.channel_id is not None:
            has_recent_images = await self.repo.has_images_in_context(
                interaction.channel_id, "All Models"
            )

        self.update_buttons(has_recent_images)
        logger.debug("embed_created", view="DescribeImageSourceView")

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )

        logger.debug("view_initialized", view="DescribeImageSourceView")

    def update_buttons(self, has_recent_images: bool) -> None:
        """Update button states based on available images."""
        self.google_search_button.disabled = False
        self.recent_images_button.disabled = not has_recent_images

    def disable_buttons(self) -> None:
        """Disable all selection buttons."""
        self.google_search_button.disabled = True
        self.recent_images_button.disabled = True
        self.cancel_button.disabled = True

    def hide_buttons(self) -> None:
        """Remove all selection buttons."""
        self.clear_items()

    @discord.ui.button(label="Google Search", style=discord.ButtonStyle.primary)
    async def google_search_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeImageSourceView"],
    ) -> None:
        """Open Google Image search for description."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        # Show the GoogleSearchModal
        modal = GoogleSearchModal(on_submit=self._handle_google_search)
        await interaction.response.send_modal(modal)

    async def _handle_google_search(
        self, interaction: discord.Interaction, query: str
    ) -> None:
        """Handle Google search query submission for description.

        This method orchestrates the Google Image search flow for image description:
        1. Show processing message
        2. Screen the query via Haiku content screening
        3. If rejected: log to database and show error
        4. If approved: execute SerpAPI search
        5. Display results in a carousel for single selection

        Args:
            interaction: The Discord interaction from the modal submit.
            query: The search query entered by the user.
        """
        from src.core.content_screening import screen_search_query
        from src.providers.serpapi_provider import SerpAPIError, search_google_images

        await interaction.response.defer()

        # 1. Show processing message
        if self.embed:
            self.embed.title = "Google Image Search"
            self.embed.description = f"Searching for: {query}... Processing"
        if self.message:
            await self.message.edit(embed=self.embed, view=None)

        # 2. Screen the query via Haiku
        try:
            screening_result = await screen_search_query(query)
        except Exception as e:
            logger.error(
                "content_screening_error",
                view="DescribeImageSourceView",
                query=query,
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Search Blocked"
                self.embed.description = (
                    "Content screening service is unavailable. Please try again later."
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        if not screening_result.allowed:
            # Log rejection to database
            if self.repo and interaction.channel_id is not None:
                guild_id = interaction.guild_id if interaction.guild else None
                await self.repo.log_search_rejection(
                    user_id=interaction.user.id,
                    channel_id=interaction.channel_id,
                    guild_id=guild_id,
                    query_text=query,
                    rejection_reason=screening_result.reason or "Content policy violation",
                )
                logger.info(
                    "search_query_rejected",
                    view="DescribeImageSourceView",
                    user_id=interaction.user.id,
                    channel_id=interaction.channel_id,
                    query=query,
                    reason=screening_result.reason,
                )

            if self.embed:
                self.embed.title = "Search Blocked"
                self.embed.description = (
                    f"Your search for **{query}** was blocked.\n\n"
                    f"Reason: {screening_result.reason or 'Content policy violation'}"
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        # 3. Execute SerpAPI search
        try:
            results = await search_google_images(query, num_results=10)
        except ValueError as e:
            logger.error(
                "serpapi_config_error",
                view="DescribeImageSourceView",
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Search Error"
                self.embed.description = (
                    "Google Image Search is not configured. "
                    "Please contact the bot administrator."
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return
        except SerpAPIError as e:
            logger.error(
                "serpapi_search_error",
                view="DescribeImageSourceView",
                query=query,
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Search Error"
                self.embed.description = "Search failed, please try again."
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        if not results:
            if self.embed:
                self.embed.title = "No Results"
                self.embed.description = f"No images found for: {query}"
                self.embed.color = EMBED_COLOR_INFO
            if self.message:
                await self.message.edit(embed=self.embed, view=None)
            return

        # 4. Show results in DescribeGoogleResultsCarouselView for single selection
        result_dicts = [
            {
                "url": r.url,
                "thumbnail_url": r.thumbnail_url or "",
                "title": r.title or "",
                "source_url": r.source_url or "",
            }
            for r in results
        ]

        # Create return callback
        async def on_return(
            return_interaction: discord.Interaction,
            view: "DescribeGoogleResultsCarouselView",
        ) -> None:
            """Handle return from carousel to source selection."""
            await return_interaction.response.defer()
            # Re-create this view
            new_view = DescribeImageSourceView(
                interaction=return_interaction,
                user=self.user,
                on_image_selected=self.on_image_selected,
                repo=self.repo,
            )
            new_view.message = self.message
            new_view.embed = discord.Embed(
                title="Describe an Image",
                description=(
                    "Select how you want to choose an image to describe.\n\n"
                    "**Tip:** You can also run `/describe_this` with an image "
                    "attachment to describe it directly."
                ),
            )
            new_view.embed.set_author(
                name=f"{self.username} (via Apex Mage)",
                url="https://github.com/aghs-scepter/apex-mage",
                icon_url=self.pfp,
            )
            has_recent_images = False
            if self.repo and return_interaction.channel_id is not None:
                has_recent_images = await self.repo.has_images_in_context(
                    return_interaction.channel_id, "All Models"
                )
            new_view.update_buttons(has_recent_images)
            if new_view.message:
                await new_view.message.edit(embed=new_view.embed, view=new_view)

        self.stop()

        carousel = DescribeGoogleResultsCarouselView(
            interaction=interaction,
            results=result_dicts,
            query=query,
            user=self.user,
            message=self.message,
            on_image_selected=self.on_image_selected,
            on_return=on_return,
        )
        await carousel.initialize(interaction)

    @discord.ui.button(label="Recent Images", style=discord.ButtonStyle.primary)
    async def recent_images_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeImageSourceView"],
    ) -> None:
        """Select a recent image from a carousel."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if not self.repo or interaction.channel_id is None:
            return

        images = await self.repo.get_images(interaction.channel_id, "All Models")
        self.carousel_files = images

        async def on_image_selected_from_carousel(
            img_interaction: discord.Interaction,
            image_data_list: list[dict[str, str]],
        ) -> None:
            """Handle image selection from single-image carousel."""
            if not image_data_list:
                # Cancelled - embed already updated by the view
                return

            # Take the first (and should be only) selected image
            if self.on_image_selected:
                await self.on_image_selected(img_interaction, image_data_list[0])

        self.stop()

        # Use DescribeSingleImageCarouselView for single-image selection
        carousel_view = DescribeSingleImageCarouselView(
            interaction=interaction,
            files=images,
            user=self.user,
            message=self.message,
            on_select=on_image_selected_from_carousel,
        )
        await carousel_view.initialize(interaction)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeImageSourceView"],
    ) -> None:
        """Cancel the describe operation."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can select this option.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Image description was cancelled."
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class DescribeSingleImageCarouselView(discord.ui.View):
    """A single-select image carousel for the describe_this command.

    Similar to MultiImageCarouselView but only allows selecting one image.
    """

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
    ) -> None:
        """Initialize the single-image carousel view.

        Args:
            interaction: The Discord interaction that triggered this view.
            files: List of image file dicts with 'filename' and 'image' keys.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional message to edit when updating the view.
            on_select: Callback when user confirms selection. Receives the
                interaction and list containing the single selected image dict.
                Empty list indicates cancellation.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
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
        """Initialize the single-image carousel view."""
        if not self.healthy:
            self.embed, self.embed_image = await self.create_error_embed(
                "ERROR: There are no images in context. "
                "Add or generate an image to use this feature.",
            )
            self.hide_buttons()
            logger.error("carousel_no_files", view="DescribeSingleImageCarouselView")
        else:
            self.embed, self.embed_image = await self.create_embed()
            self.update_buttons()
            logger.debug("embed_created", view="DescribeSingleImageCarouselView")

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
        logger.debug("view_initialized", view="DescribeSingleImageCarouselView")

    def generate_image_chrono_bar(self) -> str:
        """Generate a visual position indicator for the carousel."""
        symbols = []
        for i in range(len(self.files)):
            is_current = i == self.current_index
            symbol = "\u25cb"  # White circle
            if is_current:
                symbol = f"**[(**{symbol}**)]**"
            symbols.append(symbol)
        return "(Newest) " + " ".join(symbols) + " (Oldest)"

    async def create_error_embed(
        self, error_message: str
    ) -> tuple[discord.Embed, None]:
        """Create an error embed."""
        embed = discord.Embed(title="Error Message", description=error_message)
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        return embed, None

    async def create_embed(self) -> tuple[discord.Embed, discord.File]:
        """Create the carousel embed with current image."""
        embed_image = await create_file_from_image(self.files[self.current_index])

        embed = discord.Embed(
            title="Select an Image to Describe",
            description=self.generate_image_chrono_bar(),
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
        """Update button states based on current position."""
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= len(self.files) - 1

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
        """Update the embed with the current image after navigation."""
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        if self.embed:
            self.embed.description = self.generate_image_chrono_bar()
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
        button: discord.ui.Button["DescribeSingleImageCarouselView"],
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
        button: discord.ui.Button["DescribeSingleImageCarouselView"],
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

    @discord.ui.button(label="Select This Image", style=discord.ButtonStyle.success)
    async def select_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeSingleImageCarouselView"],
    ) -> None:
        """Select the current image and continue."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        if self.on_select:
            await interaction.response.defer()
            self.stop()
            selected = [self.files[self.current_index]]
            self.hide_buttons()
            await self.on_select(interaction, selected)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeSingleImageCarouselView"],
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


class DescribeGoogleResultsCarouselView(discord.ui.View):
    """Carousel view for Google Image search results for the describe command.

    Displays one image at a time from search results with navigation.
    Allows selecting an image for description.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        results: list[dict[str, str]],
        query: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_image_selected: (
            Callable[
                [discord.Interaction, dict[str, str]],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
        on_return: (
            Callable[
                [discord.Interaction, "DescribeGoogleResultsCarouselView"],
                Coroutine[Any, Any, None],
            ]
            | None
        ) = None,
    ) -> None:
        """Initialize the describe Google results carousel view.

        Args:
            interaction: The Discord interaction that triggered this view.
            results: List of image result dicts with 'url' and optional 'title' keys.
            query: The search query that produced these results.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional message to edit when updating the view.
            on_image_selected: Callback when user selects an image.
                Receives interaction and image data dict.
            on_return: Callback when user clicks Return.
                Receives interaction and this view.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.results = results
        self.query = query
        self.current_index = 0
        self.message = message
        self.on_image_selected = on_image_selected
        self.on_return = on_return
        self.healthy = bool(self.results)

    def generate_chrono_bar(self) -> str:
        """Generate a visual position indicator for the carousel."""
        symbols = []
        for i in range(len(self.results)):
            is_current = i == self.current_index
            symbol = "\u25cb"  # White circle
            if is_current:
                symbol = f"**[(**{symbol}**)]**"
            symbols.append(symbol)
        return " ".join(symbols)

    async def create_embed(self) -> discord.Embed:
        """Create the carousel embed with current image."""
        result = self.results[self.current_index]

        embed = discord.Embed(
            title=f"Search Results: {self.query}",
            description=(
                f"{self.generate_chrono_bar()}\n\n"
                f"**{result.get('title', 'Untitled')}**"
            ),
        )
        embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        # Use the full URL for display
        embed.set_image(url=result["url"])

        return embed

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Initialize the describe Google results carousel view."""
        if not self.healthy:
            self.embed = discord.Embed(
                title="No Results",
                description="No images found.",
                color=EMBED_COLOR_ERROR,
            )
            self.hide_buttons()
        else:
            self.embed = await self.create_embed()
            self.update_buttons()

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[],
                view=self,
            )

    def disable_buttons(self) -> None:
        """Disable all buttons."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    def hide_buttons(self) -> None:
        """Remove all buttons."""
        self.clear_items()

    def update_buttons(self) -> None:
        """Update button states based on current position."""
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= len(self.results) - 1

    async def update_embed(self, interaction: discord.Interaction) -> None:
        """Update the embed with the current image after navigation."""
        self.embed = await self.create_embed()
        self.update_buttons()

        if self.message:
            await self.message.edit(
                embed=self.embed,
                attachments=[],
                view=self,
            )

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeGoogleResultsCarouselView"],
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
        button: discord.ui.Button["DescribeGoogleResultsCarouselView"],
    ) -> None:
        """Navigate to next image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if self.current_index < len(self.results) - 1:
            self.current_index += 1
            await self.update_embed(interaction)

    @discord.ui.button(label="Select This Image", style=discord.ButtonStyle.success)
    async def select_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeGoogleResultsCarouselView"],
    ) -> None:
        """Select the current image for description."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Download the image and convert to base64
        result = self.results[self.current_index]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(result["url"], timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        raise ValueError(f"Failed to download image: HTTP {response.status}")
                    image_bytes = await response.read()
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

            # Compress the image
            image_b64 = await asyncio.to_thread(compress_image, image_b64)

            # Create image data dict
            image_data = {
                "filename": f"google_search_{self.current_index}.jpeg",
                "image": image_b64,
            }

            self.stop()
            self.hide_buttons()

            if self.on_image_selected:
                await self.on_image_selected(interaction, image_data)

        except Exception as e:
            logger.error(
                "image_download_failed",
                view="DescribeGoogleResultsCarouselView",
                url=result["url"],
                error=str(e),
            )
            if self.embed:
                self.embed.title = "Download Error"
                self.embed.description = (
                    "Failed to download this image. Please try another one."
                )
                self.embed.color = EMBED_COLOR_ERROR
            if self.message:
                await self.message.edit(embed=self.embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.primary)
    async def return_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeGoogleResultsCarouselView"],
    ) -> None:
        """Return to the image source selection."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        self.stop()
        if self.on_return:
            await self.on_return(interaction, self)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescribeGoogleResultsCarouselView"],
    ) -> None:
        """Cancel the operation."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Image description was cancelled."
            self.embed.set_image(url=None)
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
            self.embed.set_image(url=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class DescriptionEditModal(discord.ui.Modal, title="Edit Description"):
    """Modal for editing the generated image description.

    Allows users to modify the AI-generated description before using it
    for image generation. Limited to 1000 characters.
    """

    def __init__(
        self,
        current_description: str,
        on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the description edit modal.

        Args:
            current_description: The current description text to edit.
            on_submit: Callback when the modal is submitted with the new description.
        """
        super().__init__()
        self.on_submit_callback = on_submit

        self.description: discord.ui.TextInput[DescriptionEditModal] = discord.ui.TextInput(
            label="Edit the description:",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=current_description,
            placeholder="Enter a style-first description of the image...",
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await self.on_submit_callback(interaction, self.description.value)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle errors during modal submission."""
        logger.error("modal_error", view="DescriptionEditModal", error=str(error))

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


class EditPromptModal(discord.ui.Modal, title="Edit Prompt"):
    """Modal for editing the description before using it as an edit prompt.

    Allows users to modify the description before it's used to modify
    the original image. Limited to 1000 characters.
    """

    def __init__(
        self,
        current_prompt: str,
        on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the edit prompt modal.

        Args:
            current_prompt: The current prompt text (from description).
            on_submit: Callback when the modal is submitted with the edited prompt.
        """
        super().__init__()
        self.on_submit_callback = on_submit

        self.prompt: discord.ui.TextInput[EditPromptModal] = discord.ui.TextInput(
            label="Edit the prompt:",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=current_prompt,
            placeholder="Describe how to modify the image...",
        )
        self.add_item(self.prompt)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await self.on_submit_callback(interaction, self.prompt.value)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle errors during modal submission."""
        logger.error("modal_error", view="EditPromptModal", error=str(error))

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


class EditPromptConfirmView(discord.ui.View):
    """View for confirming or editing a prompt before using it for image modification.

    Shows the description as a prompt with options to edit it first or proceed directly.
    After confirmation, transitions to ImageEditPerformView to perform the actual edit.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        prompt: str,
        source_image_data: dict[str, str],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        """Initialize the edit prompt confirm view.

        Args:
            interaction: The Discord interaction.
            prompt: The description to use as edit prompt.
            source_image_data: The source image to modify.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional existing message to update.
            image_provider: Image provider for calling the modification API.
            rate_limiter: Rate limiter for image modification.
            gcs_adapter: GCS adapter for uploading images.
            repo: Repository adapter for storing images to context.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.interaction = interaction
        self.prompt = prompt
        self.source_image_data = source_image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.repo = repo
        self.embed: discord.Embed | None = None

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Display the confirm view with edit prompt option.

        Args:
            interaction: The Discord interaction.
        """
        # Truncate prompt for display if too long
        display_prompt = self.prompt
        if len(display_prompt) > 500:
            display_prompt = display_prompt[:497] + "..."

        self.embed = discord.Embed(
            title="Edit Prompt Confirmation",
            description=(
                f"**Prompt:**\n{display_prompt}\n\n"
                "Would you like to edit this prompt before modifying the image?"
            ),
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Show the source image as thumbnail
        embed_image = await create_file_from_image(self.source_image_data)
        self.embed.set_thumbnail(url=f"attachment://{embed_image.filename}")

        if self.message is not None:
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

    async def _proceed_with_edit(
        self, interaction: discord.Interaction, prompt: str
    ) -> None:
        """Proceed to perform the image edit.

        Args:
            interaction: The Discord interaction.
            prompt: The prompt to use for the edit.
        """
        if self.message is None:
            logger.error("message_not_set", view="EditPromptConfirmView")
            return

        # Transition to ImageEditPerformView
        perform_view = ImageEditPerformView(
            interaction=interaction,
            message=self.message,
            user=self.user,
            image_data=self.source_image_data,
            edit_type="description_edit",
            prompt=prompt,
            on_complete=None,  # ImageEditResultView handles result display
            rate_limiter=self.rate_limiter,
            image_provider=self.image_provider,
            image_data_list=[self.source_image_data],
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        self.stop()
        await perform_view.initialize(interaction)

    async def _handle_edit_modal_submit(
        self, interaction: discord.Interaction, edited_prompt: str
    ) -> None:
        """Handle submission from the edit prompt modal.

        Args:
            interaction: The Discord interaction.
            edited_prompt: The edited prompt text.
        """
        await interaction.response.defer()
        self.prompt = edited_prompt
        await self._proceed_with_edit(interaction, edited_prompt)

    @discord.ui.button(
        label="Edit Prompt",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def edit_prompt_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptConfirmView"],
    ) -> None:
        """Open modal to edit the prompt before proceeding."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        modal = EditPromptModal(
            current_prompt=self.prompt,
            on_submit=self._handle_edit_modal_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Use As-Is",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def use_as_is_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptConfirmView"],
    ) -> None:
        """Proceed with the current prompt without editing."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self._proceed_with_edit(interaction, self.prompt)

    @discord.ui.button(
        label="X",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["EditPromptConfirmView"],
    ) -> None:
        """Cancel and return to the routing view."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can cancel this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Edit prompt was cancelled."
            self.embed.set_thumbnail(url=None)

        if self.message:
            await self.message.edit(embed=self.embed, attachments=[], view=None)
        self.stop()

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
            self.embed.set_thumbnail(url=None)
        if self.message:
            try:
                await self.message.edit(embed=self.embed, attachments=[], view=None)
            except Exception:
                pass  # Message may have been deleted


class DescriptionRoutingView(discord.ui.View):
    """View for routing description to different actions.

    After the user accepts a description, this view shows buttons to:
    - Create Similar Image: Generate a new image using the description as prompt
    - Use as Edit Prompt: Modify the original image using the description
    - Copy Text: Copy the description to clipboard (uses Discord's copy feature)
    - Cancel: Dismiss the flow
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        description: str,
        reference_image_data: dict[str, str],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
        repo: "RepositoryAdapter | None" = None,
    ) -> None:
        """Initialize the description routing view.

        Args:
            interaction: The Discord interaction.
            description: The image description to route.
            reference_image_data: The original analyzed image data for reference.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional existing message to update.
            image_provider: Image provider for calling the generation API.
            rate_limiter: Rate limiter for image generation.
            gcs_adapter: GCS adapter for uploading images.
            repo: Repository adapter for storing images to context.
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.interaction = interaction
        self.description = description
        self.reference_image_data = reference_image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.repo = repo
        self.embed: discord.Embed | None = None
        self._generating = False

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Display the routing view with buttons.

        Args:
            interaction: The Discord interaction.
        """
        self.embed = discord.Embed(
            title="What would you like to do?",
            description=(
                f"**Your description:**\n{self.description}\n\n"
                "Choose an action below:"
            ),
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Show the reference image as thumbnail
        embed_image = await create_file_from_image(self.reference_image_data)
        self.embed.set_thumbnail(url=f"attachment://{embed_image.filename}")

        if self.message is not None:
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

    async def _generate_similar_image(self, interaction: discord.Interaction) -> None:
        """Generate a new image using the description as prompt.

        Args:
            interaction: The Discord interaction.
        """
        self._generating = True
        self.hide_buttons()

        # Update embed to show generating state
        if self.embed:
            self.embed.title = "Generating Image..."
            self.embed.description = (
                "Using description as prompt...\n"
                "(This may take up to 180 seconds)"
            )
            # Add the prompt as a field
            display_prompt = self.description
            if len(display_prompt) > 1024:
                display_prompt = display_prompt[:1021] + "..."
            self.embed.add_field(
                name="Prompt",
                value=display_prompt,
                inline=False,
            )

        if self.message:
            embed_image = await create_file_from_image(self.reference_image_data)
            await self.message.edit(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )

        try:
            # Check rate limit
            if self.rate_limiter:
                rate_check = await self.rate_limiter.check(
                    interaction.user.id, "image"
                )
                if not rate_check.allowed:
                    wait_msg = (
                        f" Try again in {int(rate_check.wait_seconds)} seconds."
                        if rate_check.wait_seconds
                        else ""
                    )
                    error_message = (
                        f"You're requesting too many images and have been "
                        f"rate-limited. The bot can handle a maximum of "
                        f"{getenv('FAL_RATE_LIMIT', '8')} image "
                        f"requests per hour.{wait_msg}"
                    )
                    if self.embed:
                        self.embed.title = "Rate Limited"
                        self.embed.description = error_message
                        self.embed.color = EMBED_COLOR_ERROR
                        self.embed.clear_fields()
                    if self.message:
                        embed_image = await create_file_from_image(self.reference_image_data)
                        await self.message.edit(
                            embed=self.embed,
                            attachments=[embed_image],
                            view=self,
                        )
                    self._generating = False
                    return

            # Generate the image
            if not self.image_provider:
                raise RuntimeError("Image provider not initialized")

            # Store the prompt in repo if available
            if self.repo and interaction.channel_id:
                await self.repo.create_channel(interaction.channel_id)
                await self.repo.add_message(
                    interaction.channel_id, "Fal.AI", "prompt", True, self.description
                )

            async with asyncio.timeout(API_TIMEOUT_SECONDS):
                generated_images = await self.image_provider.generate(
                    ImageRequest(prompt=self.description)
                )
            generated_image = generated_images[0]

            if generated_image.url is None:
                raise ValueError("Generated image has no URL")

            image_b64 = image_strip_headers(generated_image.url, "jpeg")
            image_b64 = await asyncio.to_thread(compress_image, image_b64)

            # Record the request after successful operation
            if self.rate_limiter:
                await self.rate_limiter.record(interaction.user.id, "image")

            has_nsfw = generated_image.has_nsfw_content or False
            output_filename = "image.jpeg"
            if has_nsfw:
                output_filename = "SPOILER_image.jpeg"

            # Upload to GCS for download button
            download_url: str | None = None
            if self.gcs_adapter and interaction.channel_id is not None:
                try:
                    download_url = await asyncio.to_thread(
                        self.gcs_adapter.upload_generated_image,
                        interaction.channel_id,
                        image_b64,
                    )
                    logger.info(
                        "image_uploaded_to_gcs",
                        channel_id=interaction.channel_id,
                        download_url=download_url,
                    )
                except Exception as upload_error:
                    logger.error(
                        "gcs_upload_failed",
                        channel_id=interaction.channel_id,
                        error=str(upload_error),
                    )
                    # Continue without download URL - image still shows

            # Show ImageGenerationResultView with the result
            result_view = ImageGenerationResultView(
                interaction=interaction,
                message=self.message,
                user=self.user,
                image_data={
                    "filename": output_filename,
                    "image": image_b64,
                },
                prompt=self.description,
                download_url=download_url,
                repo=self.repo,
                image_provider=self.image_provider,
                rate_limiter=self.rate_limiter,
                gcs_adapter=self.gcs_adapter,
            )
            await result_view.initialize(interaction)
            self._generating = False
            self.stop()

        except TimeoutError:
            logger.error("image_generation_timeout", timeout_seconds=API_TIMEOUT_SECONDS)
            if self.embed:
                self.embed.title = "Generation Timed Out"
                self.embed.description = (
                    "Image generation timed out after 180 seconds. "
                    "Please try again."
                )
                self.embed.color = EMBED_COLOR_ERROR
                self.embed.clear_fields()
            if self.message:
                embed_image = await create_file_from_image(self.reference_image_data)
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            self._generating = False

        except Exception as ex:
            logger.error(
                "image_generation_error",
                view="DescriptionRoutingView",
                error=str(ex),
            )
            if self.embed:
                self.embed.title = "Generation Failed"
                self.embed.description = f"An error occurred: {ex}"
                self.embed.color = EMBED_COLOR_ERROR
                self.embed.clear_fields()
            if self.message:
                embed_image = await create_file_from_image(self.reference_image_data)
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            self._generating = False

    @discord.ui.button(
        label="Create Similar Image",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def create_similar_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionRoutingView"],
    ) -> None:
        """Generate a new image using the description as prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the current operation to complete.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self._generate_similar_image(interaction)

    @discord.ui.button(
        label="Use as Edit Prompt",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def use_as_edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionRoutingView"],
    ) -> None:
        """Use the description to modify the original image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the current operation to complete.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Show EditPromptConfirmView to confirm/edit the prompt before modifying
        confirm_view = EditPromptConfirmView(
            interaction=interaction,
            prompt=self.description,
            source_image_data=self.reference_image_data,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
        )
        self.stop()
        await confirm_view.initialize(interaction)

    @discord.ui.button(
        label="Copy Text",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def copy_text_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionRoutingView"],
    ) -> None:
        """Send the description as an ephemeral message for easy copying."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Send the description as ephemeral so user can copy it
        await interaction.response.send_message(
            f"**Description (click to copy):**\n```\n{self.description}\n```",
            ephemeral=True,
        )

    @discord.ui.button(
        label="X",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionRoutingView"],
    ) -> None:
        """Cancel the routing flow."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can cancel this.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Cannot cancel while generating. Please wait.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()

        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Description routing was cancelled."
            self.embed.set_thumbnail(url=None)
            self.embed.clear_fields()

        if self.message:
            await self.message.edit(embed=self.embed, attachments=[], view=self)
        self.stop()

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        if self._generating:
            return  # Don't timeout during generation

        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
            self.embed.clear_fields()
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class DescriptionDisplayView(discord.ui.View):
    """View for displaying an image description with action buttons.

    Shows the Haiku-generated description in an embed with the analyzed image
    as a thumbnail. Provides buttons to create an image, edit the prompt, or cancel.

    Button layout: Create Image (green), Edit Prompt (blurple), X (red)

    Edit Prompt allows up to 3 edits total. After the 2nd edit, a warning is shown
    that only one more edit is allowed.
    """

    MAX_EDITS = 3

    def __init__(
        self,
        interaction: discord.Interaction,
        image_data: dict[str, str],
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
        gcs_adapter: "GCSAdapter | None" = None,
        repo: "RepositoryAdapter | None" = None,
        edit_count: int = 0,
        initial_description: str | None = None,
    ) -> None:
        """Initialize the description display view.

        Args:
            interaction: The Discord interaction that triggered this view.
            image_data: Dict with 'filename' and 'image' (base64) keys.
            user: Optional user dict with 'name', 'id', and 'pfp' keys.
            message: Optional existing message to update.
            image_provider: Image provider for calling the generation API.
            rate_limiter: Rate limiter for image generation.
            gcs_adapter: GCS adapter for uploading images.
            repo: Repository adapter for storing images to context.
            edit_count: Number of edits already made (for cycling).
            initial_description: Pre-existing description (for cycling after edit).
        """
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.interaction = interaction
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.image_data = image_data
        self.message = message
        self.description: str = initial_description or ""
        self.embed: discord.Embed | None = None
        self._generating = False
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.gcs_adapter = gcs_adapter
        self.repo = repo
        self.edit_count = edit_count

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Generate description and display the view.

        Calls haiku_describe_image() to generate a description (if not provided),
        then displays the result in an embed with action buttons.

        Args:
            interaction: The Discord interaction.
        """
        # If we already have a description (from edit cycling), skip generation
        if self.description:
            await self._display_result(interaction)
            return

        self._generating = True

        # Create loading embed
        self.embed = discord.Embed(
            title="Generating Description...",
            description="Analyzing image with Haiku vision...",
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Show thumbnail of the image being analyzed
        embed_image = await create_file_from_image(self.image_data)
        self.embed.set_thumbnail(url=f"attachment://{embed_image.filename}")

        # Disable buttons during generation
        self.create_image_button.disabled = True
        self.edit_prompt_button.disabled = True

        # Display loading state
        if self.message is not None:
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

        # Generate description using Haiku vision
        try:
            # Determine media type from filename
            filename = self.image_data.get("filename", "image.jpeg").lower()
            if filename.endswith(".png"):
                media_type = "image/png"
            elif filename.endswith(".gif"):
                media_type = "image/gif"
            elif filename.endswith(".webp"):
                media_type = "image/webp"
            else:
                media_type = "image/jpeg"

            self.description = await haiku_describe_image(
                image_base64=self.image_data["image"],
                media_type=media_type,
            )

            logger.info(
                "description_generated",
                view="DescriptionDisplayView",
                description_length=len(self.description),
            )

        except ImageDescriptionError as e:
            logger.error(
                "description_generation_failed",
                view="DescriptionDisplayView",
                error=str(e),
            )
            # Show error in embed
            self.embed.title = "Description Generation Failed"
            self.embed.description = str(e)
            self.embed.color = EMBED_COLOR_ERROR
            self.hide_buttons()

            if self.message:
                # Re-create the file since it was consumed
                embed_image = await create_file_from_image(self.image_data)
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            self._generating = False
            return

        self._generating = False
        await self._display_result(interaction)

    async def _display_result(self, interaction: discord.Interaction) -> None:
        """Display the description result with action buttons.

        Args:
            interaction: The Discord interaction.
        """
        # Build description text with optional warning
        description_text = self.description
        if self.edit_count == self.MAX_EDITS - 1:
            # After 2nd edit (edit_count=2), show warning before 3rd edit
            description_text = (
                f"{self.description}\n\n"
                "**You can edit the prompt one more time before further editing is disabled.**"
            )

        # Update embed with description
        self.embed = discord.Embed(
            title="Image Description",
            description=description_text,
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Show thumbnail of the analyzed image
        embed_image = await create_file_from_image(self.image_data)
        self.embed.set_thumbnail(url=f"attachment://{embed_image.filename}")

        # Enable buttons (disable Edit Prompt if max edits reached)
        self.create_image_button.disabled = False
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
        self, interaction: discord.Interaction, new_description: str
    ) -> None:
        """Handle edit prompt modal submission - cycle back to same view.

        Args:
            interaction: The Discord interaction from the modal.
            new_description: The new description text.
        """
        # Increment edit count and cycle back to this view with new description
        new_edit_count = self.edit_count + 1

        # Create new view with updated description and edit count
        new_view = DescriptionDisplayView(
            interaction=interaction,
            image_data=self.image_data,
            user=self.user,
            message=self.message,
            image_provider=self.image_provider,
            rate_limiter=self.rate_limiter,
            gcs_adapter=self.gcs_adapter,
            repo=self.repo,
            edit_count=new_edit_count,
            initial_description=new_description,
        )

        # Respond to modal and initialize new view
        await interaction.response.defer()
        self.stop()
        await new_view.initialize(interaction)

    async def _generate_image(self, interaction: discord.Interaction) -> None:
        """Generate an image using the description and show variations carousel.

        Args:
            interaction: The Discord interaction.
        """
        self._generating = True
        self.hide_buttons()

        # Update embed to show generating state
        if self.embed:
            self.embed.title = "Generating Image..."
            self.embed.description = (
                "Using description as prompt...\n"
                "(This may take up to 180 seconds)"
            )
            # Add the prompt as a field
            display_prompt = self.description
            if len(display_prompt) > 1024:
                display_prompt = display_prompt[:1021] + "..."
            self.embed.add_field(
                name="Prompt",
                value=display_prompt,
                inline=False,
            )

        if self.message:
            embed_image = await create_file_from_image(self.image_data)
            await self.message.edit(
                embed=self.embed,
                attachments=[embed_image],
                view=self,
            )

        try:
            # Check rate limit
            if self.rate_limiter:
                rate_check = await self.rate_limiter.check(
                    interaction.user.id, "image"
                )
                if not rate_check.allowed:
                    wait_msg = (
                        f" Try again in {int(rate_check.wait_seconds)} seconds."
                        if rate_check.wait_seconds
                        else ""
                    )
                    error_message = (
                        f"You're requesting too many images and have been "
                        f"rate-limited. The bot can handle a maximum of "
                        f"{getenv('FAL_RATE_LIMIT', '8')} image "
                        f"requests per hour.{wait_msg}"
                    )
                    if self.embed:
                        self.embed.title = "Rate Limited"
                        self.embed.description = error_message
                        self.embed.color = EMBED_COLOR_ERROR
                        self.embed.clear_fields()
                    if self.message:
                        embed_image = await create_file_from_image(self.image_data)
                        await self.message.edit(
                            embed=self.embed,
                            attachments=[embed_image],
                            view=self,
                        )
                    self._generating = False
                    return

            # Generate the image
            if not self.image_provider:
                raise RuntimeError("Image provider not initialized")

            # Store the prompt in repo if available
            if self.repo and interaction.channel_id:
                await self.repo.create_channel(interaction.channel_id)
                await self.repo.add_message(
                    interaction.channel_id, "Fal.AI", "prompt", True, self.description
                )

            async with asyncio.timeout(API_TIMEOUT_SECONDS):
                generated_images = await self.image_provider.generate(
                    ImageRequest(prompt=self.description)
                )
            generated_image = generated_images[0]

            if generated_image.url is None:
                raise ValueError("Generated image has no URL")

            image_b64 = image_strip_headers(generated_image.url, "jpeg")
            image_b64 = await asyncio.to_thread(compress_image, image_b64)

            # Record the request after successful operation
            if self.rate_limiter:
                await self.rate_limiter.record(interaction.user.id, "image")

            has_nsfw = generated_image.has_nsfw_content or False
            output_filename = "image.jpeg"
            if has_nsfw:
                output_filename = "SPOILER_image.jpeg"

            self._generating = False

            # Show VariationCarouselView with the generated image
            if self.message is None:
                raise RuntimeError("Message is None")

            carousel_view = VariationCarouselView(
                interaction=interaction,
                message=self.message,
                user=self.user,
                original_image={
                    "filename": output_filename,
                    "image": image_b64,
                },
                prompt=self.description,
                repo=self.repo,
                image_provider=self.image_provider,
                rate_limiter=self.rate_limiter,
            )
            self.stop()
            await carousel_view.initialize(interaction)

        except TimeoutError:
            logger.error("image_generation_timeout", timeout_seconds=API_TIMEOUT_SECONDS)
            if self.embed:
                self.embed.title = "Generation Timed Out"
                self.embed.description = (
                    "Image generation timed out after 180 seconds. "
                    "Please try again."
                )
                self.embed.color = EMBED_COLOR_ERROR
                self.embed.clear_fields()
            if self.message:
                embed_image = await create_file_from_image(self.image_data)
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            self._generating = False

        except Exception as ex:
            logger.error(
                "image_generation_error",
                view="DescriptionDisplayView",
                error=str(ex),
            )
            if self.embed:
                self.embed.title = "Generation Failed"
                self.embed.description = f"An error occurred: {ex}"
                self.embed.color = EMBED_COLOR_ERROR
                self.embed.clear_fields()
            if self.message:
                embed_image = await create_file_from_image(self.image_data)
                await self.message.edit(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self,
                )
            self._generating = False

    @discord.ui.button(label="Create Image", style=discord.ButtonStyle.success, row=0)
    async def create_image_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionDisplayView"],
    ) -> None:
        """Generate an image using the description as prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the current operation to complete.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self._generate_image(interaction)

    @discord.ui.button(label="Edit Prompt", style=discord.ButtonStyle.primary, row=0)
    async def edit_prompt_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionDisplayView"],
    ) -> None:
        """Open modal to edit the prompt, then cycle back to same view."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can edit this.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the description to finish generating.",
                ephemeral=True,
            )
            return

        if self.edit_count >= self.MAX_EDITS:
            await interaction.response.send_message(
                "Maximum number of edits reached.",
                ephemeral=True,
            )
            return

        modal = DescriptionEditModal(
            current_description=self.description,
            on_submit=self._handle_edit_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["DescriptionDisplayView"],
    ) -> None:
        """Cancel the description flow."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can cancel this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.hide_buttons()

        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Image description was cancelled."
            self.embed.set_thumbnail(url=None)

        if self.message:
            await self.message.edit(embed=self.embed, attachments=[], view=self)
        self.stop()

    async def on_timeout(self) -> None:
        """Update the embed on timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = (
                "This interaction has timed out. Please start again."
            )
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass  # Message may have been deleted


class VariationCarouselView(discord.ui.View):
    """A carousel view for displaying image variations.

    Allows users to navigate between an original image and up to 3 variations.
    Provides buttons for generating variations (Same Prompt or AI Remix) and
    adding the selected image to context.

    UI Layout:
    - Embed shows current image with position indicator
    - Source thumbnail shown above (if from modify_image)
    - Row 0: [<] [>] navigation
    - Row 1: [Same Prompt] [AI Remix] variation buttons
    - Row 2: [Add to Context] [Cancel]
    """

    MAX_VARIATIONS = 3

    def __init__(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
        user: dict[str, Any] | None,
        original_image: dict[str, str],
        prompt: str,
        source_image: dict[str, str] | None = None,
        repo: "RepositoryAdapter | None" = None,
        image_provider: "ImageProvider | None" = None,
        rate_limiter: "SlidingWindowRateLimiter | None" = None,
    ) -> None:
        """Initialize the variation carousel view.

        Args:
            interaction: The Discord interaction.
            message: The message to update with the carousel.
            user: User dict with name, id, and pfp keys.
            original_image: The original image data with filename and image keys.
            prompt: The prompt used for image generation.
            source_image: Optional source image for modify_image comparison.
            repo: Repository adapter for storing images to context.
            image_provider: Image provider for generating variations.
            rate_limiter: Rate limiter for image generation.
        """
        super().__init__(timeout=RESULT_VIEW_TIMEOUT)
        self.interaction = interaction
        self.message = message
        self.user = user
        self.original_image = original_image
        self.prompt = prompt
        self.source_image = source_image
        self.repo = repo
        self.image_provider = image_provider
        self.rate_limiter = rate_limiter
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.added_to_context = False
        self._generating = False  # Prevent concurrent generation

        # Carousel state
        self.variations: list[dict[str, str]] = []
        self.current_index = 0  # 0 = original, 1-3 = variations

    def _get_all_images(self) -> list[dict[str, str]]:
        """Get list of all images (original + variations)."""
        return [self.original_image] + self.variations

    def _get_current_image(self) -> dict[str, str]:
        """Get the currently displayed image."""
        all_images = self._get_all_images()
        return all_images[self.current_index]

    def _generate_position_indicator(self) -> str:
        """Generate a visual position indicator for the carousel.

        Dynamic dots matching actual image count (E4-T3):
        - Uses filled circle for current position
        - Uses empty circles for other positions
        - Bold brackets around the current selection

        Returns:
            Position indicator string like "**[(Original)]**" or "o **[(1)]**".
        """
        all_images = self._get_all_images()
        total = len(all_images)

        # Build position dots dynamically (only for actual images)
        parts = []
        for i in range(total):
            if i == self.current_index:
                # Current position: filled circle with label in bold brackets
                if i == 0:
                    parts.append("**[(●)]** Original")
                else:
                    parts.append(f"**[(●)]** {i}")
            else:
                # Other positions: empty circle
                parts.append("\u25cb")

        return " ".join(parts)

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the carousel embed."""
        self.embed = discord.Embed(
            title="Image Variations",
            description=self._generate_position_indicator(),
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        # Add prompt as a field (truncated if too long)
        if self.prompt:
            display_prompt = self.prompt
            if len(display_prompt) > 1024:
                display_prompt = display_prompt[:1021] + "..."
            self.embed.add_field(
                name="Prompt",
                value=display_prompt,
                inline=False,
            )

        # Create the current image file
        current_image = self._get_current_image()
        result_file = await create_file_from_image(current_image)
        self.embed.set_image(url=f"attachment://{result_file.filename}")

        # Build list of attachments
        attachments: list[discord.File] = [result_file]

        # Add source thumbnail if provided (for modify_image comparison)
        if self.source_image:
            source_file = discord.File(
                io.BytesIO(base64.b64decode(self.source_image["image"])),
                filename="source_thumbnail.jpeg",
            )
            self.embed.set_thumbnail(url="attachment://source_thumbnail.jpeg")
            self.embed.set_footer(text="Source image shown in thumbnail")
            attachments.append(source_file)

        # Update button states
        self._update_buttons()

        await self.message.edit(
            embed=self.embed,
            attachments=attachments,
            view=self,
        )

    async def _update_embed(self) -> None:
        """Update the embed with the current image after navigation."""
        if self.embed:
            self.embed.description = self._generate_position_indicator()

        # Create the current image file
        current_image = self._get_current_image()
        result_file = await create_file_from_image(current_image)
        if self.embed:
            self.embed.set_image(url=f"attachment://{result_file.filename}")

        # Build list of attachments
        attachments: list[discord.File] = [result_file]

        # Add source thumbnail if provided
        if self.source_image:
            source_file = discord.File(
                io.BytesIO(base64.b64decode(self.source_image["image"])),
                filename="source_thumbnail.jpeg",
            )
            attachments.append(source_file)

        # Update button states
        self._update_buttons()

        await self.message.edit(
            embed=self.embed,
            attachments=attachments,
            view=self,
        )

    def _update_buttons(self) -> None:
        """Update button disabled states based on current state."""
        all_images = self._get_all_images()
        total = len(all_images)

        # Navigation buttons: disabled at bounds
        self.previous_button.disabled = self.current_index <= 0
        self.next_button.disabled = self.current_index >= total - 1

        # Variation buttons: disabled after 3 variations generated
        at_max_variations = len(self.variations) >= self.MAX_VARIATIONS
        self.same_prompt_button.disabled = at_max_variations
        self.ai_remix_button.disabled = at_max_variations

    def _disable_all_buttons(self) -> None:
        """Disable all non-link buttons."""
        for child in self.children:
            if isinstance(child, discord.ui.Button) and not child.url:
                child.disabled = True

    def _hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    async def on_timeout(self) -> None:
        """Update the embed when the view times out."""
        if self.embed:
            if not self.added_to_context:
                self.embed.description = (
                    "This interaction has timed out. "
                    "The image was NOT added to context."
                )
            self.embed.color = EMBED_COLOR_ERROR if not self.added_to_context else EMBED_COLOR_INFO

        self._disable_all_buttons()

        try:
            await self.message.edit(embed=self.embed, view=self)
        except Exception:
            pass  # Message may have been deleted

    # Row 0: Navigation buttons
    @discord.ui.button(label="<", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
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
            await self._update_embed()

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary, row=0)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
    ) -> None:
        """Navigate to next image."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        all_images = self._get_all_images()
        if self.current_index < len(all_images) - 1:
            self.current_index += 1
            await self._update_embed()

    # Row 1: Variation generation buttons
    @discord.ui.button(label="Same Prompt", style=discord.ButtonStyle.secondary, row=1)
    async def same_prompt_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
    ) -> None:
        """Generate a variation using the same prompt.

        Relies on model randomness to produce variations of the original image.
        """
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if len(self.variations) >= self.MAX_VARIATIONS:
            await interaction.response.send_message(
                "Maximum number of variations reached.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the current generation to complete.",
                ephemeral=True,
            )
            return

        if not self.image_provider:
            await interaction.response.send_message(
                "Image generation is not available.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self._generating = True

        # Show generating status
        if self.embed:
            self.embed.description = f"{self._generate_position_indicator()}\nGenerating variation..."

        # Disable buttons during generation
        self._disable_all_buttons()
        await self.message.edit(embed=self.embed, view=self)

        try:
            variation_image = await generate_variation_same_prompt(
                original_prompt=self.prompt,
                image_provider=self.image_provider,
                user_id=self.user_id,
                rate_limiter=self.rate_limiter,
            )

            # Add the variation and navigate to it
            self.variations.append(variation_image)
            self.current_index = len(self._get_all_images()) - 1

            logger.info(
                "same_prompt_variation_added",
                view="VariationCarouselView",
                variation_count=len(self.variations),
            )

            # Update the embed with the new variation
            await self._update_embed()

        except RateLimitExceededError as e:
            retry_msg = ""
            if e.retry_after:
                minutes = int(e.retry_after // 60)
                retry_msg = f" Try again in {minutes} minute(s)."
            if self.embed:
                self.embed.description = (
                    f"{self._generate_position_indicator()}\n"
                    f"Rate limit exceeded.{retry_msg}"
                )
            self._update_buttons()
            await self.message.edit(embed=self.embed, view=self)

        except VariationError as e:
            logger.error(
                "same_prompt_variation_failed",
                view="VariationCarouselView",
                error=str(e),
            )
            if self.embed:
                self.embed.description = (
                    f"{self._generate_position_indicator()}\n"
                    f"Failed to generate variation: {e}"
                )
            self._update_buttons()
            await self.message.edit(embed=self.embed, view=self)

        finally:
            self._generating = False

    @discord.ui.button(label="AI Remix", style=discord.ButtonStyle.secondary, row=1)
    async def ai_remix_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
    ) -> None:
        """Generate a variation with AI-remixed prompt.

        Uses Haiku to slightly modify the prompt while preserving style,
        then generates a new image.
        """
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        if len(self.variations) >= self.MAX_VARIATIONS:
            await interaction.response.send_message(
                "Maximum number of variations reached.",
                ephemeral=True,
            )
            return

        if self._generating:
            await interaction.response.send_message(
                "Please wait for the current generation to complete.",
                ephemeral=True,
            )
            return

        if not self.image_provider:
            await interaction.response.send_message(
                "Image generation is not available.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self._generating = True

        # Show generating status
        if self.embed:
            self.embed.description = (
                f"{self._generate_position_indicator()}\n"
                "Remixing prompt and generating variation..."
            )

        # Disable buttons during generation
        self._disable_all_buttons()
        await self.message.edit(embed=self.embed, view=self)

        try:
            remixed_prompt, variation_image = await generate_variation_remixed(
                original_prompt=self.prompt,
                image_provider=self.image_provider,
                user_id=self.user_id,
                rate_limiter=self.rate_limiter,
            )

            # Add the variation and navigate to it
            self.variations.append(variation_image)
            self.current_index = len(self._get_all_images()) - 1

            logger.info(
                "remixed_variation_added",
                view="VariationCarouselView",
                variation_count=len(self.variations),
                remixed_prompt_preview=remixed_prompt[:100] if remixed_prompt else "",
            )

            # Update the embed with the new variation
            # Also update the prompt field to show the remixed prompt
            if self.embed and self.embed.fields:
                # Update the prompt field to show remixed prompt
                display_prompt = remixed_prompt
                if len(display_prompt) > 1024:
                    display_prompt = display_prompt[:1021] + "..."
                self.embed.set_field_at(
                    0,
                    name="Prompt (AI Remixed)",
                    value=display_prompt,
                    inline=False,
                )

            await self._update_embed()

        except RateLimitExceededError as e:
            retry_msg = ""
            if e.retry_after:
                minutes = int(e.retry_after // 60)
                retry_msg = f" Try again in {minutes} minute(s)."
            if self.embed:
                self.embed.description = (
                    f"{self._generate_position_indicator()}\n"
                    f"Rate limit exceeded.{retry_msg}"
                )
            self._update_buttons()
            await self.message.edit(embed=self.embed, view=self)

        except VariationError as e:
            logger.error(
                "remixed_variation_failed",
                view="VariationCarouselView",
                error=str(e),
            )
            if self.embed:
                self.embed.description = (
                    f"{self._generate_position_indicator()}\n"
                    f"Failed to generate remixed variation: {e}"
                )
            self._update_buttons()
            await self.message.edit(embed=self.embed, view=self)

        finally:
            self._generating = False

    # Row 2: Action buttons
    @discord.ui.button(label="Add to Context", style=discord.ButtonStyle.success, row=2)
    async def add_to_context_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
    ) -> None:
        """Add the currently displayed image to the channel context."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Get the currently displayed image
        current_image = self._get_current_image()

        # Store the image in context
        if self.repo and interaction.channel_id is not None:
            try:
                await self.repo.create_channel(interaction.channel_id)
                images = [current_image]
                str_images = json.dumps(images)
                await self.repo.add_message_with_images(
                    interaction.channel_id,
                    "Fal.AI",
                    "prompt",
                    False,
                    "Image Variation",
                    str_images,
                    is_image_only_context=True,
                )
                self.added_to_context = True
                logger.info(
                    "variation_carousel_added_to_context",
                    view="VariationCarouselView",
                    channel_id=interaction.channel_id,
                    image_index=self.current_index,
                )
            except Exception as e:
                logger.error(
                    "variation_carousel_add_failed",
                    view="VariationCarouselView",
                    error=str(e),
                )
                if self.embed:
                    self.embed.description = f"Failed to add image to context: {e}"
                    self.embed.color = EMBED_COLOR_ERROR
                await self.message.edit(embed=self.embed, view=self)
                return

        # E4-T4: Remove ALL buttons after Add to Context
        self._hide_buttons()
        self.stop()

        # Update embed description
        if self.embed:
            position_label = "original" if self.current_index == 0 else f"variation {self.current_index}"
            self.embed.description = (
                f"Image ({position_label}) added to context successfully!\n"
                "You can use it for future /describe_this and /modify_image commands."
            )

        await self.message.edit(embed=self.embed, view=self)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger, row=2)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["VariationCarouselView"],
    ) -> None:
        """Cancel the variation carousel without adding to context."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self._hide_buttons()

        if self.embed:
            self.embed.title = "Operation Cancelled"
            self.embed.description = "Image variation was cancelled. No image was added to context."
            self.embed.set_image(url=None)
            self.embed.set_thumbnail(url=None)

        await self.message.edit(embed=self.embed, attachments=[], view=self)
        self.stop()
