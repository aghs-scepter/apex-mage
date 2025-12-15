"""Tests for mock provider implementations.

These tests verify that the mock providers correctly implement the AIProvider
and ImageProvider protocols and that all tracking features work as expected.
"""

import inspect

from src.core.providers import (
    ChatMessage,
    ImageModifyRequest,
    ImageRequest,
)
from tests.mocks.providers import MockAIProvider, MockImageProvider


class TestMockAIProviderProtocol:
    """Tests that MockAIProvider implements the AIProvider protocol."""

    def test_mock_ai_provider_has_chat_method(self) -> None:
        """Verify MockAIProvider has the chat method."""
        provider = MockAIProvider()
        assert hasattr(provider, "chat")
        assert callable(provider.chat)

    def test_mock_ai_provider_has_chat_stream_method(self) -> None:
        """Verify MockAIProvider has the chat_stream method."""
        provider = MockAIProvider()
        assert hasattr(provider, "chat_stream")
        assert callable(provider.chat_stream)

    def test_mock_ai_provider_implements_protocol(self) -> None:
        """Verify MockAIProvider has all methods required by AIProvider protocol."""
        provider = MockAIProvider()
        # Check that all protocol methods exist with correct signatures
        # (structural subtyping - if it has the methods, it implements the protocol)
        assert inspect.iscoroutinefunction(provider.chat)
        assert inspect.isasyncgenfunction(provider.chat_stream)


