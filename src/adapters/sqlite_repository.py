"""SQLite implementation of repository protocols.

This module provides a SQLite-backed implementation of all repository protocols:
- ChannelRepository
- VendorRepository
- MessageRepository
- RateLimitRepository

All methods are async, wrapping synchronous sqlite3 calls with asyncio.to_thread.
The class supports both file-based and in-memory (:memory:) databases.
"""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast

from src.ports.repositories import (
    ApiKey,
    Channel,
    Message,
    MessageImage,
    Vendor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SQL Schema Definitions
# =============================================================================

_CREATE_CHANNELS_TABLE = """
CREATE TABLE IF NOT EXISTS channels(
    channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id INT NOT NULL
);
"""

_CREATE_VENDORS_TABLE = """
CREATE TABLE IF NOT EXISTS vendors(
    vendor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_name VARCHAR(255) NOT NULL,
    vendor_model_name VARCHAR(255) NOT NULL
);
"""

_CREATE_CHANNEL_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS channel_messages(
    channel_message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    message_data TEXT,
    message_images TEXT DEFAULT '[]',
    message_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    visible BOOLEAN DEFAULT TRUE,
    is_image_prompt BOOLEAN DEFAULT FALSE,
    image_b64 TEXT DEFAULT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id),
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
);
"""

_CREATE_API_KEYS_TABLE = """
CREATE TABLE IF NOT EXISTS api_keys(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT,
    scopes TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
"""

_CREATE_API_KEYS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
"""

_CREATE_BANS_TABLE = """
CREATE TABLE IF NOT EXISTS bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_BAN_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS ban_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    performed_by TEXT NOT NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_BEHAVIOR_PRESETS_TABLE = """
CREATE TABLE IF NOT EXISTS behavior_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, name)
);
"""

# =============================================================================
# SQL Query Definitions
# =============================================================================

_INSERT_CHANNEL = """
INSERT INTO channels(discord_id) VALUES(?);
"""

_SELECT_CHANNEL = """
SELECT * FROM channels WHERE discord_id = ?;
"""

_INSERT_VENDOR = """
INSERT INTO vendors(vendor_name, vendor_model_name) VALUES(?, ?);
"""

_SELECT_VENDOR = """
SELECT * FROM vendors WHERE vendor_name = ?;
"""

_INSERT_MESSAGE = """
INSERT INTO channel_messages(
    channel_id,
    vendor_id,
    message_type,
    message_data,
    is_image_prompt
)
SELECT
    (SELECT channel_id FROM channels WHERE discord_id = ?),
    (SELECT vendor_id FROM vendors WHERE vendor_name = ?),
    ?,
    ?,
    ?
;
"""

_INSERT_MESSAGE_WITH_IMAGES = """
INSERT INTO channel_messages(
    channel_id,
    vendor_id,
    message_type,
    message_data,
    message_images,
    is_image_prompt
)
SELECT
    (SELECT channel_id FROM channels WHERE discord_id = ?),
    (SELECT vendor_id FROM vendors WHERE vendor_name = ?),
    ?,
    ?,
    ?,
    ?
