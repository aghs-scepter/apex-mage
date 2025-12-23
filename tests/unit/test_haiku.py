"""Unit tests for the Haiku API utility wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import APIStatusError

from src.core.haiku import (
    HAIKU_MODEL,
    HaikuError,
    haiku_complete,
    haiku_vision,
)


class TestHaikuComplete:
    """Tests for haiku_complete function."""

    @pytest.mark.asyncio
    async def test_returns_text_response(self) -> None:
        """Test that haiku_complete returns the text content from the API."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Hello, world!")]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="Say hello",
                )

            assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_uses_correct_model(self) -> None:
        """Test that haiku_complete uses the correct Haiku model."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="Test",
                )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["model"] == HAIKU_MODEL

    @pytest.mark.asyncio
    async def test_passes_system_prompt(self) -> None:
        """Test that haiku_complete passes the system prompt correctly."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_complete(
                    system_prompt="Be concise.",
                    user_message="Test",
                )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["system"] == "Be concise."

    @pytest.mark.asyncio
    async def test_passes_user_message(self) -> None:
        """Test that haiku_complete passes the user message correctly."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="What is 2 + 2?",
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "What is 2 + 2?"

    @pytest.mark.asyncio
    async def test_uses_default_max_tokens(self) -> None:
        """Test that haiku_complete uses default max_tokens of 1024."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="Test",
                )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_uses_custom_max_tokens(self) -> None:
        """Test that haiku_complete respects custom max_tokens."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="Test",
                    max_tokens=512,
                )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_raises_error_without_api_key(self) -> None:
        """Test that haiku_complete raises HaikuError without API key."""
        with patch.dict("os.environ", {}, clear=True):
            # Make sure ANTHROPIC_API_KEY is not set
            import os
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            with pytest.raises(HaikuError) as exc_info:
                await haiku_complete(
                    system_prompt="You are helpful.",
                    user_message="Test",
                )

            assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_error_on_empty_response(self) -> None:
        """Test that haiku_complete raises HaikuError on empty response."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = []

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                with pytest.raises(HaikuError) as exc_info:
                    await haiku_complete(
                        system_prompt="You are helpful.",
                        user_message="Test",
                    )

            assert "Empty response" in str(exc_info.value)


class TestHaikuVision:
    """Tests for haiku_vision function."""

    @pytest.mark.asyncio
    async def test_returns_text_response(self) -> None:
        """Test that haiku_vision returns the text content from the API."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="A beautiful sunset")]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                )

            assert result == "A beautiful sunset"

    @pytest.mark.asyncio
    async def test_passes_image_in_correct_format(self) -> None:
        """Test that haiku_vision passes the image in the correct format."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            assert len(messages) == 1
            content = messages[0]["content"]
            assert len(content) == 1  # Only image, no text
            assert content[0]["type"] == "image"
            assert content[0]["source"]["type"] == "base64"
            assert content[0]["source"]["data"] == "iVBORw0KGgoAAAA=="

    @pytest.mark.asyncio
    async def test_uses_default_media_type(self) -> None:
        """Test that haiku_vision uses default media type of image/jpeg."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            content = messages[0]["content"]
            assert content[0]["source"]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_uses_custom_media_type(self) -> None:
        """Test that haiku_vision respects custom media type."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                    media_type="image/png",
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            content = messages[0]["content"]
            assert content[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_includes_user_message_when_provided(self) -> None:
        """Test that haiku_vision includes user_message when provided."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                    user_message="What colors do you see?",
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            content = messages[0]["content"]
            assert len(content) == 2  # Image and text
            assert content[1]["type"] == "text"
            assert content[1]["text"] == "What colors do you see?"

    @pytest.mark.asyncio
    async def test_raises_error_without_api_key(self) -> None:
        """Test that haiku_vision raises HaikuError without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            with pytest.raises(HaikuError) as exc_info:
                await haiku_vision(
                    system_prompt="Describe this image.",
                    image_base64="iVBORw0KGgoAAAA==",
                )

            assert "ANTHROPIC_API_KEY" in str(exc_info.value)


class TestRetryLogic:
    """Tests for retry logic in Haiku API calls."""

    @pytest.mark.asyncio
    async def test_retries_on_529_error(self) -> None:
        """Test that the API retries on 529 (overloaded) error."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_success = MagicMock()
            mock_response_success.content = [MagicMock(text="Success")]

            mock_response_529 = MagicMock()
            mock_response_529.status_code = 529
            error_529 = APIStatusError(
                message="Overloaded",
                response=mock_response_529,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[error_529, mock_response_success]
            )
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    result = await haiku_complete(
                        system_prompt="You are helpful.",
                        user_message="Test",
                    )

            assert result == "Success"
            mock_sleep.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_retries_on_500_error(self) -> None:
        """Test that the API retries on 500 (server error)."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_success = MagicMock()
            mock_response_success.content = [MagicMock(text="Success")]

            mock_response_500 = MagicMock()
            mock_response_500.status_code = 500
            error_500 = APIStatusError(
                message="Server error",
                response=mock_response_500,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[error_500, mock_response_success]
            )
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    result = await haiku_complete(
                        system_prompt="You are helpful.",
                        user_message="Test",
                    )

            assert result == "Success"

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        """Test that the API raises HaikuError after max retries."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_529 = MagicMock()
            mock_response_529.status_code = 529
            error_529 = APIStatusError(
                message="Overloaded",
                response=mock_response_529,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=error_529)
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    with pytest.raises(HaikuError) as exc_info:
                        await haiku_complete(
                            system_prompt="You are helpful.",
                            user_message="Test",
                        )

            assert "Haiku API error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_retry_on_400_error(self) -> None:
        """Test that the API does not retry on 400 (bad request) error."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_400 = MagicMock()
            mock_response_400.status_code = 400
            error_400 = APIStatusError(
                message="Bad request",
                response=mock_response_400,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=error_400)
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    with pytest.raises(HaikuError):
                        await haiku_complete(
                            system_prompt="You are helpful.",
                            user_message="Test",
                        )

            # Should not have slept (no retry)
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self) -> None:
        """Test that the API retries on timeout error."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_success = MagicMock()
            mock_response_success.content = [MagicMock(text="Success")]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[TimeoutError("Timeout"), mock_response_success]
            )
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    result = await haiku_complete(
                        system_prompt="You are helpful.",
                        user_message="Test",
                    )

            assert result == "Success"
            mock_sleep.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_raises_after_timeout_retries_exhausted(self) -> None:
        """Test that the API raises HaikuError after timeout retries exhausted."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=TimeoutError("Timeout")
            )
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    with pytest.raises(HaikuError) as exc_info:
                        await haiku_complete(
                            system_prompt="You are helpful.",
                            user_message="Test",
                        )

            assert "timed out" in str(exc_info.value)


