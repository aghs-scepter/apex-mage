"""Discord command handler decorators."""

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import uuid4

import discord

from src.core.logging import bind_contextvars, clear_contextvars, get_logger

structured_logger = get_logger(__name__)

# Global command counter shared across all commands (resets on restart)
_command_count = 0

T = TypeVar("T")

# Type alias for async command handlers
CommandHandler = Callable[..., Awaitable[T]]


def count_command(func: CommandHandler[T]) -> CommandHandler[T]:
    """Decorator that increments and logs the global command counter.

    Also generates a correlation ID for request tracing and binds it
    to the logging context for the duration of the command.
    """

    @functools.wraps(func)
    async def wrapper(
        interaction: discord.Interaction, *args: Any, **kwargs: Any
    ) -> T:
        global _command_count
        _command_count += 1

        # Generate correlation ID for this request
        correlation_id = str(uuid4())[:8]

        # Bind context for all subsequent log calls
        bind_contextvars(
            correlation_id=correlation_id,
            command=func.__name__,
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
        )

        try:
            structured_logger.info("command_started", count=_command_count)
            result = await func(interaction, *args, **kwargs)
            structured_logger.info("command_completed")
            return result
        except Exception as ex:
            structured_logger.exception("command_failed", error=str(ex))
            raise
        finally:
            clear_contextvars()

    return wrapper  # type: ignore[return-value]