;
"""

_SELECT_VISIBLE_MESSAGES = """
SELECT
    channel_messages.channel_message_id,
    message_type,
    message_data,
    message_images,
    message_timestamp,
    vendors.vendor_name
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = ? OR ? = "All Models")
AND channel_messages.visible = TRUE
AND channel_messages.is_image_prompt = FALSE
ORDER BY channel_messages.message_timestamp ASC
;
"""

_SELECT_LATEST_MESSAGES = """
SELECT
    channel_messages.channel_message_id,
    message_type,
    message_data,
    message_images,
    message_timestamp,
    vendors.vendor_name
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = ? OR ? = "All Models")
AND channel_messages.visible = TRUE
AND channel_messages.is_image_prompt = FALSE
ORDER BY channel_messages.message_timestamp ASC
LIMIT ?
;
"""

_SELECT_LATEST_IMAGES = """
SELECT
    channel_messages.channel_message_id,
    message_type,
    message_data,
    message_images,
    message_timestamp,
    vendors.vendor_name
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = ? OR ? = "All Models")
AND channel_messages.visible = TRUE
AND channel_messages.is_image_prompt = FALSE
AND channel_messages.message_images != "[]"
ORDER BY channel_messages.message_timestamp DESC
LIMIT ?
;
"""

_SELECT_HAS_IMAGES_IN_CONTEXT = """
SELECT
    channel_messages.channel_message_id
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = ? OR ? = "All Models")
AND channel_messages.visible = TRUE
AND channel_messages.is_image_prompt = FALSE
AND channel_messages.message_images != "[]"
ORDER BY channel_messages.message_timestamp DESC
LIMIT 1
;
"""

_DEACTIVATE_OLD_MESSAGES = """
UPDATE channel_messages
SET visible = FALSE
WHERE channel_id = (SELECT channel_id FROM channels WHERE discord_id = ?)
AND (vendor_id = (SELECT vendor_id FROM vendors WHERE vendor_name = ?) OR ? = "All Models")
AND channel_message_id NOT IN (
    SELECT
        channel_message_id
    FROM channel_messages
    WHERE channel_id = (SELECT channel_id FROM channels WHERE discord_id = ?)
    AND (vendor_id = (SELECT vendor_id FROM vendors WHERE vendor_name = ?) OR ? = "All Models")
    AND visible = TRUE
    ORDER BY message_timestamp DESC, channel_message_id DESC
    LIMIT ?
)
;
"""

_CLEAR_MESSAGES = """
UPDATE channel_messages
SET visible = FALSE
WHERE channel_id = (SELECT channel_id FROM channels WHERE discord_id = ?)
AND (vendor_id = (SELECT vendor_id FROM vendors WHERE vendor_name = ?) Or ? = "All Models")
;
"""

_COUNT_RECENT_TEXT_REQUESTS = """
SELECT
    COUNT(channel_messages.channel_message_id) AS count
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND vendors.vendor_name = ?
AND channel_messages.message_type = "prompt"
AND channel_messages.message_timestamp BETWEEN datetime('now', '-1 hour') AND datetime('now')
;
"""

_COUNT_RECENT_IMAGE_REQUESTS = """
SELECT
    COUNT(channel_messages.channel_message_id) AS count
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND vendors.vendor_name = ?
AND channel_messages.message_type = "prompt"
AND channel_messages.is_image_prompt = 1
AND channel_messages.message_timestamp BETWEEN datetime('now', '-1 hour') AND datetime('now')
;
"""

# API Keys queries
_INSERT_API_KEY = """
INSERT INTO api_keys(key_hash, user_id, name, scopes, expires_at)
VALUES (?, ?, ?, ?, ?);
"""

_SELECT_API_KEY_BY_HASH = """
SELECT id, key_hash, user_id, name, scopes, created_at, last_used_at, expires_at, is_active
FROM api_keys
WHERE key_hash = ? AND is_active = 1 AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'));
"""

_UPDATE_API_KEY_LAST_USED = """
UPDATE api_keys
SET last_used_at = CURRENT_TIMESTAMP
WHERE key_hash = ?;
"""

_REVOKE_API_KEY = """
UPDATE api_keys
SET is_active = 0
WHERE key_hash = ?;
"""

# Ban queries
_SELECT_BAN_BY_USERNAME = """
SELECT id, username, reason, created_at
FROM bans
WHERE username = ?;
"""

_INSERT_BAN = """
INSERT INTO bans (username, reason)
VALUES (?, ?);
"""

_DELETE_BAN = """
DELETE FROM bans
WHERE username = ?;
"""

_INSERT_BAN_HISTORY = """
INSERT INTO ban_history (username, action, reason, performed_by)
VALUES (?, ?, ?, ?);
"""

# Behavior presets queries
_SELECT_PRESET = """
SELECT id, guild_id, name, description, prompt_text, created_by, created_at
FROM behavior_presets
WHERE guild_id = ? AND name = ?;
"""

_SELECT_PRESETS_BY_GUILD = """
SELECT id, guild_id, name, description, prompt_text, created_by, created_at
FROM behavior_presets
WHERE guild_id = ?
ORDER BY name ASC;
"""

_COUNT_PRESETS_BY_GUILD = """
SELECT COUNT(*) AS count
FROM behavior_presets
WHERE guild_id = ?;
"""

_INSERT_PRESET = """
INSERT INTO behavior_presets (guild_id, name, description, prompt_text, created_by)
VALUES (?, ?, ?, ?, ?);
"""

_UPDATE_PRESET = """
UPDATE behavior_presets
SET description = COALESCE(?, description),
    prompt_text = COALESCE(?, prompt_text)
