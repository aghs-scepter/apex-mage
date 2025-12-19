"""Unit tests for AnthropicProvider.

Tests the Anthropic Claude provider implementation including:
- Message format conversion
- Response parsing
- Error handling with retries
- Streaming responses
- System prompt handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import APIStatusError

from src.core.providers import ChatMessage, ChatResponse
from src.providers.anthropic_provider import AnthropicProvider


class TestAnthropicProviderInit:
    """Tests for AnthropicProvider initialization."""

    def test_init_creates_client(self) -> None:
        """Test that initialization creates an AsyncAnthropic client."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            provider = AnthropicProvider(api_key="test-key")
            mock_class.assert_called_once_with(api_key="test-key")
            assert provider._default_model == "claude-sonnet-4-20250514"

    def test_init_custom_model(self) -> None:
        """Test initialization with custom default model."""
        with patch("src.providers.anthropic_provider.AsyncAnthropic"):
            provider = AnthropicProvider(
                api_key="test-key",
                default_model="claude-opus-4-20250514",
            )
            assert provider._default_model == "claude-opus-4-20250514"

    def test_init_custom_retry_settings(self) -> None:
        """Test initialization with custom retry settings."""
        with patch("src.providers.anthropic_provider.AsyncAnthropic"):
            provider = AnthropicProvider(
                api_key="test-key",
                max_retries=10,
                backoff_factor=3.0,
            )
            assert provider._max_retries == 10
            assert provider._backoff_factor == 3.0


class TestMessageConversion:
    """Tests for message format conversion."""

    @pytest.fixture
    def provider(self) -> AnthropicProvider:
        """Create a provider with mocked client."""
        with patch("src.providers.anthropic_provider.AsyncAnthropic"):
            return AnthropicProvider(api_key="test-key")

    def test_convert_user_message(self, provider: AnthropicProvider) -> None:
        """Test converting a user message."""
        messages = [ChatMessage(role="user", content="Hello")]
        result = provider._convert_messages(messages)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_convert_assistant_message(
        self, provider: AnthropicProvider
    ) -> None:
        """Test converting an assistant message."""
        messages = [ChatMessage(role="assistant", content="Hi there")]
        result = provider._convert_messages(messages)
        assert result == [{"role": "assistant", "content": "Hi there"}]

    def test_convert_multiple_messages(
        self, provider: AnthropicProvider
    ) -> None:
        """Test converting multiple messages preserves order."""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
            ChatMessage(role="user", content="How are you?"),
        ]
        result = provider._convert_messages(messages)
        assert result == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]

    def test_convert_skips_system_messages(
        self, provider: AnthropicProvider
    ) -> None:
        """Test that system messages are filtered out."""
        messages = [
            ChatMessage(role="system", content="You are helpful"),
            ChatMessage(role="user", content="Hello"),
        ]
        result = provider._convert_messages(messages)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_convert_empty_messages(
        self, provider: AnthropicProvider
    ) -> None:
        """Test converting an empty message list."""
        result = provider._convert_messages([])
        assert result == []


