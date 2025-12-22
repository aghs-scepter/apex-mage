"""SerpAPI Google Image Search provider implementation.

This module provides functionality for searching Google Images via SerpAPI.
It returns structured image results with URLs, thumbnails, titles, and source URLs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)


class SerpAPIError(Exception):
    """Exception raised for SerpAPI errors.

    This exception is raised when the SerpAPI request fails due to
    network errors, API errors, or other issues.
    """

    pass


@dataclass
class GoogleImageResult:
    """Represents a single Google Image search result.

    Attributes:
        url: Direct URL to the full-size image.
        thumbnail_url: URL to a thumbnail version of the image, if available.
        title: Title or alt text of the image, if available.
        source_url: URL of the page where the image was found, if available.
    """

    url: str
    thumbnail_url: str | None
    title: str | None
    source_url: str | None


async def search_google_images(
    query: str,
    num_results: int = 10,
    api_key: str | None = None,
) -> list[GoogleImageResult]:
    """Search Google Images via SerpAPI.

    Performs an image search using SerpAPI's Google Images endpoint and
    returns structured results with image URLs and metadata.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 10).
            Note: SerpAPI may return fewer results depending on the query.
        api_key: Optional API key. If not provided, reads from
            SERPAPI_API_KEY environment variable.

    Returns:
        A list of GoogleImageResult objects containing image data.

    Raises:
        ValueError: If no API key is provided and SERPAPI_API_KEY
            environment variable is not set.
        SerpAPIError: If the API request fails or returns an error.
    """
    # Get API key from parameter or environment
    effective_api_key = api_key or os.environ.get("SERPAPI_API_KEY")
    if not effective_api_key:
        raise ValueError(
            "SERPAPI_API_KEY environment variable is not set. "
            "Please set it or provide an api_key parameter."
        )

    # Build request parameters
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": effective_api_key,
        "num": str(num_results),
    }

    logger.debug("Searching Google Images for: %s", query)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://serpapi.com/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        "SerpAPI request failed with status %d: %s",
                        response.status,
                        error_text,
                    )
                    raise SerpAPIError(
                        f"SerpAPI request failed with status {response.status}: {error_text}"
                    )

                data = await response.json()

    except aiohttp.ClientError as ex:
        logger.error("Network error during SerpAPI request: %s", ex)
        raise SerpAPIError(f"Network error during SerpAPI request: {ex}") from ex

    # Check for API-level errors in response
    if "error" in data:
        error_message = data.get("error", "Unknown error")
        logger.error("SerpAPI returned error: %s", error_message)
        raise SerpAPIError(f"SerpAPI error: {error_message}")

    # Parse image results
    images_results = data.get("images_results", [])
    results: list[GoogleImageResult] = []

    for item in images_results[:num_results]:
        # Extract image data from result
        # SerpAPI returns 'original' for full-size image URL
        image_url = item.get("original")
        if not image_url:
            # Skip results without a valid image URL
            continue

        result = GoogleImageResult(
            url=image_url,
            thumbnail_url=item.get("thumbnail"),
            title=item.get("title"),
            source_url=item.get("link"),
        )
        results.append(result)

    logger.debug("Found %d image results for query: %s", len(results), query)
    return results
