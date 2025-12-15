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
        assert provider._create_model == "fal-ai/flux-pro/v1.1-ultra"
        assert provider._modify_model == "fal-ai/flux-pro/v1/canny"

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
    async def test_generate_passes_negative_prompt(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that negative prompt is passed when provided."""
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
            assert call_kwargs["arguments"]["negative_prompt"] == "blurry, low quality"

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
    async def test_generate_custom_dimensions(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that custom dimensions are passed."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test", width=512, height=768)
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert call_kwargs["arguments"]["image_size"] == {
                "width": 512,
                "height": 768,
            }

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
    async def test_generate_passes_guidance_scale(
        self, provider: FalAIProvider, mock_fal_response: dict
    ) -> None:
        """Test that guidance scale is passed when provided."""
        with patch(
            "src.providers.fal_provider.fal_client.subscribe"
        ) as mock_subscribe:
            mock_subscribe.return_value = mock_fal_response

            request = ImageRequest(prompt="Test", guidance_scale=7.5)
            await provider.generate(request)

            call_kwargs = mock_subscribe.call_args.kwargs
            assert call_kwargs["arguments"]["guidance_scale"] == 7.5

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
            assert call_kwargs["application"] == "fal-ai/flux-pro/v1.1-ultra"

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
    async def test_modify_passes_control_image_url(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the uploaded image URL."""
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
            assert call_kwargs["arguments"]["control_image_url"] == "https://fal.ai/uploaded.jpg"

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
    async def test_modify_passes_guidance_scale(
        self, provider: FalAIProvider, sample_image_data: str
    ) -> None:
        """Test that modify passes the guidance scale."""
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
            assert call_kwargs["arguments"]["guidance_scale"] == 10.0

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
            assert call_kwargs["application"] == "fal-ai/flux-pro/v1/canny"

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
    """Tests for error handling."""

    @pytest.fixture
    def provider(self) -> FalAIProvider:
        """Create a FalAIProvider for testing."""
        return FalAIProvider(api_key="test-key")

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


class TestGetModels:
    """Tests for get_models functionality."""

    @pytest.mark.asyncio
    async def test_get_models_returns_configured_models(self) -> None:
        """Test that get_models returns the configured models."""
        provider = FalAIProvider(api_key="test-key")
        models = await provider.get_models()

        assert models == [
            "fal-ai/flux-pro/v1.1-ultra",
            "fal-ai/flux-pro/v1/canny",
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
