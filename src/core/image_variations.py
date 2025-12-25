"""Image variation generation utilities.

This module provides functions for generating image variations:
1. Same-prompt variations: regenerate with the same prompt, relying on model randomness
2. AI-remixed variations: use Haiku to slightly modify the prompt before regenerating

Both functions are designed to work with the VariationCarouselView and integrate
with the rate limiting system.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.core.haiku import HaikuError, haiku_complete
from src.core.image_utils import compress_image, image_strip_headers
from src.core.logging import get_logger
from src.core.providers import ImageRequest

if TYPE_CHECKING:
    from src.core.providers import ImageProvider
    from src.core.rate_limit import SlidingWindowRateLimiter

logger = get_logger(__name__)

# Timeout for image generation API calls (seconds)
API_TIMEOUT_SECONDS = 180

# System prompt for remixing image prompts
REMIX_SYSTEM_PROMPT = """Create a variation of this image generation prompt following these rules:

MUST PRESERVE (copy exactly):
- Any text, words, letters, or quotes that appear in the prompt
- The core subject/theme (main character, object, or scene)
- The overall artistic style and aesthetic

ALLOWED CHANGES (pick one small variation):
- Lighting (time of day, shadows, glow)
- Camera angle or perspective
- Minor details (colors, textures, background elements)
- Mood or atmosphere

IMPORTANT: If the original prompt contains specific text (like words on a sign, title text, or spoken words), you MUST include that exact text in your output.

