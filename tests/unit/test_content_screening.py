"""Unit tests for content screening utility.

Tests the Claude Haiku-based content screening functionality including:
- Allowed query handling
- Blocked query handling with reasons
- API error handling (fail closed)
- JSON parsing error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import APIStatusError

from src.core.content_screening import ScreeningResult, screen_search_query


class TestScreeningResult:
    """Tests for ScreeningResult dataclass."""

    def test_allowed_result(self) -> None:
        """Test creating an allowed result."""
        result = ScreeningResult(allowed=True, reason=None)
        assert result.allowed is True
        assert result.reason is None

    def test_blocked_result(self) -> None:
        """Test creating a blocked result with reason."""
        result = ScreeningResult(allowed=False, reason="Content is harmful")
        assert result.allowed is False
        assert result.reason == "Content is harmful"


class TestScreenSearchQuery:
    """Tests for screen_search_query function."""

    @pytest.mark.asyncio
    async def test_allowed_query_returns_allowed(self) -> None:
        """Test that an allowed query returns ScreeningResult(allowed=True, reason=None)."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock API response for allowed query
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text='{"allowed": true}')]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("cute puppies")

            assert result.allowed is True
            assert result.reason is None

    @pytest.mark.asyncio
    async def test_blocked_query_returns_blocked_with_reason(self) -> None:
        """Test that a blocked query returns ScreeningResult(allowed=False, reason='...')."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock API response for blocked query
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(
                    text='{"allowed": false, "reason": "Query contains harmful content"}'
                )
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("illegal harmful content")

            assert result.allowed is False
            assert result.reason == "Query contains harmful content"

    @pytest.mark.asyncio
    async def test_api_error_returns_service_unavailable(self) -> None:
        """Test that API error returns blocked with 'service unavailable' reason."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock API error
            mock_response_500 = MagicMock()
            mock_response_500.status_code = 500
            error = APIStatusError(
                message="Internal server error",
                response=mock_response_500,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=error)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_service_unavailable(self) -> None:
        """Test that JSON parse error returns blocked with 'service unavailable' reason."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock response with invalid JSON
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="This is not valid JSON")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_service_unavailable(self) -> None:
        """Test that missing API key returns blocked with 'service unavailable' reason."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY from environment
            result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_empty_response_returns_service_unavailable(self) -> None:
        """Test that empty API response returns blocked with 'service unavailable' reason."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock empty response
            mock_response = MagicMock()
            mock_response.content = []

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_missing_allowed_field_returns_service_unavailable(
        self,
    ) -> None:
        """Test that response missing 'allowed' field returns blocked."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock response with valid JSON but missing 'allowed' field
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text='{"some_other_field": true}')
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_blocked_without_reason_uses_default(self) -> None:
        """Test that blocked response without reason uses default message."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock response blocked but no reason provided
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text='{"allowed": false}')]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Query blocked by content screening"

    @pytest.mark.asyncio
    async def test_uses_correct_model(self) -> None:
        """Test that the correct Haiku model is used."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text='{"allowed": true}')]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await screen_search_query("test query")

            # Verify the model used
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_query_included_in_prompt(self) -> None:
        """Test that the query is included in the message to the API."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text='{"allowed": true}')]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await screen_search_query("beautiful sunset photos")

            # Verify the query is in the message
            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            assert len(messages) == 1
            assert "beautiful sunset photos" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_service_unavailable(
        self,
    ) -> None:
        """Test that unexpected exceptions return blocked with 'service unavailable'."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock unexpected exception
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is False
            assert result.reason == "Screening service unavailable"

    @pytest.mark.asyncio
    async def test_whitespace_in_json_response(self) -> None:
        """Test that JSON response with whitespace is parsed correctly."""
        with patch(
            "src.core.content_screening.AsyncAnthropic"
        ) as mock_client_class:
            # Mock response with whitespace around JSON
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text='  \n{"allowed": true}\n  ')
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await screen_search_query("test query")

            assert result.allowed is True
            assert result.reason is None
