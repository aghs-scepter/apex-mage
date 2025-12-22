"""Unit tests for SerpAPI provider.

Tests the SerpAPI Google Image Search provider implementation including:
- Successful response parsing
- Error handling for missing API key
- Error handling for API failures
- Network error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.providers.serpapi_provider import (
    GoogleImageResult,
    SerpAPIError,
    search_google_images,
)


class TestGoogleImageResult:
    """Tests for GoogleImageResult dataclass."""

    def test_create_with_all_fields(self) -> None:
        """Test creating a result with all fields populated."""
        result = GoogleImageResult(
            url="https://example.com/image.jpg",
            thumbnail_url="https://example.com/thumb.jpg",
            title="Test Image",
            source_url="https://example.com/page",
        )
        assert result.url == "https://example.com/image.jpg"
        assert result.thumbnail_url == "https://example.com/thumb.jpg"
        assert result.title == "Test Image"
        assert result.source_url == "https://example.com/page"

    def test_create_with_optional_fields_none(self) -> None:
        """Test creating a result with optional fields as None."""
        result = GoogleImageResult(
            url="https://example.com/image.jpg",
            thumbnail_url=None,
            title=None,
            source_url=None,
        )
        assert result.url == "https://example.com/image.jpg"
        assert result.thumbnail_url is None
        assert result.title is None
        assert result.source_url is None


class TestSearchGoogleImages:
    """Tests for search_google_images function."""

    @pytest.fixture
    def mock_serpapi_response(self) -> dict:
        """Create a mock SerpAPI response."""
        return {
            "images_results": [
                {
                    "original": "https://example.com/image1.jpg",
                    "thumbnail": "https://example.com/thumb1.jpg",
                    "title": "Image One",
                    "link": "https://example.com/page1",
                },
                {
                    "original": "https://example.com/image2.jpg",
                    "thumbnail": "https://example.com/thumb2.jpg",
                    "title": "Image Two",
                    "link": "https://example.com/page2",
                },
                {
                    "original": "https://example.com/image3.jpg",
                    "thumbnail": None,
                    "title": None,
                    "link": None,
                },
            ]
        }

    @pytest.mark.asyncio
    async def test_successful_search_returns_results(
        self, mock_serpapi_response: dict
    ) -> None:
        """Test that successful search returns list of GoogleImageResult."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_serpapi_response)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images("cats", api_key="test-key")

            assert len(results) == 3
            assert all(isinstance(r, GoogleImageResult) for r in results)

    @pytest.mark.asyncio
    async def test_parses_image_urls_correctly(
        self, mock_serpapi_response: dict
    ) -> None:
        """Test that image URLs are correctly extracted from response."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_serpapi_response)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images("cats", api_key="test-key")

            assert results[0].url == "https://example.com/image1.jpg"
            assert results[1].url == "https://example.com/image2.jpg"
            assert results[2].url == "https://example.com/image3.jpg"

    @pytest.mark.asyncio
    async def test_parses_metadata_correctly(
        self, mock_serpapi_response: dict
    ) -> None:
        """Test that metadata fields are correctly extracted."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_serpapi_response)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images("cats", api_key="test-key")

            # First result has all metadata
            assert results[0].thumbnail_url == "https://example.com/thumb1.jpg"
            assert results[0].title == "Image One"
            assert results[0].source_url == "https://example.com/page1"

            # Third result has None for optional fields
            assert results[2].thumbnail_url is None
            assert results[2].title is None
            assert results[2].source_url is None

    @pytest.mark.asyncio
    async def test_respects_num_results_parameter(self) -> None:
        """Test that num_results limits the returned results."""
        many_results = {
            "images_results": [
                {
                    "original": f"https://example.com/image{i}.jpg",
                    "thumbnail": f"https://example.com/thumb{i}.jpg",
                    "title": f"Image {i}",
                    "link": f"https://example.com/page{i}",
                }
                for i in range(20)
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=many_results)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images(
                "cats", num_results=5, api_key="test-key"
            )

            assert len(results) == 5

    @pytest.mark.asyncio
    async def test_skips_results_without_original_url(self) -> None:
        """Test that results without 'original' URL are skipped."""
        response_with_missing_urls = {
            "images_results": [
                {
                    "original": "https://example.com/image1.jpg",
                    "title": "Valid Image",
                },
                {
                    # Missing 'original' field
                    "thumbnail": "https://example.com/thumb2.jpg",
                    "title": "Invalid Image",
                },
                {
                    "original": "https://example.com/image3.jpg",
                    "title": "Another Valid Image",
                },
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_with_missing_urls)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images("cats", api_key="test-key")

            assert len(results) == 2
            assert results[0].url == "https://example.com/image1.jpg"
            assert results[1].url == "https://example.com/image3.jpg"

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self) -> None:
        """Test that empty API response returns empty list."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            results = await search_google_images("cats", api_key="test-key")

            assert results == []


class TestMissingAPIKey:
    """Tests for missing API key handling."""

    @pytest.mark.asyncio
    async def test_raises_value_error_when_no_api_key(self) -> None:
        """Test that ValueError is raised when no API key is available."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                await search_google_images("cats")

            assert "SERPAPI_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_uses_env_var_when_no_parameter(self) -> None:
        """Test that environment variable is used when api_key not provided."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "env-key"}), patch(
            "aiohttp.ClientSession"
        ) as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            # Should not raise - uses env var
            await search_google_images("cats")

            # Verify the request was made with the env key
            call_kwargs = mock_session.get.call_args
            assert "env-key" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_parameter_overrides_env_var(self) -> None:
        """Test that api_key parameter overrides environment variable."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "env-key"}), patch(
            "aiohttp.ClientSession"
        ) as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await search_google_images("cats", api_key="param-key")

            # Verify the request was made with the parameter key
            call_kwargs = mock_session.get.call_args
            assert "param-key" in str(call_kwargs)


