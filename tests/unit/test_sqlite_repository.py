"""Unit tests for SQLiteRepository implementation.

This module contains comprehensive tests for the SQLiteRepository class,
which implements ChannelRepository, VendorRepository, MessageRepository,
and RateLimitRepository protocols.

All tests use an in-memory SQLite database for isolation and speed.
"""

import pytest
import pytest_asyncio

from src.adapters.sqlite_repository import SQLiteRepository
from src.ports.repositories import (
    Channel,
    Message,
    Vendor,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def repo() -> SQLiteRepository:
    """Provides a clean in-memory SQLite repository for each test.

    The repository is connected and schema is initialized before yielding.
    Connection is automatically closed after the test completes.

    Yields:
        SQLiteRepository: A fresh repository instance with empty database.
    """
    async with SQLiteRepository(":memory:") as repository:
        yield repository


@pytest_asyncio.fixture
async def repo_with_channel_and_vendor(repo: SQLiteRepository) -> SQLiteRepository:
    """Provides a repository with a pre-created channel and vendor.

    Creates:
        - Channel with external_id=12345
        - Vendor "Anthropic" with model "claude-3-sonnet"

    Yields:
        SQLiteRepository: Repository with test data.
    """
    await repo.create_channel(12345)
    await repo.create_vendor("Anthropic", "claude-3-sonnet")
    return repo


# =============================================================================
# ChannelRepository Tests
# =============================================================================


class TestChannelRepository:
    """Tests for ChannelRepository methods."""

    async def test_create_channel(self, repo: SQLiteRepository) -> None:
        """Test that create_channel creates a new channel successfully."""
        channel = await repo.create_channel(12345)

        assert isinstance(channel, Channel)
        assert channel.id == 1  # First channel gets ID 1
        assert channel.external_id == 12345

    async def test_create_channel_returns_existing(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that create_channel returns existing channel if it exists."""
        channel1 = await repo.create_channel(12345)
        channel2 = await repo.create_channel(12345)

        # Should return same channel, not create a duplicate
        assert channel1.id == channel2.id
        assert channel1.external_id == channel2.external_id

    async def test_get_channel_exists(self, repo: SQLiteRepository) -> None:
        """Test that get_channel returns channel when it exists."""
        created = await repo.create_channel(12345)
        retrieved = await repo.get_channel(12345)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.external_id == 12345

    async def test_get_channel_not_exists(self, repo: SQLiteRepository) -> None:
        """Test that get_channel returns None when channel doesn't exist."""
        result = await repo.get_channel(99999)

        assert result is None

    async def test_get_or_create_channel_creates(self, repo: SQLiteRepository) -> None:
        """Test that get_or_create_channel creates when channel is missing."""
        # Verify channel doesn't exist
        assert await repo.get_channel(12345) is None

        channel = await repo.get_or_create_channel(12345)

        assert isinstance(channel, Channel)
        assert channel.external_id == 12345

    async def test_get_or_create_channel_gets(self, repo: SQLiteRepository) -> None:
        """Test that get_or_create_channel returns existing channel."""
        created = await repo.create_channel(12345)
        retrieved = await repo.get_or_create_channel(12345)

        assert retrieved.id == created.id


# =============================================================================
# VendorRepository Tests
# =============================================================================


class TestVendorRepository:
    """Tests for VendorRepository methods."""

    async def test_create_vendor(self, repo: SQLiteRepository) -> None:
        """Test that create_vendor creates a new vendor successfully."""
        vendor = await repo.create_vendor("Anthropic", "claude-3-sonnet")

        assert isinstance(vendor, Vendor)
        assert vendor.id == 1  # First vendor gets ID 1
        assert vendor.name == "Anthropic"
        assert vendor.model_name == "claude-3-sonnet"

    async def test_create_vendor_returns_existing(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that create_vendor returns existing vendor if it exists."""
        vendor1 = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        vendor2 = await repo.create_vendor("Anthropic", "claude-3-opus")

        # Should return same vendor, not create a duplicate
        # Note: model_name from second call is ignored
        assert vendor1.id == vendor2.id
        assert vendor1.name == vendor2.name

    async def test_get_vendor_exists(self, repo: SQLiteRepository) -> None:
        """Test that get_vendor returns vendor when it exists."""
        created = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        retrieved = await repo.get_vendor("Anthropic")

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Anthropic"
        assert retrieved.model_name == "claude-3-sonnet"

    async def test_get_vendor_not_exists(self, repo: SQLiteRepository) -> None:
        """Test that get_vendor returns None when vendor doesn't exist."""
        result = await repo.get_vendor("NonExistent")

        assert result is None

    async def test_get_or_create_vendor_creates(self, repo: SQLiteRepository) -> None:
        """Test that get_or_create_vendor creates when vendor is missing."""
        # Verify vendor doesn't exist
        assert await repo.get_vendor("Anthropic") is None

        vendor = await repo.get_or_create_vendor("Anthropic", "claude-3-sonnet")

        assert isinstance(vendor, Vendor)
        assert vendor.name == "Anthropic"
        assert vendor.model_name == "claude-3-sonnet"

    async def test_get_or_create_vendor_gets(self, repo: SQLiteRepository) -> None:
        """Test that get_or_create_vendor returns existing vendor."""
        created = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        retrieved = await repo.get_or_create_vendor("Anthropic", "different-model")

        assert retrieved.id == created.id
        assert retrieved.model_name == "claude-3-sonnet"  # Original model preserved


# =============================================================================
# MessageRepository Tests
# =============================================================================


class TestMessageRepository:
    """Tests for MessageRepository methods."""

    async def test_save_message(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that save_message saves and can be retrieved."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        message = Message(
            channel_id=12345,  # external_id
            vendor_id=vendor.id,
            message_type="prompt",
            content="Hello, Claude!",
        )
        message_id = await repo.save_message(message)

        assert message_id > 0

        # Verify message was saved by retrieving it
        messages = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages) == 1
        assert messages[0].content == "Hello, Claude!"
        assert messages[0].message_type == "prompt"

    async def test_save_message_with_images(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that save_message_with_images saves with image data."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        message = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="response",
            content="Here are some images.",
        )
        image_urls = [
            "https://example.com/image1.png",
            "https://example.com/image2.png",
        ]
        message_id = await repo.save_message_with_images(message, image_urls)

        assert message_id > 0

        # Verify message and images were saved
        messages = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages) == 1
        assert len(messages[0].images) == 2
        assert messages[0].images[0].url == "https://example.com/image1.png"
        assert messages[0].images[1].url == "https://example.com/image2.png"

    async def test_get_visible_messages(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that get_visible_messages returns active messages."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save multiple messages
        for i in range(3):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt" if i % 2 == 0 else "response",
                content=f"Message {i}",
            )
            await repo.save_message(msg)

        messages = await repo.get_visible_messages(12345, "Anthropic")

        assert len(messages) == 3
        # Messages should be in chronological order
        assert messages[0].content == "Message 0"
        assert messages[1].content == "Message 1"
        assert messages[2].content == "Message 2"

    async def test_get_visible_messages_excludes_inactive(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that get_visible_messages doesn't return deactivated messages."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save 5 messages
        for i in range(5):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Message {i}",
            )
            await repo.save_message(msg)

        # Deactivate old messages, keeping only 2
        await repo.deactivate_old_messages(12345, "Anthropic", window_size=2)

        messages = await repo.get_visible_messages(12345, "Anthropic")

        # Should only return 2 most recent messages
        assert len(messages) == 2
        assert messages[0].content == "Message 3"
        assert messages[1].content == "Message 4"

    async def test_get_latest_messages_respects_limit(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that get_latest_messages respects the limit parameter."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save 10 messages
        for i in range(10):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Message {i}",
            )
            await repo.save_message(msg)

        messages = await repo.get_latest_messages(12345, "Anthropic", limit=3)

        assert len(messages) == 3

    async def test_get_latest_images(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that get_latest_images only returns messages with images."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save message without images
        msg_no_images = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="prompt",
            content="No images here",
        )
        await repo.save_message(msg_no_images)

        # Save message with images
        msg_with_images = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="response",
            content="Here are images",
        )
        await repo.save_message_with_images(
            msg_with_images,
            ["https://example.com/image.png"],
        )

        # Save another message without images
        msg_no_images2 = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="prompt",
            content="Also no images",
        )
        await repo.save_message(msg_no_images2)

        images = await repo.get_latest_images(12345, "Anthropic", limit=10)

        assert len(images) == 1
        assert images[0].content == "Here are images"
        assert len(images[0].images) == 1

    async def test_has_images_in_context_true(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that has_images_in_context returns True when images exist."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        msg = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="response",
            content="Image response",
        )
        await repo.save_message_with_images(msg, ["https://example.com/image.png"])

        result = await repo.has_images_in_context(12345, "Anthropic")

        assert result is True

    async def test_has_images_in_context_false(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that has_images_in_context returns False when no images."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        msg = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="prompt",
            content="No images",
        )
        await repo.save_message(msg)

        result = await repo.has_images_in_context(12345, "Anthropic")

        assert result is False

    async def test_deactivate_old_messages(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that deactivate_old_messages marks old messages inactive."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save 5 messages
        for i in range(5):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Message {i}",
            )
            await repo.save_message(msg)

        # Keep only 3 most recent
        await repo.deactivate_old_messages(12345, "Anthropic", window_size=3)

        messages = await repo.get_visible_messages(12345, "Anthropic")

        assert len(messages) == 3
        # Should be the 3 most recent
        assert messages[0].content == "Message 2"
        assert messages[1].content == "Message 3"
        assert messages[2].content == "Message 4"

    async def test_clear_messages(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that clear_messages soft-deletes all messages."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Save multiple messages
        for i in range(3):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Message {i}",
            )
            await repo.save_message(msg)

        # Verify messages exist
        messages_before = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages_before) == 3

        # Clear all messages
        await repo.clear_messages(12345, "Anthropic")

        # Verify all messages are gone
        messages_after = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages_after) == 0


