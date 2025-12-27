"""Google search-related views for Discord UI.

This module contains views for Google Image search functionality,
including the search modal and results carousel.
"""

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

from src.clients.discord.constants import EMBED_COLOR_INFO
from src.clients.discord.utils import get_user_info
from src.core.logging import get_logger

if TYPE_CHECKING:
    pass

__all__ = [
    "GoogleSearchModal",
    "PresetSelect",
    "PresetSelectView",
]

logger = get_logger(__name__)


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
