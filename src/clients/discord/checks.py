"""Global checks for Discord bot commands."""

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

logger = get_logger(__name__)


class BanCheckCommandTree(app_commands.CommandTree["DiscordBot"]):
    """Custom CommandTree that enforces global ban checks on all interactions.

    This subclass overrides interaction_check to verify users are not banned
    before allowing any slash command to execute.
    """

    async def interaction_check(self, interaction: discord.Interaction["DiscordBot"]) -> bool:
        """Check if the user is banned before allowing command execution.

        If the user is banned, sends a visible (non-ephemeral) message
        with the ban reason and prevents the command from executing.

        Args:
            interaction: The Discord interaction to check.

        Returns:
            True if the user is not banned and can proceed,
            False if the user is banned.
        """
        # Get the bot instance from the client
        bot = interaction.client
        user_id = interaction.user.id
        username = interaction.user.name

        # Check if user is banned
        is_banned = await bot.repo.is_user_banned(user_id)

        if is_banned:
            # Get the ban reason
            reason = await bot.repo.get_ban_reason(user_id)
            reason_text = reason if reason else "No reason provided"

            # Send visible message (not ephemeral) so it stays in chat
            await interaction.response.send_message(
                f"You are banned from using this bot. Reason: {reason_text}",
                ephemeral=False,
            )

            logger.info(
                "banned_user_command_blocked",
                username=username,
                user_id=interaction.user.id,
                command=interaction.command.name if interaction.command else "unknown",
                reason=reason_text,
            )

            return False

        return True


def register_global_checks(bot: "DiscordBot") -> None:
    """Register global interaction checks with the bot.

    Note: This function is now a no-op since the ban check is implemented
    directly in BanCheckCommandTree.interaction_check. It is kept for
    backwards compatibility and to allow future additional checks.

    Args:
        bot: The Discord bot instance.
    """
    # Ban check is now handled by BanCheckCommandTree.interaction_check
    # This function is kept for backwards compatibility
    pass
