"""Structured logging configuration using structlog.

This module provides a centralized logging configuration that supports both
development (pretty-printed) and production (JSON) output formats.

Usage:
    from src.core.logging import get_logger, configure_logging

    # At application startup
    configure_logging(development=True)  # or False for production

    # In modules
    logger = get_logger(__name__)
    logger.info("message", key="value", another_key=123)
"""

import logging
import sys
from os import getenv
from typing import Any, cast

import structlog
from structlog.types import Processor


def configure_logging(
    development: bool | None = None,
    log_level: str | None = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        development: If True, use pretty-printed output. If False, use JSON.
                    If None, reads from ENVIRONMENT env var (default: development).
        log_level: Log level string (DEBUG, INFO, WARNING, ERROR).
                  If None, reads from LOG_LEVEL env var (default: INFO).
    """
    if development is None:
        env = getenv("ENVIRONMENT", "development").lower()
        development = env != "production"

    if log_level is None:
        log_level = getenv("LOG_LEVEL", "INFO").upper()

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Common processors for all modes
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if development:
        # Development: pretty-printed, colored output
        processors: list[Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Production: JSON output for log aggregation
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    # Use force=True to override any existing configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )
    # Also explicitly set the root logger level
    logging.getLogger().setLevel(numeric_level)

    # Set log level for third-party libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        A bound structlog logger instance.
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_contextvars(**kwargs: Any) -> None:
    """Bind context variables that will be included in all subsequent log calls.

    This is useful for adding request-scoped context like correlation IDs.

    Args:
        **kwargs: Key-value pairs to bind to the logging context.

    Example:
        bind_contextvars(correlation_id="abc-123", user_id=456)
        logger.info("processing")  # Will include correlation_id and user_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_contextvars() -> None:
    """Clear all bound context variables.

    Call this at the end of a request to clean up the context.
    """
    structlog.contextvars.clear_contextvars()


def unbind_contextvars(*keys: str) -> None:
    """Remove specific context variables.

    Args:
        *keys: Names of context variables to remove.
    """
    structlog.contextvars.unbind_contextvars(*keys)
