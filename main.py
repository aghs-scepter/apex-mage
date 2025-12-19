"""Entry point for the Discord bot."""

import asyncio
import os

import discord

from src.clients.discord import (
    DiscordBot,
    create_bot,
    register_chat_commands,
    register_image_commands,
)
from src.core.health import (
    HealthChecker,
    ServiceCheck,
    ServiceStatus,
    start_health_server,
)
from src.core.logging import configure_logging, get_logger

# Configure structured logging (reads ENVIRONMENT and LOG_LEVEL from env)
configure_logging()

logger = get_logger(__name__)

# Application version (can be set via environment variable)
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


def create_health_checker(bot: DiscordBot) -> HealthChecker:
    """Create health checker with service checks for the bot.

    Args:
        bot: The Discord bot instance.

    Returns:
        Configured HealthChecker instance.
    """
    checker = HealthChecker(version=APP_VERSION)

    async def check_database() -> ServiceCheck:
        """Check database connectivity."""
        try:
            if bot._repository is None:
                return ServiceCheck(
                    name="database",
                    status=ServiceStatus.UNHEALTHY,
                    message="Database not initialized",
                )
            # Check that connection exists
            if bot._repository._connection is None:
                return ServiceCheck(
                    name="database",
                    status=ServiceStatus.UNHEALTHY,
                    message="Database connection not established",
                )
            return ServiceCheck(
                name="database",
                status=ServiceStatus.HEALTHY,
                message="Connected",
            )
        except Exception as ex:
            return ServiceCheck(
                name="database",
                status=ServiceStatus.UNHEALTHY,
                message=str(ex),
            )

    async def check_discord() -> ServiceCheck:
        """Check Discord connection status."""
        if bot.is_ready():
            return ServiceCheck(
                name="discord",
                status=ServiceStatus.HEALTHY,
                message="Connected",
                details={"guilds": len(bot.guilds)},
            )
        elif bot.is_closed():
            return ServiceCheck(
                name="discord",
                status=ServiceStatus.UNHEALTHY,
                message="Connection closed",
            )
        else:
            return ServiceCheck(
                name="discord",
                status=ServiceStatus.DEGRADED,
                message="Connecting...",
            )

    async def check_anthropic() -> ServiceCheck:
        """Check Anthropic API configuration."""
        if bot._ai_provider is None:
            return ServiceCheck(
                name="anthropic",
                status=ServiceStatus.UNHEALTHY,
                message="Provider not initialized",
            )
        # Check if API key is configured
        if os.getenv("ANTHROPIC_API_KEY"):
            return ServiceCheck(
                name="anthropic",
                status=ServiceStatus.HEALTHY,
                message="API key configured",
            )
        return ServiceCheck(
            name="anthropic",
            status=ServiceStatus.UNHEALTHY,
            message="API key not configured",
        )

    async def check_fal() -> ServiceCheck:
        """Check Fal.AI API configuration."""
        if bot._image_provider is None:
            return ServiceCheck(
                name="fal",
                status=ServiceStatus.UNHEALTHY,
                message="Provider not initialized",
            )
        if os.getenv("FAL_KEY"):
            return ServiceCheck(
                name="fal",
                status=ServiceStatus.HEALTHY,
                message="API key configured",
            )
        return ServiceCheck(
            name="fal",
            status=ServiceStatus.UNHEALTHY,
            message="API key not configured",
        )

    checker.add_check("database", check_database)
    checker.add_check("discord", check_discord)
    checker.add_check("anthropic", check_anthropic)
    checker.add_check("fal", check_fal)

    return checker


async def main() -> None:
    """Initialize and start the Discord bot with health monitoring."""
    bot = create_bot()

    # Register command handlers
    register_chat_commands(bot)
    register_image_commands(bot)

    # Create health checker (checks will work once bot is initialized)
    health_checker = create_health_checker(bot)

    # Start health server if enabled (default: enabled)
    health_server = None
    health_enabled = os.getenv("HEALTH_ENABLED", "true").lower() == "true"
    health_port = int(os.getenv("HEALTH_PORT", "8080"))

    if health_enabled:
        health_server = await start_health_server(
            health_checker,
            host="0.0.0.0",
            port=health_port,
        )

    # Set up on_ready event handler
    @bot.event
    async def on_ready() -> None:
        """On bot startup, log success and set presence.

        Note: Command syncing is controlled by SYNC_COMMANDS env var in setup_hook.
        We no longer sync per-guild on every startup to avoid hitting Discord's
        200 command creates per day rate limit.
        """
        if bot.user:
            logger.info("bot_ready", user=str(bot.user), user_id=bot.user.id)

        # Set bot presence (doesn't require syncing)
        await bot.change_presence(
            activity=discord.CustomActivity(name="/help for commands")
        )

        # Log connected guilds without syncing
        for guild in bot.guilds:
            logger.info("guild_connected", guild=guild.name, guild_id=guild.id)

    try:
        # Start the bot
        logger.info("bot_starting")
        await bot.start(os.environ["DISCORD_BOT_TOKEN"])
    finally:
        # Clean up health server on shutdown
        if health_server:
            await health_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
