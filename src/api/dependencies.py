"""FastAPI dependency injection for providers and repositories.

This module provides FastAPI dependencies that inject configured instances
of providers and repositories into route handlers.

Example:
    from fastapi import Depends
    from src.api.dependencies import get_ai_provider
    from src.core.providers import AIProvider

    @router.post("/chat")
    async def chat(
        message: str,
        ai_provider: AIProvider = Depends(get_ai_provider)
    ):
        response = await ai_provider.chat([ChatMessage(role="user", content=message)])
        return {"response": response.content}
"""

from typing import AsyncGenerator

from src.adapters import GCSAdapter, RepositoryAdapter, SQLiteRepository
from src.core.logging import get_logger
from src.core.providers import AIProvider, ImageProvider
from src.core.rate_limit import (
    InMemoryRateLimitStorage,
    RateLimit,
    SlidingWindowRateLimiter,
)

logger = get_logger(__name__)


class AppState:
    """Application state container for shared resources.

    This class holds singleton instances of providers and repositories
    that are shared across all request handlers.
    """

    def __init__(self) -> None:
        self._repository: SQLiteRepository | None = None
        self._repo_adapter: RepositoryAdapter | None = None
        self._ai_provider: AIProvider | None = None
        self._image_provider: ImageProvider | None = None
        self._rate_limiter: SlidingWindowRateLimiter | None = None
        self._gcs_adapter: GCSAdapter | None = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the app state has been initialized."""
        return self._initialized

    async def initialize(
        self,
        db_path: str = "data/app.db",
        anthropic_api_key: str | None = None,
        fal_api_key: str | None = None,
        chat_rate_limit: int = 30,
        image_rate_limit: int = 8,
    ) -> None:
        """Initialize all providers and repositories.

        Args:
            db_path: Path to the SQLite database.
            anthropic_api_key: Anthropic API key (or None to use env var).
            fal_api_key: Fal.AI API key (or None to use env var).
            chat_rate_limit: Max chat requests per hour.
            image_rate_limit: Max image requests per hour.
        """
        if self._initialized:
            logger.warning("app_state_already_initialized")
            return

        # Import providers here to avoid circular imports
        from src.providers.anthropic_provider import AnthropicProvider
        from src.providers.fal_provider import FalAIProvider

        # Initialize repository
        self._repository = SQLiteRepository(db_path)
        await self._repository.connect()
        self._repo_adapter = RepositoryAdapter(self._repository)
        await self._repo_adapter.validate_vendors()
        logger.info("repository_initialized", db_path=db_path)

        # Initialize AI providers
        self._ai_provider = AnthropicProvider(api_key=anthropic_api_key)
        self._image_provider = FalAIProvider(api_key=fal_api_key)
        logger.info("ai_providers_initialized", providers=["anthropic", "fal"])

        # Initialize GCS adapter
        self._gcs_adapter = GCSAdapter()
        logger.info("gcs_adapter_initialized")

        # Initialize rate limiter
        storage = InMemoryRateLimitStorage()
        self._rate_limiter = SlidingWindowRateLimiter(
            storage,
            {
                "chat": RateLimit(max_requests=chat_rate_limit, window_seconds=3600),
                "image": RateLimit(max_requests=image_rate_limit, window_seconds=3600),
            },
        )
        logger.info(
            "rate_limiter_initialized",
            chat_limit=chat_rate_limit,
            image_limit=image_rate_limit,
        )

        self._initialized = True
        logger.info("app_state_initialized")

    async def shutdown(self) -> None:
        """Clean up resources on shutdown."""
        if self._repository is not None:
            await self._repository.close()
            logger.info("repository_closed")
        self._initialized = False
        logger.info("app_state_shutdown")

    @property
    def repository(self) -> RepositoryAdapter:
        """Get the repository adapter."""
        if self._repo_adapter is None:
            raise RuntimeError("App state not initialized")
        return self._repo_adapter

    @property
    def ai_provider(self) -> AIProvider:
        """Get the AI provider."""
        if self._ai_provider is None:
            raise RuntimeError("App state not initialized")
        return self._ai_provider

    @property
    def image_provider(self) -> ImageProvider:
        """Get the image provider."""
        if self._image_provider is None:
            raise RuntimeError("App state not initialized")
        return self._image_provider

    @property
    def rate_limiter(self) -> SlidingWindowRateLimiter:
        """Get the rate limiter."""
        if self._rate_limiter is None:
            raise RuntimeError("App state not initialized")
        return self._rate_limiter

    @property
    def gcs_adapter(self) -> GCSAdapter:
        """Get the GCS adapter."""
        if self._gcs_adapter is None:
            raise RuntimeError("App state not initialized")
        return self._gcs_adapter


# Global app state instance
_app_state = AppState()


def get_app_state() -> AppState:
    """Get the global app state instance."""
    return _app_state


async def get_repository() -> AsyncGenerator[RepositoryAdapter, None]:
    """FastAPI dependency for repository adapter."""
    yield _app_state.repository


async def get_ai_provider() -> AsyncGenerator[AIProvider, None]:
    """FastAPI dependency for AI provider."""
    yield _app_state.ai_provider


async def get_image_provider() -> AsyncGenerator[ImageProvider, None]:
    """FastAPI dependency for image provider."""
    yield _app_state.image_provider


async def get_rate_limiter() -> AsyncGenerator[SlidingWindowRateLimiter, None]:
    """FastAPI dependency for rate limiter."""
    yield _app_state.rate_limiter


async def get_gcs_adapter() -> AsyncGenerator[GCSAdapter, None]:
    """FastAPI dependency for GCS adapter."""
    yield _app_state.gcs_adapter