# =============================================================================
# RateLimitRepository Tests
# =============================================================================


class TestRateLimitRepository:
    """Tests for RateLimitRepository methods."""

    async def test_get_recent_text_request_count(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that get_recent_text_request_count counts text prompts."""
        # Setup: create channel and Anthropic vendor
        await repo.create_channel(12345)
        vendor = await repo.create_vendor("Anthropic", "claude-3-sonnet")

        # Save some prompt messages (these count for text rate limit)
        for i in range(3):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Prompt {i}",
                is_image_prompt=False,
            )
            await repo.save_message(msg)

        # Save a response (should not count)
        response_msg = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="response",
            content="Response",
        )
        await repo.save_message(response_msg)

        count = await repo.get_recent_text_request_count(12345)

        assert count == 3

    async def test_get_recent_image_request_count(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that get_recent_image_request_count counts image prompts."""
        # Setup: create channel and Fal.AI vendor
        await repo.create_channel(12345)
        vendor = await repo.create_vendor("Fal.AI", "flux-model")

        # Save some image prompt messages
        for i in range(2):
            msg = Message(
                channel_id=12345,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Image prompt {i}",
                is_image_prompt=True,
            )
            await repo.save_message(msg)

        # Save a non-image prompt (should not count)
        text_msg = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="prompt",
            content="Text prompt",
            is_image_prompt=False,
        )
        await repo.save_message(text_msg)

        count = await repo.get_recent_image_request_count(12345)

        assert count == 2


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    async def test_empty_database_returns_empty_list(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that querying empty database returns empty list."""
        # Create channel and vendor but no messages
        await repo.create_channel(12345)
        await repo.create_vendor("Anthropic", "claude-3-sonnet")

        messages = await repo.get_visible_messages(12345, "Anthropic")

        assert messages == []

    async def test_large_message_content(
        self, repo_with_channel_and_vendor: SQLiteRepository
    ) -> None:
        """Test that repository handles large text content."""
        repo = repo_with_channel_and_vendor
        vendor = await repo.get_vendor("Anthropic")
        assert vendor is not None

        # Create a message with large content (100KB of text)
        large_content = "x" * 100_000

        msg = Message(
            channel_id=12345,
            vendor_id=vendor.id,
            message_type="prompt",
            content=large_content,
        )
        message_id = await repo.save_message(msg)

        assert message_id > 0

        # Verify it can be retrieved correctly
        messages = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages) == 1
        assert len(messages[0].content) == 100_000
        assert messages[0].content == large_content

    async def test_multiple_channels_isolated(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that messages are isolated between channels."""
        # Setup: create two channels and one vendor
        await repo.create_channel(11111)
        await repo.create_channel(22222)
        vendor = await repo.create_vendor("Anthropic", "claude-3-sonnet")

        # Save message to channel 1
        msg1 = Message(
            channel_id=11111,
            vendor_id=vendor.id,
            message_type="prompt",
            content="Message in channel 1",
        )
        await repo.save_message(msg1)

        # Save message to channel 2
        msg2 = Message(
            channel_id=22222,
            vendor_id=vendor.id,
            message_type="prompt",
            content="Message in channel 2",
        )
        await repo.save_message(msg2)

        # Verify channel 1 only sees its message
        messages_ch1 = await repo.get_visible_messages(11111, "Anthropic")
        assert len(messages_ch1) == 1
        assert messages_ch1[0].content == "Message in channel 1"

        # Verify channel 2 only sees its message
        messages_ch2 = await repo.get_visible_messages(22222, "Anthropic")
        assert len(messages_ch2) == 1
        assert messages_ch2[0].content == "Message in channel 2"

    async def test_multiple_vendors_isolated(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that messages are isolated between vendors."""
        # Setup: create one channel and two vendors
        await repo.create_channel(12345)
        vendor1 = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        vendor2 = await repo.create_vendor("OpenAI", "gpt-4")

        # Save message with vendor 1
        msg1 = Message(
            channel_id=12345,
            vendor_id=vendor1.id,
            message_type="prompt",
            content="Anthropic message",
        )
        await repo.save_message(msg1)

        # Save message with vendor 2
        msg2 = Message(
            channel_id=12345,
            vendor_id=vendor2.id,
            message_type="prompt",
            content="OpenAI message",
        )
        await repo.save_message(msg2)

        # Verify Anthropic vendor only sees its message
        messages_anthropic = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages_anthropic) == 1
        assert messages_anthropic[0].content == "Anthropic message"

        # Verify OpenAI vendor only sees its message
        messages_openai = await repo.get_visible_messages(12345, "OpenAI")
        assert len(messages_openai) == 1
        assert messages_openai[0].content == "OpenAI message"

    async def test_all_models_filter(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that 'All Models' vendor filter returns all vendor messages."""
        # Setup: create one channel and two vendors
        await repo.create_channel(12345)
        vendor1 = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        vendor2 = await repo.create_vendor("OpenAI", "gpt-4")

        # Save messages with different vendors
        msg1 = Message(
            channel_id=12345,
            vendor_id=vendor1.id,
            message_type="prompt",
            content="Anthropic message",
        )
        await repo.save_message(msg1)

        msg2 = Message(
            channel_id=12345,
            vendor_id=vendor2.id,
            message_type="prompt",
            content="OpenAI message",
        )
        await repo.save_message(msg2)

        # Use "All Models" filter - should return both
        messages = await repo.get_visible_messages(12345, "All Models")

        assert len(messages) == 2

    async def test_connection_not_established(self) -> None:
        """Test that operations fail gracefully without connection."""
        repo = SQLiteRepository(":memory:")
        # Don't call connect()

        with pytest.raises(RuntimeError, match="Database not connected"):
            await repo.get_channel(12345)

    async def test_context_manager(self) -> None:
        """Test that async context manager properly manages connection."""
        async with SQLiteRepository(":memory:") as repo:
            # Should be connected and usable
            channel = await repo.create_channel(12345)
            assert channel.external_id == 12345

        # After exiting context, connection should be closed
        # We can't easily test this directly, but verify no exception was raised

    async def test_clear_messages_preserves_other_channels(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that clear_messages only affects specified channel."""
        # Setup
        await repo.create_channel(11111)
        await repo.create_channel(22222)
        vendor = await repo.create_vendor("Anthropic", "claude-3-sonnet")

        # Add messages to both channels
        for channel_id in [11111, 22222]:
            msg = Message(
                channel_id=channel_id,
                vendor_id=vendor.id,
                message_type="prompt",
                content=f"Message in {channel_id}",
            )
            await repo.save_message(msg)

        # Clear only channel 1
        await repo.clear_messages(11111, "Anthropic")

        # Channel 1 should be empty
        messages_ch1 = await repo.get_visible_messages(11111, "Anthropic")
        assert len(messages_ch1) == 0

        # Channel 2 should still have its message
        messages_ch2 = await repo.get_visible_messages(22222, "Anthropic")
        assert len(messages_ch2) == 1

    async def test_deactivate_preserves_other_vendors(
        self, repo: SQLiteRepository
    ) -> None:
        """Test that deactivate_old_messages only affects specified vendor."""
        # Setup
        await repo.create_channel(12345)
        vendor1 = await repo.create_vendor("Anthropic", "claude-3-sonnet")
        vendor2 = await repo.create_vendor("OpenAI", "gpt-4")

        # Add messages for both vendors
        for i in range(3):
            msg1 = Message(
                channel_id=12345,
                vendor_id=vendor1.id,
                message_type="prompt",
                content=f"Anthropic {i}",
            )
            await repo.save_message(msg1)

            msg2 = Message(
                channel_id=12345,
                vendor_id=vendor2.id,
                message_type="prompt",
                content=f"OpenAI {i}",
            )
            await repo.save_message(msg2)

        # Deactivate old Anthropic messages, keeping only 1
        await repo.deactivate_old_messages(12345, "Anthropic", window_size=1)

        # Anthropic should have only 1 message
        messages_anthropic = await repo.get_visible_messages(12345, "Anthropic")
        assert len(messages_anthropic) == 1

        # OpenAI should still have all 3 messages
        messages_openai = await repo.get_visible_messages(12345, "OpenAI")
        assert len(messages_openai) == 3
