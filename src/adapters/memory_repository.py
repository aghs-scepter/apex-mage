"""In-memory implementation of repository protocols for testing.

This module provides an in-memory implementation of all repository protocols:
- AsyncChannelRepository
- AsyncVendorRepository
- AsyncMessageRepository
- AsyncRateLimitRepository
- AsyncApiKeyRepository

All data is stored in memory using dictionaries and lists.
This adapter is designed for testing: fast, isolated, and no persistence.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from src.ports.repositories import (
    ApiKey,
    Channel,
    Message,
    MessageImage,
    Vendor,
)


class MemoryRepository:
    """In-memory implementation of all repository protocols.

    This class implements AsyncChannelRepository, AsyncVendorRepository,
    AsyncMessageRepository, AsyncRateLimitRepository, and AsyncApiKeyRepository.
    All data is stored in memory and is lost when the instance is destroyed.

    The class supports async context manager protocol for compatibility with
    SQLiteRepository, but no actual resources need to be managed.

    Example:
        async with MemoryRepository() as repo:
            channel = await repo.get_or_create_channel(12345)
            await repo.save_message(message)

    For testing without context manager:
        repo = MemoryRepository()
        await repo.connect()
        # ... use repo ...
    """

    def __init__(self) -> None:
        """Initialize the repository with empty data structures."""
        self._connected: bool = False

        # Channel storage: external_id -> Channel
        self._channels: dict[int, Channel] = {}
        self._channel_id_counter: int = 1

        # Vendor storage: name -> Vendor
        self._vendors: dict[str, Vendor] = {}
        self._vendor_id_counter: int = 1

        # Message storage: list of all messages
        self._messages: list[Message] = []
        self._message_id_counter: int = 1

        # API Key storage: key_hash -> ApiKey
        self._api_keys: dict[str, ApiKey] = {}
        self._api_key_id_counter: int = 1

        # Ban storage: user_id -> (username, reason, created_at)
        self._bans: dict[int, tuple[str, str, datetime]] = {}
        self._ban_history: list[dict[str, Any]] = []

        # Behavior presets: (guild_id, name) -> preset dict
        self._presets: dict[tuple[str, str], dict[str, Any]] = {}
        self._preset_id_counter: int = 1

        # Search rejections: list of rejection records
        self._search_rejections: list[dict[str, Any]] = []
        self._search_rejection_id_counter: int = 1

        # Prompt refinements: list of refinement records
        self._prompt_refinements: list[dict[str, Any]] = []

        # Usage log: list of command usage records
        self._usage_log: list[dict[str, Any]] = []
        self._usage_log_id_counter: int = 1

        # Whitelist storage: user_id -> whitelist entry dict
        self._whitelist: dict[int, dict[str, Any]] = {}

    async def __aenter__(self) -> "MemoryRepository":
        """Async context manager entry: connect to the repository."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit: close the repository."""
        await self.close()

    async def connect(self) -> None:
        """Connect to the repository (no-op for in-memory).

        This method exists for API compatibility with SQLiteRepository.
        """
        self._connected = True

    async def close(self) -> None:
        """Close the repository (no-op for in-memory).

        This method exists for API compatibility with SQLiteRepository.
        """
        self._connected = False

    def _ensure_connected(self) -> None:
        """Ensure the repository is connected."""
        if not self._connected:
            raise RuntimeError(
                "Repository not connected. Call connect() or use async context manager."
            )

    def _now(self) -> datetime:
        """Get the current UTC timestamp."""
        return datetime.now(UTC)

    # =========================================================================
    # AsyncChannelRepository Implementation
    # =========================================================================

    async def get_channel(self, external_id: int) -> Channel | None:
        """Retrieve a channel by its external platform ID."""
        self._ensure_connected()
        return self._channels.get(external_id)

    async def create_channel(self, external_id: int) -> Channel:
        """Create a new channel record.

        If channel already exists, returns the existing one.
        """
        self._ensure_connected()
        existing = self._channels.get(external_id)
        if existing is not None:
            return existing

        channel = Channel(id=self._channel_id_counter, external_id=external_id)
        self._channels[external_id] = channel
        self._channel_id_counter += 1
        return channel

    async def get_or_create_channel(self, external_id: int) -> Channel:
        """Get an existing channel or create it if it doesn't exist."""
        return await self.create_channel(external_id)

    # =========================================================================
    # AsyncVendorRepository Implementation
    # =========================================================================

    async def get_vendor(self, name: str) -> Vendor | None:
        """Retrieve a vendor by its name."""
        self._ensure_connected()
        return self._vendors.get(name)

    async def create_vendor(self, name: str, model_name: str) -> Vendor:
        """Create a new vendor record.

        If vendor already exists, returns the existing one.
        """
        self._ensure_connected()
        existing = self._vendors.get(name)
        if existing is not None:
            return existing

        vendor = Vendor(id=self._vendor_id_counter, name=name, model_name=model_name)
        self._vendors[name] = vendor
        self._vendor_id_counter += 1
        return vendor

    async def get_or_create_vendor(self, name: str, model_name: str) -> Vendor:
        """Get an existing vendor or create it if it doesn't exist."""
        return await self.create_vendor(name, model_name)

    # =========================================================================
    # AsyncMessageRepository Implementation
    # =========================================================================

    def _get_vendor_name_by_id(self, vendor_id: int) -> str | None:
        """Look up vendor name by vendor ID."""
        for vendor in self._vendors.values():
            if vendor.id == vendor_id:
                return vendor.name
        return None

    def _get_channel_id_by_external_id(self, external_id: int) -> int | None:
        """Look up internal channel ID by external ID."""
        channel = self._channels.get(external_id)
        return channel.id if channel else None

    def _matches_vendor(self, vendor_name: str, filter_vendor: str) -> bool:
        """Check if a vendor name matches the filter (including 'All Models')."""
        return filter_vendor == "All Models" or vendor_name == filter_vendor

    async def save_message(self, message: Message) -> int:
        """Save a message to the repository."""
        self._ensure_connected()

        # Look up vendor name from vendor_id
        vendor_name = self._get_vendor_name_by_id(message.vendor_id)
        if vendor_name is None:
            raise ValueError(f"Vendor with id {message.vendor_id} not found")

        # Create new message with ID and timestamp
        new_message = replace(
            message,
            id=self._message_id_counter,
            timestamp=self._now() if message.timestamp is None else message.timestamp,
        )
        self._messages.append(new_message)
        self._message_id_counter += 1

        return new_message.id  # type: ignore[return-value]

    async def save_message_with_images(
        self,
        message: Message,
        image_urls: list[str],
    ) -> int:
        """Save a message with associated image URLs."""
        self._ensure_connected()

        # Look up vendor name from vendor_id
        vendor_name = self._get_vendor_name_by_id(message.vendor_id)
        if vendor_name is None:
            raise ValueError(f"Vendor with id {message.vendor_id} not found")

        # Create images from URLs
        images = [MessageImage(url=url) for url in image_urls]

        # Create new message with ID, timestamp, and images
        new_message = replace(
            message,
            id=self._message_id_counter,
            timestamp=self._now() if message.timestamp is None else message.timestamp,
            images=images,
        )
        self._messages.append(new_message)
        self._message_id_counter += 1

        return new_message.id  # type: ignore[return-value]

    async def get_visible_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> list[Message]:
        """Get all visible (active) messages for a channel and vendor."""
        self._ensure_connected()

        channel_id = self._get_channel_id_by_external_id(channel_external_id)
        if channel_id is None:
            return []

        # Filter messages by channel, vendor, visibility, and not image prompts
        result = []
        for msg in self._messages:
            # channel_id in message is actually external_id (matches SQLite behavior)
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name is None:
                continue

            if not self._matches_vendor(msg_vendor_name, vendor_name):
                continue

            if not msg.visible:
                continue

            if msg.is_image_prompt:
                continue

            if msg.is_image_only_context:
                continue

            result.append(msg)

        # Sort by timestamp
        result.sort(key=lambda m: m.timestamp or datetime.min.replace(tzinfo=UTC))
        return result

    async def get_latest_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent messages for a channel and vendor.

        Note: Despite the name, this matches SQLite behavior which returns
        the first N messages ordered by timestamp ascending (not the most recent).
        """
        self._ensure_connected()

        # Get visible messages and take the first N (matching SQLite behavior)
        visible = await self.get_visible_messages(channel_external_id, vendor_name)
        return visible[:limit] if limit > 0 else visible

    async def get_latest_images(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent image messages for a channel and vendor."""
        self._ensure_connected()

        channel_id = self._get_channel_id_by_external_id(channel_external_id)
        if channel_id is None:
            return []

        # Filter messages that have images
        result = []
        for msg in self._messages:
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name is None:
                continue

            if not self._matches_vendor(msg_vendor_name, vendor_name):
                continue

            if not msg.visible:
                continue

            if msg.is_image_prompt:
                continue

            if not msg.images:
                continue

            result.append(msg)

        # Sort by timestamp descending and take limit
        result.sort(key=lambda m: m.timestamp or datetime.min.replace(tzinfo=UTC), reverse=True)
        return result[:limit]

    async def has_images_in_context(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> bool:
        """Check if the channel's context contains any images."""
        images = await self.get_latest_images(channel_external_id, vendor_name, 1)
        return len(images) > 0

    async def deactivate_old_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        window_size: int,
    ) -> None:
        """Mark messages outside the context window as inactive."""
        self._ensure_connected()

        # Get all visible messages for this channel/vendor
        visible_messages = []
        for i, msg in enumerate(self._messages):
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name is None:
                continue

            if not self._matches_vendor(msg_vendor_name, vendor_name):
                continue

            if msg.visible:
                visible_messages.append((i, msg))

        # Sort by timestamp descending, then by id descending
        visible_messages.sort(
            key=lambda x: (x[1].timestamp or datetime.min.replace(tzinfo=UTC), x[1].id or 0),
            reverse=True,
        )

        # Mark messages beyond window_size as invisible
        for idx, (list_index, msg) in enumerate(visible_messages):
            if idx >= window_size:
                self._messages[list_index] = replace(msg, visible=False)

    async def clear_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> None:
        """Soft-delete all messages for a channel and vendor."""
        self._ensure_connected()

        for i, msg in enumerate(self._messages):
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name is None:
                continue

            if not self._matches_vendor(msg_vendor_name, vendor_name):
                continue

            self._messages[i] = replace(msg, visible=False)

    async def deactivate_image_messages(
        self,
        channel_external_id: int,
        message_ids: list[int],
    ) -> None:
        """Soft-delete specific image messages by their IDs.

        Used to enforce the carousel image limit by deactivating the oldest
        image messages when new images push the count over the limit.

        Args:
            channel_external_id: The Discord channel ID (used for logging).
            message_ids: List of message IDs to deactivate.
        """
        if not message_ids:
            return

        self._ensure_connected()
        message_id_set = set(message_ids)

        for i, msg in enumerate(self._messages):
            if msg.id in message_id_set:
                self._messages[i] = replace(msg, visible=False)

    # =========================================================================
    # AsyncRateLimitRepository Implementation
    # =========================================================================

    async def get_recent_text_request_count(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> int:
        """Get the count of recent text requests for a channel and vendor."""
        self._ensure_connected()

        one_hour_ago = self._now() - timedelta(hours=1)
        count = 0

        for msg in self._messages:
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name != vendor_name:
                continue

            if msg.message_type != "prompt":
                continue

            # Check timestamp is within last hour
            if msg.timestamp is None:
                continue
            msg_ts = msg.timestamp
            if msg_ts.tzinfo is None:
                msg_ts = msg_ts.replace(tzinfo=UTC)
            if msg_ts < one_hour_ago:
                continue

            count += 1

        return count

    async def get_recent_image_request_count(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> int:
        """Get the count of recent image requests for a channel and vendor."""
        self._ensure_connected()

        one_hour_ago = self._now() - timedelta(hours=1)
        count = 0

        for msg in self._messages:
            if msg.channel_id != channel_external_id:
                continue

            msg_vendor_name = self._get_vendor_name_by_id(msg.vendor_id)
            if msg_vendor_name != vendor_name:
                continue

            if msg.message_type != "prompt":
                continue

            if not msg.is_image_prompt:
                continue

            # Check timestamp is within last hour
            if msg.timestamp is None:
                continue
            msg_ts = msg.timestamp
            if msg_ts.tzinfo is None:
                msg_ts = msg_ts.replace(tzinfo=UTC)
            if msg_ts < one_hour_ago:
                continue

            count += 1

        return count

    # =========================================================================
    # AsyncApiKeyRepository Implementation
    # =========================================================================

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Retrieve an API key by its hash."""
        self._ensure_connected()

        api_key = self._api_keys.get(key_hash)
        if api_key is None:
            return None

        # Check if active
        if not api_key.is_active:
            return None

        # Check if expired
        if api_key.expires_at is not None:
            expires_at = api_key.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= self._now():
                return None

        return api_key

    async def create(self, api_key: ApiKey) -> ApiKey:
        """Create a new API key record."""
        self._ensure_connected()

        # Create with ID and created_at
        new_key = ApiKey(
            id=self._api_key_id_counter,
            key_hash=api_key.key_hash,
            user_id=api_key.user_id,
            name=api_key.name,
            scopes=api_key.scopes,
            created_at=api_key.created_at or self._now(),
            last_used_at=api_key.last_used_at,
            expires_at=api_key.expires_at,
            is_active=api_key.is_active,
        )

        self._api_keys[api_key.key_hash] = new_key
        self._api_key_id_counter += 1

        return new_key

    async def update_last_used(self, key_hash: str) -> None:
        """Update the last_used_at timestamp for an API key."""
        self._ensure_connected()

        if key_hash in self._api_keys:
            old_key = self._api_keys[key_hash]
            self._api_keys[key_hash] = ApiKey(
                id=old_key.id,
                key_hash=old_key.key_hash,
                user_id=old_key.user_id,
                name=old_key.name,
                scopes=old_key.scopes,
                created_at=old_key.created_at,
                last_used_at=self._now(),
                expires_at=old_key.expires_at,
                is_active=old_key.is_active,
            )

    async def revoke(self, key_hash: str) -> bool:
        """Revoke an API key by setting is_active to False."""
        self._ensure_connected()

        if key_hash not in self._api_keys:
            return False

        old_key = self._api_keys[key_hash]
        self._api_keys[key_hash] = ApiKey(
            id=old_key.id,
            key_hash=old_key.key_hash,
            user_id=old_key.user_id,
            name=old_key.name,
            scopes=old_key.scopes,
            created_at=old_key.created_at,
            last_used_at=old_key.last_used_at,
            expires_at=old_key.expires_at,
            is_active=False,
        )
        return True

    # =========================================================================
    # BanRepository Implementation
    # =========================================================================

    async def is_user_banned(self, user_id: int) -> bool:
        """Check if a user is banned.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            True if the user is banned, False otherwise.
        """
        self._ensure_connected()
        return user_id in self._bans

    async def get_ban_reason(self, user_id: int) -> str | None:
        """Get the ban reason for a user.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            The ban reason if the user is banned, None otherwise.
        """
        self._ensure_connected()
        ban_info = self._bans.get(user_id)
        if ban_info is None:
            return None
        return ban_info[1]  # (username, reason, created_at)

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
        self._ensure_connected()

        self._bans[user_id] = (username, reason, self._now())
        self._ban_history.append({
            "user_id": user_id,
            "username": username,
            "action": "ban",
            "reason": reason,
            "performed_by": performed_by,
            "performed_at": self._now(),
        })

    async def remove_ban(self, user_id: int, performed_by: str) -> None:
        """Remove a ban for a user.

        Args:
            user_id: The Discord user ID to unban.
            performed_by: The username of the person performing the unban.
        """
        self._ensure_connected()

        username = "unknown"
        if user_id in self._bans:
            username = self._bans[user_id][0]  # Get username from ban record
            del self._bans[user_id]

        self._ban_history.append({
            "user_id": user_id,
            "username": username,
            "action": "unban",
            "reason": None,
            "performed_by": performed_by,
            "performed_at": self._now(),
        })

    # =========================================================================
    # BehaviorPresetRepository Implementation
    # =========================================================================

    async def get_preset(self, guild_id: str, name: str) -> dict[str, Any] | None:
        """Get a specific behavior preset by guild and name.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name.

        Returns:
            The preset as a dictionary, or None if not found.
        """
        self._ensure_connected()
        return self._presets.get((guild_id, name))

    async def list_presets(self, guild_id: str) -> list[dict[str, Any]]:
        """List all behavior presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            List of presets as dictionaries, ordered by name.
        """
        self._ensure_connected()

        result = [
            preset
            for (gid, _), preset in self._presets.items()
            if gid == guild_id
        ]
        result.sort(key=lambda p: p.get("name", ""))
        return result

    async def count_presets(self, guild_id: str) -> int:
        """Count the number of presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            The number of presets in the guild.
        """
        self._ensure_connected()
        return sum(1 for (gid, _) in self._presets if gid == guild_id)

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
            created_by: The Discord user ID who created the preset.
        """
        self._ensure_connected()

        preset = {
            "id": self._preset_id_counter,
            "guild_id": guild_id,
            "name": name,
            "description": description,
            "prompt_text": prompt_text,
            "created_by": created_by,
            "created_at": self._now().isoformat(),
        }
        self._presets[(guild_id, name)] = preset
        self._preset_id_counter += 1

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
        self._ensure_connected()

        key = (guild_id, name)
        if key not in self._presets:
            return

        preset = self._presets[key]
        if description is not None:
            preset["description"] = description
        if prompt_text is not None:
            preset["prompt_text"] = prompt_text

    async def delete_preset(self, guild_id: str, name: str) -> None:
        """Delete a behavior preset.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name to delete.
        """
        self._ensure_connected()

        key = (guild_id, name)
        if key in self._presets:
            del self._presets[key]

    # =========================================================================
    # SearchRejectionRepository Implementation
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
        self._ensure_connected()

        self._search_rejections.append({
            "id": self._search_rejection_id_counter,
            "user_id": user_id,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "query_text": query_text,
            "rejection_reason": rejection_reason,
            "created_at": self._now().isoformat(),
        })
        self._search_rejection_id_counter += 1

    # =========================================================================
    # PromptRefinementRepository Implementation
    # =========================================================================

    async def save_prompt_refinement(
        self,
        channel_id: int,
        user_id: int,
        original_prompt: str,
        refined_prompt: str,
        refinement_type: str,
        was_used: bool,
    ) -> None:
        """Save a prompt refinement record for analytics.

        Records when a user's prompt is refined by AI assistance and whether
        the user chose to use the refined version.

        Args:
            channel_id: The Discord channel ID where the refinement occurred.
            user_id: The Discord user ID who triggered the refinement.
            original_prompt: The user's original prompt text.
            refined_prompt: The AI-refined prompt text.
            refinement_type: Type of refinement ('create_image', 'modify_image',
                or 'describe_this').
            was_used: Whether the user selected the refined version.
        """
        self._ensure_connected()

        self._prompt_refinements.append({
            "channel_id": channel_id,
            "user_id": user_id,
            "original_prompt": original_prompt,
            "refined_prompt": refined_prompt,
            "refinement_type": refinement_type,
            "was_used": was_used,
            "created_at": self._now().isoformat(),
        })

    async def get_refinement_stats(self) -> dict[str, dict[str, int]]:
        """Get aggregated statistics on prompt refinements.

        Returns counts grouped by refinement type, including total count
        and how many refinements were actually used by users.

        Returns:
            Dictionary mapping refinement_type to stats dict with keys:
            - 'total': Total number of refinements of this type
            - 'used': Number of refinements that were actually used
            - 'usage_rate': Percentage of refinements used (0-100)

            Example:
            {
                'create_image': {'total': 100, 'used': 75, 'usage_rate': 75},
                'modify_image': {'total': 50, 'used': 30, 'usage_rate': 60},
            }
        """
        self._ensure_connected()

        # Aggregate counts by refinement_type
        type_counts: dict[str, dict[str, int]] = {}

        for refinement in self._prompt_refinements:
            rtype = refinement["refinement_type"]
            if rtype not in type_counts:
                type_counts[rtype] = {"total": 0, "used": 0}

            type_counts[rtype]["total"] += 1
            if refinement["was_used"]:
                type_counts[rtype]["used"] += 1

        # Calculate usage_rate for each type
        stats: dict[str, dict[str, int]] = {}
        for rtype, counts in type_counts.items():
            total = counts["total"]
            used = counts["used"]
            usage_rate = round((used / total) * 100) if total > 0 else 0
            stats[rtype] = {
                "total": total,
                "used": used,
                "usage_rate": usage_rate,
            }

        return stats

    # =========================================================================
    # UsageLogRepository Implementation
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
        self._ensure_connected()

        self._usage_log.append({
            "id": self._usage_log_id_counter,
            "user_id": user_id,
            "username": username,
            "guild_id": guild_id,
            "command_name": command_name,
            "command_type": command_type,
            "outcome": outcome,
            "timestamp": self._now().isoformat(),
        })
        self._usage_log_id_counter += 1

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
        self._ensure_connected()

        # Aggregate by user
        user_stats: dict[int, dict[str, Any]] = {}

        for entry in self._usage_log:
            # Filter by guild_id if specified
            if guild_id is not None and entry["guild_id"] != guild_id:
                continue

            uid = entry["user_id"]
            if uid not in user_stats:
                user_stats[uid] = {
                    "user_id": uid,
                    "username": entry["username"],
                    "image_count": 0,
                    "text_count": 0,
                }

            if entry["command_type"] == "image":
                user_stats[uid]["image_count"] += 1
            else:
                user_stats[uid]["text_count"] += 1

        # Calculate scores and sort
        result = list(user_stats.values())
        for user in result:
            user["score"] = (user["image_count"] * 5) + user["text_count"]

        result.sort(key=lambda u: u["score"], reverse=True)
        return result[:limit]

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
        self._ensure_connected()

        image_count = 0
        text_count = 0
        username = None

        for entry in self._usage_log:
            if entry["user_id"] != user_id:
                continue
            if guild_id is not None and entry["guild_id"] != guild_id:
                continue

            username = entry["username"]
            if entry["command_type"] == "image":
                image_count += 1
            else:
                text_count += 1

        if username is None:
            return None

        return {
            "user_id": user_id,
            "username": username,
            "image_count": image_count,
            "text_count": text_count,
            "score": (image_count * 5) + text_count,
        }

    # =========================================================================
    # WhitelistRepository Implementation
    # =========================================================================

    async def is_user_whitelisted(self, user_id: int) -> bool:
        """Check if a user is whitelisted.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            True if the user is whitelisted, False otherwise.
        """
        self._ensure_connected()
        return user_id in self._whitelist

    async def get_whitelist_entry(self, user_id: int) -> dict[str, Any] | None:
        """Get a whitelist entry for a user.

        Args:
            user_id: The Discord user ID to check.

        Returns:
            The whitelist entry as a dictionary, or None if not found.
        """
        self._ensure_connected()
        return self._whitelist.get(user_id)

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
        self._ensure_connected()
        self._whitelist[user_id] = {
            "user_id": user_id,
            "username": username,
            "added_by": added_by,
            "added_at": self._now().isoformat(),
            "notes": notes,
        }

    async def remove_from_whitelist(self, user_id: int) -> None:
        """Remove a user from the whitelist.

        Args:
            user_id: The Discord user ID to remove.
        """
        self._ensure_connected()
        if user_id in self._whitelist:
            del self._whitelist[user_id]

    async def list_whitelist(self) -> list[dict[str, Any]]:
        """List all whitelisted users.

        Returns:
            List of whitelist entries as dictionaries, ordered by added_at desc.
        """
        self._ensure_connected()
        entries = list(self._whitelist.values())
        # Sort by added_at descending
        entries.sort(key=lambda e: e.get("added_at", ""), reverse=True)
        return entries

    # =========================================================================
    # Testing Utilities
    # =========================================================================

    def reset(self) -> None:
        """Reset all data in the repository.

        This is useful for isolating tests from each other.
        """
        self._channels.clear()
        self._channel_id_counter = 1

        self._vendors.clear()
        self._vendor_id_counter = 1

        self._messages.clear()
        self._message_id_counter = 1

        self._api_keys.clear()
        self._api_key_id_counter = 1

        self._bans.clear()
        self._ban_history.clear()

        self._presets.clear()
        self._preset_id_counter = 1

        self._search_rejections.clear()
        self._search_rejection_id_counter = 1

        self._prompt_refinements.clear()

        self._usage_log.clear()
        self._usage_log_id_counter = 1
