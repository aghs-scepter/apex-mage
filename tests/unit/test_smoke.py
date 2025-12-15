"""Smoke tests to verify pytest infrastructure works correctly."""

import pytest


class TestSmokeSync:
    """Synchronous smoke tests."""

    def test_basic_assertion(self) -> None:
        """Verify basic test execution works."""
        assert True

    def test_arithmetic(self) -> None:
        """Verify pytest can run simple assertions."""
        assert 2 + 2 == 4

    def test_string_operations(self) -> None:
        """Verify string assertions work."""
        message = "apex-mage"
        assert "apex" in message
        assert message.startswith("apex")


class TestSmokeAsync:
    """Asynchronous smoke tests to verify pytest-asyncio works."""

    @pytest.mark.asyncio
    async def test_async_basic(self) -> None:
        """Verify async test execution works."""
        result = await self._async_identity(42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_async_string(self) -> None:
        """Verify async tests can handle string operations."""
        result = await self._async_upper("hello")
        assert result == "HELLO"

    async def _async_identity(self, value: int) -> int:
        """Return the input value (helper for async testing)."""
        return value

    async def _async_upper(self, value: str) -> str:
        """Return uppercase string (helper for async testing)."""
        return value.upper()


class TestFixtures:
    """Tests to verify fixtures work correctly."""

    def test_in_memory_db_fixture(self, in_memory_db) -> None:
        """Verify the in-memory database fixture works."""
        cursor = in_memory_db.cursor()
        cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("INSERT INTO test (name) VALUES (?)", ("test_value",))
        in_memory_db.commit()

        cursor.execute("SELECT name FROM test WHERE id = 1")
        row = cursor.fetchone()
        assert row["name"] == "test_value"

    def test_sample_user_data_fixture(self, sample_user_data) -> None:
        """Verify the sample user data fixture provides expected data."""
        assert "user_id" in sample_user_data
        assert "username" in sample_user_data
        assert sample_user_data["username"] == "test_user"

    @pytest.mark.asyncio
    async def test_async_db_fixture(self, async_in_memory_db) -> None:
        """Verify the async database fixture works in async context."""
        cursor = async_in_memory_db.cursor()
        cursor.execute("SELECT 1 as value")
        row = cursor.fetchone()
        assert row["value"] == 1
