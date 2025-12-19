"""Unit tests for FalAIProvider.

Tests the Fal.AI image generation provider implementation including:
- Request formatting for image generation
- Response parsing to GeneratedImage
- Image modification
- Error handling
- Model listing
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from src.core.providers import (
    GeneratedImage,
    ImageModifyRequest,
    ImageRequest,
)
from src.providers.fal_provider import FalAIError, FalAIProvider


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
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

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
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="A cat sitting on a couch")
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert call_kwargs["arguments"]["prompt"] == "A cat sitting on a couch"

    @pytest.mark.asyncio
    async def test_generate_ignores_negative_prompt(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that negative prompt is ignored (not supported by nano-banana-pro)."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(
                prompt="A landscape",
                negative_prompt="blurry, low quality",
            )
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
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

        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_response

            request = ImageRequest(prompt="Test", num_images=2)
            result = await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert call_kwargs["arguments"]["num_images"] == 2
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_generate_uses_aspect_ratio(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that nano-banana-pro uses aspect_ratio instead of image_size."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test", width=512, height=768)
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            # nano-banana-pro uses aspect_ratio instead of image_size
            assert "image_size" not in call_kwargs["arguments"]
            assert call_kwargs["arguments"]["aspect_ratio"] == "1:1"
            assert call_kwargs["arguments"]["resolution"] == "1K"
            assert call_kwargs["arguments"]["output_format"] == "png"

    @pytest.mark.asyncio
    async def test_generate_default_dimensions_not_passed(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that default dimensions are not passed to API."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test", width=1024, height=1024)
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert "image_size" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_generate_ignores_guidance_scale(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that guidance_scale is ignored (not supported by nano-banana-pro)."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test", guidance_scale=7.5)
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            # nano-banana-pro does not support guidance_scale
            assert "guidance_scale" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_generate_uses_create_model(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that the correct model is used for generation."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test")
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
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

        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_response

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

        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_response

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

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

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

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args.kwargs
            assert call_kwargs["content_type"] == "image/jpeg"
            assert call_kwargs["file_name"] == "image.jpeg"

    @pytest.mark.asyncio
    async def test_modify_passes_image_urls(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the uploaded image URL in image_urls array."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            # nano-banana-pro/edit uses image_urls array
            assert call_kwargs["arguments"]["image_urls"] == ["https://fal.ai/uploaded.jpg"]

    @pytest.mark.asyncio
    async def test_modify_passes_prompt(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the prompt."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Add a rainbow",
            )
            await provider.modify(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert call_kwargs["arguments"]["prompt"] == "Add a rainbow"

    @pytest.mark.asyncio
    async def test_modify_ignores_guidance_scale(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify ignores guidance_scale (not supported by nano-banana-pro/edit)."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
                guidance_scale=10.0,
            )
            await provider.modify(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            # nano-banana-pro/edit does not support guidance_scale
            assert "guidance_scale" not in call_kwargs["arguments"]

    @pytest.mark.asyncio
    async def test_modify_uses_modify_model(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify uses the correct model."""
        mock_response = {"images": [{"url": "https://fal.ai/modified.jpg"}]}

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.return_value = mock_response

            request = ImageModifyRequest(
                image_data=sample_image_data,
                prompt="Test",
            )
            await provider.modify(request)

            call_kwargs = mock_subscribe.call_args.kwargs
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
        """Test that API errors are wrapped in FalAIError."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("API connection failed")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            assert "Image generation failed" in str(exc_info.value)
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
        """Test that modification API errors are wrapped in FalAIError."""
        image_data = base64.b64encode(b"test").decode("utf-8")

        with patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            mock_subscribe.side_effect = Exception("Modification failed")

            request = ImageModifyRequest(image_data=image_data, prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.modify(request)

            assert "Image modification failed" in str(exc_info.value)


class TestRetryBehavior:
    """Tests for retry logic with exponential backoff.

    Tests that:
    - Transient errors (network, rate limit, 503) trigger retries
    - Permanent errors (401, 400) fail immediately without retries
    - Correct number of retries occur before final failure
    """

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider with retries enabled and short delay."""
        return FalAIProvider(api_key="test-key", max_retries=3, base_delay=0.1)

    @pytest.mark.asyncio
    async def test_retries_on_network_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that network errors trigger retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("Network error: connection reset")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            # Should have retried 3 times (4 total attempts)
            assert mock_subscribe.call_count == 4
            # Sleep should have been called 3 times (between retries)
            assert mock_sleep.call_count == 3
            assert "after 4 attempts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that rate limit errors (429) trigger retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("HTTP 429: rate limit exceeded")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should have retried 3 times (4 total attempts)
            assert mock_subscribe.call_count == 4
            assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_service_unavailable(
        self, provider: FalAIProvider
    ) -> None:
        """Test that 503 errors trigger retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("HTTP 503: service unavailable")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should have retried 3 times (4 total attempts)
            assert mock_subscribe.call_count == 4
            assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(
        self, provider: FalAIProvider
    ) -> None:
        """Test that authentication errors (401) fail immediately without retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("HTTP 401: unauthorized")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError) as exc_info:
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_subscribe.call_count == 1
            assert mock_sleep.call_count == 0
            # Should NOT say "after X attempts"
            assert "after" not in str(exc_info.value).lower() or "attempts" not in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_no_retry_on_bad_request(
        self, provider: FalAIProvider
    ) -> None:
        """Test that bad request errors (400) fail immediately without retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("HTTP 400: bad request")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_subscribe.call_count == 1
            assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_no_retry_on_forbidden(
        self, provider: FalAIProvider
    ) -> None:
        """Test that forbidden errors (403) fail immediately without retries."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.side_effect = Exception("HTTP 403: forbidden")

            request = ImageRequest(prompt="Test")

            with pytest.raises(FalAIError):
                await provider.generate(request)

            # Should fail immediately without retries
            assert mock_subscribe.call_count == 1
            assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(
        self, provider: FalAIProvider
    ) -> None:
        """Test that retry delays follow exponential backoff pattern."""
        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            # Use "connection" to trigger NETWORK classification (retryable)
            mock_subscribe.side_effect = Exception("connection error")

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
        """Test that operation succeeds if it recovers before max retries."""
        mock_response = {
            "images": [{"url": "https://fal.ai/success.jpg", "width": 1024, "height": 1024}],
            "has_nsfw_concepts": [False],
        }

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            # Fail twice with network error (retryable), then succeed
            mock_subscribe.side_effect = [
                Exception("connection reset"),
                Exception("connection reset"),
                mock_response,
            ]

            request = ImageRequest(prompt="Test")
            result = await provider.generate(request)

            # Should have made 3 calls (2 failures + 1 success)
            assert mock_subscribe.call_count == 3
            # Should have slept twice (between failures)
            assert mock_sleep.call_count == 2
            # Should return successful result
            assert len(result) == 1
            assert result[0].url == "https://fal.ai/success.jpg"

    @pytest.mark.asyncio
    async def test_retry_on_modify_operation(
        self, provider: FalAIProvider
    ) -> None:
        """Test that retry logic also works for modify operations."""
        import base64
        image_data = base64.b64encode(b"test").decode("utf-8")

        with patch("asyncio.sleep") as mock_sleep, patch(
            "src.providers.fal_provider.fal_client.upload"
        ) as mock_upload, patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_upload.return_value = "https://fal.ai/uploaded.jpg"
            # Use "connection" to trigger NETWORK classification (retryable)
            mock_subscribe.side_effect = Exception("connection error")

            request = ImageModifyRequest(image_data=image_data, prompt="Test")

            with pytest.raises(FalAIError):
                await provider.modify(request)

            # Should have retried 3 times (4 total attempts for subscribe)
            assert mock_subscribe.call_count == 4
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
