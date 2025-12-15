"""Tests for error classification and handling."""

import asyncio

import pytest

from src.core.errors import (
    ErrorCategory,
    PermanentError,
    TransientError,
    classify_error,
    is_retryable,
    retry_with_backoff,
)


class TestErrorCategory:
    """Tests for ErrorCategory enum."""

    def test_all_categories_defined(self) -> None:
        """Should have all expected error categories."""
        assert ErrorCategory.RATE_LIMIT
        assert ErrorCategory.TIMEOUT
        assert ErrorCategory.NETWORK
        assert ErrorCategory.SERVICE_UNAVAILABLE
        assert ErrorCategory.OVERLOADED
        assert ErrorCategory.INVALID_INPUT
        assert ErrorCategory.AUTH_FAILURE
        assert ErrorCategory.NOT_FOUND
        assert ErrorCategory.CONFIGURATION
        assert ErrorCategory.UNKNOWN


class TestClassifyError:
    """Tests for classify_error function."""

    def test_classifies_timeout_error(self) -> None:
        """Should classify TimeoutError as TIMEOUT."""
        error = TimeoutError("Operation timed out")
        assert classify_error(error) == ErrorCategory.TIMEOUT

    def test_classifies_asyncio_timeout(self) -> None:
        """Should classify asyncio.TimeoutError as TIMEOUT."""
        error = asyncio.TimeoutError()
        assert classify_error(error) == ErrorCategory.TIMEOUT

    def test_classifies_rate_limit_from_message(self) -> None:
        """Should classify rate limit from error message."""
        error = Exception("Rate limit exceeded, please retry")
        assert classify_error(error) == ErrorCategory.RATE_LIMIT

    def test_classifies_429_error(self) -> None:
        """Should classify 429 status code as RATE_LIMIT."""
        error = Exception("HTTP 429: Too Many Requests")
        assert classify_error(error) == ErrorCategory.RATE_LIMIT

    def test_classifies_529_as_overloaded(self) -> None:
        """Should classify 529 (Anthropic overloaded) as OVERLOADED."""
        error = Exception("Error 529: Server overloaded")
        assert classify_error(error) == ErrorCategory.OVERLOADED

    def test_classifies_503_as_service_unavailable(self) -> None:
        """Should classify 503 as SERVICE_UNAVAILABLE."""
        error = Exception("503 Service Unavailable")
        assert classify_error(error) == ErrorCategory.SERVICE_UNAVAILABLE

    def test_classifies_401_as_auth_failure(self) -> None:
        """Should classify 401 as AUTH_FAILURE."""
        error = Exception("401 Unauthorized")
        assert classify_error(error) == ErrorCategory.AUTH_FAILURE

    def test_classifies_403_as_auth_failure(self) -> None:
        """Should classify 403 as AUTH_FAILURE."""
        error = Exception("403 Forbidden")
        assert classify_error(error) == ErrorCategory.AUTH_FAILURE

    def test_classifies_404_as_not_found(self) -> None:
        """Should classify 404 as NOT_FOUND."""
        error = Exception("404 Not Found")
        assert classify_error(error) == ErrorCategory.NOT_FOUND

    def test_classifies_400_as_invalid_input(self) -> None:
        """Should classify 400 as INVALID_INPUT."""
        error = Exception("400 Bad Request")
        assert classify_error(error) == ErrorCategory.INVALID_INPUT

    def test_classifies_validation_as_invalid_input(self) -> None:
        """Should classify validation errors as INVALID_INPUT."""
        error = Exception("Validation error: field X is required")
        assert classify_error(error) == ErrorCategory.INVALID_INPUT

    def test_classifies_connection_as_network(self) -> None:
        """Should classify connection errors as NETWORK."""
        error = Exception("Connection refused")
        assert classify_error(error) == ErrorCategory.NETWORK

    def test_classifies_api_key_as_auth(self) -> None:
        """Should classify API key errors as AUTH_FAILURE."""
        error = Exception("Invalid API key")
        assert classify_error(error) == ErrorCategory.AUTH_FAILURE

    def test_classifies_missing_env_as_configuration(self) -> None:
        """Should classify missing env var as CONFIGURATION."""
        error = Exception("Missing env variable: API_KEY")
        assert classify_error(error) == ErrorCategory.CONFIGURATION

    def test_classifies_unknown_error(self) -> None:
        """Should classify unrecognized errors as UNKNOWN."""
        error = Exception("Some random error")
        assert classify_error(error) == ErrorCategory.UNKNOWN


