"""Tests for image utility functions."""

import base64
import io
from unittest.mock import patch

import pytest
from PIL import Image

from src.core.image_utils import (
    compress_image,
    format_image_response,
    image_strip_headers,
)


class TestImageStripHeaders:
    """Tests for image_strip_headers function."""

    def test_strips_jpeg_header(self):
        """Should strip data URL header for JPEG images."""
        data = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        result = image_strip_headers(data, "jpeg")
        assert result == "/9j/4AAQSkZJRg=="

    def test_strips_png_header(self):
        """Should strip data URL header for PNG images."""
        data = "data:image/png;base64,iVBORw0KGgo="
        result = image_strip_headers(data, "png")
        assert result == "iVBORw0KGgo="

    def test_returns_unchanged_without_header(self):
        """Should return data unchanged if no header present."""
        data = "/9j/4AAQSkZJRg=="
        result = image_strip_headers(data, "jpeg")
        assert result == data

    def test_returns_unchanged_with_wrong_extension(self):
        """Should return data unchanged if extension doesn't match."""
        data = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        result = image_strip_headers(data, "png")
        assert result == data


class TestCompressImage:
    """Tests for compress_image function."""

    @pytest.fixture
    def sample_image_b64(self):
        """Create a sample base64-encoded image."""
        # Create a small test image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @pytest.fixture
    def large_image_b64(self):
        """Create a larger base64-encoded image."""
        img = Image.new("RGB", (1000, 1000), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @pytest.fixture
    def rgba_image_b64(self):
        """Create an RGBA image."""
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def test_compresses_image(self, sample_image_b64):
        """Should return valid base64-encoded compressed image."""
        result = compress_image(sample_image_b64)
        # Should be valid base64
        decoded = base64.b64decode(result)
        # Should be valid image
        img = Image.open(io.BytesIO(decoded))
        assert img.format == "JPEG"

    def test_resizes_large_image(self, large_image_b64):
        """Should resize image to fit within max_size."""
        result = compress_image(large_image_b64, max_size=(256, 256))
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))
        assert img.size[0] <= 256
        assert img.size[1] <= 256

    def test_maintains_aspect_ratio(self, large_image_b64):
        """Should maintain aspect ratio when resizing."""
        result = compress_image(large_image_b64, max_size=(256, 512))
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))
        # Original is 1000x1000 (1:1 ratio), max is 256x512
        # Should fit within 256x256 to maintain ratio
        assert img.size[0] == img.size[1]  # Still square

    def test_converts_rgba_to_rgb(self, rgba_image_b64):
        """Should convert RGBA images to RGB for JPEG output."""
        result = compress_image(rgba_image_b64)
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))
        assert img.mode == "RGB"

    def test_handles_missing_padding(self):
        """Should handle base64 strings with missing padding."""
        # Create valid image with intentionally missing padding
        img = Image.new("RGB", (50, 50), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        # Remove padding
        b64_no_padding = b64.rstrip("=")

        result = compress_image(b64_no_padding)
        # Should still work
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))
        assert img is not None


class TestFormatImageResponse:
    """Tests for format_image_response function."""

    @pytest.fixture
    def sample_image_b64(self):
        """Create a sample base64-encoded image."""
        img = Image.new("RGB", (50, 50), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def test_returns_filename_and_bytes(self, sample_image_b64):
        """Should return tuple of filename and bytes."""
        filename, image_bytes = format_image_response(sample_image_b64, "jpeg", False)
        assert isinstance(filename, str)
        assert isinstance(image_bytes, bytes)
        assert filename.endswith(".jpeg")

    def test_generates_unique_filenames(self, sample_image_b64):
        """Should generate unique filenames each time."""
        filename1, _ = format_image_response(sample_image_b64, "jpeg", False)
        filename2, _ = format_image_response(sample_image_b64, "jpeg", False)
        assert filename1 != filename2

    def test_nsfw_adds_spoiler_prefix(self, sample_image_b64):
        """Should add SPOILER_ prefix for NSFW images."""
        filename, _ = format_image_response(sample_image_b64, "jpeg", True)
        assert filename.startswith("SPOILER_")

    def test_non_nsfw_no_spoiler_prefix(self, sample_image_b64):
        """Should not add SPOILER_ prefix for non-NSFW images."""
        filename, _ = format_image_response(sample_image_b64, "jpeg", False)
        assert not filename.startswith("SPOILER_")

    def test_respects_file_extension(self, sample_image_b64):
        """Should use provided file extension."""
        filename, _ = format_image_response(sample_image_b64, "png", False)
        assert filename.endswith(".png")

    def test_bytes_match_input(self, sample_image_b64):
        """Returned bytes should match decoded input."""
        expected_bytes = base64.b64decode(sample_image_b64)
        _, image_bytes = format_image_response(sample_image_b64, "jpeg", False)
        assert image_bytes == expected_bytes
