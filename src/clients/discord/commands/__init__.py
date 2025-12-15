"""Discord command modules."""

from src.clients.discord.commands.chat import register_chat_commands
from src.clients.discord.commands.image import register_image_commands

__all__ = ["register_chat_commands", "register_image_commands"]
