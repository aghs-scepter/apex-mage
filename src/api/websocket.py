"""WebSocket support for real-time conversation updates.

This module provides WebSocket functionality for pushing real-time updates
to connected web clients when messages are sent via Discord or the API.

Example:
    from src.api.websocket import ConnectionManager

    manager = ConnectionManager()

    @router.websocket("/ws/{conversation_id}")
    async def websocket_endpoint(websocket: WebSocket, conversation_id: int):
        await manager.connect(websocket, conversation_id)
        try:
            while True:
                data = await websocket.receive_text()
                # Handle incoming messages
        except WebSocketDisconnect:
            manager.disconnect(websocket, conversation_id)
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class WebSocketMessage:
    """A message sent over WebSocket.

    Attributes:
        type: The message type (e.g., "message", "typing", "presence").
        payload: The message data.
        timestamp: When the message was created.
    """

    type: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "type": self.type,
                "payload": self.payload,
                "timestamp": self.timestamp.isoformat(),
            }
        )


class ConnectionManager:
    """Manages WebSocket connections for real-time updates.

    Maintains a mapping of conversation IDs to connected WebSocket clients,
    allowing targeted message broadcasting to specific conversations.
    """

    def __init__(self) -> None:
        """Initialize the connection manager."""
        # conversation_id -> list of connected websockets
        self._connections: dict[int, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, conversation_id: int) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: The WebSocket connection to register.
            conversation_id: The conversation ID to subscribe to.
        """
        await websocket.accept()
        async with self._lock:
            if conversation_id not in self._connections:
                self._connections[conversation_id] = []
            self._connections[conversation_id].append(websocket)

        logger.info(
            "websocket_connected",
            conversation_id=conversation_id,
            total_connections=len(self._connections.get(conversation_id, [])),
        )

    async def disconnect(self, websocket: WebSocket, conversation_id: int) -> None:
        """Unregister a WebSocket connection.

        Args:
            websocket: The WebSocket connection to unregister.
            conversation_id: The conversation ID that was subscribed to.
        """
        async with self._lock:
            if conversation_id in self._connections:
                try:
                    self._connections[conversation_id].remove(websocket)
                except ValueError:
                    pass
                if not self._connections[conversation_id]:
                    del self._connections[conversation_id]

        logger.info(
            "websocket_disconnected",
            conversation_id=conversation_id,
            total_connections=len(self._connections.get(conversation_id, [])),
        )

    async def send_to_conversation(
        self, conversation_id: int, message: WebSocketMessage
    ) -> int:
        """Send a message to all clients subscribed to a conversation.

        Args:
            conversation_id: The conversation ID to broadcast to.
            message: The message to send.

        Returns:
            Number of clients the message was sent to.
        """
        json_message = message.to_json()
        sent_count = 0
        disconnected: list[WebSocket] = []

        async with self._lock:
            connections = self._connections.get(conversation_id, []).copy()

        for websocket in connections:
            try:
                await websocket.send_text(json_message)
                sent_count += 1
            except Exception as e:
                logger.warning(
                    "websocket_send_failed",
                    conversation_id=conversation_id,
                    error=str(e),
                )
                disconnected.append(websocket)

        # Clean up disconnected sockets
        for websocket in disconnected:
            await self.disconnect(websocket, conversation_id)

        return sent_count

    async def broadcast(self, message: WebSocketMessage) -> int:
        """Broadcast a message to all connected clients.

        Args:
            message: The message to broadcast.

        Returns:
            Number of clients the message was sent to.
        """
        json_message = message.to_json()
        sent_count = 0
        disconnected: list[tuple[WebSocket, int]] = []

        async with self._lock:
            all_connections = [
                (ws, conv_id)
                for conv_id, websockets in self._connections.items()
                for ws in websockets
            ]

        for websocket, conv_id in all_connections:
            try:
                await websocket.send_text(json_message)
                sent_count += 1
            except Exception as e:
                logger.warning("websocket_broadcast_failed", error=str(e))
                disconnected.append((websocket, conv_id))

        # Clean up disconnected sockets
        for websocket, conv_id in disconnected:
            await self.disconnect(websocket, conv_id)

        return sent_count

    def get_connection_count(self, conversation_id: int | None = None) -> int:
        """Get the number of connected clients.

        Args:
            conversation_id: Optional conversation ID to filter by.
                If None, returns total connections across all conversations.

        Returns:
            Number of connected clients.
        """
        if conversation_id is not None:
            return len(self._connections.get(conversation_id, []))
        return sum(len(conns) for conns in self._connections.values())

    def get_active_conversations(self) -> list[int]:
        """Get list of conversation IDs with active connections.

        Returns:
            List of conversation IDs.
        """
        return list(self._connections.keys())


# Global connection manager instance
manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    return manager


# Message type constants
class MessageTypes:
    """WebSocket message type constants."""

    # Conversation events
    NEW_MESSAGE = "new_message"
    MESSAGE_UPDATED = "message_updated"
    MESSAGE_DELETED = "message_deleted"
    CONVERSATION_CLEARED = "conversation_cleared"

    # Presence events
    USER_TYPING = "user_typing"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"

    # System events
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


# Helper functions for creating common messages
def create_new_message_event(
    conversation_id: int,
    message_id: int,
    role: str,
    content: str,
    user_id: int | None = None,
) -> WebSocketMessage:
    """Create a new message event.

    Args:
        conversation_id: The conversation ID.
        message_id: The message ID.
        role: The message role (user/assistant).
        content: The message content.
        user_id: Optional user ID.

    Returns:
        WebSocketMessage to broadcast.
    """
    return WebSocketMessage(
        type=MessageTypes.NEW_MESSAGE,
        payload={
            "conversation_id": conversation_id,
            "message": {
                "id": message_id,
                "role": role,
                "content": content,
                "user_id": user_id,
            },
        },
    )


def create_typing_event(
    conversation_id: int,
    user_id: int,
    is_typing: bool = True,
) -> WebSocketMessage:
    """Create a typing indicator event.

    Args:
        conversation_id: The conversation ID.
        user_id: The user ID who is typing.
        is_typing: Whether the user is currently typing.

    Returns:
        WebSocketMessage to broadcast.
    """
    return WebSocketMessage(
        type=MessageTypes.USER_TYPING,
        payload={
            "conversation_id": conversation_id,
            "user_id": user_id,
            "is_typing": is_typing,
        },
    )


def create_error_event(
    error: str,
    code: str | None = None,
) -> WebSocketMessage:
    """Create an error event.

    Args:
        error: The error message.
        code: Optional error code.

    Returns:
        WebSocketMessage to send.
    """
    return WebSocketMessage(
        type=MessageTypes.ERROR,
        payload={
            "error": error,
            "code": code,
        },
    )
