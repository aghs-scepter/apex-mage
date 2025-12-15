"""Core business logic and protocols.

This module contains platform-agnostic business logic and protocol definitions
for AI providers and other core functionality.
"""

from src.core.carousel_logic import CarouselController, CarouselState
from src.core.conversation import ContextBuilder, ConversationContext
from src.core.errors import (
    ErrorCategory,
    PermanentError,
    TransientError,
    classify_error,
    is_retryable,
    retry_with_backoff,
)
from src.core.health import (
    HealthChecker,
    HealthReport,
    HealthServer,
    ServiceCheck,
    ServiceStatus,
    start_health_server,
)
from src.core.image_utils import (
    compress_image,
    format_image_response,
    image_strip_headers,
)
from src.core.logging import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
    get_logger,
    unbind_contextvars,
)
from src.core.providers import (
    AIProvider,
    ChatMessage,
    ChatResponse,
    GeneratedImage,
    ImageModifyRequest,
    ImageProvider,
    ImageRequest,
)
from src.core.rate_limit import (
    InMemoryRateLimitStorage,
    RateLimit,
    RateLimitResult,
    RateLimitStorage,
    SlidingWindowRateLimiter,
)

__all__ = [
    # Carousel
    "CarouselController",
    "CarouselState",
    # Chat/Text providers
    "AIProvider",
    "ChatMessage",
    "ChatResponse",
    # Error handling
    "ErrorCategory",
    "PermanentError",
    "TransientError",
    "classify_error",
    "is_retryable",
    "retry_with_backoff",
    # Health checks
    "HealthChecker",
    "HealthReport",
    "HealthServer",
    "ServiceCheck",
    "ServiceStatus",
    "start_health_server",
    # Image providers
    "GeneratedImage",
    "ImageModifyRequest",
    "ImageProvider",
    "ImageRequest",
    # Image utilities
    "compress_image",
    "format_image_response",
    "image_strip_headers",
    # Conversation context
    "ContextBuilder",
    "ConversationContext",
    # Logging
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "get_logger",
    "unbind_contextvars",
    # Rate limiting
    "InMemoryRateLimitStorage",
    "RateLimit",
    "RateLimitResult",
    "RateLimitStorage",
    "SlidingWindowRateLimiter",
]
