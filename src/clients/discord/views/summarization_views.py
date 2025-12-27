"""Summarization-related views for Discord UI.

This module contains views for conversation summarization preview
and confirmation.
"""

from collections.abc import Callable, Coroutine
from typing import Any

import discord

from src.clients.discord.constants import EMBED_COLOR_INFO, USER_INTERACTION_TIMEOUT
from src.clients.discord.utils import get_user_info
from src.core.logging import get_logger

__all__ = [
    "SummarizePreviewView",
]

logger = get_logger(__name__)


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
            except discord.NotFound:
                pass  # Message deleted, expected
            except discord.HTTPException as e:
                logger.warning("message_edit_failed", error=str(e))
