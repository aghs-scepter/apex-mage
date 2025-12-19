"""FastAPI application factory and configuration.

This module provides the main FastAPI application with CORS configuration,
lifespan management, and route registration.

Example:
    from src.api import create_app

    app = create_app()

    # Run with uvicorn:
    # uvicorn src.api.app:app --reload
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import AppState, get_app_state
from src.api.routes import (
    auth_router,
    conversations_router,
    health_router,
    images_router,
    websocket_router,
)
from src.api.routes.auth import configure_api_key_repository
from src.core.health import HealthChecker, ServiceCheck, ServiceStatus
from src.core.logging import get_logger

logger = get_logger(__name__)

# Application version
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


def _create_health_checker(app_state: AppState) -> HealthChecker:
    """Create health checker with service checks for the API.

    Args:
        app_state: The application state container.

    Returns:
        Configured HealthChecker instance.
    """
    checker = HealthChecker(version=APP_VERSION)

    async def check_database() -> ServiceCheck:
        """Check database connectivity."""
        try:
            if not app_state.is_initialized:
                return ServiceCheck(
                    name="database",
                    status=ServiceStatus.UNHEALTHY,
                    message="App state not initialized",
                )
            # Check that repository is accessible
            _ = app_state.repository
            return ServiceCheck(
                name="database",
                status=ServiceStatus.HEALTHY,
                message="Connected",
            )
        except Exception as ex:
            return ServiceCheck(
                name="database",
                status=ServiceStatus.UNHEALTHY,
                message=str(ex),
            )

    async def check_anthropic() -> ServiceCheck:
        """Check Anthropic API configuration."""
        try:
            if not app_state.is_initialized:
                return ServiceCheck(
                    name="anthropic",
                    status=ServiceStatus.UNHEALTHY,
                    message="App state not initialized",
                )
            _ = app_state.ai_provider
            if os.getenv("ANTHROPIC_API_KEY"):
                return ServiceCheck(
                    name="anthropic",
                    status=ServiceStatus.HEALTHY,
                    message="API key configured",
                )
            return ServiceCheck(
                name="anthropic",
                status=ServiceStatus.DEGRADED,
                message="API key not configured (using env var)",
            )
        except Exception as ex:
            return ServiceCheck(
                name="anthropic",
                status=ServiceStatus.UNHEALTHY,
                message=str(ex),
            )

    async def check_fal() -> ServiceCheck:
        """Check Fal.AI API configuration."""
        try:
            if not app_state.is_initialized:
                return ServiceCheck(
                    name="fal",
                    status=ServiceStatus.UNHEALTHY,
                    message="App state not initialized",
                )
            _ = app_state.image_provider
            if os.getenv("FAL_KEY"):
                return ServiceCheck(
                    name="fal",
                    status=ServiceStatus.HEALTHY,
                    message="API key configured",
                )
            return ServiceCheck(
                name="fal",
                status=ServiceStatus.DEGRADED,
                message="API key not configured (using env var)",
            )
        except Exception as ex:
            return ServiceCheck(
                name="fal",
                status=ServiceStatus.UNHEALTHY,
                message=str(ex),
            )

    checker.add_check("database", check_database)
    checker.add_check("anthropic", check_anthropic)
    checker.add_check("fal", check_fal)

    return checker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle - startup and shutdown.

    This context manager initializes resources on startup and
    cleans them up on shutdown.
    """
    # Startup
    logger.info("api_starting")

    app_state = get_app_state()

    # Get configuration from environment
    db_path = os.getenv("DATABASE_PATH", "data/app.db")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    fal_key = os.getenv("FAL_KEY")
    chat_limit = int(os.getenv("ANTHROPIC_RATE_LIMIT", "30"))
    image_limit = int(os.getenv("FAL_RATE_LIMIT", "8"))

    await app_state.initialize(
        db_path=db_path,
        anthropic_api_key=anthropic_key,
        fal_api_key=fal_key,
        chat_rate_limit=chat_limit,
        image_rate_limit=image_limit,
    )

    # Configure API key repository for persistent storage
    configure_api_key_repository(app_state.sqlite_repository)

    # Create health checker and attach to app state
    app.state.health_checker = _create_health_checker(app_state)

    logger.info("api_started", version=APP_VERSION)

    yield

    # Shutdown
    logger.info("api_shutting_down")
    await app_state.shutdown()
    logger.info("api_shutdown_complete")


def create_app(
    title: str = "Apex Mage API",
    description: str = "HTTP API for AI-powered conversational assistant",
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        title: API title for OpenAPI docs.
        description: API description for OpenAPI docs.
        cors_origins: List of allowed CORS origins. Defaults to ["*"] in
            development, should be restricted in production.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title=title,
        description=description,
        version=APP_VERSION,
        lifespan=lifespan,
    )

    # Configure CORS
    if cors_origins is None:
        # Default: allow all origins in development
        # In production, this should be configured via environment variable
        cors_origins_env = os.getenv("CORS_ORIGINS", "*")
        if cors_origins_env == "*":
            cors_origins = ["*"]
        else:
            cors_origins = [origin.strip() for origin in cors_origins_env.split(",")]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(images_router)
    app.include_router(websocket_router)

    logger.info(
        "app_configured",
        title=title,
        cors_origins=cors_origins,
    )

    return app


# Default app instance for uvicorn
app = create_app()