class TestChatCompletion:
    """Tests for chat completion functionality."""

    @pytest.fixture
    def mock_response(self) -> MagicMock:
        """Create a mock API response."""
        response = MagicMock()
        response.content = [MagicMock(text="Hello, how can I help?")]
        response.model = "claude-sonnet-4-20250514"
        response.usage = MagicMock()
        response.usage.input_tokens = 10
        response.usage.output_tokens = 20
        return response

    @pytest.fixture
    def provider_with_mock(
        self, mock_response: MagicMock
    ) -> tuple[AnthropicProvider, AsyncMock]:
        """Create a provider with mocked client that returns a response."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            mock_client = MagicMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.messages.create = mock_create
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            return provider, mock_create

    @pytest.mark.asyncio
    async def test_chat_returns_response(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that chat returns a properly formatted ChatResponse."""
        provider, _ = provider_with_mock
        messages = [ChatMessage(role="user", content="Hello")]

        result = await provider.chat(messages)

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello, how can I help?"
        assert result.model == "claude-sonnet-4-20250514"
        assert result.usage == {"input_tokens": 10, "output_tokens": 20}

    @pytest.mark.asyncio
    async def test_chat_passes_messages(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that chat passes correctly formatted messages to API."""
        provider, mock_create = provider_with_mock
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
        ]

        await provider.chat(messages)

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

    @pytest.mark.asyncio
    async def test_chat_with_system_prompt(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that system prompt is passed correctly."""
        provider, mock_create = provider_with_mock
        messages = [ChatMessage(role="user", content="Hello")]

        await provider.chat(messages, system_prompt="Be helpful")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["system"] == "Be helpful"

    @pytest.mark.asyncio
    async def test_chat_without_system_prompt(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that system parameter is omitted when no system prompt."""
        provider, mock_create = provider_with_mock
        messages = [ChatMessage(role="user", content="Hello")]

        await provider.chat(messages)

        call_kwargs = mock_create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_chat_with_max_tokens(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that max_tokens is passed correctly."""
        provider, mock_create = provider_with_mock
        messages = [ChatMessage(role="user", content="Hello")]

        await provider.chat(messages, max_tokens=2048)

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_chat_uses_default_model(
        self, provider_with_mock: tuple[AnthropicProvider, AsyncMock]
    ) -> None:
        """Test that default model is used."""
        provider, mock_create = provider_with_mock
        messages = [ChatMessage(role="user", content="Hello")]

        await provider.chat(messages)

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_chat_empty_response_content(self) -> None:
        """Test handling of empty response content."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            mock_response = MagicMock()
            mock_response.content = []
            mock_response.model = "claude-sonnet-4-20250514"
            mock_response.usage = MagicMock()
            mock_response.usage.input_tokens = 10
            mock_response.usage.output_tokens = 0

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            result = await provider.chat(
                [ChatMessage(role="user", content="Hello")]
            )

            assert result.content == ""


class TestErrorHandling:
    """Tests for error handling and retry logic."""

    @pytest.mark.asyncio
    async def test_retry_on_529_error(self) -> None:
        """Test that 529 errors trigger retry with backoff."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            # First call throws 529, second succeeds
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Success")]
            mock_response.model = "claude-sonnet-4-20250514"
            mock_response.usage = MagicMock()
            mock_response.usage.input_tokens = 10
            mock_response.usage.output_tokens = 20

            mock_response_529 = MagicMock()
            mock_response_529.status_code = 529
            error_529 = APIStatusError(
                message="Overloaded",
                response=mock_response_529,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[error_529, mock_response]
            )
            mock_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                provider = AnthropicProvider(api_key="test-key")
                result = await provider.chat(
                    [ChatMessage(role="user", content="Hello")]
                )

                assert result.content == "Success"
                mock_sleep.assert_called_once_with(1.0)  # 2.0^0 = 1.0

    @pytest.mark.asyncio
    async def test_exponential_backoff(self) -> None:
        """Test that backoff increases exponentially."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Success")]
            mock_response.model = "claude-sonnet-4-20250514"
            mock_response.usage = MagicMock()
            mock_response.usage.input_tokens = 10
            mock_response.usage.output_tokens = 20

            mock_response_529 = MagicMock()
            mock_response_529.status_code = 529
            error_529 = APIStatusError(
                message="Overloaded",
                response=mock_response_529,
                body=None,
            )

            # Fail 3 times, then succeed
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[error_529, error_529, error_529, mock_response]
            )
            mock_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                provider = AnthropicProvider(api_key="test-key")
                await provider.chat([ChatMessage(role="user", content="Hello")])

                # Verify exponential backoff: 2^0=1, 2^1=2, 2^2=4
                assert mock_sleep.call_count == 3
                calls = [call.args[0] for call in mock_sleep.call_args_list]
                assert calls == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self) -> None:
        """Test that max retries raises error after exhaustion."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            mock_response_529 = MagicMock()
            mock_response_529.status_code = 529
            error_529 = APIStatusError(
                message="Overloaded",
                response=mock_response_529,
                body=None,
            )

            mock_client = MagicMock()
            # Always fail with 529
            mock_client.messages.create = AsyncMock(side_effect=error_529)
            mock_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                provider = AnthropicProvider(
                    api_key="test-key", max_retries=3
                )

                with pytest.raises(RuntimeError) as exc_info:
                    await provider.chat(
                        [ChatMessage(role="user", content="Hello")]
                    )

                assert "Max retries exceeded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self) -> None:
        """Test that non-529 errors are raised immediately."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            mock_response_400 = MagicMock()
            mock_response_400.status_code = 400
            error_400 = APIStatusError(
                message="Bad request",
                response=mock_response_400,
                body=None,
            )

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=error_400)
            mock_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                provider = AnthropicProvider(api_key="test-key")

                with pytest.raises(APIStatusError) as exc_info:
                    await provider.chat(
                        [ChatMessage(role="user", content="Hello")]
                    )

                assert "Bad request" in str(exc_info.value)
                mock_sleep.assert_not_called()


class TestChatStream:
    """Tests for streaming chat completion."""

    @pytest.mark.asyncio
    async def test_chat_stream_yields_chunks(self) -> None:
        """Test that chat_stream yields text chunks."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            # Create an async iterator for the text_stream
            async def mock_text_stream():
                for chunk in ["Hello", ", ", "world", "!"]:
                    yield chunk

            mock_stream = MagicMock()
            mock_stream.text_stream = mock_text_stream()
            mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
            mock_stream.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(return_value=mock_stream)
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            chunks = []

            async for chunk in provider.chat_stream(
                [ChatMessage(role="user", content="Hello")]
            ):
                chunks.append(chunk)

            assert chunks == ["Hello", ", ", "world", "!"]

    @pytest.mark.asyncio
    async def test_chat_stream_passes_messages(self) -> None:
        """Test that chat_stream passes correctly formatted messages."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            async def mock_text_stream():
                yield "test"

            mock_stream = MagicMock()
            mock_stream.text_stream = mock_text_stream()
            mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
            mock_stream.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_stream_method = MagicMock(return_value=mock_stream)
            mock_client.messages.stream = mock_stream_method
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            messages = [
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi"),
            ]

            # Consume the generator
            async for _ in provider.chat_stream(messages):
                pass

            call_kwargs = mock_stream_method.call_args.kwargs
            assert call_kwargs["messages"] == [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ]

    @pytest.mark.asyncio
    async def test_chat_stream_with_system_prompt(self) -> None:
        """Test that system prompt is passed to stream."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            async def mock_text_stream():
                yield "test"

            mock_stream = MagicMock()
            mock_stream.text_stream = mock_text_stream()
            mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
            mock_stream.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_stream_method = MagicMock(return_value=mock_stream)
            mock_client.messages.stream = mock_stream_method
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")

            async for _ in provider.chat_stream(
                [ChatMessage(role="user", content="Hello")],
                system_prompt="Be helpful",
            ):
                pass

            call_kwargs = mock_stream_method.call_args.kwargs
            assert call_kwargs["system"] == "Be helpful"

    @pytest.mark.asyncio
    async def test_chat_stream_without_system_prompt(self) -> None:
        """Test that system parameter is omitted when no system prompt."""
        with patch(
            "src.providers.anthropic_provider.AsyncAnthropic"
        ) as mock_class:
            async def mock_text_stream():
                yield "test"

            mock_stream = MagicMock()
            mock_stream.text_stream = mock_text_stream()
            mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
            mock_stream.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_stream_method = MagicMock(return_value=mock_stream)
            mock_client.messages.stream = mock_stream_method
            mock_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")

            async for _ in provider.chat_stream(
                [ChatMessage(role="user", content="Hello")]
            ):
                pass

            call_kwargs = mock_stream_method.call_args.kwargs
            assert "system" not in call_kwargs


class TestProtocolCompliance:
    """Tests to verify protocol compliance."""

    def test_provider_has_chat_method(self) -> None:
        """Test that provider has chat method."""
        with patch("src.providers.anthropic_provider.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            assert hasattr(provider, "chat")
            assert callable(provider.chat)

    def test_provider_has_chat_stream_method(self) -> None:
        """Test that provider has chat_stream method."""
        with patch("src.providers.anthropic_provider.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            assert hasattr(provider, "chat_stream")
            assert callable(provider.chat_stream)
