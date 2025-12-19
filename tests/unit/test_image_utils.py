"""Tests for image utility functions."""

import base64
import io
from unittest.mock import patch

import pytest
from PIL import Image

from src.core.image_utils import (
    compress_image,
    create_composite_thumbnail,
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

    def test_does_not_upscale_small_images(self):
        """Small images should keep their original dimensions."""
        # Create a small 10x10 image
        small_img = Image.new("RGB", (10, 10), color="blue")
        buffer = io.BytesIO()
        small_img.save(buffer, format="PNG")
        small_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Compress with default max_size (512, 512)
        result = compress_image(small_base64)

        # Decode result and check dimensions
        result_bytes = base64.b64decode(result)
        result_img = Image.open(io.BytesIO(result_bytes))

        # Should NOT be upscaled to 512x512
        assert result_img.size == (10, 10), f"Expected (10, 10), got {result_img.size}"


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


class TestCreateCompositeThumbnail:
    """Tests for create_composite_thumbnail function."""

    @pytest.fixture
    def square_image_b64(self):
        """Create a square base64-encoded image."""
        img = Image.new("RGB", (200, 200), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @pytest.fixture
    def wide_image_b64(self):
        """Create a wide base64-encoded image (wider than 3:4 ratio)."""
        img = Image.new("RGB", (400, 200), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @pytest.fixture
    def tall_image_b64(self):
        """Create a tall base64-encoded image (taller than 3:4 ratio)."""
        img = Image.new("RGB", (200, 400), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def test_single_image_returns_resized_thumbnail(self, square_image_b64):
        """Single image should return a resized thumbnail."""
        result = create_composite_thumbnail([square_image_b64])

        # Decode and check dimensions
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        assert img.size == (384, 512)
        assert img.format == "JPEG"

    def test_two_images_returns_horizontal_strip(
        self, square_image_b64, wide_image_b64
    ):
        """Two images should return a horizontal strip of correct dimensions."""
        result = create_composite_thumbnail([square_image_b64, wide_image_b64])

        # Decode and check dimensions
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        # 2 images x 384 width = 768 total width
        assert img.size == (768, 512)
        assert img.format == "JPEG"

    def test_three_images_returns_horizontal_strip(
        self, square_image_b64, wide_image_b64, tall_image_b64
    ):
        """Three images should return a horizontal strip of correct dimensions."""
        result = create_composite_thumbnail(
            [square_image_b64, wide_image_b64, tall_image_b64]
        )

        # Decode and check dimensions
        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        # 3 images x 384 width = 1152 total width
        assert img.size == (1152, 512)
        assert img.format == "JPEG"

    def test_empty_list_raises_value_error(self):
        """Empty images list should raise ValueError."""
        with pytest.raises(ValueError, match="images list cannot be empty"):
            create_composite_thumbnail([])

    def test_custom_dimensions(self, square_image_b64):
        """Should respect custom thumb_height and thumb_width."""
        result = create_composite_thumbnail(
            [square_image_b64], thumb_height=256, thumb_width=192
        )

        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        assert img.size == (192, 256)

    def test_center_crops_wide_image(self, wide_image_b64):
        """Wide images should be center-cropped (sides removed)."""
        # The function should crop a wide 400x200 image to 3:4 ratio
        # then resize to 384x512
        result = create_composite_thumbnail([wide_image_b64])

        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        # Result should have correct dimensions
        assert img.size == (384, 512)

    def test_center_crops_tall_image(self, tall_image_b64):
        """Tall images should be center-cropped (top/bottom removed)."""
        # The function should crop a tall 200x400 image to 3:4 ratio
        # then resize to 384x512
        result = create_composite_thumbnail([tall_image_b64])

        decoded = base64.b64decode(result)
        img = Image.open(io.BytesIO(decoded))

        # Result should have correct dimensions
        assert img.size == (384, 512)

    def test_handles_rgba_images(self):
        """Should handle RGBA images by converting to RGB."""
        # Create an RGBA image
        img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        rgba_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        result = create_composite_thumbnail([rgba_b64])

        decoded = base64.b64decode(result)
        result_img = Image.open(io.BytesIO(decoded))

        # Should be converted to RGB for JPEG output
        assert result_img.mode == "RGB"
        assert result_img.format == "JPEG"
