"""Tests for the image API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import AuthUser, get_current_user
from src.api.routes.images import router
from src.core.providers import GeneratedImage
from src.core.rate_limit import RateLimitResult


@pytest.fixture
def mock_image_provider():
    """Create a mock image provider."""
    provider = AsyncMock()
    provider.generate = AsyncMock(
        return_value=[
            GeneratedImage(
                url="data:image/jpeg;base64,/9j/4AAQSkZJRg==",
                width=1024,
                height=1024,
                has_nsfw_content=False,
            )
        ]
    )
    provider.modify = AsyncMock(
        return_value=[
            GeneratedImage(
                url="data:image/jpeg;base64,/9j/4AAQSkZJRg==",
                width=1024,
                height=1024,
                has_nsfw_content=False,
            )
        ]
    )
    return provider


@pytest.fixture
def mock_rate_limiter():
    """Create a mock rate limiter."""
    limiter = AsyncMock()
    limiter.check = AsyncMock(
        return_value=RateLimitResult(
            allowed=True,
            remaining=7,
            reset_at=datetime.now(UTC),
            wait_seconds=None,
        )
    )
    limiter.record = AsyncMock()
    return limiter


@pytest.fixture
def mock_gcs_adapter():
    """Create a mock GCS adapter."""
    adapter = MagicMock()
    adapter.upload_image = MagicMock(
        return_value="https://storage.googleapis.com/bucket/image.jpeg"
    )
    return adapter


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    return AuthUser(user_id=12345)


@pytest.fixture
def app(mock_image_provider, mock_rate_limiter, mock_gcs_adapter, mock_user):
    """Create a test FastAPI app with mocked dependencies."""
    from src.api.dependencies import (
        get_gcs_adapter,
        get_image_provider,
        get_rate_limiter,
    )

    app = FastAPI()
    app.include_router(router)

    # Override dependencies
    app.dependency_overrides[get_image_provider] = lambda: mock_image_provider
    app.dependency_overrides[get_rate_limiter] = lambda: mock_rate_limiter
    app.dependency_overrides[get_gcs_adapter] = lambda: mock_gcs_adapter
    app.dependency_overrides[get_current_user] = lambda: mock_user

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestGenerateImage:
    """Tests for POST /images/generate."""

    @patch("src.api.routes.images.compress_image")
    @patch("src.api.routes.images.image_strip_headers")
    def test_generates_image(
        self,
        mock_strip,
        mock_compress,
        client,
        mock_image_provider,
        mock_rate_limiter,
    ):
        """Should generate image and return response."""
        mock_strip.return_value = "base64imagedata"
        mock_compress.return_value = "compressedbase64"

        response = client.post(
            "/images/generate",
            json={"prompt": "A beautiful sunset over mountains"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "image_base64" in data
        assert "filename" in data
        assert "created_at" in data

        mock_image_provider.generate.assert_called_once()
        mock_rate_limiter.record.assert_called_once()

    @patch("src.api.routes.images.compress_image")
    @patch("src.api.routes.images.image_strip_headers")
    def test_generates_image_with_dimensions(
        self,
        mock_strip,
        mock_compress,
        client,
        mock_image_provider,
    ):
        """Should pass dimensions to provider."""
        mock_strip.return_value = "base64imagedata"
        mock_compress.return_value = "compressedbase64"

        response = client.post(
            "/images/generate",
            json={"prompt": "Test", "width": 512, "height": 512},
        )

        assert response.status_code == 200

        call_args = mock_image_provider.generate.call_args
        request = call_args[0][0]
        assert request.width == 512
        assert request.height == 512

    def test_rate_limit_exceeded(self, client, mock_rate_limiter):
        """Should return 429 when rate limited."""
        mock_rate_limiter.check.return_value = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=datetime.now(UTC),
            wait_seconds=60.0,
        )

        response = client.post(
            "/images/generate",
            json={"prompt": "Test image"},
        )

        assert response.status_code == 429

    @patch("src.api.routes.images.compress_image")
    @patch("src.api.routes.images.image_strip_headers")
    def test_handles_gcs_failure(
        self,
        mock_strip,
        mock_compress,
        client,
        mock_gcs_adapter,
    ):
        """Should succeed even if GCS upload fails."""
        mock_strip.return_value = "base64imagedata"
        mock_compress.return_value = "compressedbase64"
        mock_gcs_adapter.upload_image.side_effect = Exception("GCS error")

        response = client.post(
            "/images/generate",
            json={"prompt": "Test image"},
        )

        # Should still succeed, just without cloud URL
        assert response.status_code == 200
        data = response.json()
        assert data["cloud_url"] is None

    def test_validates_prompt_required(self, client):
        """Should require prompt field."""
        response = client.post("/images/generate", json={})
        assert response.status_code == 422

    def test_validates_prompt_not_empty(self, client):
        """Should reject empty prompt."""
        response = client.post("/images/generate", json={"prompt": ""})
        assert response.status_code == 422


class TestModifyImage:
    """Tests for POST /images/modify."""

    @patch("src.api.routes.images.compress_image")
    @patch("src.api.routes.images.image_strip_headers")
    def test_modifies_image(
        self,
        mock_strip,
        mock_compress,
        client,
        mock_image_provider,
        mock_rate_limiter,
    ):
        """Should modify image and return response."""
        mock_strip.return_value = "base64imagedata"
        mock_compress.return_value = "compressedbase64"

        response = client.post(
            "/images/modify",
            json={
                "image_base64": "existingimagedata",
                "prompt": "Add more trees",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "image_base64" in data
        assert "filename" in data

        mock_image_provider.modify.assert_called_once()
        mock_rate_limiter.record.assert_called_once()

    @patch("src.api.routes.images.compress_image")
    @patch("src.api.routes.images.image_strip_headers")
    def test_passes_guidance_scale(
        self,
        mock_strip,
        mock_compress,
        client,
        mock_image_provider,
    ):
        """Should pass guidance scale to provider."""
        mock_strip.return_value = "base64imagedata"
        mock_compress.return_value = "compressedbase64"

        response = client.post(
            "/images/modify",
            json={
                "image_base64": "existingimagedata",
                "prompt": "Test",
                "guidance_scale": 12.0,
            },
        )

        assert response.status_code == 200

        call_args = mock_image_provider.modify.call_args
        request = call_args[0][0]
        assert request.guidance_scale == 12.0

    def test_rate_limit_exceeded(self, client, mock_rate_limiter):
        """Should return 429 when rate limited."""
        mock_rate_limiter.check.return_value = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=datetime.now(UTC),
            wait_seconds=60.0,
        )

        response = client.post(
            "/images/modify",
            json={
                "image_base64": "existingimagedata",
                "prompt": "Test",
            },
        )

        assert response.status_code == 429

    def test_validates_required_fields(self, client):
        """Should require image_base64 and prompt."""
        response = client.post("/images/modify", json={})
        assert response.status_code == 422

        response = client.post(
            "/images/modify", json={"image_base64": "data"}
        )
        assert response.status_code == 422

        response = client.post(
            "/images/modify", json={"prompt": "test"}
        )
        assert response.status_code == 422
