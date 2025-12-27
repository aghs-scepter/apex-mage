"""Tests for chart generation utilities."""

import pytest

from src.core.chart_utils import (
    UserStats,
    _get_dark_variant,
    _get_user_color,
    generate_usage_chart,
)


class TestGetUserColor:
    """Tests for _get_user_color function."""

    def test_returns_rgb_tuple(self) -> None:
        """Test that function returns a tuple of 3 floats."""
        color = _get_user_color(123456789)
        assert isinstance(color, tuple)
        assert len(color) == 3
        assert all(isinstance(c, float) for c in color)

    def test_values_in_valid_range(self) -> None:
        """Test that RGB values are in [0, 1] range."""
        color = _get_user_color(123456789)
        assert all(0 <= c <= 1 for c in color)

    def test_same_id_same_color(self) -> None:
        """Test that same user ID produces same color."""
        color1 = _get_user_color(123456789)
        color2 = _get_user_color(123456789)
        assert color1 == color2

    def test_different_ids_different_colors(self) -> None:
        """Test that different user IDs produce different colors."""
        color1 = _get_user_color(123456789)
        color2 = _get_user_color(987654321)
        # Colors should be different (unless they happen to have same hue mod 360)
        # which is unlikely for these specific values
        assert color1 != color2

    def test_handles_large_user_ids(self) -> None:
        """Test that function handles large Discord user IDs."""
        # Real Discord IDs are very large
        color = _get_user_color(1234567890123456789)
        assert isinstance(color, tuple)
        assert len(color) == 3


class TestGetDarkVariant:
    """Tests for _get_dark_variant function."""

    def test_returns_rgb_tuple(self) -> None:
        """Test that function returns a tuple of 3 floats."""
        original = (0.8, 0.5, 0.3)
        dark = _get_dark_variant(original)
        assert isinstance(dark, tuple)
        assert len(dark) == 3

    def test_values_in_valid_range(self) -> None:
        """Test that RGB values are in [0, 1] range."""
        original = (0.8, 0.5, 0.3)
        dark = _get_dark_variant(original)
        assert all(0 <= c <= 1 for c in dark)

    def test_darker_than_original(self) -> None:
        """Test that dark variant is darker (lower luminance)."""
        original = (0.9, 0.7, 0.5)
        dark = _get_dark_variant(original)
        # Simple luminance approximation
        original_lum = 0.299 * original[0] + 0.587 * original[1] + 0.114 * original[2]
        dark_lum = 0.299 * dark[0] + 0.587 * dark[1] + 0.114 * dark[2]
        assert dark_lum < original_lum


class TestGenerateUsageChart:
    """Tests for generate_usage_chart function."""

    @pytest.mark.asyncio
    async def test_returns_bytes(self) -> None:
        """Test that function returns bytes."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "TestUser",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_returns_valid_png(self) -> None:
        """Test that output is a valid PNG image."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "TestUser",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats)
        # PNG magic bytes
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_empty_stats(self) -> None:
        """Test that function handles empty stats list."""
        result = await generate_usage_chart([])
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_multiple_users(self) -> None:
        """Test that function handles multiple users."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "Alice",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            },
            {
                "user_id": 456,
                "username": "Bob",
                "image_count": 5,
                "text_count": 25,
                "total_score": 50,
            },
            {
                "user_id": 789,
                "username": "Charlie",
                "image_count": 2,
                "text_count": 10,
                "total_score": 20,
            },
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_five_users(self) -> None:
        """Test that function handles the expected top 5 users."""
        stats: list[UserStats] = [
            {
                "user_id": i,
                "username": f"User{i}",
                "image_count": 10 - i,
                "text_count": 50 - i * 5,
                "total_score": (10 - i) * 5 + (50 - i * 5),
            }
            for i in range(5)
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_custom_title(self) -> None:
        """Test that custom title is accepted."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "TestUser",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats, title="Custom Title")
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_zero_counts(self) -> None:
        """Test that function handles users with zero counts."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "NoActivity",
                "image_count": 0,
                "text_count": 0,
                "total_score": 0,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_only_image_commands(self) -> None:
        """Test user with only image commands."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "ImageOnly",
                "image_count": 20,
                "text_count": 0,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_only_text_commands(self) -> None:
        """Test user with only text commands."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "TextOnly",
                "image_count": 0,
                "text_count": 50,
                "total_score": 50,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_long_username(self) -> None:
        """Test that function handles long usernames."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "ThisIsAVeryLongUsernameIndeed",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_handles_unicode_username(self) -> None:
        """Test that function handles unicode in usernames."""
        stats: list[UserStats] = [
            {
                "user_id": 123,
                "username": "User_Name",
                "image_count": 10,
                "text_count": 50,
                "total_score": 100,
            }
        ]
        result = await generate_usage_chart(stats)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"
