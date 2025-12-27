"""Base utilities and shared components for Discord UI views.

This module provides common utilities used across all carousel and view modules.
"""

import base64
import io
from typing import TYPE_CHECKING

import discord

from src.clients.discord.utils import get_user_info

if TYPE_CHECKING:
    pass

__all__ = [
    "create_file_from_image",
    "get_user_info",
]


async def create_file_from_image(image_data: dict[str, str]) -> discord.File:
    """Create a discord.File object from base64 image data.

    Args:
        image_data: Dict with 'filename' and 'image' (base64) keys.

    Returns:
        A discord.File ready for attachment.
    """
    file_data = io.BytesIO(base64.b64decode(image_data["image"]))
    file_data.seek(0)
    return discord.File(file_data, filename=image_data["filename"], spoiler=False)
