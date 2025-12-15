"""HTTP API package for web UI integration.

This module provides a FastAPI-based HTTP API that exposes core operations
for web clients to interact with the AI assistant.
"""

from src.api.app import create_app
from src.api.dependencies import (
    get_ai_provider,
    get_gcs_adapter,
    get_image_provider,
    get_rate_limiter,
    get_repository,
)

__all__ = [
    "create_app",
    "get_ai_provider",
    "get_gcs_adapter",
    "get_image_provider",
    "get_rate_limiter",
    "get_repository",
]
