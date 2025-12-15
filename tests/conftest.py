"""Shared pytest fixtures for apex-mage tests."""

import sqlite3
from collections.abc import Generator

import pytest
import pytest_asyncio

from tests.mocks.providers import MockAIProvider, MockImageProvider

# Configure pytest-asyncio to use auto mode for async tests
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def in_memory_db() -> Generator[sqlite3.Connection, None, None]:
    """Provide an in-memory SQLite database connection.

    This fixture creates a fresh in-memory database for each test,
    ensuring test isolation. The connection is automatically closed
    after the test completes.

    Yields:
        sqlite3.Connection: A connection to an in-memory SQLite database.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
    yield conn
    conn.close()


@pytest.fixture
def sample_user_data() -> dict:
    """Provide sample user data for testing.

    Returns:
        dict: A dictionary containing sample user attributes.
    """
    return {
        "user_id": "123456789",
        "username": "test_user",
        "discriminator": "0001",
    }


@pytest_asyncio.fixture
async def async_in_memory_db() -> sqlite3.Connection:
    """Provide an in-memory SQLite database for async tests.

    Note: sqlite3 itself is synchronous, but this fixture can be used
    in async test functions. For true async database operations,
    consider using aiosqlite in production code.

    Returns:
        sqlite3.Connection: A connection to an in-memory SQLite database.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def mock_ai_provider() -> MockAIProvider:
    """Provide a mock AI provider for testing.

    Returns a MockAIProvider with default settings. For tests requiring
    specific responses, create the mock directly with custom responses.

    Returns:
        MockAIProvider: A mock AI provider instance.

    Example:
        def test_with_default_mock(mock_ai_provider):
            # Uses default "Mock response"
            response = await mock_ai_provider.chat([...])
            assert response.content == "Mock response"

        def test_with_custom_responses():
            # For custom responses, create directly
            provider = MockAIProvider(responses=["Custom reply"])
    """
    return MockAIProvider()


@pytest.fixture
def mock_image_provider() -> MockImageProvider:
    """Provide a mock image provider for testing.

    Returns a MockImageProvider with default settings. For tests requiring
    specific image URLs or models, create the mock directly.

    Returns:
        MockImageProvider: A mock image provider instance.

    Example:
        def test_with_default_mock(mock_image_provider):
            # Uses default mock URL
            images = await mock_image_provider.generate(...)

        def test_with_custom_urls():
            # For custom URLs, create directly
            provider = MockImageProvider(image_urls=["https://custom.com/img.png"])
    """
    return MockImageProvider()
