"""Tests for WebSocket functionality."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.websocket import (
    ConnectionManager,
    MessageTypes,
    WebSocketMessage,
    create_error_event,
    create_new_message_event,
    create_typing_event,
)


class TestWebSocketMessage:
    """Tests for WebSocketMessage dataclass."""

    def test_creates_message(self):
        """Should create a message with required fields."""
        msg = WebSocketMessage(
            type="test",
            payload={"key": "value"},
        )
        assert msg.type == "test"
        assert msg.payload == {"key": "value"}
        assert msg.timestamp is not None

    def test_to_json(self):
        """Should convert to JSON string."""
        msg = WebSocketMessage(
            type="test",
            payload={"key": "value"},
        )
        json_str = msg.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "test"
        assert parsed["payload"] == {"key": "value"}
        assert "timestamp" in parsed


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ConnectionManager for each test."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket."""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect(self, manager, mock_websocket):
        """Should accept and register connection."""
        await manager.connect(mock_websocket, conversation_id=123)

        mock_websocket.accept.assert_called_once()
        assert manager.get_connection_count(123) == 1

    @pytest.mark.asyncio
    async def test_disconnect(self, manager, mock_websocket):
        """Should unregister connection."""
        await manager.connect(mock_websocket, conversation_id=123)
        await manager.disconnect(mock_websocket, conversation_id=123)

        assert manager.get_connection_count(123) == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self, manager, mock_websocket):
        """Should handle disconnect for non-registered socket."""
        # Should not raise
        await manager.disconnect(mock_websocket, conversation_id=999)

    @pytest.mark.asyncio
    async def test_multiple_connections(self, manager):
        """Should handle multiple connections to same conversation."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1, conversation_id=123)
        await manager.connect(ws2, conversation_id=123)

        assert manager.get_connection_count(123) == 2

    @pytest.mark.asyncio
    async def test_send_to_conversation(self, manager, mock_websocket):
        """Should send message to all clients in conversation."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1, conversation_id=123)
        await manager.connect(ws2, conversation_id=123)

        msg = WebSocketMessage(type="test", payload={"data": "value"})
        sent_count = await manager.send_to_conversation(123, msg)

        assert sent_count == 2
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_to_empty_conversation(self, manager):
        """Should return 0 when no clients connected."""
        msg = WebSocketMessage(type="test", payload={})
        sent_count = await manager.send_to_conversation(999, msg)

        assert sent_count == 0

    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        """Should send to all connected clients."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1, conversation_id=123)
        await manager.connect(ws2, conversation_id=456)

        msg = WebSocketMessage(type="broadcast", payload={})
        sent_count = await manager.broadcast(msg)

        assert sent_count == 2
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_send_failure(self, manager):
        """Should handle failed sends gracefully."""
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = Exception("Connection lost")

        await manager.connect(ws_good, conversation_id=123)
        await manager.connect(ws_bad, conversation_id=123)

        msg = WebSocketMessage(type="test", payload={})
        sent_count = await manager.send_to_conversation(123, msg)

        # Only successful send counted
        assert sent_count == 1
        # Failed connection should be removed
        assert manager.get_connection_count(123) == 1

    def test_get_connection_count_total(self, manager):
        """Should return total connections when no id specified."""
        assert manager.get_connection_count() == 0

    @pytest.mark.asyncio
    async def test_get_active_conversations(self, manager):
        """Should return list of active conversation IDs."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1, conversation_id=123)
        await manager.connect(ws2, conversation_id=456)

        active = manager.get_active_conversations()
        assert 123 in active
        assert 456 in active


class TestMessageHelpers:
    """Tests for message creation helper functions."""

    def test_create_new_message_event(self):
        """Should create new message event."""
        msg = create_new_message_event(
            conversation_id=123,
            message_id=1,
            role="user",
            content="Hello",
            user_id=456,
        )

        assert msg.type == MessageTypes.NEW_MESSAGE
        assert msg.payload["conversation_id"] == 123
        assert msg.payload["message"]["id"] == 1
        assert msg.payload["message"]["role"] == "user"
        assert msg.payload["message"]["content"] == "Hello"
        assert msg.payload["message"]["user_id"] == 456

    def test_create_typing_event(self):
        """Should create typing event."""
        msg = create_typing_event(
            conversation_id=123,
            user_id=456,
            is_typing=True,
        )

        assert msg.type == MessageTypes.USER_TYPING
        assert msg.payload["conversation_id"] == 123
        assert msg.payload["user_id"] == 456
        assert msg.payload["is_typing"] is True

    def test_create_error_event(self):
        """Should create error event."""
        msg = create_error_event(
            error="Something went wrong",
            code="ERROR_CODE",
        )

        assert msg.type == MessageTypes.ERROR
        assert msg.payload["error"] == "Something went wrong"
        assert msg.payload["code"] == "ERROR_CODE"


class TestMessageTypes:
    """Tests for MessageTypes constants."""

    def test_message_type_values(self):
        """Should have expected message type constants."""
        assert MessageTypes.NEW_MESSAGE == "new_message"
        assert MessageTypes.USER_TYPING == "user_typing"
        assert MessageTypes.ERROR == "error"
        assert MessageTypes.PING == "ping"
        assert MessageTypes.PONG == "pong"
