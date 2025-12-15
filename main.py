"""Entry point for the Discord bot."""

import asyncio
import logging
import os

from src.clients.discord import (
    create_bot,
    register_chat_commands,
    register_image_commands,
)

# Configure root logger to output to stdout (for Docker logs)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Initialize and start the Discord bot."""
    bot = create_bot()

    # Register command handlers
    register_chat_commands(bot)
    register_image_commands(bot)

    # Set up on_ready event handler
    @bot.event
    async def on_ready() -> None:
        """On bot startup, log success and register commands for all guilds."""
        if bot.user:
            logging.debug(f"Logged in as {bot.user} (ID: {bot.user.id})")
        logging.debug("------")
        for guild in bot.guilds:
            await bot.register_commands(guild)

    # Start the bot
    await bot.start(os.environ["DISCORD_BOT_TOKEN"])


if __name__ == "__main__":
    asyncio.run(main())
