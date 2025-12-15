"""Discord command handler decorators."""

import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import discord

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def handle_errors(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to handle errors in command handlers.

    Catches exceptions and sends appropriate error messages to the user.
    """

    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        try:
            return await func(interaction, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Command {func.__name__} failed: {e}")
            # Check if we can still respond
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while processing your request.",
                    ephemeral=True,
                )
            else:
                try:
                    await interaction.followup.send(
                        "An error occurred while processing your request.",
                        ephemeral=True,
                    )
                except Exception:
                    pass  # Best effort

    return wrapper


def log_command(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to log command invocations."""

    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        logger.info(
            f"Command {func.__name__} invoked by user {interaction.user.id} "
            f"in channel {interaction.channel_id}"
        )
        try:
            result = await func(interaction, *args, **kwargs)
            logger.info(f"Command {func.__name__} completed successfully")
            return result
        except Exception:
            logger.info(f"Command {func.__name__} failed")
            raise

    return wrapper