Your response should ONLY be the modified prompt, with no additional text, explanation, or formatting."""


class VariationError(Exception):
    """Error raised when variation generation fails."""

    pass


class RateLimitExceededError(VariationError):
    """Error raised when rate limit is exceeded."""

    def __init__(self, retry_after: float | None = None) -> None:
        """Initialize the rate limit error.

        Args:
            retry_after: Seconds until the rate limit resets.
        """
        super().__init__("Rate limit exceeded for image generation")
        self.retry_after = retry_after


async def check_rate_limit(
    user_id: int,
    rate_limiter: SlidingWindowRateLimiter | None,
) -> None:
    """Check if the user is within rate limits.

    Args:
        user_id: The user ID to check.
        rate_limiter: The rate limiter to check against.

    Raises:
        RateLimitExceededError: If the rate limit is exceeded.
    """
    if rate_limiter is None:
        return

    rate_check = await rate_limiter.check(user_id, "image")
    if not rate_check.allowed:
        raise RateLimitExceededError(retry_after=rate_check.wait_seconds)


async def record_rate_limit(
    user_id: int,
    rate_limiter: SlidingWindowRateLimiter | None,
) -> None:
    """Record a rate-limited operation.

    Args:
        user_id: The user ID to record.
        rate_limiter: The rate limiter to record against.
    """
    if rate_limiter is not None:
        await rate_limiter.record(user_id, "image")


async def generate_variation_same_prompt(
    original_prompt: str,
    image_provider: ImageProvider,
    user_id: int,
    rate_limiter: SlidingWindowRateLimiter | None = None,
) -> dict[str, str]:
    """Generate an image variation using the same prompt.

    Relies on model randomness (different random seed) to produce
    a variation of the original image.

    Args:
        original_prompt: The original prompt to reuse.
        image_provider: The image provider to use for generation.
        user_id: The user ID for rate limiting.
        rate_limiter: Optional rate limiter to check/record usage.

    Returns:
        A dict with 'filename' and 'image' (base64) keys, compatible
        with the carousel view's image format.

    Raises:
        RateLimitExceededError: If the user has exceeded their rate limit.
        VariationError: If image generation fails.
    """
    # Check rate limit before generation
    await check_rate_limit(user_id, rate_limiter)

    logger.info(
        "generating_same_prompt_variation",
        prompt_length=len(original_prompt),
        user_id=user_id,
    )

    try:
        async with asyncio.timeout(API_TIMEOUT_SECONDS):
            generated_images = await image_provider.generate(
                ImageRequest(prompt=original_prompt)
            )

        if not generated_images:
            raise VariationError("No images returned from provider")

        generated_image = generated_images[0]

        if generated_image.url is None:
            raise VariationError("Generated image has no URL")

        # Convert URL to base64 and compress
        image_b64 = image_strip_headers(generated_image.url, "jpeg")
        image_b64 = await asyncio.to_thread(compress_image, image_b64)

        # Record successful generation
        await record_rate_limit(user_id, rate_limiter)

        # Determine filename based on NSFW flag
        has_nsfw = generated_image.has_nsfw_content or False
        filename = "SPOILER_variation.jpeg" if has_nsfw else "variation.jpeg"

        logger.info(
            "same_prompt_variation_generated",
            user_id=user_id,
            has_nsfw=has_nsfw,
        )

        return {
            "filename": filename,
            "image": image_b64,
        }

    except TimeoutError as e:
        logger.error(
            "variation_generation_timeout",
            user_id=user_id,
            timeout=API_TIMEOUT_SECONDS,
        )
        raise VariationError("Image generation timed out") from e
    except VariationError:
        raise
    except Exception as e:
        logger.error(
            "variation_generation_failed",
            user_id=user_id,
            error=str(e),
        )
        raise VariationError(f"Failed to generate variation: {e}") from e


async def remix_prompt(original_prompt: str) -> str:
    """Use Haiku to slightly modify an image prompt.

    Creates a small creative variation of the prompt while preserving
    the artistic style and core subject.

    Args:
        original_prompt: The original prompt to remix.

    Returns:
        The remixed prompt.

    Raises:
        VariationError: If prompt remixing fails.
    """
    user_message = f"Original: {original_prompt}\n\nRemixed prompt:"

    try:
        remixed = await haiku_complete(
            system_prompt=REMIX_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=512,
        )
        # Clean up the response - remove any quotes or extra whitespace
        remixed = remixed.strip().strip('"\'')

        logger.info(
            "prompt_remixed",
            original_length=len(original_prompt),
            remixed_length=len(remixed),
        )

        return remixed

    except HaikuError as e:
        logger.error("prompt_remix_failed", error=str(e))
        raise VariationError(f"Failed to remix prompt: {e}") from e


async def generate_variation_remixed(
    original_prompt: str,
    image_provider: ImageProvider,
    user_id: int,
    rate_limiter: SlidingWindowRateLimiter | None = None,
) -> tuple[str, dict[str, str]]:
    """Generate an image variation with an AI-remixed prompt.

    Uses Haiku to slightly modify the prompt while preserving style
    and aesthetic, then generates a new image.

    Args:
        original_prompt: The original prompt to remix.
        image_provider: The image provider to use for generation.
        user_id: The user ID for rate limiting.
        rate_limiter: Optional rate limiter to check/record usage.

    Returns:
        A tuple of (remixed_prompt, image_data) where image_data is a dict
        with 'filename' and 'image' (base64) keys.

    Raises:
        RateLimitExceededError: If the user has exceeded their rate limit.
        VariationError: If prompt remixing or image generation fails.
    """
    # Check rate limit before generation (Haiku call is cheap, image gen is expensive)
    await check_rate_limit(user_id, rate_limiter)

    logger.info(
        "generating_remixed_variation",
        prompt_length=len(original_prompt),
        user_id=user_id,
    )

    # First, remix the prompt using Haiku
    remixed_prompt = await remix_prompt(original_prompt)

    try:
        async with asyncio.timeout(API_TIMEOUT_SECONDS):
            generated_images = await image_provider.generate(
                ImageRequest(prompt=remixed_prompt)
            )

        if not generated_images:
            raise VariationError("No images returned from provider")

        generated_image = generated_images[0]

        if generated_image.url is None:
            raise VariationError("Generated image has no URL")

        # Convert URL to base64 and compress
        image_b64 = image_strip_headers(generated_image.url, "jpeg")
        image_b64 = await asyncio.to_thread(compress_image, image_b64)

        # Record successful generation
        await record_rate_limit(user_id, rate_limiter)

        # Determine filename based on NSFW flag
        has_nsfw = generated_image.has_nsfw_content or False
        filename = "SPOILER_variation.jpeg" if has_nsfw else "variation.jpeg"

        logger.info(
            "remixed_variation_generated",
            user_id=user_id,
            has_nsfw=has_nsfw,
            remixed_prompt_preview=remixed_prompt[:100],
        )

        return remixed_prompt, {
            "filename": filename,
            "image": image_b64,
        }

    except TimeoutError as e:
        logger.error(
            "remixed_variation_timeout",
            user_id=user_id,
            timeout=API_TIMEOUT_SECONDS,
        )
        raise VariationError("Image generation timed out") from e
    except VariationError:
        raise
    except Exception as e:
        logger.error(
            "remixed_variation_failed",
            user_id=user_id,
            error=str(e),
        )
        raise VariationError(f"Failed to generate remixed variation: {e}") from e
