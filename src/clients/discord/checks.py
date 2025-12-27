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

    # Commands that bypass whitelist/ban checks (available to everyone)
    EXEMPT_COMMANDS: frozenset[str] = frozenset({"my_status"})

    async def interaction_check(self, interaction: discord.Interaction["DiscordBot"]) -> bool:
        """Check if the user is whitelisted and not banned before allowing command execution.

        Access control flow:
        1. Skip check for exempt commands (e.g., /my_status)
        2. Check whitelist first - deny if not whitelisted
        3. Check banlist - ban takes precedence for whitelisted users
        4. Allow if whitelisted and not banned

        Args:
            interaction: The Discord interaction to check.

        Returns:
            True if the user is whitelisted and not banned,
            False otherwise.
        """
        # Get the bot instance from the client
        bot = interaction.client
        user_id = interaction.user.id
        username = interaction.user.name
        command_name = interaction.command.name if interaction.command else "unknown"

        # Allow exempt commands without any checks
        if command_name in self.EXEMPT_COMMANDS:
            return True

        # Check whitelist first
        is_whitelisted = await bot.repo.is_user_whitelisted(user_id)

        if not is_whitelisted:
            await interaction.response.send_message(
                "Access denied. Contact @aghs",
                ephemeral=False,
            )

            logger.info(
                "non_whitelisted_user_command_blocked",
                username=username,
                user_id=user_id,
                command=command_name,
            )

            return False

        # Check if whitelisted user is banned (ban takes precedence)
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
                user_id=user_id,
                command=command_name,
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
