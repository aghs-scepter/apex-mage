"""Discord bot core - setup and lifecycle management."""

from os import getenv
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from src.adapters import GCSAdapter, RepositoryAdapter, SQLiteRepository
from src.core.conversation import ContextBuilder
from src.core.logging import get_logger
from src.core.rate_limit import (
    InMemoryRateLimitStorage,
    RateLimit,
    SlidingWindowRateLimiter,
)
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.fal_provider import FalAIProvider

if TYPE_CHECKING:
    from src.core.providers import AIProvider, ImageProvider

logger = get_logger(__name__)


class DiscordBot(discord.Client):
    """Discord bot with AI providers and database integration.

    Attributes:
        tree: The command tree for slash commands.
    """

    def __init__(self) -> None:
        """Initialize the Discord bot with required intents."""
        intents = discord.Intents.default()
        intents.messages = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._repository: SQLiteRepository | None = None
        self._repo_adapter: RepositoryAdapter | None = None
        self._ai_provider: AIProvider | None = None
        self._image_provider: ImageProvider | None = None
        self._context_builder: ContextBuilder | None = None
        self._rate_limiter: SlidingWindowRateLimiter | None = None
        self._gcs_adapter: GCSAdapter | None = None

    @property
    def repo(self) -> RepositoryAdapter:
        """Get the repository adapter, raising if not initialized."""
        if self._repo_adapter is None:
            raise RuntimeError(
                "Repository not initialized. setup_hook must complete first."
            )
        return self._repo_adapter

    @property
    def ai_provider(self) -> "AIProvider":
        """Get the AI provider, raising if not initialized."""
        if self._ai_provider is None:
            raise RuntimeError(
                "AI provider not initialized. setup_hook must complete first."
            )
        return self._ai_provider

    @property
    def image_provider(self) -> "ImageProvider":
        """Get the image provider, raising if not initialized."""
        if self._image_provider is None:
            raise RuntimeError(
                "Image provider not initialized. setup_hook must complete first."
            )
        return self._image_provider

    @property
    def context_builder(self) -> ContextBuilder:
        """Get the context builder, raising if not initialized."""
        if self._context_builder is None:
            raise RuntimeError(
                "Context builder not initialized. setup_hook must complete first."
            )
        return self._context_builder

    @property
    def rate_limiter(self) -> SlidingWindowRateLimiter:
        """Get the rate limiter, raising if not initialized."""
        if self._rate_limiter is None:
            raise RuntimeError(
                "Rate limiter not initialized. setup_hook must complete first."
            )
        return self._rate_limiter

    @property
    def gcs_adapter(self) -> GCSAdapter:
        """Get the GCS adapter, raising if not initialized."""
        if self._gcs_adapter is None:
            raise RuntimeError(
                "GCS adapter not initialized. setup_hook must complete first."
            )
        return self._gcs_adapter

    async def setup_hook(self) -> None:
        """Initialize providers and sync commands with Discord."""
        # Initialize repository
        self._repository = SQLiteRepository("data/app.db")
        await self._repository.connect()
        self._repo_adapter = RepositoryAdapter(self._repository)
        await self._repo_adapter.validate_vendors()
        logger.info("repository_initialized", db_path="data/app.db")

        # Initialize AI providers
        self._ai_provider = AnthropicProvider(api_key=getenv("ANTHROPIC_API_KEY"))
        self._image_provider = FalAIProvider(api_key=getenv("FAL_KEY"))
        logger.info("ai_providers_initialized", providers=["anthropic", "fal"])

        # Initialize GCS adapter for cloud storage uploads
        self._gcs_adapter = GCSAdapter()
        logger.info("gcs_adapter_initialized")

        # Initialize context builder for conversation windowing
        self._context_builder = ContextBuilder(max_messages=50, max_tokens=100000)
        logger.info("context_builder_initialized", max_messages=50, max_tokens=100000)

        # Initialize rate limiter with in-memory storage
        chat_rate_limit = int(getenv("ANTHROPIC_RATE_LIMIT", "30"))
        image_rate_limit = int(getenv("FAL_RATE_LIMIT", "8"))
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

        # Sync commands with Discord
        await self.tree.sync()

    async def close(self) -> None:
        """Clean up resources when the client is closing."""
        if self._repository is not None:
            await self._repository.close()
            logger.info("repository_closed")
        await super().close()

    async def register_commands(self, guild: discord.Guild) -> None:
        """Register commands for a specific guild.

        Args:
            guild: The guild to register commands for.
        """
        await self.tree.sync(guild=guild)
        await self.change_presence(
            activity=discord.CustomActivity(name="/help for commands")
        )
        logger.info("commands_registered", guild=guild.name, guild_id=guild.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Handle command registration when joining a new guild.

        Args:
            guild: The guild the bot has joined.
        """
        await self.register_commands(guild)
        logger.info("guild_joined", guild=guild.name, guild_id=guild.id)


def create_bot() -> DiscordBot:
    """Create and return a configured Discord bot instance."""
    return DiscordBot()
