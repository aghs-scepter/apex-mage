"""Unit tests for FalAIProvider.

Tests the Fal.AI image generation provider implementation including:
- Request formatting for image generation
- Response parsing to GeneratedImage
- Image modification
- Error handling
- Model listing
- Retry behavior (polling only, not submission)
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.core.providers import (
    GeneratedImage,
    ImageModifyRequest,
    ImageRequest,
)
from src.providers.fal_provider import FalAIError, FalAIProvider


def create_mock_handler(result: dict[str, Any]) -> MagicMock:
    """Create a mock handler that simulates fal_client.submit() return value.

    Args:
        result: The result dict to return from handler.get()

    Returns:
        A MagicMock configured to behave like SyncRequestHandle
    """
    handler = MagicMock()
    handler.request_id = "test-request-id-12345"
    handler.iter_events.return_value = iter([])  # No events, just complete
    handler.get.return_value = result
    return handler


class TestFalAIProviderInit:
    """Tests for FalAIProvider initialization."""

    def test_init_sets_api_key_env(self) -> None:
        """Test that initialization sets the FAL_KEY environment variable."""
        with patch.dict("os.environ", {}, clear=False):
            import os
            provider = FalAIProvider(api_key="test-fal-key")
            assert os.environ.get("FAL_KEY") == "test-fal-key"
            assert provider._api_key == "test-fal-key"

    def test_init_default_models(self) -> None:
        """Test that default models are set correctly."""
        provider = FalAIProvider(api_key="test-key")
        assert provider._create_model == "fal-ai/nano-banana-pro"
        assert provider._modify_model == "fal-ai/nano-banana-pro/edit"

    def test_init_custom_models(self) -> None:
        """Test initialization with custom models."""
        provider = FalAIProvider(
            api_key="test-key",
            create_model="custom/create-model",
            modify_model="custom/modify-model",
        )
        assert provider._create_model == "custom/create-model"
        assert provider._modify_model == "custom/modify-model"


class TestImageGeneration:
    """Tests for image generation functionality."""

    @pytest.fixture
    def mock_fal_response(self) -> dict:
        """Create a mock Fal.AI API response."""
        return {
            "images": [
                {
                    "url": "https://fal.ai/images/test1.jpg",
                    "width": 1024,
                    "height": 1024,
                    "content_type": "image/jpeg",
                }
            ],
            "has_nsfw_concepts": [False],
        }

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider for testing."""
        return FalAIProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_generate_returns_images(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that generate returns a list of GeneratedImage objects."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="A beautiful sunset")
            result = await provider.generate(request)

            assert len(result) == 1
            assert isinstance(result[0], GeneratedImage)
            assert result[0].url == "https://fal.ai/images/test1.jpg"
            assert result[0].width == 1024
            assert result[0].height == 1024
            assert result[0].has_nsfw_content is False

    @pytest.mark.asyncio
    async def test_generate_passes_prompt(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that generate passes the prompt to the API."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="A cat sitting on a couch")
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["arguments"]["prompt"] == "A cat sitting on a couch"

    @pytest.mark.asyncio
    async def test_generate_ignores_negative_prompt(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that negative prompt is ignored (not supported by nano-banana-pro)."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(
                prompt="A landscape",
                negative_prompt="blurry, low quality",
            )
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            # nano-banana-pro does not support negative_prompt
            assert "negative_prompt" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_generate_passes_num_images(
        self, provider: FalAIProvider
    ) -> None:
        """Test that num_images is passed when greater than 1."""
        mock_response = {
            "images": [
                {"url": "https://fal.ai/1.jpg", "width": 1024, "height": 1024},
                {"url": "https://fal.ai/2.jpg", "width": 1024, "height": 1024},
            ],
            "has_nsfw_concepts": [False, False],
        }
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test", num_images=2)
            result = await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["arguments"]["num_images"] == 2
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_generate_uses_aspect_ratio(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that nano-banana-pro uses aspect_ratio instead of image_size."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test", width=512, height=768)
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            # nano-banana-pro uses aspect_ratio instead of image_size
            assert "image_size" not in call_kwargs["arguments"]
            assert call_kwargs["arguments"]["aspect_ratio"] == "1:1"
            assert call_kwargs["arguments"]["resolution"] == "1K"
            assert call_kwargs["arguments"]["output_format"] == "jpeg"

    @pytest.mark.asyncio
    async def test_generate_default_dimensions_not_passed(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that default dimensions are not passed to API."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test", width=1024, height=1024)
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert "image_size" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_generate_ignores_guidance_scale(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that guidance_scale is ignored (not supported by nano-banana-pro)."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test", guidance_scale=7.5)
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            # nano-banana-pro does not support guidance_scale
            assert "guidance_scale" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_generate_uses_create_model(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that the correct model is used for generation."""
        mock_handler = create_mock_handler(mock_fal_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")
            await provider.generate(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["application"] == "fal-ai/nano-banana-pro"

    @pytest.mark.asyncio
    async def test_generate_handles_missing_nsfw_concepts(
        self, provider: FalAIProvider
    ) -> None:
        """Test handling when has_nsfw_concepts is not returned."""
        mock_response = {
            "images": [
                {"url": "https://fal.ai/images/test.jpg", "width": 1024, "height": 1024}
            ]
        }
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")
            result = await provider.generate(request)

            assert result[0].has_nsfw_content is None

    @pytest.mark.asyncio
    async def test_generate_uses_request_dimensions_for_response(
        self, provider: FalAIProvider
    ) -> None:
        """Test that request dimensions are used if not in response."""
        mock_response = {
            "images": [{"url": "https://fal.ai/test.jpg"}]
        }
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test", width=800, height=600)
            result = await provider.generate(request)

            assert result[0].width == 800
            assert result[0].height == 600


class TestImageModification:
    """Tests for image modification functionality."""

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider for testing."""
        return FalAIProvider(api_key="test-key")

    @pytest.fixture
    def sample_image_data(self) -> str:
        """Create sample base64 image data."""
        # Minimal valid JPEG header for testing
        jpeg_bytes = bytes([0xFF, 0xD8, 0xFF, 0xE0])
        return base64.b64encode(jpeg_bytes).decode("utf-8")

    @pytest.mark.asyncio
    async def test_modify_returns_images(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify returns a list of GeneratedImage objects."""
        mock_response = {
            "images": [
                {
                    "url": "https://fal.ai/modified.jpg",
                    "width": 1024,
                    "height": 1024,
                    "content_type": "image/jpeg",
                }
            ],
            "has_nsfw_concepts": [False],
        }
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Make it more colorful",
            )
            result = await provider.modify(request)

            assert len(result) == 1
            assert isinstance(result[0], GeneratedImage)
            assert result[0].url == "https://fal.ai/modified.jpg"

    @pytest.mark.asyncio
    async def test_modify_uploads_image(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify uploads the source image."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args.kwargs
            assert call_kwargs["content_type"] == "image/jpeg"
            assert call_kwargs["file_name"] == "image_0.jpeg"

    @pytest.mark.asyncio
    async def test_modify_passes_image_urls(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the uploaded image URL in image_urls array."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            call_kwargs = mock_submit.call_args.kwargs
            # nano-banana-pro/edit uses image_urls array
            assert call_kwargs["arguments"]["image_urls"] == ["https://fal.ai/uploaded.jpg"]

    @pytest.mark.asyncio
    async def test_modify_passes_prompt(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the prompt."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Add a rainbow",
            )
            await provider.modify(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["arguments"]["prompt"] == "Add a rainbow"

    @pytest.mark.asyncio
    async def test_modify_ignores_guidance_scale(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify ignores guidance_scale (not supported by nano-banana-pro/edit)."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
                guidance_scale=10.0,
            )
            await provider.modify(request)

            call_kwargs = mock_submit.call_args.kwargs
            # nano-banana-pro/edit does not support guidance_scale
            assert "guidance_scale" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_modify_uses_modify_model(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify uses the correct model."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["application"] == "fal-ai/nano-banana-pro/edit"

    @pytest.mark.asyncio
    async def test_modify_invalid_base64_raises_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that invalid base64 data raises FalAIError."""
        request = ImageModifyRequest(
            image_data="not-valid-base64!!!",
            prompt="Test",
        )

        with pytest.raises(FalAIError) as exc_info:
            await provider.modify(request)

        assert "Invalid base64 image data" in str(exc_info.value)


class TestErrorHandling:
    """Tests for error handling.

    Note: Uses max_retries=0 to disable retries and ensure fast test execution.
    Retry behavior is tested separately in TestRetryBehavior.
    """

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider for testing with retries disabled."""
        return FalAIProvider(api_key="test-key", max_retries=0)

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_fal_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that API errors during submission are wrapped in FalAIError."""
        with patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.side_effect = Exception("API connection failed")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            assert "Failed to submit image generation" in str(exc_info.value)
            assert "API connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_modify_upload_error_raises_fal_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that upload errors are wrapped in FalAIError."""
        # Valid base64 data
        image_data = base64.b64encode(b"test").decode("utf-8")

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload:
            mock_upload.side_effect = Exception("Upload failed")

            request = ImageModifyRequest(image_data=image_data, prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.modify(request)

            assert "Failed to upload image" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_modify_api_error_raises_fal_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that modification API errors during submission are wrapped in FalAIError."""
        image_data = base64.b64encode(b"test").decode("utf-8")

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.side_effect = Exception("Modification failed")

            request = ImageModifyRequest(image_data=image_data, prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.modify(request)

            assert "Failed to submit image modification" in str(exc_info.value)


class TestRetryBehavior:
    """Tests for retry logic with exponential backoff.

    IMPORTANT: Retry logic only applies to POLLING, not to job submission.
    This prevents double-charging when errors occur after job submission.

    Tests that:
    - Submission errors are NOT retried (to prevent double-charging)
    - Polling errors (network, rate limit, 503) trigger retries
    - Permanent errors (401, 400) fail immediately without retries
    - Correct number of retries occur before final failure
    """

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider with retries enabled and short delay."""
        return FalAIProvider(api_key="test-key", max_retries=3, base_delay=0.1)

    @pytest.mark.asyncio
    async def test_no_retry_on_submit_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that submission errors are NOT retried (prevents double-charging)."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.side_effect = Exception("Network error: connection reset")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            # Submit should only be called ONCE - no retries for submit
            assert mock_submit.call_count == 1
            # No sleep because no retries happened
            assert mock_sleep.call_count == 0
            assert "Failed to submit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retries_on_polling_network_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that network errors during polling trigger retries."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        # iter_events fails with network error
        mock_handler.iter_events.side_effect = Exception("Network error: connection reset")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            # Submit called once (not retried)
            assert mock_submit.call_count == 1
            # iter_events retried 4 times (1 initial + 3 retries)
            assert mock_handler.iter_events.call_count == 4
            # Sleep called 3 times between retries
            assert mock_sleep.call_count == 3
            assert "after 4 attempts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that rate limit errors (429) during polling trigger retries."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        mock_handler.iter_events.side_effect = Exception("HTTP 429: rate limit exceeded")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Submit called once, polling retried
            assert mock_submit.call_count == 1
            assert mock_handler.iter_events.call_count == 4
            assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_service_unavailable(
        self, provider: FalAIProvider
    ) -> None:
        """Test that 503 errors during polling trigger retries."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        mock_handler.iter_events.side_effect = Exception("HTTP 503: service unavailable")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Submit called once, polling retried
            assert mock_submit.call_count == 1
            assert mock_handler.iter_events.call_count == 4
            assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that authentication errors (401) during polling fail immediately."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        mock_handler.iter_events.side_effect = Exception("HTTP 401: unauthorized")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_submit.call_count == 1
            assert mock_handler.iter_events.call_count == 1
            assert mock_sleep.call_count == 0
            # Should NOT say "after X attempts"
            assert "after" not in str(exc_info.value).lower() or "attempts" not in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_no_retry_on_bad_request(
        self, provider: FalAIProvider
    ) -> None:
        """Test that bad request errors (400) during polling fail immediately."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        mock_handler.iter_events.side_effect = Exception("HTTP 400: bad request")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_submit.call_count == 1
            assert mock_handler.iter_events.call_count == 1
            assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_no_retry_on_forbidden(
        self, provider: FalAIProvider
    ) -> None:
        """Test that forbidden errors (403) during polling fail immediately."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        mock_handler.iter_events.side_effect = Exception("HTTP 403: forbidden")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_submit.call_count == 1
            assert mock_handler.iter_events.call_count == 1
            assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(
        self, provider: FalAIProvider
    ) -> None:
        """Test that retry delays follow exponential backoff pattern."""
        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        # Use "connection" to trigger NETWORK classification (retryable)
        mock_handler.iter_events.side_effect = Exception("connection error")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Check exponential backoff: base_delay * 2^attempt
            # With base_delay=0.1: 0.1, 0.2, 0.4
            delays = [call.args[0] for call in mock_sleep.call_args_list]
            assert len(delays) == 3
            assert delays[0] == pytest.approx(0.1)  # 0.1 * 2^0
            assert delays[1] == pytest.approx(0.2)  # 0.1 * 2^1
            assert delays[2] == pytest.approx(0.4)  # 0.1 * 2^2

    @pytest.mark.asyncio
    async def test_success_after_transient_failures(
        self, provider: FalAIProvider
    ) -> None:
        """Test that polling succeeds if it recovers before max retries."""
        mock_response = {
            "images": [{"url": "https://fal.ai/success.jpg", "width": 1024, "height": 1024}],
            "has_nsfw_concepts": [False],
        }

        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        # Fail twice with network error (retryable), then succeed
        mock_handler.iter_events.side_effect = [
            Exception("connection reset"),
            Exception("connection reset"),
            iter([]),  # Success - no events
        ]
        mock_handler.get.return_value = mock_response

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_submit.return_value = mock_handler

            request = ImageRequest(prompt="Test")
            result = await provider.generate(request)

            # Submit called once (not retried)
            assert mock_submit.call_count == 1
            # iter_events called 3 times (2 failures + 1 success)
            assert mock_handler.iter_events.call_count == 3
            # Should have slept twice (between failures)
            assert mock_sleep.call_count == 2
            # Should return successful result
            assert len(result) == 1
            assert result[0].url == "https://fal.ai/success.jpg"

    @pytest.mark.asyncio
    async def test_retry_on_modify_operation(
        self, provider: FalAIProvider
    ) -> None:
        """Test that polling retry logic also works for modify operations."""
        import base64
        image_data = base64.b64encode(b"test").decode("utf-8")

        mock_handler = MagicMock()
        mock_handler.request_id = "test-id"
        # Use "connection" to trigger NETWORK classification (retryable)
        mock_handler.iter_events.side_effect = Exception("connection error")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(image_data=image_data, prompt="Test")

            with pytest.raises(FalAIError):
                await provider.modify(request)

            # Submit called once (not retried to prevent double-charging)
            assert mock_submit.call_count == 1
            # Polling retried 4 times (1 initial + 3 retries)
            assert mock_handler.iter_events.call_count == 4
            assert mock_sleep.call_count == 3


class TestGetModels:
    """Tests for get_models functionality."""

    @pytest.mark.asyncio
    async def test_get_models_returns_configured_models(self) -> None:
        """Test that get_models returns the configured models."""
        provider = FalAIProvider(api_key="test-key")
        models = await provider.get_models()

        assert models == [
            "fal-ai/nano-banana-pro",
            "fal-ai/nano-banana-pro/edit",
        ]

    @pytest.mark.asyncio
    async def test_get_models_returns_custom_models(self) -> None:
        """Test that get_models returns custom models when configured."""
        provider = FalAIProvider(
            api_key="test-key",
            create_model="custom/create",
            modify_model="custom/modify",
        )
        models = await provider.get_models()

        assert models == ["custom/create", "custom/modify"]


class TestProtocolCompliance:
    """Tests to verify protocol compliance."""

    def test_provider_has_generate_method(self) -> None:
        """Test that provider has generate method."""
        provider = FalAIProvider(api_key="test-key")
        assert hasattr(provider, "generate")
        assert callable(provider.generate)

    def test_provider_has_modify_method(self) -> None:
        """Test that provider has modify method."""
        provider = FalAIProvider(api_key="test-key")
        assert hasattr(provider, "modify")
        assert callable(provider.modify)

    def test_provider_has_get_models_method(self) -> None:
        """Test that provider has get_models method."""
        provider = FalAIProvider(api_key="test-key")
        assert hasattr(provider, "get_models")
        assert callable(provider.get_models)


class TestQueueUpdateCallback:
    """Tests for the queue update callback."""

    def test_on_queue_update_does_not_raise(self) -> None:
        """Test that queue update callback handles updates gracefully."""
        provider = FalAIProvider(api_key="test-key")

        # Should not raise any exceptions
        provider._on_queue_update({"status": "waiting"})
        provider._on_queue_update(MagicMock())
        provider._on_queue_update(None)


class TestMultiImageModification:
    """Tests for multi-image modification functionality."""

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider for testing."""
        return FalAIProvider(api_key="test-key")

    @pytest.fixture
    def sample_image_data(self) -> str:
        """Create sample base64 image data."""
        # Minimal valid JPEG header for testing
        jpeg_bytes = bytes([0xFF, 0xD8, 0xFF, 0xE0])
        return base64.b64encode(jpeg_bytes).decode("utf-8")

    @pytest.mark.asyncio
    async def test_modify_with_image_data_list(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify uploads multiple images when image_data_list is provided."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.side_effect = [
                "https://fal.ai/uploaded_0.jpg",
                "https://fal.ai/uploaded_1.jpg",
                "https://fal.ai/uploaded_2.jpg",
            ]
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,  # Required for backward compat
                prompt="Combine these images",
                image_data_list=[sample_image_data, sample_image_data, sample_image_data],
            )
            await provider.modify(request)

            # Should have uploaded 3 images
            assert mock_upload.call_count == 3

            # Verify all URLs were passed to the API
            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["arguments"]["image_urls"] == [
                "https://fal.ai/uploaded_0.jpg",
                "https://fal.ai/uploaded_1.jpg",
                "https://fal.ai/uploaded_2.jpg",
            ]

    @pytest.mark.asyncio
    async def test_modify_image_data_list_filenames(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that multi-image upload uses correct filenames."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}
        mock_handler = create_mock_handler(mock_response)

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.submit"
        ) as mock_submit:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_submit.return_value = mock_handler

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
                image_data_list=[sample_image_data, sample_image_data],
            )
            await provider.modify(request)

            # Verify filenames are numbered correctly
            calls = mock_upload.call_args_list
            assert calls[0].kwargs["file_name"] == "image_0.jpeg"
            assert calls[1].kwargs["file_name"] == "image_1.jpeg"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_modify_invalid_image_in_list_raises_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that invalid base64 in image_data_list raises descriptive error."""
        # Use invalid base64 as FIRST image to avoid network calls
        request = ImageModifyRequest(
            image_data="not-valid-base64!!!",  # Invalid, will fail first
            prompt="Test",
            image_data_list=["not-valid-base64!!!"],  # Invalid base64
        )

        with pytest.raises(FalAIError) as exc_info:
            await provider.modify(request)

        # Error should mention invalid base64 for image 1
        error_msg = str(exc_info.value).lower()
        assert "invalid base64" in error_msg
        assert "image 1" in error_msg
