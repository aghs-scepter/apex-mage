"""Discord command handler decorators."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

import discord

from src.core.logging import bind_contextvars, clear_contextvars, get_logger

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

structured_logger = get_logger(__name__)

# Global command counter shared across all commands (resets on restart)
_command_count = 0

T = TypeVar("T")

# Type alias for async command handlers
CommandHandler = Callable[..., Awaitable[T]]

# Commands classified by type for usage logging
IMAGE_COMMANDS: frozenset[str] = frozenset({
    "create_image",
    "modify_image",
    "describe_this",
    "upload_image",
})

TEXT_COMMANDS: frozenset[str] = frozenset({
    "prompt",
    "summarize",
    "clear",
    "help",
})


def _get_command_type(command_name: str) -> str | None:
    """Get the command type for usage logging.

    Args:
        command_name: The name of the command.

    Returns:
        'image' for image commands, 'text' for text commands, None if not tracked.
    """
    if command_name in IMAGE_COMMANDS:
        return "image"
    if command_name in TEXT_COMMANDS:
        return "text"
    return None


def _classify_exception(ex: BaseException) -> str:
    """Classify an exception into an outcome type for usage logging.

    Args:
        ex: The exception to classify.

    Returns:
        One of: 'timeout', 'cancelled', 'rate_limited', 'error'
    """
    # Check for timeout errors
    if isinstance(ex, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"

    # Check for cancellation
    if isinstance(ex, asyncio.CancelledError):
        return "cancelled"

    # Check for rate limit errors (check error message patterns)
    error_str = str(ex).lower()
    if "rate" in error_str and "limit" in error_str:
        return "rate_limited"
    if "429" in error_str or "too many requests" in error_str:
        return "rate_limited"

    # Check for RateLimitExceededError from image_variations
    if type(ex).__name__ == "RateLimitExceededError":
        return "rate_limited"

    return "error"


async def _log_usage(
    interaction: discord.Interaction[DiscordBot],
    command_name: str,
    outcome: str,
) -> None:
    """Log command usage if user is whitelisted and not banned.

    Args:
        interaction: The Discord interaction.
        command_name: The name of the command.
        outcome: The outcome ('success', 'error', 'timeout', 'cancelled', 'rate_limited').
    """
    command_type = _get_command_type(command_name)
    if command_type is None:
        # Command not tracked for usage logging
        return

    try:
        bot = interaction.client
        user_id = interaction.user.id
        username = interaction.user.name
        guild_id = interaction.guild_id

        # Only log for whitelisted, unbanned users
        is_whitelisted = await bot.repo.is_user_whitelisted(user_id)
        if not is_whitelisted:
            return

        is_banned = await bot.repo.is_user_banned(user_id)
        if is_banned:
            return

        # Log the usage
        await bot.repo.log_command_usage(
            user_id=user_id,
            username=username,
            guild_id=guild_id,
            command_name=command_name,
            command_type=command_type,
            outcome=outcome,
        )

        structured_logger.debug(
            "usage_logged",
            command=command_name,
            command_type=command_type,
            outcome=outcome,
            user_id=user_id,
        )

    except Exception as log_ex:
        # Don't let logging failures break the command
        structured_logger.warning(
            "usage_logging_failed",
            error=str(log_ex),
            command=command_name,
        )


def count_command(func: CommandHandler[T]) -> CommandHandler[T]:
    """Decorator that increments and logs the global command counter.

    Also generates a correlation ID for request tracing, binds it
    to the logging context for the duration of the command, and
    logs command usage for whitelisted users.
    """

    @functools.wraps(func)
    async def wrapper(
        interaction: discord.Interaction[DiscordBot], *args: Any, **kwargs: Any
    ) -> T:
        global _command_count
        _command_count += 1

        command_name = func.__name__

        # Generate correlation ID for this request
        correlation_id = str(uuid4())[:8]

        # Bind context for all subsequent log calls
        bind_contextvars(
            correlation_id=correlation_id,
            command=command_name,
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
        )

        outcome = "success"
        try:
            structured_logger.info("command_started", count=_command_count)
            result = await func(interaction, *args, **kwargs)
            structured_logger.info("command_completed")
            return result
        except asyncio.CancelledError:
            # CancelledError is a BaseException, not Exception
            outcome = "cancelled"
            structured_logger.info("command_cancelled")
            raise
        except Exception as ex:
            outcome = _classify_exception(ex)
            structured_logger.exception("command_failed", error=str(ex))
            raise
        finally:
            # Log usage before clearing context
            await _log_usage(interaction, command_name, outcome)
            clear_contextvars()

    return wrapper
