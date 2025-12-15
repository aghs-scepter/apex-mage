"""Tests for rate limiting logic."""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.rate_limit import (
    InMemoryRateLimitStorage,
    RateLimit,
    RateLimitResult,
    SlidingWindowRateLimiter,
)


class TestInMemoryStorage:
    """Tests for InMemoryRateLimitStorage class."""

    @pytest.mark.asyncio
    async def test_empty_storage_returns_zero(self):
        """Empty storage should return 0 count."""
        storage = InMemoryRateLimitStorage()
        count = await storage.get_request_count(1, "chat", datetime.now(UTC))
        assert count == 0

    @pytest.mark.asyncio
    async def test_records_and_counts_requests(self):
        """Should record requests and count them correctly."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        await storage.record_request(1, "chat", now)
        await storage.record_request(1, "chat", now)
        count = await storage.get_request_count(1, "chat", now - timedelta(hours=1))
        assert count == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self):
        """Should count requests per user separately."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        await storage.record_request(1, "chat", now)
        await storage.record_request(2, "chat", now)
        await storage.record_request(1, "chat", now)

        user1_count = await storage.get_request_count(1, "chat", now - timedelta(hours=1))
        user2_count = await storage.get_request_count(2, "chat", now - timedelta(hours=1))

        assert user1_count == 2
        assert user2_count == 1

    @pytest.mark.asyncio
    async def test_filters_by_action(self):
        """Should count requests per action type separately."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        await storage.record_request(1, "chat", now)
        await storage.record_request(1, "image", now)
        await storage.record_request(1, "chat", now)

        chat_count = await storage.get_request_count(1, "chat", now - timedelta(hours=1))
        image_count = await storage.get_request_count(1, "image", now - timedelta(hours=1))

        assert chat_count == 2
        assert image_count == 1

    @pytest.mark.asyncio
    async def test_filters_by_timestamp(self):
        """Should only count requests since the given timestamp."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        old_time = now - timedelta(hours=2)

        await storage.record_request(1, "chat", old_time)
        await storage.record_request(1, "chat", now)

        # Count from 1 hour ago should only include the recent request
        count = await storage.get_request_count(1, "chat", now - timedelta(hours=1))
        assert count == 1

        # Count from 3 hours ago should include both
        count_all = await storage.get_request_count(1, "chat", now - timedelta(hours=3))
        assert count_all == 2

    @pytest.mark.asyncio
    async def test_clear_removes_all_requests(self):
        """Clear should remove all stored requests."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        await storage.record_request(1, "chat", now)
        await storage.record_request(2, "image", now)

        storage.clear()

        count = await storage.get_request_count(1, "chat", now - timedelta(hours=1))
        assert count == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_requests(self):
        """Cleanup should remove old requests."""
        storage = InMemoryRateLimitStorage()
        now = datetime.now(UTC)
        old_time = now - timedelta(hours=2)

        await storage.record_request(1, "chat", old_time)
        await storage.record_request(1, "chat", now)

        # Cleanup requests older than 1 hour
        storage.cleanup_old_requests(now - timedelta(hours=1))

        count = await storage.get_request_count(1, "chat", now - timedelta(hours=3))
        assert count == 1  # Only the recent one remains


class TestSlidingWindowRateLimiter:
    """Tests for SlidingWindowRateLimiter class."""

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        """Should allow requests within the rate limit."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(10, 3600)})
        result = await limiter.check(1, "chat")
        assert result.allowed is True
        assert result.remaining == 10

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self):
        """Should block requests over the rate limit."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(2, 3600)})
        now = datetime.now(UTC)

        # Record 2 requests (at limit)
        await storage.record_request(1, "chat", now)
        await storage.record_request(1, "chat", now)

        result = await limiter.check(1, "chat")
        assert result.allowed is False
        assert result.remaining == 0
        assert result.wait_seconds is not None

    @pytest.mark.asyncio
    async def test_records_request(self):
        """Record should store the request."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(10, 3600)})

        await limiter.record(1, "chat")

        result = await limiter.check(1, "chat")
        assert result.remaining == 9

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self):
        """Should raise ValueError for unknown action types."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(10, 3600)})

        with pytest.raises(ValueError, match="No rate limit configured"):
            await limiter.check(1, "unknown")

    @pytest.mark.asyncio
    async def test_different_users_independent(self):
        """Rate limits should be per-user."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(2, 3600)})

        # User 1 hits limit
        await limiter.record(1, "chat")
        await limiter.record(1, "chat")

        # User 2 should still be allowed
        result = await limiter.check(2, "chat")
        assert result.allowed is True
        assert result.remaining == 2

    @pytest.mark.asyncio
    async def test_different_actions_independent(self):
        """Rate limits should be per-action."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(
            storage,
            {"chat": RateLimit(2, 3600), "image": RateLimit(5, 3600)},
        )

        # Hit chat limit
        await limiter.record(1, "chat")
        await limiter.record(1, "chat")

        # Image should still be allowed
        result = await limiter.check(1, "image")
        assert result.allowed is True
        assert result.remaining == 5

    @pytest.mark.asyncio
    async def test_remaining_decrements_correctly(self):
        """Remaining count should decrement with each request."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(5, 3600)})

        result0 = await limiter.check(1, "chat")
        assert result0.remaining == 5

        await limiter.record(1, "chat")
        result1 = await limiter.check(1, "chat")
        assert result1.remaining == 4

        await limiter.record(1, "chat")
        result2 = await limiter.check(1, "chat")
        assert result2.remaining == 3

    @pytest.mark.asyncio
    async def test_reset_at_is_in_future(self):
        """Reset time should be in the future."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(10, 3600)})

        now = datetime.now(UTC)
        result = await limiter.check(1, "chat")

        assert result.reset_at > now

    @pytest.mark.asyncio
    async def test_wait_seconds_only_when_blocked(self):
        """wait_seconds should only be set when blocked."""
        storage = InMemoryRateLimitStorage()
        limiter = SlidingWindowRateLimiter(storage, {"chat": RateLimit(10, 3600)})

        result = await limiter.check(1, "chat")
        assert result.allowed is True
        assert result.wait_seconds is None


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_allowed_result(self):
        """Allowed result should have expected values."""
        result = RateLimitResult(
            allowed=True,
            remaining=5,
            reset_at=datetime.now(UTC),
        )
        assert result.allowed is True
        assert result.remaining == 5
        assert result.wait_seconds is None

    def test_blocked_result(self):
        """Blocked result should include wait_seconds."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=datetime.now(UTC),
            wait_seconds=3600.0,
        )
        assert result.allowed is False
        assert result.remaining == 0
        assert result.wait_seconds == 3600.0


class TestRateLimit:
    """Tests for RateLimit dataclass."""

    def test_rate_limit_values(self):
        """RateLimit should store configuration correctly."""
        limit = RateLimit(max_requests=30, window_seconds=3600)
        assert limit.max_requests == 30
        assert limit.window_seconds == 3600
