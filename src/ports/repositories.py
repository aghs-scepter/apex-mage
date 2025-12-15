"""Repository protocols for data access.

This module defines the interfaces (Protocols) for data persistence operations.
Implementations can use SQLite, PostgreSQL, or any other storage backend.
All types are platform-agnostic (no Discord, Slack, or other client types).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Channel:
    """Represents a conversation channel/context.

    A channel is where conversations take place. In Discord this maps to a
    Discord channel, but the abstraction allows for other platforms.

    Attributes:
        id: Internal database ID for the channel.
        external_id: External platform ID (e.g., Discord channel ID).
    """

    id: int
    external_id: int


@dataclass
class Vendor:
    """Represents an AI vendor configuration.

    A vendor is an AI service provider (e.g., Anthropic, OpenAI) with an
    associated model configuration.

    Attributes:
        id: Internal database ID for the vendor.
        name: Human-readable vendor name (e.g., "anthropic", "openai").
        model_name: The model identifier or configuration (may be JSON).
    """

    id: int
    name: str
    model_name: str


@dataclass
class MessageImage:
    """Represents an image attached to a message.

    Attributes:
        url: URL where the image can be accessed.
        base64_data: Optional base64-encoded image data for inline images.
    """

    url: str
    base64_data: str | None = None


@dataclass
class Message:
    """Represents a conversation message.

    Messages include both user prompts and AI responses. They belong to a
    channel and are associated with a specific vendor.

    Attributes:
        id: Internal database ID for the message. None for new messages.
        channel_id: ID of the channel this message belongs to.
        vendor_id: ID of the vendor this message is associated with.
        message_type: Role of the message ("user" or "assistant").
        content: The text content of the message.
        timestamp: When the message was created.
        visible: Whether the message is active in the conversation context.
        is_image_prompt: Whether this message is an image generation prompt.
        images: List of images attached to this message.
    """

    channel_id: int
    vendor_id: int
    message_type: str
    content: str
    id: int | None = None
    timestamp: datetime | None = None
    visible: bool = True
    is_image_prompt: bool = False
    images: list[MessageImage] = field(default_factory=list)


# =============================================================================
# Repository Protocols
# =============================================================================


class ChannelRepository(Protocol):
    """Protocol for channel persistence operations.

    Implementations handle the storage and retrieval of conversation channels.
    """

    def get_channel(self, external_id: int) -> Channel | None:
        """Retrieve a channel by its external platform ID.

        Args:
            external_id: The external platform ID (e.g., Discord channel ID).

        Returns:
            The Channel if found, None otherwise.
        """
        ...

    def create_channel(self, external_id: int) -> Channel:
        """Create a new channel record.

        If a channel with the given external_id already exists, this method
        should return the existing channel without creating a duplicate.

        Args:
            external_id: The external platform ID for the channel.

        Returns:
            The created or existing Channel.
        """
        ...

    def get_or_create_channel(self, external_id: int) -> Channel:
        """Get an existing channel or create it if it doesn't exist.

        This is a convenience method that combines get_channel and create_channel.

        Args:
            external_id: The external platform ID for the channel.

        Returns:
            The existing or newly created Channel.
        """
        ...


class VendorRepository(Protocol):
    """Protocol for vendor persistence operations.

    Implementations handle the storage and retrieval of AI vendor configurations.
    """

    def get_vendor(self, name: str) -> Vendor | None:
        """Retrieve a vendor by its name.

        Args:
            name: The vendor name (e.g., "anthropic").

        Returns:
            The Vendor if found, None otherwise.
        """
        ...

    def create_vendor(self, name: str, model_name: str) -> Vendor:
        """Create a new vendor record.

        If a vendor with the given name already exists, this method should
        return the existing vendor without creating a duplicate.

        Args:
            name: The vendor name.
            model_name: The model identifier or configuration.

        Returns:
            The created or existing Vendor.
        """
        ...

    def get_or_create_vendor(self, name: str, model_name: str) -> Vendor:
        """Get an existing vendor or create it if it doesn't exist.

        Args:
            name: The vendor name.
            model_name: The model identifier (used only if creating).

        Returns:
            The existing or newly created Vendor.
        """
        ...


class MessageRepository(Protocol):
    """Protocol for message persistence operations.

    Implementations handle the storage and retrieval of conversation messages.
    Messages can include text content and optional image attachments.
    """

    def save_message(self, message: Message) -> int:
        """Save a message to the repository.

        For new messages (id=None), creates a new record.
        For existing messages (id is set), updates the record.

        Args:
            message: The message to save.

        Returns:
            The ID of the saved message.
        """
        ...

    def save_message_with_images(
        self,
        message: Message,
        image_urls: list[str],
    ) -> int:
        """Save a message with associated image URLs.

        This is a convenience method for saving messages that have image
        attachments (e.g., AI-generated images).

        Args:
            message: The message to save.
            image_urls: List of image URLs to attach to the message.

        Returns:
            The ID of the saved message.
        """
        ...

    def get_visible_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> list[Message]:
        """Get all visible (active) messages for a channel and vendor.

        Returns messages that are currently part of the conversation context.
        Messages that have been deactivated or soft-deleted are excluded.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.

        Returns:
            List of visible messages in chronological order.
        """
        ...

    def get_latest_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent messages for a channel and vendor.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.
            limit: Maximum number of messages to return.

        Returns:
            List of recent messages in chronological order (oldest first).
        """
        ...

    def get_latest_images(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent image messages for a channel and vendor.

        Returns messages that are image prompts or contain image attachments.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.
            limit: Maximum number of image messages to return.

        Returns:
            List of recent image messages in chronological order.
        """
        ...

    def has_images_in_context(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> bool:
        """Check if the channel's context contains any images.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.

        Returns:
            True if at least one image exists in the context, False otherwise.
        """
        ...

    def deactivate_old_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        window_size: int,
    ) -> None:
        """Mark messages outside the context window as inactive.

        Messages older than the window are set to visible=False, removing them
        from the active conversation context while preserving them for history.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.
            window_size: Number of recent messages to keep active.
        """
        ...

    def clear_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> None:
        """Soft-delete all messages for a channel and vendor.

        This resets the conversation context by marking all messages as
        invisible. The messages are preserved in the database for auditing.

        Args:
            channel_external_id: The external platform ID for the channel.
            vendor_name: The vendor name to filter by.
        """
        ...


class RateLimitRepository(Protocol):
    """Protocol for rate limiting data operations.

    Implementations track request counts for enforcing rate limits.
    """

    def get_recent_text_request_count(self, channel_external_id: int) -> int:
        """Get the count of recent text requests for a channel.

        The definition of "recent" is implementation-specific (e.g., last hour).

        Args:
            channel_external_id: The external platform ID for the channel.

        Returns:
            Number of recent text requests.
        """
        ...

    def get_recent_image_request_count(self, channel_external_id: int) -> int:
        """Get the count of recent image requests for a channel.

        The definition of "recent" is implementation-specific (e.g., last hour).

        Args:
            channel_external_id: The external platform ID for the channel.

        Returns:
            Number of recent image requests.
        """
        ...
