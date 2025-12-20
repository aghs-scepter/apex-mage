"""Global checks for Discord bot commands."""

from typing import TYPE_CHECKING

import discord

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

logger = get_logger(__name__)


def register_global_checks(bot: "DiscordBot") -> None:
    """Register global interaction checks with the bot.

    This sets up checks that run before every slash command.

    Args:
        bot: The Discord bot instance.
    """

    @bot.tree.interaction_check  # type: ignore[arg-type]
    async def global_ban_check(interaction: discord.Interaction["DiscordBot"]) -> bool:
        """Check if the user is banned before allowing command execution.

        If the user is banned, sends a visible (non-ephemeral) message
        with the ban reason and prevents the command from executing.

        Args:
            interaction: The Discord interaction to check.

        Returns:
            True if the user is not banned and can proceed,
            False if the user is banned.
        """
        username = interaction.user.name

        # Check if user is banned
        is_banned = await bot.repo.is_user_banned(username)

        if is_banned:
            # Get the ban reason
            reason = await bot.repo.get_ban_reason(username)
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