class TestMockAIProviderChat:
    """Tests for MockAIProvider.chat() method."""

    async def test_chat_returns_response(self, mock_ai_provider: MockAIProvider) -> None:
        """Verify chat returns a ChatResponse with expected fields."""
        messages = [ChatMessage(role="user", content="Hello")]
        response = await mock_ai_provider.chat(messages)

        assert response.content == "Mock response"
        assert response.model == "mock-model"
        assert response.usage == {"input_tokens": 10, "output_tokens": 20}

    async def test_chat_tracks_call_count(self) -> None:
        """Verify chat increments call_count on each call."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Hi")]

        assert provider.call_count == 0
        await provider.chat(messages)
        assert provider.call_count == 1
        await provider.chat(messages)
        assert provider.call_count == 2

    async def test_chat_stores_last_messages(self) -> None:
        """Verify chat stores the messages argument."""
        provider = MockAIProvider()
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ]

        await provider.chat(messages)

        assert provider.last_messages is not None
        assert len(provider.last_messages) == 2
        assert provider.last_messages[0].content == "Hello"
        assert provider.last_messages[1].content == "Hi there"

    async def test_chat_stores_system_prompt(self) -> None:
        """Verify chat stores the system_prompt argument."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Hi")]

        await provider.chat(messages, system_prompt="Be helpful")

        assert provider.last_system_prompt == "Be helpful"

    async def test_chat_stores_max_tokens(self) -> None:
        """Verify chat stores the max_tokens argument."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Hi")]

        await provider.chat(messages, max_tokens=2048)

        assert provider.last_max_tokens == 2048

    async def test_chat_uses_custom_responses(self) -> None:
        """Verify chat cycles through configured responses."""
        provider = MockAIProvider(responses=["First", "Second", "Third"])
        messages = [ChatMessage(role="user", content="Hi")]

        response1 = await provider.chat(messages)
        assert response1.content == "First"

        response2 = await provider.chat(messages)
        assert response2.content == "Second"

        response3 = await provider.chat(messages)
        assert response3.content == "Third"

    async def test_chat_repeats_last_response(self) -> None:
        """Verify chat repeats last response when exhausted."""
        provider = MockAIProvider(responses=["Only one"])
        messages = [ChatMessage(role="user", content="Hi")]

        await provider.chat(messages)
        response = await provider.chat(messages)

        assert response.content == "Only one"


class TestMockAIProviderStream:
    """Tests for MockAIProvider.chat_stream() method."""

    async def test_chat_stream_yields_chunks(self) -> None:
        """Verify chat_stream yields response in chunks."""
        provider = MockAIProvider(responses=["Hello world test"])
        messages = [ChatMessage(role="user", content="Hi")]

        chunks = []
        async for chunk in provider.chat_stream(messages):
            chunks.append(chunk)

        assert chunks == ["Hello ", "world ", "test"]

    async def test_chat_stream_tracks_call_count(self) -> None:
        """Verify chat_stream increments call_count."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Hi")]

        assert provider.call_count == 0
        async for _ in provider.chat_stream(messages):
            pass
        assert provider.call_count == 1

    async def test_chat_stream_stores_messages(self) -> None:
        """Verify chat_stream stores messages argument."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Test message")]

        async for _ in provider.chat_stream(messages):
            pass

        assert provider.last_messages is not None
        assert provider.last_messages[0].content == "Test message"

    async def test_chat_stream_stores_system_prompt(self) -> None:
        """Verify chat_stream stores system_prompt argument."""
        provider = MockAIProvider()
        messages = [ChatMessage(role="user", content="Hi")]

        async for _ in provider.chat_stream(messages, system_prompt="Be concise"):
            pass

        assert provider.last_system_prompt == "Be concise"


class TestMockImageProviderProtocol:
    """Tests that MockImageProvider implements the ImageProvider protocol."""

    def test_mock_image_provider_has_generate_method(self) -> None:
        """Verify MockImageProvider has the generate method."""
        provider = MockImageProvider()
        assert hasattr(provider, "generate")
        assert callable(provider.generate)

    def test_mock_image_provider_has_modify_method(self) -> None:
        """Verify MockImageProvider has the modify method."""
        provider = MockImageProvider()
        assert hasattr(provider, "modify")
        assert callable(provider.modify)

    def test_mock_image_provider_has_get_models_method(self) -> None:
        """Verify MockImageProvider has the get_models method."""
        provider = MockImageProvider()
        assert hasattr(provider, "get_models")
        assert callable(provider.get_models)

    def test_mock_image_provider_implements_protocol(self) -> None:
        """Verify MockImageProvider has all methods required by ImageProvider protocol."""
        provider = MockImageProvider()
        # Check that all protocol methods exist with correct signatures
        # (structural subtyping - if it has the methods, it implements the protocol)
        assert inspect.iscoroutinefunction(provider.generate)
        assert inspect.iscoroutinefunction(provider.modify)
        assert inspect.iscoroutinefunction(provider.get_models)


class TestMockImageProviderGenerate:
    """Tests for MockImageProvider.generate() method."""

    async def test_generate_returns_images(
        self, mock_image_provider: MockImageProvider
    ) -> None:
        """Verify generate returns GeneratedImage objects."""
        request = ImageRequest(prompt="A cat")
        images = await mock_image_provider.generate(request)

        assert len(images) == 1
        assert images[0].url == "https://mock.example.com/image.png"
        assert images[0].width == 1024
        assert images[0].height == 1024
        assert images[0].seed == 12345
        assert images[0].content_type == "image/png"

    async def test_generate_respects_num_images(self) -> None:
        """Verify generate returns requested number of images."""
        provider = MockImageProvider(
            image_urls=["https://example.com/1.png", "https://example.com/2.png"]
        )
        request = ImageRequest(prompt="A cat", num_images=2)

        images = await provider.generate(request)

        assert len(images) == 2
        assert images[0].url == "https://example.com/1.png"
        assert images[1].url == "https://example.com/2.png"

    async def test_generate_cycles_urls(self) -> None:
        """Verify generate cycles through URLs for more images than URLs."""
        provider = MockImageProvider(image_urls=["https://example.com/only.png"])
        request = ImageRequest(prompt="A cat", num_images=3)

        images = await provider.generate(request)

        assert len(images) == 3
        for img in images:
            assert img.url == "https://example.com/only.png"

    async def test_generate_uses_request_dimensions(self) -> None:
        """Verify generate uses dimensions from request."""
        provider = MockImageProvider()
        request = ImageRequest(prompt="A cat", width=512, height=768)

        images = await provider.generate(request)

        assert images[0].width == 512
        assert images[0].height == 768

    async def test_generate_tracks_call_count(self) -> None:
        """Verify generate increments call_count."""
        provider = MockImageProvider()
        request = ImageRequest(prompt="A cat")

        assert provider.call_count == 0
        await provider.generate(request)
        assert provider.call_count == 1
        await provider.generate(request)
        assert provider.call_count == 2

    async def test_generate_stores_last_request(self) -> None:
        """Verify generate stores the request argument."""
        provider = MockImageProvider()
        request = ImageRequest(
            prompt="A beautiful sunset",
            negative_prompt="ugly",
            width=768,
            height=768,
        )

        await provider.generate(request)

        assert provider.last_request is not None
        assert provider.last_request.prompt == "A beautiful sunset"
        assert provider.last_request.negative_prompt == "ugly"
        assert provider.last_request.width == 768

    async def test_generate_assigns_unique_seeds(self) -> None:
        """Verify generate assigns different seeds to each image."""
        provider = MockImageProvider()
        request = ImageRequest(prompt="A cat", num_images=3)

        images = await provider.generate(request)

        seeds = [img.seed for img in images]
        assert len(set(seeds)) == 3  # All unique


class TestMockImageProviderModify:
    """Tests for MockImageProvider.modify() method."""

    async def test_modify_returns_image(self) -> None:
        """Verify modify returns a GeneratedImage."""
        provider = MockImageProvider()
        request = ImageModifyRequest(
            image_data="base64data",
            prompt="Add a rainbow",
        )

        images = await provider.modify(request)

        assert len(images) == 1
        assert images[0].url == "https://mock.example.com/image.png"
        assert images[0].seed == 54321

    async def test_modify_tracks_call_count(self) -> None:
        """Verify modify increments call_count."""
        provider = MockImageProvider()
        request = ImageModifyRequest(image_data="data", prompt="modify")

        assert provider.call_count == 0
        await provider.modify(request)
        assert provider.call_count == 1

    async def test_modify_stores_request(self) -> None:
        """Verify modify stores the request argument."""
        provider = MockImageProvider()
        request = ImageModifyRequest(
            image_data="base64imagedata",
            prompt="Make it blue",
            guidance_scale=5.0,
        )

        await provider.modify(request)

        assert provider.last_modify_request is not None
        assert provider.last_modify_request.prompt == "Make it blue"
        assert provider.last_modify_request.guidance_scale == 5.0


class TestMockImageProviderGetModels:
    """Tests for MockImageProvider.get_models() method."""

    async def test_get_models_returns_default_models(self) -> None:
        """Verify get_models returns default model list."""
        provider = MockImageProvider()
        models = await provider.get_models()

        assert models == ["mock-model-v1", "mock-model-v2"]

    async def test_get_models_returns_custom_models(self) -> None:
        """Verify get_models returns custom model list."""
        provider = MockImageProvider(models=["custom-model", "another-model"])
        models = await provider.get_models()

        assert models == ["custom-model", "another-model"]


class TestFixtureIntegration:
    """Tests that fixtures work correctly."""

    async def test_mock_ai_provider_fixture(
        self, mock_ai_provider: MockAIProvider
    ) -> None:
        """Verify mock_ai_provider fixture provides working mock."""
        messages = [ChatMessage(role="user", content="Hello")]
        response = await mock_ai_provider.chat(messages)

        assert response.content == "Mock response"
        assert mock_ai_provider.call_count == 1

    async def test_mock_image_provider_fixture(
        self, mock_image_provider: MockImageProvider
    ) -> None:
        """Verify mock_image_provider fixture provides working mock."""
        request = ImageRequest(prompt="Test")
        images = await mock_image_provider.generate(request)

        assert len(images) == 1
        assert mock_image_provider.call_count == 1
