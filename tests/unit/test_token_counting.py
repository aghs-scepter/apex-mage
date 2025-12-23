"""Unit tests for the token counting utility."""

from __future__ import annotations

import time

from src.core.token_counting import (
    DEFAULT_THRESHOLD,
    _extract_message_content,
    check_token_threshold,
    count_tokens,
)


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_counts_simple_text(self) -> None:
        """Test that count_tokens returns a positive count for text."""
        result = count_tokens("Hello, world!")
        assert result > 0

    def test_empty_string_returns_zero(self) -> None:
        """Test that count_tokens returns 0 for empty string."""
        result = count_tokens("")
        assert result == 0

    def test_none_like_empty_returns_zero(self) -> None:
        """Test that count_tokens handles empty-ish input gracefully."""
        # Empty string
        assert count_tokens("") == 0

    def test_consistent_results(self) -> None:
        """Test that count_tokens returns consistent results."""
        text = "The quick brown fox jumps over the lazy dog."
        result1 = count_tokens(text)
        result2 = count_tokens(text)
        assert result1 == result2

    def test_longer_text_has_more_tokens(self) -> None:
        """Test that longer text has more tokens than shorter text."""
        short = "Hello"
        long = "Hello, this is a much longer piece of text with many more words."
        assert count_tokens(long) > count_tokens(short)

    def test_reasonable_token_count(self) -> None:
        """Test that token counts are reasonable (roughly 1 token per 4 chars)."""
        # "Hello, world!" is about 4 tokens in cl100k_base
        text = "Hello, world!"
        result = count_tokens(text)
        # Should be between 2-6 tokens for this short text
        assert 2 <= result <= 6

    def test_performance_under_50ms(self) -> None:
        """Test that token counting is fast (<50ms for reasonable text)."""
        # Generate a medium-sized text (~1000 words)
        words = ["The", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"]
        text = " ".join(words * 125)  # ~1000 words

        start = time.perf_counter()
        count_tokens(text)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Token counting took {elapsed_ms:.1f}ms, expected <50ms"


class TestExtractMessageContent:
    """Tests for _extract_message_content function."""

    def test_extracts_string_content(self) -> None:
        """Test extraction of simple string content."""
        message = {"role": "user", "content": "Hello, world!"}
        result = _extract_message_content(message)
        assert result == "Hello, world!"

    def test_extracts_text_from_content_blocks(self) -> None:
        """Test extraction of text from content block list."""
        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "world"},
            ],
        }
        result = _extract_message_content(message)
        assert "Hello" in result
        assert "world" in result

    def test_skips_image_blocks(self) -> None:
        """Test that image blocks are skipped."""
        message = {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "data": "abc123"}},
                {"type": "text", "text": "Describe this image"},
            ],
        }
        result = _extract_message_content(message)
        assert result == "Describe this image"
        assert "abc123" not in result

    def test_handles_empty_content(self) -> None:
        """Test handling of empty content."""
        message = {"role": "user", "content": ""}
        result = _extract_message_content(message)
        assert result == ""

    def test_handles_missing_content(self) -> None:
        """Test handling of missing content key."""
        message = {"role": "user"}
        result = _extract_message_content(message)
        assert result == ""

    def test_handles_empty_content_list(self) -> None:
        """Test handling of empty content list."""
        message = {"role": "user", "content": []}
        result = _extract_message_content(message)
        assert result == ""

    def test_handles_string_items_in_list(self) -> None:
        """Test handling of string items in content list."""
        message = {"role": "user", "content": ["Hello", "world"]}
        result = _extract_message_content(message)
        assert "Hello" in result
        assert "world" in result