class TestAPIErrors:
    """Tests for API error handling."""

    @pytest.mark.asyncio
    async def test_raises_serpapi_error_on_non_200_status(self) -> None:
        """Test that SerpAPIError is raised for non-200 HTTP status."""
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(SerpAPIError) as exc_info:
                await search_google_images("cats", api_key="test-key")

            assert "401" in str(exc_info.value)
            assert "Unauthorized" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_serpapi_error_on_api_error_response(self) -> None:
        """Test that SerpAPIError is raised when API returns error in response."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"error": "Invalid API key"}
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(SerpAPIError) as exc_info:
                await search_google_images("cats", api_key="test-key")

            assert "Invalid API key" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_serpapi_error_on_rate_limit(self) -> None:
        """Test that SerpAPIError is raised on rate limit (429)."""
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="Rate limit exceeded")

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(SerpAPIError) as exc_info:
                await search_google_images("cats", api_key="test-key")

            assert "429" in str(exc_info.value)


class TestNetworkErrors:
    """Tests for network error handling."""

    @pytest.mark.asyncio
    async def test_raises_serpapi_error_on_connection_error(self) -> None:
        """Test that SerpAPIError is raised on connection failure."""
        import aiohttp

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(
                side_effect=aiohttp.ClientError("Connection failed")
            )
            mock_session_class.return_value = mock_session

            with pytest.raises(SerpAPIError) as exc_info:
                await search_google_images("cats", api_key="test-key")

            assert "Network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_serpapi_error_on_timeout(self) -> None:
        """Test that SerpAPIError is raised on timeout."""
        import aiohttp

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(
                side_effect=aiohttp.ClientError("Request timeout")
            )
            mock_session_class.return_value = mock_session

            with pytest.raises(SerpAPIError) as exc_info:
                await search_google_images("cats", api_key="test-key")

            assert "Network error" in str(exc_info.value)


class TestRequestParameters:
    """Tests for request parameter handling."""

    @pytest.mark.asyncio
    async def test_passes_correct_engine_parameter(self) -> None:
        """Test that 'google_images' engine is used."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await search_google_images("cats", api_key="test-key")

            call_args = mock_session.get.call_args
            params = call_args.kwargs.get("params", {})
            assert params["engine"] == "google_images"

    @pytest.mark.asyncio
    async def test_passes_query_parameter(self) -> None:
        """Test that search query is passed correctly."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await search_google_images("cute puppies", api_key="test-key")

            call_args = mock_session.get.call_args
            params = call_args.kwargs.get("params", {})
            assert params["q"] == "cute puppies"

    @pytest.mark.asyncio
    async def test_passes_num_results_parameter(self) -> None:
        """Test that num parameter is passed correctly."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await search_google_images("cats", num_results=5, api_key="test-key")

            call_args = mock_session.get.call_args
            params = call_args.kwargs.get("params", {})
            assert params["num"] == "5"

    @pytest.mark.asyncio
    async def test_uses_correct_api_endpoint(self) -> None:
        """Test that the correct SerpAPI endpoint is used."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"images_results": []})

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await search_google_images("cats", api_key="test-key")

            call_args = mock_session.get.call_args
            url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
            assert url == "https://serpapi.com/search"
