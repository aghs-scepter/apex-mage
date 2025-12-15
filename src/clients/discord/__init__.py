"""Discord client package."""

from src.clients.discord.bot import DiscordBot, create_bot
from src.clients.discord.commands import register_chat_commands, register_image_commands
from src.clients.discord.decorators import handle_errors, log_command

__all__ = [
    "DiscordBot",
    "create_bot",
    "handle_errors",
    "log_command",
    "register_chat_commands",
    "register_image_commands",
]
