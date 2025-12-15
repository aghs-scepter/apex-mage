"""Rate limiting logic with pluggable storage.

This module provides a sliding window rate limiter with configurable limits
per action type and pluggable storage backends.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed under the current limit.
        remaining: Number of requests remaining in the current window.
        reset_at: When the current window resets.
        wait_seconds: Seconds to wait before retrying (if not allowed).
    """

    allowed: bool
    remaining: int
    reset_at: datetime
    wait_seconds: float | None = None


@dataclass
class RateLimit:
    """Rate limit configuration for an action type.

    Attributes:
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Size of the sliding window in seconds.
    """

    max_requests: int
    window_seconds: int


class RateLimitStorage(Protocol):
    """Protocol for rate limit storage backends.

    Implementations must be able to count requests within a time window
    and record new requests with timestamps.
    """

    async def get_request_count(
        self, user_id: int, action: str, since: datetime
    ) -> int:
        """Get the count of requests since the given timestamp.

        Args:
            user_id: The user ID to check.
            action: The action type (e.g., "chat", "image").
            since: Count requests since this timestamp.

        Returns:
            Number of requests since the given timestamp.
        """
        ...

    async def record_request(
        self, user_id: int, action: str, timestamp: datetime
    ) -> None:
        """Record a new request.

        Args:
            user_id: The user ID making the request.
            action: The action type (e.g., "chat", "image").
            timestamp: The timestamp of the request.
        """
        ...


class SlidingWindowRateLimiter:
    """Sliding window rate limiter with pluggable storage.

    This rate limiter uses a sliding window algorithm where requests
    are counted within a time window that slides with the current time.
    """

    def __init__(self, storage: RateLimitStorage, limits: dict[str, RateLimit]):
        """Initialize the rate limiter.

        Args:
            storage: Storage backend for persisting request counts.
            limits: Dictionary mapping action types to their rate limits.
        """
        self._storage = storage
        self._limits = limits

    async def check(self, user_id: int, action: str) -> RateLimitResult:
        """Check if a request is allowed under the rate limit.

        Args:
            user_id: The user ID to check.
            action: The action type (e.g., "chat", "image").

        Returns:
            RateLimitResult indicating whether the request is allowed.

        Raises:
            ValueError: If the action type has no configured limit.
        """
        if action not in self._limits:
            raise ValueError(f"No rate limit configured for action: {action}")

        limit = self._limits[action]
        now = datetime.now(UTC)
        window_start = datetime.fromtimestamp(
            now.timestamp() - limit.window_seconds, tz=UTC
        )
        reset_at = datetime.fromtimestamp(
            now.timestamp() + limit.window_seconds, tz=UTC
        )

        count = await self._storage.get_request_count(user_id, action, window_start)
        remaining = max(0, limit.max_requests - count)
        allowed = count < limit.max_requests

        wait_seconds = None
        if not allowed:
            # Calculate time until the oldest request in the window expires
            wait_seconds = float(limit.window_seconds)

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_at=reset_at,
            wait_seconds=wait_seconds,
        )

    async def record(self, user_id: int, action: str) -> None:
        """Record a request for rate limiting.

        Args:
            user_id: The user ID making the request.
            action: The action type (e.g., "chat", "image").
        """
        now = datetime.now(UTC)
        await self._storage.record_request(user_id, action, now)


class InMemoryRateLimitStorage:
    """In-memory storage for rate limiting.

    Suitable for testing or single-instance deployments.
    Request data is stored in memory and lost on restart.
    """

    def __init__(self) -> None:
        """Initialize the in-memory storage."""
        self._requests: dict[tuple[int, str], list[datetime]] = field(
            default_factory=dict
        )
        self._requests = {}

    async def get_request_count(
        self, user_id: int, action: str, since: datetime
    ) -> int:
        """Get the count of requests since the given timestamp.

        Args:
            user_id: The user ID to check.
            action: The action type.
            since: Count requests since this timestamp.

        Returns:
            Number of requests since the given timestamp.
        """
        key = (user_id, action)
        if key not in self._requests:
            return 0

        # Filter requests within the window
        requests = self._requests[key]
        count = sum(1 for ts in requests if ts >= since)
        return count

    async def record_request(
        self, user_id: int, action: str, timestamp: datetime
    ) -> None:
        """Record a new request.

        Args:
            user_id: The user ID making the request.
            action: The action type.
            timestamp: The timestamp of the request.
        """
        key = (user_id, action)
        if key not in self._requests:
            self._requests[key] = []
        self._requests[key].append(timestamp)

    def clear(self) -> None:
        """Clear all stored requests."""
        self._requests.clear()

    def cleanup_old_requests(self, before: datetime) -> None:
        """Remove requests older than the given timestamp.

        Args:
            before: Remove requests before this timestamp.
        """
        for key in list(self._requests.keys()):
            self._requests[key] = [
                ts for ts in self._requests[key] if ts >= before
            ]
            # Remove empty entries
            if not self._requests[key]:
                del self._requests[key]
