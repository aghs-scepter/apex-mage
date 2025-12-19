"""Shared utilities for Discord commands."""

import asyncio
from typing import TYPE_CHECKING

import discord

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

logger = get_logger(__name__)


async def handle_text_overflow(
    bot: "DiscordBot", text_type: str, text: str, channel_id: int
) -> tuple[str, str | None]:
    """Handle text overflow by truncating and uploading to cloud storage if needed.

    Args:
        bot: The Discord bot instance with GCS adapter.
        text_type: The type of text ("prompt" or "response")
        text: The original text
        channel_id: The channel ID

    Returns:
        Tuple of (modified_text, cloud_url or None)
    """
    if len(text) > 1024:
        try:
            cloud_url = await asyncio.to_thread(
                bot.gcs_adapter.upload_text, text_type, channel_id, text
            )
            modified_text = (
                text[:950]
                + f"**--[{text_type.capitalize()} too long! "
                f"Use the button to see the full {text_type}.]--**"
            )
            return modified_text, cloud_url
        except Exception as ex:
            logger.error(
                "cloud_upload_failed",
                text_type=text_type,
                channel_id=channel_id,
                error=str(ex),
            )
            modified_text = (
                text[:950]
                + f"**--[{text_type.capitalize()} too long! "
                f"Full {text_type} upload failed.]--**"
            )
            return modified_text, None
    return text, None


def create_embed_user(interaction: discord.Interaction) -> dict[str, object]:
    """Create user slug for embed decoration.

    Args:
        interaction: The Discord interaction.

    Returns:
        Dictionary containing user display name, id, and avatar.
    """
    return {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar,
    }
