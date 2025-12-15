"""Entry point for the HTTP API server.

This module provides the Uvicorn entrypoint for running the FastAPI
application as a standalone server.

Usage:
    # Development (with auto-reload):
    python api_main.py

    # Or directly with uvicorn:
    uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

    # Production:
    uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --workers 4
"""

import os

import uvicorn

from src.core.logging import configure_logging

# Configure structured logging before importing app
configure_logging()

if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    workers = int(os.getenv("API_WORKERS", "1"))

    # Run with uvicorn
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # Can't use workers with reload
    )
