"""Claude Haiku API utility wrapper.

This module provides reusable async functions for Claude Haiku completions,
supporting both text and vision (image) inputs. It includes retry logic with
exponential backoff for transient failures.

Example usage:
    # Text completion
    response = await haiku_complete(
        system_prompt="You are a helpful assistant.",
        user_message="What is 2 + 2?",
    )

    # Vision (image analysis)
    response = await haiku_vision(
        system_prompt="Describe this image in detail.",
        image_base64="iVBORw0KGgoAAAANSUhEUgAA...",
        user_message="What do you see?",
    )
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from anthropic import APIStatusError, AsyncAnthropic

from src.core.logging import get_logger

logger = get_logger(__name__)

# Model to use for Haiku completions
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Default timeout for API calls (30 seconds)
DEFAULT_TIMEOUT = 30.0

# Retry configuration: 1 retry with 1s then 2s backoff
MAX_RETRIES = 1
BACKOFF_DELAYS = [1.0, 2.0]


class HaikuError(Exception):
    """Error raised when Haiku API calls fail after retries."""

    pass


async def haiku_complete(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> str:
    """Complete a text prompt using Claude Haiku.

    This function sends a text completion request to Claude Haiku with
    retry logic for transient failures.

    Args:
        system_prompt: The system prompt to guide the model behavior.
        user_message: The user message/prompt to complete.
        max_tokens: Maximum number of tokens in the response. Defaults to 1024.

    Returns:
        The raw text content from the model response.

    Raises:
        HaikuError: If the API call fails after retries, or if the API key
            is missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        raise HaikuError("ANTHROPIC_API_KEY environment variable is required")

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": user_message,
        }
    ]

    return await _call_haiku_api(
        api_key=api_key,
        system_prompt=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    )


async def haiku_vision(
    system_prompt: str,
    image_base64: str,
    user_message: str | None = None,
    max_tokens: int = 1024,
    media_type: str = "image/jpeg",
) -> str:
    """Analyze an image using Claude Haiku vision capabilities.

    This function sends an image to Claude Haiku for analysis, with
    retry logic for transient failures.

    Args:
        system_prompt: The system prompt to guide the model behavior.
        image_base64: The base64-encoded image data (without data URL prefix).
        user_message: Optional text message to accompany the image. If not
            provided, the model will analyze the image based on the system prompt.
        max_tokens: Maximum number of tokens in the response. Defaults to 1024.
        media_type: The MIME type of the image. Defaults to "image/jpeg".
            Common values: "image/jpeg", "image/png", "image/gif", "image/webp".

    Returns:
        The raw text content from the model response.

    Raises:
        HaikuError: If the API call fails after retries, or if the API key
            is missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        raise HaikuError("ANTHROPIC_API_KEY environment variable is required")

    # Build the content list with image and optional text
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_base64,
            },
        }
    ]

    # Add text message if provided
    if user_message:
        content.append(
            {
                "type": "text",
                "text": user_message,
            }
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": content,
        }
    ]

    return await _call_haiku_api(
        api_key=api_key,
        system_prompt=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    )


async def _call_haiku_api(
    api_key: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    """Internal function to call the Haiku API with retry logic.

    Args:
        api_key: The Anthropic API key.
        system_prompt: The system prompt.
        messages: The messages to send.
        max_tokens: Maximum tokens in response.

    Returns:
        The text content from the response.

    Raises:
        HaikuError: If all retries fail.
    """
    client = AsyncAnthropic(
        api_key=api_key,
        timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=10.0),
    )

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )

            # Extract text content from response
            if not response.content or not hasattr(response.content[0], "text"):
                logger.error(
                    "Empty response from Haiku API",
                    extra={"attempt": attempt + 1},
                )
                raise HaikuError("Empty response from Haiku API")

            return response.content[0].text

        except APIStatusError as e:
            last_error = e
            logger.warning(
                "Haiku API error",
                extra={
                    "attempt": attempt + 1,
                    "status_code": e.status_code,
                    "message": str(e),
                },
            )

            # Retry on transient errors (429, 500, 502, 503, 529)
            if e.status_code in (429, 500, 502, 503, 529) and attempt < MAX_RETRIES:
                delay = BACKOFF_DELAYS[attempt] if attempt < len(BACKOFF_DELAYS) else 2.0
                await asyncio.sleep(delay)
                continue

            # Non-retryable error or max retries exceeded
            raise HaikuError(f"Haiku API error: {e}") from e

        except TimeoutError as e:
            last_error = e
            logger.warning(
                "Haiku API timeout",
                extra={"attempt": attempt + 1, "timeout": DEFAULT_TIMEOUT},
            )

            if attempt < MAX_RETRIES:
                delay = BACKOFF_DELAYS[attempt] if attempt < len(BACKOFF_DELAYS) else 2.0
                await asyncio.sleep(delay)
                continue

            raise HaikuError("Haiku API request timed out") from e

        except Exception as e:
            last_error = e
            logger.error(
                "Unexpected error calling Haiku API",
                extra={"attempt": attempt + 1, "error": str(e)},
            )
            raise HaikuError(f"Unexpected error: {e}") from e

    # This should not be reached, but just in case
    raise HaikuError(f"Max retries exceeded: {last_error}")
