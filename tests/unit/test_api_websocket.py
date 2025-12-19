"""Tests for WebSocket functionality."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import create_access_token
from src.api.routes.websocket import router
from src.api.websocket import (
    ConnectionManager,
    MessageTypes,
    WebSocketMessage,
    create_error_event,
    create_new_message_event,
    create_typing_event,
    get_connection_manager,
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


# ============================================================================
# WebSocket Route Integration Tests
# ============================================================================


@pytest.fixture
def websocket_app() -> FastAPI:
    """Create a FastAPI app with WebSocket routes for testing."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def websocket_client(websocket_app: FastAPI) -> TestClient:
    """Create a test client for WebSocket testing."""
    return TestClient(websocket_app)


@pytest.fixture
def valid_token() -> str:
    """Create a valid JWT token for testing."""
    return create_access_token(user_id=123)


@pytest.fixture
def autocleanup_manager():
    """Ensure connection manager is clean before and after tests."""
    manager = get_connection_manager()
    # Clear any existing connections
    manager._connections.clear()
    yield manager
    # Cleanup after test
    manager._connections.clear()


class TestConversationWebSocket:
    """Tests for /ws/conversations/{conversation_id} endpoint."""

    def test_connect_without_token(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should allow connection without token."""
        with websocket_client.websocket_connect("/ws/conversations/123") as ws:
            # Connection succeeds
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_connect_with_valid_token(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should authenticate user with valid token."""
        with websocket_client.websocket_connect(
            f"/ws/conversations/123?token={valid_token}"
        ) as ws:
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_connect_with_invalid_token(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should allow connection with invalid token but log warning."""
        # Invalid token still allows connection (optional auth)
        with websocket_client.websocket_connect(
            "/ws/conversations/123?token=invalid-token"
        ) as ws:
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_ping_pong(self, websocket_client: TestClient, autocleanup_manager):
        """Should respond to ping with pong."""
        with websocket_client.websocket_connect("/ws/conversations/456") as ws:
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()

            assert response["type"] == "pong"
            assert "timestamp" in response
            assert response["payload"] == {}

    def test_typing_indicator_authenticated(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should broadcast typing indicator when authenticated."""
        with websocket_client.websocket_connect(
            f"/ws/conversations/789?token={valid_token}"
        ) as ws:
            # Send typing indicator
            ws.send_json({"type": "user_typing", "payload": {"is_typing": True}})

            # Should receive the broadcast (we're the only client)
            response = ws.receive_json()
            assert response["type"] == "user_typing"
            assert response["payload"]["conversation_id"] == 789
            assert response["payload"]["user_id"] == 123  # from token
            assert response["payload"]["is_typing"] is True

    def test_typing_indicator_unauthenticated_ignored(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should not broadcast typing indicator when not authenticated."""
        with websocket_client.websocket_connect("/ws/conversations/789") as ws:
            # Send typing indicator
            ws.send_json({"type": "user_typing", "payload": {"is_typing": True}})

            # Send ping to verify connection is still working
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()

            # Should only get pong response, no typing broadcast
            assert response["type"] == "pong"

    def test_unknown_message_type(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should handle unknown message types gracefully."""
        with websocket_client.websocket_connect("/ws/conversations/123") as ws:
            ws.send_json({"type": "unknown_type", "payload": {}})

            # Should not crash, can still ping/pong
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_invalid_json(self, websocket_client: TestClient, autocleanup_manager):
        """Should return error for invalid JSON."""
        with websocket_client.websocket_connect("/ws/conversations/123") as ws:
            ws.send_text("not valid json {{{")
            response = ws.receive_json()

            assert response["type"] == "error"
            assert response["payload"]["code"] == "INVALID_JSON"
            assert "Invalid JSON" in response["payload"]["error"]

    def test_client_disconnect(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should handle clean client disconnection."""
        manager = autocleanup_manager

        with websocket_client.websocket_connect("/ws/conversations/111") as ws:
            # Verify connection registered
            assert manager.get_connection_count(111) == 1
            ws.send_json({"type": "ping", "payload": {}})
            ws.receive_json()

        # After exiting context, connection should be cleaned up
        # Note: The cleanup happens via WebSocketDisconnect exception
        assert manager.get_connection_count(111) == 0


class TestGlobalWebSocket:
    """Tests for /ws/all endpoint."""

    def test_requires_authentication(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should reject connection without token."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with websocket_client.websocket_connect("/ws/all") as ws:
                ws.send_json({"type": "ping", "payload": {}})

        # WebSocket should be closed with code 4001
        assert exc_info.value.code == 4001

    def test_rejects_invalid_token(
        self, websocket_client: TestClient, autocleanup_manager
    ):
        """Should reject connection with invalid token."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with websocket_client.websocket_connect(
                "/ws/all?token=invalid-token"
            ) as ws:
                ws.send_json({"type": "ping", "payload": {}})

        assert exc_info.value.code == 4001

    def test_accepts_valid_token(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should accept connection with valid token."""
        with websocket_client.websocket_connect(
            f"/ws/all?token={valid_token}"
        ) as ws:
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_ping_pong(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should respond to ping with pong."""
        with websocket_client.websocket_connect(
            f"/ws/all?token={valid_token}"
        ) as ws:
            ws.send_json({"type": "ping", "payload": {}})
            response = ws.receive_json()

            assert response["type"] == "pong"
            assert response["payload"] == {}
            assert "timestamp" in response

    def test_invalid_json(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should return error for invalid JSON."""
        with websocket_client.websocket_connect(
            f"/ws/all?token={valid_token}"
        ) as ws:
            ws.send_text("{{invalid json")
            response = ws.receive_json()

            assert response["type"] == "error"
            assert response["payload"]["code"] == "INVALID_JSON"

    def test_uses_conversation_id_zero(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should register with conversation_id=0 for global subscriptions."""
        manager = autocleanup_manager

        with websocket_client.websocket_connect(
            f"/ws/all?token={valid_token}"
        ) as ws:
            # Verify connection registered with id=0
            assert manager.get_connection_count(0) == 1
            ws.send_json({"type": "ping", "payload": {}})
            ws.receive_json()

        # After disconnect
        assert manager.get_connection_count(0) == 0

    def test_client_disconnect(
        self, websocket_client: TestClient, valid_token: str, autocleanup_manager
    ):
        """Should handle clean client disconnection."""
        manager = autocleanup_manager

        with websocket_client.websocket_connect(
            f"/ws/all?token={valid_token}"
        ) as ws:
            assert manager.get_connection_count(0) == 1
            ws.send_json({"type": "ping", "payload": {}})
            ws.receive_json()

        # Connection should be cleaned up after context exit
        assert manager.get_connection_count(0) == 0
