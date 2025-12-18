"""WebSocket routes for real-time conversation updates.

These routes provide WebSocket endpoints for subscribing to
real-time updates from conversations.
"""

import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.api.auth import AuthError, decode_access_token
from src.api.websocket import (
    MessageTypes,
    WebSocketMessage,
    create_error_event,
    get_connection_manager,
)
from src.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])


async def authenticate_websocket(websocket: WebSocket) -> int | None:
    """Authenticate a WebSocket connection.

    Checks for a token in query parameters or first message.

    Args:
        websocket: The WebSocket connection.

    Returns:
        User ID if authenticated, None otherwise.
    """
    # Check query parameter
    token = websocket.query_params.get("token")
    if token:
        try:
            token_data = decode_access_token(token)
            return int(token_data.sub)
        except AuthError as e:
            logger.warning("websocket_auth_failed", error=e.message)
            return None
    return None


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(
    websocket: WebSocket,
    conversation_id: int,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for conversation updates.

    Connect to receive real-time updates for a specific conversation.
    Authentication is optional but recommended - provide a JWT token
    via the 'token' query parameter.

    Message format (JSON):
        - type: Message type (ping, typing, etc.)
        - payload: Message-specific data

    Incoming message types:
        - ping: Heartbeat message, server responds with pong
        - typing: Indicate user is typing

    Outgoing message types:
        - new_message: New message in conversation
        - user_typing: Another user is typing
        - error: Error message
        - pong: Response to ping
    """
    manager = get_connection_manager()

    # Optional authentication
    user_id: int | None = None
    if token:
        try:
            token_data = decode_access_token(token)
            user_id = int(token_data.sub)
            logger.info(
                "websocket_authenticated",
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except AuthError as e:
            logger.warning(
                "websocket_auth_failed",
                error=e.message,
                conversation_id=conversation_id,
            )
            # Allow unauthenticated connections but log the failure

    await manager.connect(websocket, conversation_id)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type")
                payload = message.get("payload", {})

                if msg_type == MessageTypes.PING:
                    # Respond to ping with pong
                    pong = WebSocketMessage(type=MessageTypes.PONG, payload={})
                    await websocket.send_text(pong.to_json())

                elif msg_type == MessageTypes.USER_TYPING:
                    # Broadcast typing indicator to other clients
                    if user_id:
                        typing_msg = WebSocketMessage(
                            type=MessageTypes.USER_TYPING,
                            payload={
                                "conversation_id": conversation_id,
                                "user_id": user_id,
                                "is_typing": payload.get("is_typing", True),
                            },
                        )
                        await manager.send_to_conversation(conversation_id, typing_msg)

                else:
                    logger.warning(
                        "unknown_websocket_message",
                        type=msg_type,
                        conversation_id=conversation_id,
                    )

            except json.JSONDecodeError:
                error_msg = create_error_event(
                    "Invalid JSON message", code="INVALID_JSON"
                )
                await websocket.send_text(error_msg.to_json())

    except WebSocketDisconnect:
        await manager.disconnect(websocket, conversation_id)
        logger.info(
            "websocket_client_disconnected",
            conversation_id=conversation_id,
            user_id=user_id,
        )
    except Exception as e:
        logger.exception(
            "websocket_error",
            conversation_id=conversation_id,
            error=str(e),
        )
        await manager.disconnect(websocket, conversation_id)


@router.websocket("/ws/all")
async def global_websocket(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for all conversation updates.

    Connect to receive real-time updates across all conversations.
    Requires authentication via 'token' query parameter.
    """
    # Require authentication for global feed
    user_id: int | None = None
    if token:
        try:
            token_data = decode_access_token(token)
            user_id = int(token_data.sub)
        except AuthError as e:
            await websocket.close(code=4001, reason=f"Authentication failed: {e.message}")
            return
    else:
        await websocket.close(code=4001, reason="Authentication required")
        return

    manager = get_connection_manager()

    # Use conversation_id=0 for global subscriptions
    await manager.connect(websocket, 0)

    logger.info("global_websocket_connected", user_id=user_id)

    try:
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == MessageTypes.PING:
                    pong = WebSocketMessage(type=MessageTypes.PONG, payload={})
                    await websocket.send_text(pong.to_json())

            except json.JSONDecodeError:
                error_msg = create_error_event(
                    "Invalid JSON message", code="INVALID_JSON"
                )
                await websocket.send_text(error_msg.to_json())

    except WebSocketDisconnect:
        await manager.disconnect(websocket, 0)
        logger.info("global_websocket_disconnected", user_id=user_id)
    except Exception as e:
        logger.exception("global_websocket_error", error=str(e))
        await manager.disconnect(websocket, 0)
