"""API routes package.

This module contains all route handlers for the HTTP API.
"""

from src.api.routes.auth import router as auth_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.health import router as health_router
from src.api.routes.images import router as images_router
from src.api.routes.websocket import router as websocket_router

__all__ = [
    "auth_router",
    "conversations_router",
    "health_router",
    "images_router",
    "websocket_router",
]
