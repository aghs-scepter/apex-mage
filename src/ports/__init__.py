"""Ports (interfaces) for the application.

This module contains Protocol definitions that define the boundaries between
the application core and external systems (databases, APIs, etc.).

Sync protocols (ChannelRepository, etc.) are provided for documentation and
testing with sync implementations. For async implementations (like SQLite with
asyncio), use the Async* variants (AsyncChannelRepository, etc.).
"""

from src.ports.repositories import (
    AsyncChannelRepository,
    AsyncMessageRepository,
    AsyncRateLimitRepository,
    AsyncVendorRepository,
    Channel,
    ChannelRepository,
    Message,
    MessageImage,
    MessageRepository,
    RateLimitRepository,
    Vendor,
    VendorRepository,
)

__all__ = [
    # Data classes
    "Channel",
    "Message",
    "MessageImage",
    "Vendor",
    # Sync protocols (for documentation/sync implementations)
    "ChannelRepository",
    "MessageRepository",
    "RateLimitRepository",
    "VendorRepository",
    # Async protocols (for async implementations like SQLite)
    "AsyncChannelRepository",
    "AsyncMessageRepository",
    "AsyncRateLimitRepository",
    "AsyncVendorRepository",
]