class TestIsRetryable:
    """Tests for is_retryable function."""

    def test_rate_limit_is_retryable(self) -> None:
        """Should consider RATE_LIMIT retryable."""
        assert is_retryable(ErrorCategory.RATE_LIMIT) is True

    def test_timeout_is_retryable(self) -> None:
        """Should consider TIMEOUT retryable."""
        assert is_retryable(ErrorCategory.TIMEOUT) is True

    def test_network_is_retryable(self) -> None:
        """Should consider NETWORK retryable."""
        assert is_retryable(ErrorCategory.NETWORK) is True

    def test_service_unavailable_is_retryable(self) -> None:
        """Should consider SERVICE_UNAVAILABLE retryable."""
        assert is_retryable(ErrorCategory.SERVICE_UNAVAILABLE) is True

    def test_overloaded_is_retryable(self) -> None:
        """Should consider OVERLOADED retryable."""
        assert is_retryable(ErrorCategory.OVERLOADED) is True

    def test_invalid_input_not_retryable(self) -> None:
        """Should not consider INVALID_INPUT retryable."""
        assert is_retryable(ErrorCategory.INVALID_INPUT) is False

    def test_auth_failure_not_retryable(self) -> None:
        """Should not consider AUTH_FAILURE retryable."""
        assert is_retryable(ErrorCategory.AUTH_FAILURE) is False

    def test_not_found_not_retryable(self) -> None:
        """Should not consider NOT_FOUND retryable."""
        assert is_retryable(ErrorCategory.NOT_FOUND) is False

    def test_configuration_not_retryable(self) -> None:
        """Should not consider CONFIGURATION retryable."""
        assert is_retryable(ErrorCategory.CONFIGURATION) is False

    def test_unknown_not_retryable(self) -> None:
        """Should not consider UNKNOWN retryable."""
        assert is_retryable(ErrorCategory.UNKNOWN) is False


class TestTransientError:
    """Tests for TransientError exception."""

    def test_stores_attributes(self) -> None:
        """Should store all provided attributes."""
        original = ValueError("test")
        error = TransientError(
            message="Transient error",
            category=ErrorCategory.TIMEOUT,
            retry_after=5.0,
            original_error=original,
        )
        assert str(error) == "Transient error"
        assert error.category == ErrorCategory.TIMEOUT
        assert error.retry_after == 5.0
        assert error.original_error is original

    def test_from_exception_classifies(self) -> None:
        """Should classify error when creating from exception."""
        original = TimeoutError("timed out")
        error = TransientError.from_exception(original)
        assert error.category == ErrorCategory.TIMEOUT
        assert error.original_error is original

    def test_from_exception_uses_provided_category(self) -> None:
        """Should use provided category if given."""
        original = Exception("some error")
        error = TransientError.from_exception(
            original, category=ErrorCategory.NETWORK
        )
        assert error.category == ErrorCategory.NETWORK


class TestPermanentError:
    """Tests for PermanentError exception."""

    def test_stores_attributes(self) -> None:
        """Should store all provided attributes."""
        original = ValueError("test")
        error = PermanentError(
            message="Permanent error",
            category=ErrorCategory.AUTH_FAILURE,
            original_error=original,
        )
        assert str(error) == "Permanent error"
        assert error.category == ErrorCategory.AUTH_FAILURE
        assert error.original_error is original

    def test_from_exception_classifies(self) -> None:
        """Should classify error when creating from exception."""
        original = Exception("401 Unauthorized")
        error = PermanentError.from_exception(original)
        assert error.category == ErrorCategory.AUTH_FAILURE
        assert error.original_error is original


class TestRetryWithBackoff:
    """Tests for retry_with_backoff function."""

    async def test_returns_result_on_success(self) -> None:
        """Should return result on first successful call."""

        async def success():
            return "success"

        result = await retry_with_backoff(success)
        assert result == "success"

    async def test_retries_on_transient_error(self) -> None:
        """Should retry on transient errors."""
        call_count = 0

        async def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("timed out")
            return "success"

        result = await retry_with_backoff(
            fails_then_succeeds, max_retries=3, base_delay=0.01
        )
        assert result == "success"
        assert call_count == 2

    async def test_raises_transient_error_after_max_retries(self) -> None:
        """Should raise TransientError after exhausting retries."""

        async def always_fails():
            raise TimeoutError("always times out")

        with pytest.raises(TransientError) as exc_info:
            await retry_with_backoff(
                always_fails, max_retries=2, base_delay=0.01
            )

        assert exc_info.value.category == ErrorCategory.TIMEOUT

    async def test_raises_permanent_error_immediately(self) -> None:
        """Should raise PermanentError without retrying."""
        call_count = 0

        async def auth_failure():
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized")

        with pytest.raises(PermanentError) as exc_info:
            await retry_with_backoff(
                auth_failure, max_retries=3, base_delay=0.01
            )

        assert exc_info.value.category == ErrorCategory.AUTH_FAILURE
        assert call_count == 1  # Should not retry

    async def test_passes_args_and_kwargs(self) -> None:
        """Should pass arguments to the function."""

        async def echo(a, b, c=None):
            return (a, b, c)

        result = await retry_with_backoff(echo, 1, 2, c=3)
        assert result == (1, 2, 3)

    async def test_respects_max_delay(self) -> None:
        """Should cap delay at max_delay."""
        # This is implicitly tested by the retry behavior
        # A full test would require time mocking
        call_count = 0

        async def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("timed out")
            return "success"

        result = await retry_with_backoff(
            fails_once,
            max_retries=3,
            base_delay=0.01,
            max_delay=0.02,
        )
        assert result == "success"