WHERE guild_id = ? AND name = ?;
"""

_DELETE_PRESET = """
DELETE FROM behavior_presets
WHERE guild_id = ? AND name = ?;
"""


# =============================================================================
# Repository Implementation
# =============================================================================


class SQLiteRepository:
    """SQLite implementation of all repository protocols.

    This class implements ChannelRepository, VendorRepository, MessageRepository,
    and RateLimitRepository. It manages a single SQLite connection that is shared
    across all operations.

    The class supports async context manager protocol for automatic resource cleanup.

    Example:
        async with SQLiteRepository("data/app.db") as repo:
            channel = await repo.get_or_create_channel(12345)
            await repo.save_message(message)

    For testing, use `:memory:` as the db_path:
        repo = SQLiteRepository(":memory:")
        await repo.connect()
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the repository with a database path.

        Args:
            db_path: Path to the SQLite database file, or ":memory:" for
                an in-memory database (useful for testing).
        """
        self._db_path = str(db_path)
        self._connection: sqlite3.Connection | None = None

    async def __aenter__(self) -> "SQLiteRepository":
        """Async context manager entry: connect to the database."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit: close the database connection."""
        await self.close()

    async def connect(self) -> None:
        """Connect to the database and initialize the schema.

        This method must be called before using any repository methods,
        unless using the async context manager.
        """
        logger.debug(f"Connecting to database: {self._db_path}")
        self._connection = await asyncio.to_thread(self._connect_sync)
        await self._initialize_schema()
        logger.debug("Database connection established and schema initialized")

    def _connect_sync(self) -> sqlite3.Connection:
        """Synchronous connection setup.

        Note: check_same_thread=False is required because we use asyncio.to_thread()
        to run synchronous SQLite operations. The connection is created in one thread
        but may be used from different thread pool workers. This is safe as long as
        we don't have concurrent writes (our async wrapper ensures sequential access).
        """
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def _initialize_schema(self) -> None:
        """Create database tables if they don't exist."""
        if self._connection is None:
            raise RuntimeError("Database not connected")

        def init_sync() -> None:
            assert self._connection is not None
            self._connection.execute(_CREATE_CHANNELS_TABLE)
            self._connection.execute(_CREATE_VENDORS_TABLE)
            self._connection.execute(_CREATE_CHANNEL_MESSAGES_TABLE)
            self._connection.execute(_CREATE_API_KEYS_TABLE)
            self._connection.execute(_CREATE_API_KEYS_INDEX)
            self._connection.execute(_CREATE_BANS_TABLE)
            self._connection.execute(_CREATE_BAN_HISTORY_TABLE)
            self._connection.execute(_CREATE_BEHAVIOR_PRESETS_TABLE)
            self._connection.commit()

        await asyncio.to_thread(init_sync)

    async def close(self) -> None:
        """Close the database connection.

        This method should be called when the repository is no longer needed,
        unless using the async context manager.
        """
        if self._connection is not None:
            logger.debug("Closing database connection")
            await asyncio.to_thread(self._connection.close)
            self._connection = None

    def _ensure_connected(self) -> sqlite3.Connection:
        """Ensure the database is connected and return the connection."""
        if self._connection is None:
            raise RuntimeError(
                "Database not connected. Call connect() or use async context manager."
            )
        return self._connection

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a sqlite3.Row to a dictionary."""
        return {key: row[key] for key in row.keys()}

    # =========================================================================
    # ChannelRepository Implementation
    # =========================================================================

    async def get_channel(self, external_id: int) -> Channel | None:
        """Retrieve a channel by its external platform ID."""
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_CHANNEL, (external_id,))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        if row is None:
            return None
        return Channel(id=row["channel_id"], external_id=row["discord_id"])

    async def create_channel(self, external_id: int) -> Channel:
        """Create a new channel record.

        If channel already exists, returns the existing one.
        """
        existing = await self.get_channel(external_id)
        if existing is not None:
            logger.debug(f"Channel {external_id} already exists")
            return existing

        conn = self._ensure_connected()

        def insert_sync() -> int:
            cursor = conn.execute(_INSERT_CHANNEL, (external_id,))
            conn.commit()
            return cursor.lastrowid or 0

        channel_id = await asyncio.to_thread(insert_sync)
        logger.debug(f"Created channel {external_id} with id {channel_id}")
        return Channel(id=channel_id, external_id=external_id)

    async def get_or_create_channel(self, external_id: int) -> Channel:
        """Get an existing channel or create it if it doesn't exist."""
        return await self.create_channel(external_id)

    # =========================================================================
    # VendorRepository Implementation
    # =========================================================================

    async def get_vendor(self, name: str) -> Vendor | None:
        """Retrieve a vendor by its name."""
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_VENDOR, (name,))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        if row is None:
            return None
        return Vendor(
            id=row["vendor_id"],
            name=row["vendor_name"],
            model_name=row["vendor_model_name"],
        )

    async def create_vendor(self, name: str, model_name: str) -> Vendor:
        """Create a new vendor record.

        If vendor already exists, returns the existing one.
        """
        existing = await self.get_vendor(name)
        if existing is not None:
            logger.debug(f"Vendor {name} already exists")
            return existing

        conn = self._ensure_connected()

        def insert_sync() -> int:
            cursor = conn.execute(_INSERT_VENDOR, (name, model_name))
            conn.commit()
            return cursor.lastrowid or 0

        vendor_id = await asyncio.to_thread(insert_sync)
        logger.debug(f"Created vendor {name} with id {vendor_id}")
        return Vendor(id=vendor_id, name=name, model_name=model_name)

    async def get_or_create_vendor(self, name: str, model_name: str) -> Vendor:
        """Get an existing vendor or create it if it doesn't exist."""
        return await self.create_vendor(name, model_name)

    # =========================================================================
    # MessageRepository Implementation
    # =========================================================================

    def _row_to_message(self, row: sqlite3.Row, vendor_name: str) -> Message:
        """Convert a database row to a Message object."""
        # Parse images from JSON string
        images_json = row["message_images"] or "[]"
        try:
            image_urls = json.loads(images_json)
        except json.JSONDecodeError:
            image_urls = []

        images = [MessageImage(url=url) for url in image_urls if url]

        return Message(
            id=row["channel_message_id"],
            channel_id=0,  # Not needed for returned messages
            vendor_id=0,  # Not needed for returned messages
            message_type=row["message_type"],
            content=row["message_data"] or "",
            timestamp=row["message_timestamp"],
            images=images,
        )

    async def save_message(self, message: Message) -> int:
        """Save a message to the repository."""
        conn = self._ensure_connected()

        # We need to look up channel and vendor by their external identifiers
        # The message contains channel_id which is actually the external_id (discord_id)
        # and vendor_id which we need to resolve to vendor_name

        def insert_sync() -> int:
            # Get vendor name from vendor_id
            cursor = conn.execute(
                "SELECT vendor_name FROM vendors WHERE vendor_id = ?",
                (message.vendor_id,),
            )
            vendor_row = cursor.fetchone()
            if vendor_row is None:
                raise ValueError(f"Vendor with id {message.vendor_id} not found")
            vendor_name = vendor_row["vendor_name"]

            cursor = conn.execute(
                _INSERT_MESSAGE,
                (
                    message.channel_id,  # This is external_id (discord_id)
                    vendor_name,
                    message.message_type,
                    message.content,
                    message.is_image_prompt,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

        message_id = await asyncio.to_thread(insert_sync)
        logger.debug(f"Saved message with id {message_id}")
        return message_id

    async def save_message_with_images(
        self,
        message: Message,
        image_urls: list[str],
    ) -> int:
        """Save a message with associated image URLs."""
        conn = self._ensure_connected()

        def insert_sync() -> int:
            # Get vendor name from vendor_id
            cursor = conn.execute(
                "SELECT vendor_name FROM vendors WHERE vendor_id = ?",
                (message.vendor_id,),
            )
            vendor_row = cursor.fetchone()
            if vendor_row is None:
                raise ValueError(f"Vendor with id {message.vendor_id} not found")
            vendor_name = vendor_row["vendor_name"]

            images_json = json.dumps(image_urls)
            cursor = conn.execute(
                _INSERT_MESSAGE_WITH_IMAGES,
                (
                    message.channel_id,  # This is external_id (discord_id)
                    vendor_name,
                    message.message_type,
                    message.content,
                    images_json,
                    message.is_image_prompt,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

        message_id = await asyncio.to_thread(insert_sync)
        logger.debug(f"Saved message with images, id {message_id}")
        return message_id

    async def get_visible_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> list[Message]:
        """Get all visible (active) messages for a channel and vendor."""
        conn = self._ensure_connected()

        def query_sync() -> list[sqlite3.Row]:
            cursor = conn.execute(
                _SELECT_VISIBLE_MESSAGES,
                (channel_external_id, vendor_name, vendor_name),
            )
            return cursor.fetchall()

        rows = await asyncio.to_thread(query_sync)
        return [self._row_to_message(row, vendor_name) for row in rows]

    async def get_latest_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent messages for a channel and vendor."""
        conn = self._ensure_connected()

        def query_sync() -> list[sqlite3.Row]:
            cursor = conn.execute(
                _SELECT_LATEST_MESSAGES,
                (channel_external_id, vendor_name, vendor_name, limit),
            )
            return cursor.fetchall()

        rows = await asyncio.to_thread(query_sync)
        return [self._row_to_message(row, vendor_name) for row in rows]

    async def get_latest_images(
        self,
        channel_external_id: int,
        vendor_name: str,
        limit: int,
    ) -> list[Message]:
        """Get the most recent image messages for a channel and vendor."""
        conn = self._ensure_connected()

        def query_sync() -> list[sqlite3.Row]:
            cursor = conn.execute(
                _SELECT_LATEST_IMAGES,
                (channel_external_id, vendor_name, vendor_name, limit),
            )
            return cursor.fetchall()

        rows = await asyncio.to_thread(query_sync)
        return [self._row_to_message(row, vendor_name) for row in rows]

    async def has_images_in_context(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> bool:
        """Check if the channel's context contains any images."""
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(
                _SELECT_HAS_IMAGES_IN_CONTEXT,
                (channel_external_id, vendor_name, vendor_name),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        return row is not None

    async def deactivate_old_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
        window_size: int,
    ) -> None:
        """Mark messages outside the context window as inactive."""
        conn = self._ensure_connected()

        def update_sync() -> None:
            conn.execute(
                _DEACTIVATE_OLD_MESSAGES,
                (
                    channel_external_id,  # WHERE clause channel
                    vendor_name,  # WHERE clause vendor
                    vendor_name,  # WHERE clause "All Models" check
                    channel_external_id,  # Subquery channel
                    vendor_name,  # Subquery vendor
                    vendor_name,  # Subquery "All Models" check
                    window_size,  # LIMIT
                ),
            )
            conn.commit()

        await asyncio.to_thread(update_sync)
        logger.debug(
            f"Deactivated old messages for channel {channel_external_id}, "
            f"vendor {vendor_name}, keeping {window_size}"
        )

    async def clear_messages(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> None:
        """Soft-delete all messages for a channel and vendor."""
        conn = self._ensure_connected()

        def update_sync() -> None:
            conn.execute(
                _CLEAR_MESSAGES,
                (channel_external_id, vendor_name, vendor_name),
            )
            conn.commit()

        await asyncio.to_thread(update_sync)
        logger.debug(
            f"Cleared messages for channel {channel_external_id}, vendor {vendor_name}"
        )

    # =========================================================================
    # RateLimitRepository Implementation
    # =========================================================================

    async def get_recent_text_request_count(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> int:
        """Get the count of recent text requests for a channel and vendor."""
        conn = self._ensure_connected()

        def query_sync() -> int:
            cursor = conn.execute(
                _COUNT_RECENT_TEXT_REQUESTS,
                (channel_external_id, vendor_name),
            )
            row = cursor.fetchone()
            return row["count"] if row else 0

        return await asyncio.to_thread(query_sync)

    async def get_recent_image_request_count(
        self,
        channel_external_id: int,
        vendor_name: str,
    ) -> int:
        """Get the count of recent image requests for a channel and vendor."""
        conn = self._ensure_connected()

        def query_sync() -> int:
            cursor = conn.execute(
                _COUNT_RECENT_IMAGE_REQUESTS,
                (channel_external_id, vendor_name),
            )
            row = cursor.fetchone()
            return row["count"] if row else 0

        return await asyncio.to_thread(query_sync)

    # =========================================================================
    # ApiKeyRepository Implementation
    # =========================================================================

    def _row_to_api_key(self, row: sqlite3.Row) -> ApiKey:
        """Convert a database row to an ApiKey object."""
        # Parse scopes from JSON string
        scopes_json = row["scopes"] or "[]"
        try:
            scopes = json.loads(scopes_json)
        except json.JSONDecodeError:
            scopes = []

        return ApiKey(
            id=row["id"],
            key_hash=row["key_hash"],
            user_id=row["user_id"],
            name=row["name"],
            scopes=scopes,
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            expires_at=row["expires_at"],
            is_active=bool(row["is_active"]),
        )

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Retrieve an API key by its hash."""
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_API_KEY_BY_HASH, (key_hash,))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        if row is None:
            return None
        return self._row_to_api_key(row)

    async def create(self, api_key: ApiKey) -> ApiKey:
        """Create a new API key record."""
        conn = self._ensure_connected()

        scopes_json = json.dumps(api_key.scopes)
        expires_at = api_key.expires_at.isoformat() if api_key.expires_at else None

        def insert_sync() -> int:
            cursor = conn.execute(
                _INSERT_API_KEY,
                (
                    api_key.key_hash,
                    api_key.user_id,
                    api_key.name,
                    scopes_json,
                    expires_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

        api_key_id = await asyncio.to_thread(insert_sync)
        logger.debug(f"Created API key with id {api_key_id}")

        # Return the created key with ID populated
        return ApiKey(
            id=api_key_id,
            key_hash=api_key.key_hash,
            user_id=api_key.user_id,
            name=api_key.name,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            expires_at=api_key.expires_at,
            is_active=api_key.is_active,
        )

    async def update_last_used(self, key_hash: str) -> None:
        """Update the last_used_at timestamp for an API key."""
        conn = self._ensure_connected()

        def update_sync() -> None:
            conn.execute(_UPDATE_API_KEY_LAST_USED, (key_hash,))
            conn.commit()

        await asyncio.to_thread(update_sync)
        logger.debug(f"Updated last_used_at for API key hash {key_hash[:8]}...")

    async def revoke(self, key_hash: str) -> bool:
        """Revoke an API key by setting is_active to False."""
        conn = self._ensure_connected()

        def update_sync() -> int:
            cursor = conn.execute(_REVOKE_API_KEY, (key_hash,))
            conn.commit()
            return cursor.rowcount

        rows_affected = await asyncio.to_thread(update_sync)
        if rows_affected > 0:
            logger.info(f"Revoked API key hash {key_hash[:8]}...")
            return True
        return False

    # =========================================================================
    # BanRepository Implementation
    # =========================================================================

    async def is_user_banned(self, username: str) -> bool:
        """Check if a user is banned.

        Args:
            username: The Discord username to check.

        Returns:
            True if the user is banned, False otherwise.
        """
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_BAN_BY_USERNAME, (username,))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        return row is not None

    async def get_ban_reason(self, username: str) -> str | None:
        """Get the ban reason for a user.

        Args:
            username: The Discord username to check.

        Returns:
            The ban reason if the user is banned, None otherwise.
        """
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_BAN_BY_USERNAME, (username,))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        if row is None:
            return None
        return cast(str, row["reason"])

    async def add_ban(
        self,
        username: str,
        reason: str,
        performed_by: str,
    ) -> None:
        """Add a ban for a user.

        Args:
            username: The Discord username to ban.
            reason: The reason for the ban.
            performed_by: The username of the person performing the ban.

        Raises:
            sqlite3.IntegrityError: If the user is already banned.
        """
        conn = self._ensure_connected()

        def insert_sync() -> None:
            conn.execute(_INSERT_BAN, (username, reason))
            conn.execute(
                _INSERT_BAN_HISTORY,
                (username, "ban", reason, performed_by),
            )
            conn.commit()

        await asyncio.to_thread(insert_sync)
        logger.info(f"User {username} banned by {performed_by}: {reason}")

    async def remove_ban(self, username: str, performed_by: str) -> None:
        """Remove a ban for a user.

        Args:
            username: The Discord username to unban.
            performed_by: The username of the person performing the unban.
        """
        conn = self._ensure_connected()

        def delete_sync() -> None:
            conn.execute(_DELETE_BAN, (username,))
            conn.execute(
                _INSERT_BAN_HISTORY,
                (username, "unban", None, performed_by),
            )
            conn.commit()

        await asyncio.to_thread(delete_sync)
        logger.info(f"User {username} unbanned by {performed_by}")

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
        conn = self._ensure_connected()

        def query_sync() -> sqlite3.Row | None:
            cursor = conn.execute(_SELECT_PRESET, (guild_id, name))
            return cast(sqlite3.Row | None, cursor.fetchone())

        row = await asyncio.to_thread(query_sync)
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_presets(self, guild_id: str) -> list[dict[str, Any]]:
        """List all behavior presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            List of presets as dictionaries, ordered by name.
        """
        conn = self._ensure_connected()

        def query_sync() -> list[sqlite3.Row]:
            cursor = conn.execute(_SELECT_PRESETS_BY_GUILD, (guild_id,))
            return cursor.fetchall()

        rows = await asyncio.to_thread(query_sync)
        return [self._row_to_dict(row) for row in rows]

    async def count_presets(self, guild_id: str) -> int:
        """Count the number of presets for a guild.

        Args:
            guild_id: The Discord guild ID.

        Returns:
            The number of presets in the guild.
        """
        conn = self._ensure_connected()

        def query_sync() -> int:
            cursor = conn.execute(_COUNT_PRESETS_BY_GUILD, (guild_id,))
            row = cursor.fetchone()
            return row["count"] if row else 0

        return await asyncio.to_thread(query_sync)

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
        conn = self._ensure_connected()

        def insert_sync() -> None:
            conn.execute(
                _INSERT_PRESET,
                (guild_id, name, description, prompt_text, created_by),
            )
            conn.commit()

        await asyncio.to_thread(insert_sync)
        logger.debug(f"Created behavior preset '{name}' for guild {guild_id}")

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
        conn = self._ensure_connected()

        def update_sync() -> None:
            conn.execute(
                _UPDATE_PRESET,
                (description, prompt_text, guild_id, name),
            )
            conn.commit()

        await asyncio.to_thread(update_sync)
        logger.debug(f"Updated behavior preset '{name}' for guild {guild_id}")

    async def delete_preset(self, guild_id: str, name: str) -> None:
        """Delete a behavior preset.

        Args:
            guild_id: The Discord guild ID.
            name: The preset name to delete.
        """
        conn = self._ensure_connected()

        def delete_sync() -> None:
            conn.execute(_DELETE_PRESET, (guild_id, name))
            conn.commit()

        await asyncio.to_thread(delete_sync)
        logger.debug(f"Deleted behavior preset '{name}' for guild {guild_id}")
