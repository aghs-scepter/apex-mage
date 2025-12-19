"""Error classification and handling utilities.

This module provides error classification to distinguish between transient
errors (that can be retried) and permanent errors (that should fail fast).

Example:
    from src.core.errors import (
        classify_error,
        ErrorCategory,
        is_retryable,
        TransientError,
        PermanentError,
    )

    try:
        result = await api_call()
    except Exception as ex:
        category = classify_error(ex)
        if is_retryable(category):
            # Retry with backoff
            pass
        else:
            # Log and fail
            raise PermanentError.from_exception(ex)
"""

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum, auto
from typing import TypeVar, cast

from src.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ErrorCategory(Enum):
    """Classification of error types for handling decisions."""

    # Transient errors - safe to retry
    RATE_LIMIT = auto()  # API rate limiting
    TIMEOUT = auto()  # Request/operation timeout
    NETWORK = auto()  # Network connectivity issues
    SERVICE_UNAVAILABLE = auto()  # Temporary service outage (5xx)
    OVERLOADED = auto()  # Server overloaded (529)

    # Permanent errors - should not retry
    INVALID_INPUT = auto()  # Bad request data (4xx)
    AUTH_FAILURE = auto()  # Authentication/authorization error
    NOT_FOUND = auto()  # Resource not found
    CONFIGURATION = auto()  # Missing configuration or setup issue
    UNKNOWN = auto()  # Unclassified error


# Categories that are safe to retry
RETRYABLE_CATEGORIES = {
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.TIMEOUT,
    ErrorCategory.NETWORK,
    ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCategory.OVERLOADED,
}


class TransientError(Exception):
    """Error that is temporary and can be retried.

    Attributes:
        category: The specific type of transient error.
        retry_after: Suggested wait time before retry (seconds), if known.
        original_error: The underlying exception that was classified.
    """

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        retry_after: float | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retry_after = retry_after
        self.original_error = original_error

    @classmethod
    def from_exception(
        cls,
        ex: Exception,
        category: ErrorCategory | None = None,
        retry_after: float | None = None,
    ) -> "TransientError":
        """Create a TransientError from an existing exception."""
        if category is None:
            category = classify_error(ex)
        return cls(
            message=str(ex),
            category=category,
            retry_after=retry_after,
            original_error=ex,
        )


class PermanentError(Exception):
    """Error that is permanent and should not be retried.

    Attributes:
        category: The specific type of permanent error.
        original_error: The underlying exception that was classified.
    """

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.original_error = original_error

    @classmethod
    def from_exception(
        cls,
        ex: Exception,
        category: ErrorCategory | None = None,
    ) -> "PermanentError":
        """Create a PermanentError from an existing exception."""
        if category is None:
            category = classify_error(ex)
        return cls(
            message=str(ex),
            category=category,
            original_error=ex,
        )


def classify_error(error: Exception) -> ErrorCategory:
    """Classify an exception into an error category.

    Args:
        error: The exception to classify.

    Returns:
        The ErrorCategory that best matches the error.
    """
    error_str = str(error).lower()

    # Check for timeout errors
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return ErrorCategory.TIMEOUT

    # Check for connection/network errors
    if "connection" in error_str or "network" in error_str:
        return ErrorCategory.NETWORK

    # Check for rate limiting
    if "rate" in error_str and "limit" in error_str:
        return ErrorCategory.RATE_LIMIT
    if "429" in error_str or "too many requests" in error_str:
        return ErrorCategory.RATE_LIMIT

    # Check for server overload (Anthropic-specific)
    if "529" in error_str or "overloaded" in error_str:
        return ErrorCategory.OVERLOADED

    # Check for service unavailable
    if "503" in error_str or "service unavailable" in error_str:
        return ErrorCategory.SERVICE_UNAVAILABLE
    if "502" in error_str or "bad gateway" in error_str:
        return ErrorCategory.SERVICE_UNAVAILABLE

    # Check for authentication errors
    if "401" in error_str or "unauthorized" in error_str:
        return ErrorCategory.AUTH_FAILURE
    if "403" in error_str or "forbidden" in error_str:
        return ErrorCategory.AUTH_FAILURE
    if "api key" in error_str or "authentication" in error_str:
        return ErrorCategory.AUTH_FAILURE

    # Check for not found
    if "404" in error_str or "not found" in error_str:
        return ErrorCategory.NOT_FOUND

    # Check for invalid input
    if "400" in error_str or "bad request" in error_str:
        return ErrorCategory.INVALID_INPUT
    if "invalid" in error_str or "validation" in error_str:
        return ErrorCategory.INVALID_INPUT

    # Check for configuration errors
    if "configuration" in error_str or "not configured" in error_str:
        return ErrorCategory.CONFIGURATION
    if "missing" in error_str and ("key" in error_str or "env" in error_str):
        return ErrorCategory.CONFIGURATION

    return ErrorCategory.UNKNOWN


def is_retryable(category: ErrorCategory) -> bool:
    """Check if an error category is safe to retry.

    Args:
        category: The error category to check.

    Returns:
        True if the error is transient and can be retried.
    """
    return category in RETRYABLE_CATEGORIES


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    **kwargs: object,
) -> T:
    """Retry a function with exponential backoff for transient errors.

    Args:
        func: Async function to call.
        *args: Positional arguments to pass to func.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay between retries (seconds).
        exponential_base: Base for exponential backoff calculation.
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The result of the function call.

    Raises:
        TransientError: If all retries are exhausted.
        PermanentError: If a non-retryable error occurs.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as ex:
            last_error = ex
            category = classify_error(ex)

            if not is_retryable(category):
                logger.warning(
                    "permanent_error",
                    category=category.name,
                    error=str(ex),
                )
                raise PermanentError.from_exception(ex, category) from ex

            if attempt >= max_retries:
                logger.error(
                    "max_retries_exceeded",
                    category=category.name,
                    attempts=attempt + 1,
                    error=str(ex),
                )
                raise TransientError.from_exception(ex, category) from ex

            # Calculate delay with exponential backoff
            delay = min(base_delay * (exponential_base**attempt), max_delay)

            logger.warning(
                "retrying_after_error",
                category=category.name,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay_seconds=delay,
                error=str(ex),
            )

            await asyncio.sleep(delay)

    # Should never reach here, but just in case
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected state in retry_with_backoff")