class TestHaikuDescribeImage:
    """Tests for haiku_describe_image function."""

    @pytest.mark.asyncio
    async def test_returns_description(self) -> None:
        """Test that haiku_describe_image returns a description."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="Digital art style, vibrant colors. A cat on a chair.")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_describe_image
                result = await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert result == "Digital art style, vibrant colors. A cat on a chair."

    @pytest.mark.asyncio
    async def test_strips_whitespace(self) -> None:
        """Test that haiku_describe_image strips leading/trailing whitespace."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="  Description with whitespace  ")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_describe_image
                result = await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert result == "Description with whitespace"

    @pytest.mark.asyncio
    async def test_uses_image_description_system_prompt(self) -> None:
        """Test that haiku_describe_image uses the correct system prompt."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import (
                    IMAGE_DESCRIPTION_SYSTEM_PROMPT,
                    haiku_describe_image,
                )
                await haiku_describe_image(image_base64="iVBORw0KGgo==")

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["system"] == IMAGE_DESCRIPTION_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_uses_max_tokens_512(self) -> None:
        """Test that haiku_describe_image uses max_tokens of 512."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_describe_image
                await haiku_describe_image(image_base64="iVBORw0KGgo==")

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_uses_default_jpeg_media_type(self) -> None:
        """Test that haiku_describe_image uses jpeg as default media type."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_describe_image
                await haiku_describe_image(image_base64="iVBORw0KGgo==")

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            content = messages[0]["content"]
            assert content[0]["source"]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_accepts_png_media_type(self) -> None:
        """Test that haiku_describe_image accepts PNG media type."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]

            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_describe_image
                await haiku_describe_image(
                    image_base64="iVBORw0KGgo==", media_type="image/png"
                )

            call_kwargs = mock_create.call_args.kwargs
            messages = call_kwargs["messages"]
            content = messages[0]["content"]
            assert content[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_raises_image_description_error_on_api_key_missing(self) -> None:
        """Test that haiku_describe_image raises ImageDescriptionError on missing API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            from src.core.haiku import ImageDescriptionError, haiku_describe_image
            with pytest.raises(ImageDescriptionError) as exc_info:
                await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_image_description_error_on_timeout(self) -> None:
        """Test that haiku_describe_image raises ImageDescriptionError on timeout."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=TimeoutError("Timeout"))
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                    from src.core.haiku import ImageDescriptionError, haiku_describe_image
                    with pytest.raises(ImageDescriptionError) as exc_info:
                        await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert "Request timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_image_description_error_on_empty_response(self) -> None:
        """Test that haiku_describe_image raises ImageDescriptionError on empty response."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = []

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import ImageDescriptionError, haiku_describe_image
                with pytest.raises(ImageDescriptionError) as exc_info:
                    await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert "No description generated" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_image_description_error_on_api_error(self) -> None:
        """Test that haiku_describe_image raises ImageDescriptionError on API error."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response_400 = MagicMock()
            mock_response_400.status_code = 400
            error_400 = APIStatusError(
                message="Bad request",
                response=mock_response_400,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=error_400)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import ImageDescriptionError, haiku_describe_image
                with pytest.raises(ImageDescriptionError) as exc_info:
                    await haiku_describe_image(image_base64="iVBORw0KGgo==")

            assert "Failed to describe image" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_image_description_error_is_subclass_of_haiku_error(self) -> None:
        """Test that ImageDescriptionError is a subclass of HaikuError."""
        from src.core.haiku import HaikuError, ImageDescriptionError
        assert issubclass(ImageDescriptionError, HaikuError)
