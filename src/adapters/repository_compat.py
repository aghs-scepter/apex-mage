"""Compatibility adapter for SQLiteRepository.

This module provides a compatibility layer that wraps SQLiteRepository with
helper methods matching the current mem.py interface patterns. This allows
gradual migration from the global mem.py functions to dependency-injected
repository usage.

All methods are async and delegate to the underlying repository.
"""

import json
import logging
from os import getenv
from typing import Any, Optional

from src.adapters.sqlite_repository import SQLiteRepository
from src.ports.repositories import Message

logger = logging.getLogger(__name__)

# Context window size - number of previous messages to use as context
# High values increase cost and latency
WINDOW = 35


class RepositoryAdapter:
    """Adapter that wraps SQLiteRepository with mem.py-compatible methods.

    This class provides a bridge between the old mem.py interface and the
    new repository pattern. It handles:
    - Vendor validation from allowed_vendors.json
    - Channel creation
    - Message storage and retrieval
    - Rate limit enforcement

    Example:
        repo = SQLiteRepository("data/app.db")
        await repo.connect()
        adapter = RepositoryAdapter(repo)
        await adapter.validate_vendors()

        # Then use like mem.py functions
        await adapter.create_channel(channel_id)
        await adapter.add_message(channel_id, 'Anthropic', 'prompt', False, "Hello")
    """

    def __init__(self, repository: SQLiteRepository) -> None:
        """Initialize the adapter with a repository instance.

        Args:
            repository: An already-connected SQLiteRepository instance.
        """
        self._repo = repository
        self._vendor_cache: dict[str, int] = {}

    async def validate_vendors(self) -> None:
        """Load vendors from allowed_vendors.json and ensure they exist in DB.

        Reads the allowed_vendors.json file and creates vendor records for
        each entry. This should be called during bot startup.

        Raises:
            FileNotFoundError: If allowed_vendors.json is not found.
            Exception: For other errors during vendor creation.
        """
        logger.debug("Validating vendors...")
        try:
            with open("allowed_vendors.json") as file:
                allowed_vendors = json.load(file)
            for vendor_name in allowed_vendors.keys():
                model_config = json.dumps(allowed_vendors[vendor_name]["model"])
                vendor = await self._repo.create_vendor(vendor_name, model_config)
                self._vendor_cache[vendor_name] = vendor.id
                logger.debug(f"Vendor {vendor_name} validated with id {vendor.id}")
        except FileNotFoundError:
            logger.error("allowed_vendors.json file not found.")
            raise
        except Exception as ex:
            logger.error(f"Error validating vendors: {ex}")
            raise

    async def create_channel(self, discord_id: int) -> None:
        """Create a channel record if it doesn't exist.

        Args:
            discord_id: The Discord channel ID.
        """
        logger.debug(f"Creating channel {discord_id}...")
        await self._repo.get_or_create_channel(discord_id)
        logger.debug(f"Channel {discord_id} created or already exists.")

    async def _get_vendor_id(self, vendor_name: str) -> int:
        """Get vendor ID from cache or database.

        Args:
            vendor_name: The vendor name.

        Returns:
            The vendor's internal ID.

        Raises:
            ValueError: If vendor is not found.
        """
        if vendor_name in self._vendor_cache:
            return self._vendor_cache[vendor_name]

        vendor = await self._repo.get_vendor(vendor_name)
        if vendor is None:
            raise ValueError(f"Vendor '{vendor_name}' not found")
        self._vendor_cache[vendor_name] = vendor.id
        return vendor.id

    async def add_message(
        self,
        discord_id: int,
        vendor_name: str,
        message_type: str,
        is_image_prompt: bool,
        message_data: str,
    ) -> None:
        """Add a message to the database.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The AI vendor name (e.g., 'Anthropic').
            message_type: Type of message ('prompt', 'assistant', 'behavior').
            is_image_prompt: Whether this is an image generation prompt.
            message_data: The message content.
        """
        logger.debug("Adding message to database...")
        vendor_id = await self._get_vendor_id(vendor_name)
        message = Message(
            channel_id=discord_id,
            vendor_id=vendor_id,
            message_type=message_type,
            content=message_data,
            is_image_prompt=is_image_prompt,
        )
        await self._repo.save_message(message)
        logger.debug("Message added to database.")

    async def add_message_with_images(
        self,
        discord_id: int,
        vendor_name: str,
        message_type: str,
        is_image_prompt: bool,
        message_data: str,
        message_images: str,
    ) -> None:
        """Add a message with images to the database.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The AI vendor name (e.g., 'Anthropic').
            message_type: Type of message ('prompt', 'assistant', 'behavior').
            is_image_prompt: Whether this is an image generation prompt.
            message_data: The message content.
            message_images: JSON string containing image data.
        """
        logger.debug("Adding message with images to database...")
        vendor_id = await self._get_vendor_id(vendor_name)
        message = Message(
            channel_id=discord_id,
            vendor_id=vendor_id,
            message_type=message_type,
            content=message_data,
            is_image_prompt=is_image_prompt,
        )
        # Parse the images JSON to extract URLs/data
        image_urls = json.loads(message_images) if message_images else []
        await self._repo.save_message_with_images(message, image_urls)
        logger.debug("Message with images added to database.")

    async def get_visible_messages(
        self,
        discord_id: int,
        vendor_name: str,
    ) -> list[dict[str, Any]]:
        """Get all visible messages for a channel as dicts.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').

        Returns:
            List of message dictionaries in chronological order.
        """
        logger.debug(
            f"Getting visible messages for channel {discord_id} and vendor {vendor_name}..."
        )
        messages = await self._repo.get_visible_messages(discord_id, vendor_name)
        result = [self._message_to_dict(msg) for msg in messages]
        logger.debug(
            f"Visible messages retrieved for channel {discord_id} and vendor {vendor_name}."
        )
        return result

    async def get_latest_images(
        self,
        discord_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Get the latest image messages for a channel as dicts.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').
            limit: Maximum number of messages to retrieve.

        Returns:
            List of message dictionaries containing images.
        """
        logger.debug(
            f"Getting latest image messages for channel {discord_id} and vendor {vendor_name}..."
        )
        messages = await self._repo.get_latest_images(discord_id, vendor_name, limit)
        result = [self._message_to_dict(msg) for msg in messages]
        logger.debug(
            f"Latest image messages retrieved for channel {discord_id} and vendor {vendor_name}."
        )
        return result

    async def deactivate_old_messages(
        self,
        discord_id: int,
        vendor_name: str,
        window: int,
    ) -> None:
        """Mark messages outside the context window as inactive.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').
            window: Number of recent messages to keep active.
        """
        logger.debug(
            f"Deactivating old messages for channel {discord_id} and vendor {vendor_name}..."
        )
        await self._repo.deactivate_old_messages(discord_id, vendor_name, window)
        logger.debug(
            f"Old messages deactivated for channel {discord_id} and vendor {vendor_name}."
        )

    async def clear_messages(
        self,
        discord_id: int,
        vendor_name: str,
    ) -> None:
        """Soft-delete all messages for a channel and vendor.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').
        """
        logger.debug(
            f"Clearing messages for channel {discord_id} and vendor {vendor_name}..."
        )
        await self._repo.clear_messages(discord_id, vendor_name)
        logger.debug(
            f"Messages cleared for channel {discord_id} and vendor {vendor_name}."
        )

    async def enforce_text_rate_limits(self, channel_id: int) -> bool:
        """Check if channel is within text rate limits.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        request_count = await self._repo.get_recent_text_request_count(channel_id)
        rate_limit = int(getenv("ANTHROPIC_RATE_LIMIT", "30"))

        if request_count < rate_limit:
            return True
        else:
            logger.warning(f"Text request rate limit exceeded for channel {channel_id}.")
            return False

    async def enforce_image_rate_limits(self, channel_id: int) -> bool:
        """Check if channel is within image rate limits.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        request_count = await self._repo.get_recent_image_request_count(channel_id)
        rate_limit = int(getenv("FAL_RATE_LIMIT", "8"))

        if request_count < rate_limit:
            return True
        else:
            logger.warning(f"Image request rate limit exceeded for channel {channel_id}.")
            return False

    @staticmethod
    def _message_to_dict(message: Message) -> dict[str, Any]:
        """Convert a Message object to a dict for backward compatibility.

        Args:
            message: The Message object to convert.

        Returns:
            Dictionary with keys matching mem.py's row_to_dict output.
        """
        # Parse images back to the format expected by existing code
        images_data = []
        for img in message.images:
            images_data.append(img.url)

        return {
            "channel_message_id": message.id,
            "message_type": message.message_type,
            "message_data": message.content,
            "message_images": json.dumps(images_data) if images_data else "[]",
            "message_timestamp": message.timestamp,
        }
