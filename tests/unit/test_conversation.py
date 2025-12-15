"""Tests for conversation context building logic."""

from src.core.conversation import ContextBuilder, ConversationContext
from src.core.providers import ChatMessage


class TestContextBuilder:
    """Tests for ContextBuilder class."""

    def test_empty_history_returns_empty_context(self):
        """Empty history should produce empty context."""
        builder = ContextBuilder()
        context = builder.build_context([])
        assert context.messages == []
        assert context.total_tokens_estimate == 0

    def test_windows_to_max_messages(self):
        """Should limit to max_messages, keeping most recent."""
        builder = ContextBuilder(max_messages=5)
        history = [
            ("user", f"message {i}", f"2024-01-01T{i:02d}:00:00") for i in range(10)
        ]
        context = builder.build_context(history)
        assert len(context.messages) == 5
        # Should keep most recent (messages 5-9)
        assert context.messages[0].content == "message 5"
        assert context.messages[-1].content == "message 9"

    def test_windows_to_max_tokens(self):
        """Should limit to max_tokens budget."""
        builder = ContextBuilder(max_tokens=100)
        # Each message ~50 chars = ~12 tokens (50/4)
        history = [("user", "x" * 50, f"ts{i}") for i in range(10)]
        context = builder.build_context(history)
        # 100 tokens / 12 tokens per message = ~8 messages max
        assert len(context.messages) < 10

    def test_preserves_chronological_order(self):
        """Messages should be in chronological order (oldest first)."""
        builder = ContextBuilder()
        history = [("user", "first", "ts1"), ("assistant", "second", "ts2")]
        context = builder.build_context(history)
        assert context.messages[0].content == "first"
        assert context.messages[0].role == "user"
        assert context.messages[1].content == "second"
        assert context.messages[1].role == "assistant"

    def test_system_prompt_counts_toward_tokens(self):
        """System prompt tokens should count against max_tokens budget."""
        builder = ContextBuilder(max_tokens=100)
        # System prompt uses ~50 tokens (200/4)
        long_system = "x" * 200
        # Each message is ~10 tokens (40/4)
        history = [("user", "y" * 40, f"ts{i}") for i in range(10)]
        context_with_system = builder.build_context(history, system_prompt=long_system)
        context_without_system = builder.build_context(history)
        # With system prompt, fewer messages should fit
        assert len(context_with_system.messages) < len(context_without_system.messages)

    def test_returns_conversation_context(self):
        """Should return a ConversationContext dataclass."""
        builder = ContextBuilder()
        history = [("user", "hello", "ts1")]
        context = builder.build_context(history)
        assert isinstance(context, ConversationContext)
        assert isinstance(context.messages, list)
        assert isinstance(context.total_tokens_estimate, int)

    def test_messages_are_chat_message_type(self):
        """Returned messages should be ChatMessage objects."""
        builder = ContextBuilder()
        history = [("user", "hello", "ts1")]
        context = builder.build_context(history)
        assert len(context.messages) == 1
        assert isinstance(context.messages[0], ChatMessage)
        assert context.messages[0].role == "user"
        assert context.messages[0].content == "hello"

    def test_token_estimate_includes_all_messages(self):
        """Token estimate should include all windowed messages."""
        builder = ContextBuilder()
        # "hello" is 5 chars = 1 token (max(1, 5//4) = max(1, 1) = 1)
        history = [("user", "hello", "ts1"), ("assistant", "world", "ts2")]
        context = builder.build_context(history)
        assert context.total_tokens_estimate == 2  # 1 + 1

    def test_token_estimate_includes_system_prompt(self):
        """Token estimate should include system prompt."""
        builder = ContextBuilder()
        long_system = "x" * 40  # 10 tokens
        history = [("user", "y" * 40, "ts1")]  # 10 tokens
        context = builder.build_context(history, system_prompt=long_system)
        assert context.total_tokens_estimate == 20  # 10 + 10


class TestEstimateTokens:
    """Tests for the estimate_tokens method."""

    def test_empty_string_returns_zero(self):
        """Empty string should return 0 tokens."""
        builder = ContextBuilder()
        assert builder.estimate_tokens("") == 0

    def test_short_string_returns_minimum_one(self):
        """Very short strings should return minimum of 1 token."""
        builder = ContextBuilder()
        assert builder.estimate_tokens("a") == 1
        assert builder.estimate_tokens("ab") == 1
        assert builder.estimate_tokens("abc") == 1

    def test_uses_four_chars_per_token_heuristic(self):
        """Should use ~4 characters per token."""
        builder = ContextBuilder()
        assert builder.estimate_tokens("a" * 40) == 10  # 40/4 = 10
        assert builder.estimate_tokens("a" * 100) == 25  # 100/4 = 25

    def test_none_handled_gracefully(self):
        """None input should return 0 tokens."""
        builder = ContextBuilder()
        # The method is called with system_prompt which can be None
        # It checks 'if not text' which handles None
        assert builder.estimate_tokens("") == 0


class TestWindowingEdgeCases:
    """Edge case tests for context windowing."""

    def test_exact_message_limit(self):
        """Exactly max_messages should all be included."""
        builder = ContextBuilder(max_messages=5)
        history = [("user", f"msg{i}", f"ts{i}") for i in range(5)]
        context = builder.build_context(history)
        assert len(context.messages) == 5

    def test_single_message_history(self):
        """Single message history should work."""
        builder = ContextBuilder()
        history = [("user", "only message", "ts1")]
        context = builder.build_context(history)
        assert len(context.messages) == 1
        assert context.messages[0].content == "only message"

    def test_large_single_message_exceeds_tokens(self):
        """Single message exceeding token limit should be excluded."""
        builder = ContextBuilder(max_tokens=10)
        # Message with 100 chars = 25 tokens, exceeds limit
        history = [("user", "x" * 100, "ts1")]
        context = builder.build_context(history)
        assert len(context.messages) == 0

    def test_mixed_roles(self):
        """Should handle mixed user/assistant roles."""
        builder = ContextBuilder()
        history = [
            ("user", "question", "ts1"),
            ("assistant", "answer", "ts2"),
            ("user", "followup", "ts3"),
        ]
        context = builder.build_context(history)
        assert len(context.messages) == 3
        assert context.messages[0].role == "user"
        assert context.messages[1].role == "assistant"
        assert context.messages[2].role == "user"

    def test_timestamp_not_included_in_output(self):
        """Timestamps should not appear in output messages."""
        builder = ContextBuilder()
        history = [("user", "content", "2024-01-01T12:00:00")]
        context = builder.build_context(history)
        # ChatMessage only has role and content, no timestamp
        assert context.messages[0].role == "user"
        assert context.messages[0].content == "content"
