"""Content screening utility using Claude Haiku.

This module provides a utility for screening search queries before allowing
them to be processed. It uses Claude Haiku to evaluate whether queries are
appropriate for Google Image search, blocking only clearly illegal or harmful
content.

The screening is permissive by design - most queries should be allowed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from anthropic import APIStatusError, AsyncAnthropic

from src.core.logging import get_logger

logger = get_logger(__name__)


def _strip_markdown_json(response: str) -> str:
    """Strip markdown code block wrappers from JSON response.

    Handles these formats:
    - ```json\\n{...}\\n``` (with language tag)
    - ```\\n{...}\\n``` (without language tag)
    - {...} (raw JSON, returned unchanged)

    Args:
        response: The response text, possibly wrapped in markdown code blocks.

    Returns:
        The extracted JSON string with code block markers removed.
    """
    response = response.strip()
    # Handle ```json ... ``` or ``` ... ```
    if response.startswith("```"):
        # Find the end of the opening fence
        first_newline = response.find("\n")
        if first_newline != -1:
            # Strip opening fence (```json or ```)
            response = response[first_newline + 1 :]
        # Strip closing fence
        if response.endswith("```"):
            response = response[:-3]
    return response.strip()


# Model to use for content screening
SCREENING_MODEL = "claude-haiku-4-5-20251001"

# System prompt for content screening
SCREENING_PROMPT = """You are a content screening assistant. Evaluate if the following search query is appropriate for a Google Image search.

Be PERMISSIVE - only block queries that are:
- Clearly illegal (CSAM, weapons instructions, drug manufacturing)
- Explicitly requesting violent/gore content
- Obviously harmful

Most queries should be ALLOWED. Normal searches for people, places, art, etc. are fine.

Respond with JSON only:
- If allowed: {"allowed": true}
- If blocked: {"allowed": false, "reason": "brief explanation"}

Query to evaluate: """


@dataclass
class ScreeningResult:
    """Result of content screening.

    Attributes:
        allowed: Whether the query is allowed to proceed.
        reason: Detailed reason when blocked, None when allowed.
    """

    allowed: bool
    reason: str | None


async def screen_search_query(query: str) -> ScreeningResult:
    """Screen a search query for inappropriate content using Claude Haiku.

    This function evaluates whether a search query is appropriate for
    Google Image search. It is permissive by design, only blocking
    clearly illegal or harmful content.

    Args:
        query: The search query to screen.

    Returns:
        ScreeningResult with allowed=True if safe, or allowed=False with
        a detailed reason explaining why the query was blocked.

    Note:
        Fails closed - if the Haiku API fails for any reason, the function
        returns allowed=False with a service unavailable message.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set, blocking query")
        return ScreeningResult(
            allowed=False,
            reason="Screening service unavailable",
        )

    client = AsyncAnthropic(api_key=api_key)

    try:
        response = await client.messages.create(
            model=SCREENING_MODEL,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": f"{SCREENING_PROMPT}{query}",
                }
            ],
        )

        # Extract content from response
        if not response.content or not hasattr(response.content[0], "text"):
            logger.error(
                "Empty response from screening API",
                query=query,
            )
            return ScreeningResult(
                allowed=False,
                reason="Screening service unavailable",
            )

        response_text = response.content[0].text.strip()

        # Strip markdown code blocks if present (Haiku sometimes wraps JSON)
        response_text = _strip_markdown_json(response_text)

        # Parse JSON response
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse screening response as JSON",
                query=query,
                response=response_text,
                error=str(e),
            )
            return ScreeningResult(
                allowed=False,
                reason="Screening service unavailable",
            )

        # Validate response structure
        if "allowed" not in result:
            logger.error(
                "Screening response missing 'allowed' field",
                query=query,
                response=result,
            )
            return ScreeningResult(
                allowed=False,
                reason="Screening service unavailable",
            )

        if result["allowed"]:
            logger.debug("Query allowed", query=query)
            return ScreeningResult(allowed=True, reason=None)
        else:
            reason = result.get("reason", "Query blocked by content screening")
            logger.info(
                "Query blocked by screening",
                query=query,
                reason=reason,
            )
            return ScreeningResult(allowed=False, reason=reason)

    except APIStatusError as e:
        logger.error(
            "Anthropic API error during screening",
            query=query,
            status_code=e.status_code,
            error=str(e),
        )
        return ScreeningResult(
            allowed=False,
            reason="Screening service unavailable",
        )
    except Exception as e:
        logger.error(
            "Unexpected error during screening",
            query=query,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ScreeningResult(
            allowed=False,
            reason="Screening service unavailable",
        )
