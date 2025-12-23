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
from typing import Any, cast

import httpx
from anthropic import APIStatusError, AsyncAnthropic
from anthropic.types import MessageParam

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
                messages=cast(list[MessageParam], messages),
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


# System prompt for image description optimized for image generation models
IMAGE_DESCRIPTION_SYSTEM_PROMPT = """You are an image description expert. Your task is to describe images in a way that is optimized for image generation models (like fal.ai, Stable Diffusion, etc).

Requirements:
- Start with style descriptions (art style, colors, lighting, mood) at the FRONT of your output
- Follow with a detailed description of the scene, subjects, and composition
- Write a single paragraph with no line breaks
- Be concise but detailed - aim for 2-4 sentences
- Avoid flowery or poetic language - be direct and descriptive
- Focus on visual elements that would help an image model recreate the image

Example output format:
'Digital art style, vibrant colors, soft lighting. A tabby cat sits on a wooden chair in a sunlit room, looking directly at the camera with green eyes.'"""


class ImageDescriptionError(HaikuError):
    """Error raised when image description fails."""

    pass


async def haiku_describe_image(
    image_base64: str,
    media_type: str = "image/jpeg",
) -> str:
    """Generate a style-first description of an image using Claude Haiku.

    This function uses Haiku's vision capabilities to analyze an image and
    produce a description optimized for image generation models. The output
    starts with style descriptors (art style, colors, lighting) followed by
    scene details.

    Args:
        image_base64: The base64-encoded image data (without data URL prefix).
        media_type: The MIME type of the image. Defaults to "image/jpeg".
            Supported: "image/jpeg", "image/png", "image/gif", "image/webp".

    Returns:
        A style-first description of the image suitable for image generation
        model prompts.

    Raises:
        ImageDescriptionError: If the image description fails. This could be
            due to API errors, invalid image data, or content policy violations.

    Example:
        >>> description = await haiku_describe_image(image_base64="iVBORw...")
        >>> print(description)
        'Digital art style, vibrant colors, soft lighting. A tabby cat...'
    """
    try:
        description = await haiku_vision(
            system_prompt=IMAGE_DESCRIPTION_SYSTEM_PROMPT,
            image_base64=image_base64,
            user_message="Describe this image.",
            max_tokens=512,
            media_type=media_type,
        )
        return description.strip()
    except HaikuError as e:
        error_message = str(e)
        # Provide more specific error messages based on the error type
        if "API key" in error_message:
            raise ImageDescriptionError(
                "Failed to describe image: API key not configured"
            ) from e
        elif "timed out" in error_message.lower():
            raise ImageDescriptionError(
                "Failed to describe image: Request timed out"
            ) from e
        elif "Empty response" in error_message:
            raise ImageDescriptionError(
                "Failed to describe image: No description generated"
            ) from e
        else:
            raise ImageDescriptionError(
                f"Failed to describe image: {error_message}"
            ) from e


class SummarizationError(HaikuError):
    """Error raised when conversation summarization fails."""

    pass


def _format_conversation_for_summary(messages: list[dict[str, str]]) -> str:
    """Format a list of messages into a readable conversation transcript.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


async def haiku_summarize_conversation(
    messages: list[dict[str, str]],
    guidance: str | None = None,
) -> str:
    """Summarize a conversation to approximately 25% of its original length.

    This function uses Claude Haiku to compress a conversation while
    preserving the most important information according to a priority order:
    1. Key facts and explicit decisions
    2. Current active task/request
    3. User preferences mentioned
    4. Technical details relevant to ongoing work
    5. Recent context over old context

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
            Example: [{"role": "user", "content": "Hello"}, ...]
        guidance: Optional focus area for the summary. If provided, the
            summary will emphasize information related to this guidance.
            Example: "the authentication bug" -> emphasizes auth-related context.

    Returns:
        A structured summary starting with "Summary of conversation:"
        that preserves essential context for continuing the conversation.

    Raises:
        SummarizationError: If the summarization fails due to API errors,
            empty input, or other issues.

    Example:
        >>> messages = [
        ...     {"role": "user", "content": "I need help with the auth bug"},
        ...     {"role": "assistant", "content": "Can you describe the symptoms?"},
        ...     {"role": "user", "content": "Users get logged out after 5 minutes"},
        ... ]
        >>> summary = await haiku_summarize_conversation(messages)
        >>> print(summary)
        'Summary of conversation: User is debugging an authentication issue...'
    """
    # Import here to avoid circular imports
    from src.core.prompts.summarization import build_summarization_prompt

    if not messages:
        raise SummarizationError("Cannot summarize empty conversation")

    # Check if any message has actual content
    has_content = any(msg.get("content", "").strip() for msg in messages)
    if not has_content:
        raise SummarizationError("Conversation contains no content")

    # Format conversation for the API
    conversation_text = _format_conversation_for_summary(messages)

    if not conversation_text.strip():
        raise SummarizationError("Conversation contains no content")

    # Build the system prompt with optional guidance
    system_prompt = build_summarization_prompt(guidance)

    try:
        # Use higher max_tokens to allow for comprehensive summary
        # Target is ~25% but we give Haiku room to work
        summary = await haiku_complete(
            system_prompt=system_prompt,
            user_message=conversation_text,
            max_tokens=2048,
        )
        return summary.strip()
    except HaikuError as e:
        error_message = str(e)
        if "API key" in error_message:
            raise SummarizationError(
                "Failed to summarize: API key not configured"
            ) from e
        elif "timed out" in error_message.lower():
            raise SummarizationError(
                "Failed to summarize: Request timed out"
            ) from e
        elif "Empty response" in error_message:
            raise SummarizationError(
                "Failed to summarize: No summary generated"
            ) from e
        else:
            raise SummarizationError(
                f"Failed to summarize: {error_message}"
            ) from e
