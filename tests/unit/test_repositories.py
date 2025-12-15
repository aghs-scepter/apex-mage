"""Unit tests for repository protocols and dataclasses."""

from datetime import datetime

from src.ports.repositories import (
    Channel,
    ChannelRepository,
    Message,
    MessageImage,
    MessageRepository,
    RateLimitRepository,
    Vendor,
    VendorRepository,
)


class TestDataClasses:
    """Tests for repository dataclasses."""

    def test_channel_creation(self) -> None:
        """Test Channel dataclass creation."""
        channel = Channel(id=1, external_id=123456789)
        assert channel.id == 1
        assert channel.external_id == 123456789

    def test_vendor_creation(self) -> None:
        """Test Vendor dataclass creation."""
        vendor = Vendor(id=1, name="anthropic", model_name="claude-3-sonnet")
        assert vendor.id == 1
        assert vendor.name == "anthropic"
        assert vendor.model_name == "claude-3-sonnet"

    def test_message_image_creation(self) -> None:
        """Test MessageImage dataclass creation."""
        image = MessageImage(url="https://example.com/image.png")
        assert image.url == "https://example.com/image.png"
        assert image.base64_data is None

        image_with_data = MessageImage(
            url="https://example.com/image.png",
            base64_data="base64encodeddata",
        )
        assert image_with_data.base64_data == "base64encodeddata"

    def test_message_creation_minimal(self) -> None:
        """Test Message dataclass creation with minimal fields."""
        message = Message(
            channel_id=1,
            vendor_id=1,
            message_type="user",
            content="Hello, world!",
        )
        assert message.channel_id == 1
        assert message.vendor_id == 1
        assert message.message_type == "user"
        assert message.content == "Hello, world!"
        assert message.id is None
        assert message.timestamp is None
        assert message.visible is True
        assert message.is_image_prompt is False
        assert message.images == []

    def test_message_creation_full(self) -> None:
        """Test Message dataclass creation with all fields."""
        now = datetime.now()
        images = [MessageImage(url="https://example.com/img.png")]
        message = Message(
            id=42,
            channel_id=1,
            vendor_id=2,
            message_type="assistant",
            content="Here is your image.",
            timestamp=now,
            visible=True,
            is_image_prompt=True,
            images=images,
        )
        assert message.id == 42
        assert message.timestamp == now
        assert message.is_image_prompt is True
        assert len(message.images) == 1
        assert message.images[0].url == "https://example.com/img.png"


class TestProtocolCompliance:
    """Tests that verify Protocol structural typing works correctly."""

    def test_channel_repository_protocol(self) -> None:
        """Test that a class can implement ChannelRepository protocol."""

        class MockChannelRepo:
            def get_channel(self, external_id: int) -> Channel | None:
                return Channel(id=1, external_id=external_id)

            def create_channel(self, external_id: int) -> Channel:
                return Channel(id=1, external_id=external_id)

            def get_or_create_channel(self, external_id: int) -> Channel:
                return Channel(id=1, external_id=external_id)

        repo: ChannelRepository = MockChannelRepo()
        result = repo.get_channel(12345)
        assert result is not None
        assert result.external_id == 12345

    def test_vendor_repository_protocol(self) -> None:
        """Test that a class can implement VendorRepository protocol."""

        class MockVendorRepo:
            def get_vendor(self, name: str) -> Vendor | None:
                return Vendor(id=1, name=name, model_name="test-model")

            def create_vendor(self, name: str, model_name: str) -> Vendor:
                return Vendor(id=1, name=name, model_name=model_name)

            def get_or_create_vendor(self, name: str, model_name: str) -> Vendor:
                return Vendor(id=1, name=name, model_name=model_name)

        repo: VendorRepository = MockVendorRepo()
        result = repo.get_vendor("anthropic")
        assert result is not None
        assert result.name == "anthropic"

    def test_message_repository_protocol(self) -> None:
        """Test that a class can implement MessageRepository protocol."""

        class MockMessageRepo:
            def save_message(self, message: Message) -> int:
                return 1

            def save_message_with_images(
                self,
                message: Message,
                image_urls: list[str],
            ) -> int:
                return 1

            def get_visible_messages(
                self,
                channel_external_id: int,
                vendor_name: str,
            ) -> list[Message]:
                return []

            def get_latest_messages(
                self,
                channel_external_id: int,
                vendor_name: str,
                limit: int,
            ) -> list[Message]:
                return []

            def get_latest_images(
                self,
                channel_external_id: int,
                vendor_name: str,
                limit: int,
            ) -> list[Message]:
                return []

            def has_images_in_context(
                self,
                channel_external_id: int,
                vendor_name: str,
            ) -> bool:
                return False

            def deactivate_old_messages(
                self,
                channel_external_id: int,
                vendor_name: str,
                window_size: int,
            ) -> None:
                pass

            def clear_messages(
                self,
                channel_external_id: int,
                vendor_name: str,
            ) -> None:
                pass

        repo: MessageRepository = MockMessageRepo()
        msg = Message(
            channel_id=1,
            vendor_id=1,
            message_type="user",
            content="test",
        )
        result = repo.save_message(msg)
        assert result == 1

    def test_rate_limit_repository_protocol(self) -> None:
        """Test that a class can implement RateLimitRepository protocol."""

        class MockRateLimitRepo:
            def get_recent_text_request_count(self, channel_external_id: int) -> int:
                return 5

            def get_recent_image_request_count(self, channel_external_id: int) -> int:
                return 2

        repo: RateLimitRepository = MockRateLimitRepo()
        assert repo.get_recent_text_request_count(12345) == 5
        assert repo.get_recent_image_request_count(12345) == 2
