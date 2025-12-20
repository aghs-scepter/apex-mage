"""Image utility functions for processing and formatting images.

This module provides platform-agnostic image processing utilities including
base64 header stripping, image compression, and response formatting.
"""

import base64
import binascii
import io
from typing import cast
from uuid import uuid4

from PIL import Image, ImageOps
from PIL.Image import Image as PILImage


def image_strip_headers(image_data: str, file_extension: str) -> str:
    """Strip the data URL header from a base64-encoded image.

    If the image data starts with a data URL prefix (e.g., "data:image/jpeg;base64,"),
    this function removes it and returns just the base64 content.

    Args:
        image_data: The base64-encoded image data, optionally with a data URL header.
        file_extension: The expected file extension (e.g., "jpeg", "png").

    Returns:
        The image data with the header removed, or the original data if no header present.
    """
    header_prefix = f"data:image/{file_extension};base64,"
    if image_data.startswith(header_prefix):
        return image_data[len(header_prefix) :]
    return image_data


def compress_image(
    image_data_b64: str,
    max_size: tuple[int, int] = (512, 512),
    quality: int = 75,
) -> str:
    """Compress an image to reduce its size while maintaining quality.

    The image is resized to fit within max_size while preserving aspect ratio,
    then saved as JPEG with the specified quality.

    Args:
        image_data_b64: The base64-encoded image data.
        max_size: Maximum dimensions (width, height) in pixels. Default is (512, 512).
        quality: JPEG quality level from 1-100. Default is 75.

    Returns:
        The base64-encoded compressed image data.

    Raises:
        binascii.Error: If the input is not valid base64 data after padding.
    """
    try:
        image_data = base64.b64decode(image_data_b64)
    except binascii.Error:
        # Add extra padding only if initial decode fails
        padded = image_data_b64
        while len(padded) % 4:
            padded += "="
        image_data = base64.b64decode(padded)

    img: PILImage = Image.open(io.BytesIO(image_data))

    # Convert RGBA or P modes to RGB if necessary
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Calculate new dimensions while maintaining aspect ratio
    # Cap ratio at 1.0 to prevent upscaling small images
    ratio = min(max_size[0] / img.size[0], max_size[1] / img.size[1], 1.0)
    new_size = cast(tuple[int, int], tuple(int(x * ratio) for x in img.size))

    # Resize and compress the image
    img = img.resize(new_size, Image.Resampling.LANCZOS)

    # Save to BytesIO buffer
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)

    # Convert back to base64
    compressed_image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return compressed_image_b64


def format_image_response(
    image_data_b64: str,
    file_extension: str,
    nsfw: bool,
) -> tuple[str, bytes]:
    """Format a base64-encoded image into a filename and raw bytes.

    Generates a unique filename and decodes the image data. For NSFW images,
    the filename is prefixed with "SPOILER_" to enable content hiding in
    platforms that support it.

    Args:
        image_data_b64: The base64-encoded image data.
        file_extension: The file extension for the output filename (e.g., "jpeg").
        nsfw: Whether the image contains NSFW content.

    Returns:
        A tuple of (filename, image_bytes) where filename includes the SPOILER_
        prefix for NSFW images.
    """
    # Decode the base64 data
    image_bytes = base64.b64decode(image_data_b64)

    # Generate filename with optional SPOILER prefix for NSFW content
    if nsfw:
        filename = f"SPOILER_{uuid4()}.{file_extension}"
    else:
        filename = f"{uuid4()}.{file_extension}"

    return filename, image_bytes


def create_composite_thumbnail(
    images: list[str],
    thumb_height: int = 512,
    thumb_width: int = 435,
    border_width: int = 4,
    border_color: tuple[int, int, int] = (51, 51, 51),
) -> str:
    """Create a horizontal strip composite of multiple images.

    Args:
        images: List of base64-encoded image strings (1-3 images).
        thumb_height: Height of each thumbnail in pixels (default 512).
        thumb_width: Width of each thumbnail in pixels (default 435, which is 85% of 512).
        border_width: Width of border around each thumbnail in pixels (default 4).
        border_color: RGB color tuple for border (default dark gray #333333).

    Returns:
        Base64-encoded composite image string (JPEG format).

    Raises:
        ValueError: If images list is empty.

    Notes:
        - Single image: Returns resized/cropped thumbnail of that image with border
        - Multiple images: Returns horizontal strip with borders around each image
        - Images are center-cropped to fit the thumbnail dimensions
          (equal amount cut from both sides for wide images, top/bottom for
          tall images)
        - Each thumbnail has a border added, so final width per image is
          thumb_width + (2 * border_width)
    """
    if not images:
        raise ValueError("images list cannot be empty")

    thumbnails: list[PILImage] = []
    for image_b64 in images:
        # Decode the base64 image
        try:
            image_data = base64.b64decode(image_b64)
        except binascii.Error:
            # Add extra padding only if initial decode fails
            padded = image_b64
            while len(padded) % 4:
                padded += "="
            image_data = base64.b64decode(padded)

        img: PILImage = Image.open(io.BytesIO(image_data))

        # Convert RGBA or P modes to RGB if necessary
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Calculate center crop to match the target aspect ratio
        target_ratio = thumb_width / thumb_height
        current_ratio = img.size[0] / img.size[1]

        if current_ratio > target_ratio:
            # Image is wider than target - crop width (sides)
            new_width = int(img.size[1] * target_ratio)
            left = (img.size[0] - new_width) // 2
            crop_box = (left, 0, left + new_width, img.size[1])
        else:
            # Image is taller than target - crop height (top/bottom)
            new_height = int(img.size[0] / target_ratio)
            top = (img.size[1] - new_height) // 2
            crop_box = (0, top, img.size[0], top + new_height)

        cropped = img.crop(crop_box)

        # Resize to target dimensions
        thumbnail = cropped.resize(
            (thumb_width, thumb_height), Image.Resampling.LANCZOS
        )

        # Add border around the thumbnail
        thumbnail_with_border = ImageOps.expand(
            thumbnail, border=border_width, fill=border_color
        )
        thumbnails.append(thumbnail_with_border)

    # Calculate dimensions with borders
    # Each thumbnail is now (thumb_width + 2*border_width) x (thumb_height + 2*border_width)
    bordered_width = thumb_width + 2 * border_width
    bordered_height = thumb_height + 2 * border_width

    # Create composite canvas
    total_width = bordered_width * len(thumbnails)
    composite = Image.new("RGB", (total_width, bordered_height))

    # Paste thumbnails side by side
    for i, thumbnail in enumerate(thumbnails):
        composite.paste(thumbnail, (i * bordered_width, 0))

    # Save to BytesIO buffer as JPEG
    buffer = io.BytesIO()
    composite.save(buffer, format="JPEG", quality=85, optimize=True)

    # Convert to base64
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
