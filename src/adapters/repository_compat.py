"""Compatibility adapter for SQLiteRepository.

This module provides a compatibility layer that wraps SQLiteRepository with
helper methods matching the current mem.py interface patterns. This allows
gradual migration from the global mem.py functions to dependency-injected
repository usage.

All methods are async and delegate to the underlying repository.
"""

import asyncio
import json
from os import getenv
from typing import Any, cast

from src.adapters.sqlite_repository import SQLiteRepository
from src.core.logging import get_logger
from src.ports.repositories import Message

logger = get_logger(__name__)

# Context window size - number of previous messages to use as context
# High values increase cost and latency
WINDOW = 35

# Default vendor names for rate limiting
TEXT_VENDOR_NAME = "Anthropic"
IMAGE_VENDOR_NAME = "Fal.AI"

# Maximum number of images in the carousel per channel
MAX_CAROUSEL_IMAGES = 10


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
            allowed_vendors = await asyncio.to_thread(self._load_vendors_sync)
            for vendor_name in allowed_vendors.keys():
                model_config = json.dumps(allowed_vendors[vendor_name]["model"])
                vendor = await self._repo.create_vendor(vendor_name, model_config)
                self._vendor_cache[vendor_name] = vendor.id
                logger.debug("vendor_validated", vendor_name=vendor_name, vendor_id=vendor.id)
        except FileNotFoundError:
            logger.error("allowed_vendors.json file not found.")
            raise
        except Exception as ex:
            logger.error("vendor_validation_error", error=str(ex))
            raise

    @staticmethod
    def _load_vendors_sync() -> dict[str, Any]:
        """Load vendors from JSON file synchronously.

        This helper exists to be called via asyncio.to_thread() to avoid
        blocking the event loop with file I/O.

        Returns:
            Dictionary of vendor configurations.

        Raises:
            FileNotFoundError: If allowed_vendors.json is not found.
        """
        with open("allowed_vendors.json") as file:
            return cast(dict[str, Any], json.load(file))

    async def create_channel(self, discord_id: int) -> None:
        """Create a channel record if it doesn't exist.

        Args:
            discord_id: The Discord channel ID.
        """
        logger.debug("creating_channel", discord_id=discord_id)
        await self._repo.get_or_create_channel(discord_id)
        logger.debug("channel_created_or_exists", discord_id=discord_id)

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
        is_image_only_context: bool = False,
    ) -> None:
        """Add a message to the database.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The AI vendor name (e.g., 'Anthropic').
            message_type: Type of message ('prompt', 'assistant', 'behavior').
            is_image_prompt: Whether this is an image generation prompt.
            message_data: The message content.
            is_image_only_context: Whether this message is for image-only context.
                When True, excluded from /prompt text context but available for
                /describe_this and /modify_image commands.
        """
        logger.debug("Adding message to database...")
        vendor_id = await self._get_vendor_id(vendor_name)
        message = Message(
            channel_id=discord_id,
            vendor_id=vendor_id,
            message_type=message_type,
            content=message_data,
            is_image_prompt=is_image_prompt,
            is_image_only_context=is_image_only_context,
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
        is_image_only_context: bool = False,
    ) -> None:
        """Add a message with images to the database.

        Enforces the carousel image limit (MAX_CAROUSEL_IMAGES). If adding these
        images would exceed the limit, the oldest images are silently removed.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The AI vendor name (e.g., 'Anthropic').
            message_type: Type of message ('prompt', 'assistant', 'behavior').
            is_image_prompt: Whether this is an image generation prompt.
            message_data: The message content.
            message_images: JSON string containing image data.
            is_image_only_context: Whether this message is for image-only context.
                When True, excluded from /prompt text context but available for
                /describe_this and /modify_image commands.
        """
        logger.debug("Adding message with images to database...")
        vendor_id = await self._get_vendor_id(vendor_name)
        message = Message(
            channel_id=discord_id,
            vendor_id=vendor_id,
            message_type=message_type,
            content=message_data,
            is_image_prompt=is_image_prompt,
            is_image_only_context=is_image_only_context,
        )
        # Parse the images JSON to extract URLs/data
        image_urls = json.loads(message_images) if message_images else []
        await self._repo.save_message_with_images(message, image_urls)
        logger.debug("Message with images added to database.")

        # Enforce carousel image limit by deactivating oldest image messages
        await self._enforce_image_limit(discord_id, vendor_name)

    async def _enforce_image_limit(
        self,
        discord_id: int,
        vendor_name: str,
    ) -> None:
        """Enforce the carousel image limit by deactivating oldest messages.

        This method counts all images in active messages for the channel.
        If the count exceeds MAX_CAROUSEL_IMAGES, it deactivates the oldest
        image messages until the count is at or below the limit.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by.
        """
        # Get all image messages (ordered newest first)
        messages = await self._repo.get_latest_images(
            discord_id, "All Models", limit=100  # Get more to count all
        )

        # Count images and track which messages to keep
        image_count = 0
        messages_to_keep: list[int] = []

        for msg in messages:
            msg_image_count = len(msg.images)
            if image_count + msg_image_count <= MAX_CAROUSEL_IMAGES:
                image_count += msg_image_count
                if msg.id is not None:
                    messages_to_keep.append(msg.id)
            else:
                # This message would push us over the limit
                # Check if we can partially fit (we cannot - must keep whole message)
                # So we stop here and deactivate this and all older messages
                break

        # If we have messages beyond the limit, deactivate them
        if len(messages_to_keep) < len(messages):
            messages_to_deactivate = [
                msg.id for msg in messages
                if msg.id is not None and msg.id not in messages_to_keep
            ]
            if messages_to_deactivate:
                await self._repo.deactivate_image_messages(
                    discord_id, messages_to_deactivate
                )
                logger.debug(
                    f"Deactivated {len(messages_to_deactivate)} old image messages "
                    f"for channel {discord_id} to enforce {MAX_CAROUSEL_IMAGES}-image limit."
                )

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

    async def get_images(
        self,
        discord_id: int,
        vendor_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get a flat list of image data dicts for a channel.

        This method extracts individual image data from messages, suitable for
        display in carousels or other image selection UIs.

        The returned list is limited to MAX_CAROUSEL_IMAGES (10) images,
        with newest images first (index 0 = newest).

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').
            limit: Maximum number of messages to search (default 10).

        Returns:
            List of image dicts with 'filename' and 'image' keys.
            Maximum of MAX_CAROUSEL_IMAGES items returned.
        """
        logger.debug("getting_images", discord_id=discord_id)
        messages = await self._repo.get_latest_images(discord_id, vendor_name, limit)
        images: list[dict[str, Any]] = []
        for msg in messages:
            # Each message may contain multiple images
            for img in msg.images:
                # img.url contains the image dict (filename, image)
                if isinstance(img.url, dict):
                    images.append(img.url)
                elif isinstance(img.url, str):
                    # Handle legacy string format
                    try:
                        img_data = json.loads(img.url)
                        if isinstance(img_data, dict):
                            images.append(img_data)
                    except json.JSONDecodeError:
                        pass
        # Enforce the carousel image limit
        images = images[:MAX_CAROUSEL_IMAGES]
        logger.debug("images_retrieved", discord_id=discord_id, count=len(images))
        return images

    async def has_images_in_context(
        self,
        discord_id: int,
        vendor_name: str,
    ) -> bool:
        """Check if the channel's context contains any images.

        Args:
            discord_id: The Discord channel ID.
            vendor_name: The vendor name to filter by (or 'All Models').

        Returns:
            True if at least one image exists in the context, False otherwise.
        """
        logger.debug(
            f"Checking for images in context for channel {discord_id}..."
        )
        result = await self._repo.has_images_in_context(discord_id, vendor_name)
        logger.debug(
            f"Images in context for channel {discord_id}: {result}"
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

    async def enforce_text_rate_limits(
        self,
        channel_id: int,
        vendor_name: str = TEXT_VENDOR_NAME,
    ) -> bool:
        """Check if channel is within text rate limits.

        Args:
            channel_id: The Discord channel ID.
            vendor_name: The vendor name to check rate limits for.

        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        request_count = await self._repo.get_recent_text_request_count(
            channel_id, vendor_name
        )
        rate_limit = int(getenv("ANTHROPIC_RATE_LIMIT", "30"))

        if request_count < rate_limit:
            return True
        else:
            logger.warning("text_rate_limit_exceeded", channel_id=channel_id)
            return False

    async def enforce_image_rate_limits(
        self,
        channel_id: int,
        vendor_name: str = IMAGE_VENDOR_NAME,
    ) -> bool:
        """Check if channel is within image rate limits.

        Args:
            channel_id: The Discord channel ID.
            vendor_name: The vendor name to check rate limits for.

        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        request_count = await self._repo.get_recent_image_request_count(
            channel_id, vendor_name
        )
        rate_limit = int(getenv("FAL_RATE_LIMIT", "8"))

        if request_count < rate_limit:
            return True
        else:
            logger.warning("image_rate_limit_exceeded", channel_id=channel_id)
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

    # =========================================================================
    # Ban Management Methods
    # =========================================================================

    async def is_user_banned(self, user_id: int) -> bool:
        """Check if a user is banned.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            True if the user is banned, False otherwise.
        """
        return await self._repo.is_user_banned(user_id)

    async def get_ban_reason(self, user_id: int) -> str | None:
        """Get the ban reason for a user.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            The ban reason if the user is banned, None otherwise.
        """
        return await self._repo.get_ban_reason(user_id)

    async def add_ban(
        self,
        user_id: int,
        username: str,
        reason: str,
        performed_by: str,
    ) -> None:
        """Add a ban for a user.

        Args:
            user_id: The Discord user ID to ban.
            username: The Discord username (for display/audit purposes).
            reason: The reason for the ban.
            performed_by: The username of the person performing the ban.
        """
        await self._repo.add_ban(user_id, username, reason, performed_by)

    async def remove_ban(self, user_id: int, performed_by: str) -> None:
        """Remove a ban for a user.

        Args:
            user_id: The Discord user ID to unban.
            performed_by: The username of the person performing the unban.
        """
        await self._repo.remove_ban(user_id, performed_by)

    # =========================================================================
    # Preset Management Methods
    # =========================================================================

    async def list_presets(self, guild_id: str) -> list[dict[str, Any]]:
        """List all behavior presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            List of presets as dictionaries, ordered by name.
        """
        return await self._repo.list_presets(guild_id)

    async def get_preset(self, guild_id: str, name: str) -> dict[str, Any] | None:
        """Get a specific behavior preset by guild and name.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name.

        Returns:
            The preset as a dictionary, or None if not found.
        """
        return await self._repo.get_preset(guild_id, name)

    async def count_presets(self, guild_id: str) -> int:
        """Count the number of presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            The number of presets in the guild.
        """
        return await self._repo.count_presets(guild_id)

    async def create_preset(
        self,
        guild_id: str,
        name: str,
        description: str,
        prompt_text: str,
        created_by: str,
    ) -> None:
        """Create a new behavior preset.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name (must be unique within guild).
            description: A brief description of the preset.
            prompt_text: The full behavior prompt text.
            created_by: The Discord username who created the preset.
        """
        await self._repo.create_preset(guild_id, name, description, prompt_text, created_by)

    async def update_preset(
        self,
        guild_id: str,
        name: str,
        description: str | None = None,
        prompt_text: str | None = None,
    ) -> None:
        """Update an existing behavior preset.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name to update.
            description: New description (optional, None keeps existing).
            prompt_text: New prompt text (optional, None keeps existing).
        """
        await self._repo.update_preset(guild_id, name, description, prompt_text)

    async def delete_preset(self, guild_id: str, name: str) -> None:
        """Delete a behavior preset.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name to delete.
        """
        await self._repo.delete_preset(guild_id, name)

    # =========================================================================
    # Search Rejection Logging Methods
    # =========================================================================

    async def log_search_rejection(
        self,
        user_id: int,
        channel_id: int,
        guild_id: int | None,
        query_text: str,
        rejection_reason: str,
    ) -> None:
        """Log a search rejection for content screening.

        Records when a user's search query is rejected by the content
        screening system. This is used for auditing and analytics.

        Args:
            user_id: The Discord user ID who made the query.
            channel_id: The Discord channel ID where the query was made.
            guild_id: The Discord guild ID (None for DMs).
            query_text: The search query that was rejected.
            rejection_reason: The reason the query was rejected.
        """
        await self._repo.log_search_rejection(
            user_id, channel_id, guild_id, query_text, rejection_reason
        )

    # =========================================================================
    # Image Context Methods
    # =========================================================================

    async def get_image_source_urls_in_context(self, channel_id: int) -> set[str]:
        """Get source URLs of images currently in context for deduplication.

        This method extracts the source_url field from images in the channel's
        context. Only images that were added from external sources (like Google
        Image Search) will have a source_url field.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            Set of source URLs for images in context. Empty set if no images
            have source URLs.
        """
        images = await self.get_images(channel_id, "All Models")
        source_urls: set[str] = set()
        for img in images:
            if isinstance(img, dict) and "source_url" in img:
                source_urls.add(img["source_url"])
        return source_urls

    # =========================================================================
    # Usage Log Methods
    # =========================================================================

    async def log_command_usage(
        self,
        user_id: int,
        username: str,
        guild_id: int | None,
        command_name: str,
        command_type: str,
        outcome: str,
    ) -> None:
        """Log a command usage event.

        Records when a user invokes a command, its type, and outcome.
        Used for usage analytics and top user leaderboards.

        Args:
            user_id: The Discord user ID who invoked the command.
            username: The Discord username (for display/reporting).
            guild_id: The Discord guild ID (None for DMs).
            command_name: The command name (e.g., 'create_image', 'prompt').
            command_type: The command type ('image' or 'text').
            outcome: The outcome ('success', 'error', 'timeout', 'cancelled',
                'rate_limited').
        """
        await self._repo.log_command_usage(
            user_id, username, guild_id, command_name, command_type, outcome
        )

    async def get_top_users_by_usage(
        self,
        guild_id: int | None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get the top users by usage score.

        Returns users ranked by score, where score = (image_count * 5) + text_count.
        This weights image commands higher since they are more resource-intensive.

        Args:
            guild_id: The Discord guild ID to filter by (None for all guilds).
            limit: Maximum number of users to return (default 5).

        Returns:
            List of dicts with keys: user_id, username, image_count, text_count, score.
            Ordered by score descending.
        """
        return await self._repo.get_top_users_by_usage(guild_id, limit)

    async def get_user_usage_stats(
        self,
        user_id: int,
        guild_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Get usage statistics for a specific user.

        Args:
            user_id: The Discord user ID to get stats for.
            guild_id: The Discord guild ID to filter by (None for all guilds).

        Returns:
            Dict with keys: user_id, username, image_count, text_count, score.
            Returns None if the user has no usage records.
        """
        return await self._repo.get_user_usage_stats(user_id, guild_id)

    # =========================================================================
    # Whitelist Management Methods
    # =========================================================================

    async def is_user_whitelisted(self, user_id: int) -> bool:
        """Check if a user is whitelisted.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            True if the user is whitelisted, False otherwise.
        """
        return await self._repo.is_user_whitelisted(user_id)

    async def get_whitelist_entry(self, user_id: int) -> dict[str, Any] | None:
        """Get a whitelist entry for a user.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            The whitelist entry as a dictionary, or None if not found.
        """
        return await self._repo.get_whitelist_entry(user_id)

    async def add_to_whitelist(
        self,
        user_id: int,
        username: str,
        added_by: str,
        notes: str | None = None,
    ) -> None:
        """Add a user to the whitelist.

        Args:
            user_id: The Discord user ID to whitelist.
            username: The Discord username (for display purposes).
            added_by: Who whitelisted this user.
            notes: Optional notes about the user.
        """
        await self._repo.add_to_whitelist(user_id, username, added_by, notes)

    async def remove_from_whitelist(self, user_id: int) -> None:
        """Remove a user from the whitelist.

        Args:
            user_id: The Discord user ID to remove.
        """
        await self._repo.remove_from_whitelist(user_id)

    async def list_whitelist(self) -> list[dict[str, Any]]:
        """List all whitelisted users.

        Returns:
            List of whitelist entries as dictionaries, ordered by added_at desc.
        """
        return await self._repo.list_whitelist()