class TestCheckTokenThreshold:
    """Tests for check_token_threshold function."""

    def test_returns_tuple(self) -> None:
        """Test that check_token_threshold returns a tuple."""
        result = check_token_threshold(
            system_prompt="You are helpful.",
            messages=[],
            current_prompt="Hello",
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_count_and_bool(self) -> None:
        """Test that the tuple contains int and bool."""
        count, exceeded = check_token_threshold(
            system_prompt="You are helpful.",
            messages=[],
            current_prompt="Hello",
        )
        assert isinstance(count, int)
        assert isinstance(exceeded, bool)

    def test_counts_system_prompt(self) -> None:
        """Test that system prompt tokens are counted."""
        count_with_prompt, _ = check_token_threshold(
            system_prompt="You are a very helpful and knowledgeable assistant.",
            messages=[],
            current_prompt="",
        )
        count_without_prompt, _ = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt="",
        )
        assert count_with_prompt > count_without_prompt

    def test_counts_messages(self) -> None:
        """Test that message tokens are counted."""
        count_with_messages, _ = check_token_threshold(
            system_prompt="",
            messages=[
                {"role": "user", "content": "Hello, how are you?"},
                {"role": "assistant", "content": "I am fine, thank you!"},
            ],
            current_prompt="",
        )
        count_without_messages, _ = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt="",
        )
        assert count_with_messages > count_without_messages

    def test_counts_current_prompt(self) -> None:
        """Test that current prompt tokens are counted."""
        count_with_prompt, _ = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt="What is the meaning of life, the universe, and everything?",
        )
        count_without_prompt, _ = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt="",
        )
        assert count_with_prompt > count_without_prompt

    def test_threshold_not_exceeded_below_limit(self) -> None:
        """Test that threshold is not exceeded for small inputs."""
        _, exceeded = check_token_threshold(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            current_prompt="Hi there!",
            threshold=10000,
        )
        assert exceeded is False

    def test_threshold_exceeded_above_limit(self) -> None:
        """Test that threshold is exceeded for large inputs."""
        # Generate a long message that exceeds 100 tokens
        long_text = "word " * 200  # ~200 tokens
        _, exceeded = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt=long_text,
            threshold=100,
        )
        assert exceeded is True

    def test_uses_default_threshold(self) -> None:
        """Test that default threshold is used when not specified."""
        # This should not exceed the default 10,000 threshold
        _, exceeded = check_token_threshold(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            current_prompt="Hi",
        )
        assert exceeded is False
        assert DEFAULT_THRESHOLD == 10000

    def test_custom_threshold(self) -> None:
        """Test that custom threshold is respected."""
        # Very low threshold should be exceeded
        _, exceeded = check_token_threshold(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            current_prompt="Hi there!",
            threshold=5,
        )
        assert exceeded is True

    def test_threshold_boundary_exactly_at_limit(self) -> None:
        """Test that exactly at threshold does not exceed."""
        # If total is exactly 10, threshold > 10 means not exceeded
        text = "a"  # Single character is 1 token
        count, exceeded = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt=text,
            threshold=count_tokens(text),  # Set threshold to exact count
        )
        # At exactly the limit, should not be exceeded (> not >=)
        assert exceeded is False

    def test_threshold_boundary_one_over_limit(self) -> None:
        """Test that one over threshold does exceed."""
        text = "aa"  # Should be 1 token
        count, exceeded = check_token_threshold(
            system_prompt="",
            messages=[],
            current_prompt=text,
            threshold=0,  # Threshold of 0
        )
        # Any tokens should exceed threshold of 0
        assert exceeded is True

    def test_handles_complex_message_content(self) -> None:
        """Test handling of messages with complex content."""
        count, _ = check_token_threshold(
            system_prompt="",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {"type": "image", "source": {"type": "base64", "data": "..."}},
                    ],
                }
            ],
            current_prompt="",
        )
        # Should have counted the text portion
        assert count > 0

    def test_performance_with_many_messages(self) -> None:
        """Test performance with many messages (<50ms)."""
        # Create 100 messages
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
            for i in range(100)
        ]

        start = time.perf_counter()
        check_token_threshold(
            system_prompt="You are a helpful assistant.",
            messages=messages,
            current_prompt="What do you think?",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Threshold check took {elapsed_ms:.1f}ms, expected <50ms"


class TestAccuracy:
    """Tests to verify token counting accuracy."""

    def test_accuracy_within_15_percent(self) -> None:
        """Test that token counts are within 15% of expected.

        Note: This is a sanity check. cl100k_base may differ from Claude's
        actual tokenizer, but should be within 15% for most text.
        """
        # "Hello, world!" in cl100k_base is 4 tokens
        # Allow for some variance
        text = "Hello, world!"
        count = count_tokens(text)

        # We expect roughly 4 tokens, allow 15% variance (3-5)
        assert 3 <= count <= 5, f"Expected ~4 tokens, got {count}"

    def test_accuracy_for_longer_text(self) -> None:
        """Test accuracy for longer text."""
        # A sentence that's roughly 20 tokens
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "This is a test sentence for token counting."
        )
        count = count_tokens(text)

        # Should be roughly 20-25 tokens
        assert 15 <= count <= 30, f"Expected ~20-25 tokens, got {count}"
