"""Mock implementations of provider protocols for testing.

These mocks implement the AIProvider and ImageProvider protocols defined in
src/core/providers.py. They are designed for testing code that depends on
these providers without making real API calls.

Features:
- Configurable responses for predictable test behavior
- Call tracking for assertions (call_count, last_messages, etc.)
- Support for async iteration in streaming responses
"""

from collections.abc import AsyncIterator

from src.core.providers import (
    ChatMessage,
    ChatResponse,
    GeneratedImage,
    ImageModifyRequest,
    ImageRequest,
)


class MockAIProvider:
    """Mock implementation of the AIProvider protocol for testing.

    Provides configurable responses and tracks all calls for test assertions.
    Supports both regular chat completions and streaming responses.

    Attributes:
        responses: List of response strings to return. The mock cycles through
            these responses on subsequent calls.
        call_count: Number of times chat() or chat_stream() has been called.
        last_messages: The messages argument from the most recent call.
        last_system_prompt: The system_prompt argument from the most recent call.
        last_max_tokens: The max_tokens argument from the most recent chat() call.

    Example:
        >>> provider = MockAIProvider(responses=["Hello!", "How can I help?"])
        >>> response = await provider.chat([ChatMessage("user", "Hi")])
        >>> assert response.content == "Hello!"
        >>> assert provider.call_count == 1
        >>> assert provider.last_messages[0].content == "Hi"
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        """Initialize the mock AI provider.

        Args:
            responses: List of response strings to return. Defaults to
                ["Mock response"]. The mock uses responses in order,
                repeating the last one if more calls are made than
                responses provided.
        """
        self.responses = responses or ["Mock response"]
        self.call_count = 0
        self.last_messages: list[ChatMessage] | None = None
        self.last_system_prompt: str | None = None
        self.last_max_tokens: int | None = None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Generate a mock chat completion.

        Records all arguments for later assertion and returns the next
        configured response.

        Args:
            messages: The conversation history.
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.

        Returns:
            A ChatResponse with the configured mock response.
        """
        self.call_count += 1
        self.last_messages = messages
        self.last_system_prompt = system_prompt
        self.last_max_tokens = max_tokens

        response_idx = min(self.call_count - 1, len(self.responses) - 1)
        return ChatResponse(
            content=self.responses[response_idx],
            model="mock-model",
            usage={"input_tokens": 10, "output_tokens": 20},
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Generate a mock streaming chat completion.

        Records all arguments and yields the configured response word by word.

        Args:
            messages: The conversation history.
            system_prompt: Optional system prompt.

        Yields:
            String chunks (words followed by spaces) of the mock response.
        """
        self.call_count += 1
        self.last_messages = messages
        self.last_system_prompt = system_prompt

        response_idx = min(self.call_count - 1, len(self.responses) - 1)
        words = self.responses[response_idx].split()
        for i, word in enumerate(words):
            # Add space after word except for last word
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word


class MockImageProvider:
    """Mock implementation of the ImageProvider protocol for testing.

    Provides configurable image URLs and tracks all calls for test assertions.
    Supports both image generation and modification operations.

    Attributes:
        image_urls: List of image URLs to return in generated images.
        call_count: Number of times generate() or modify() has been called.
        last_request: The request argument from the most recent generate() call.
        last_modify_request: The request argument from the most recent modify() call.
        models: List of model names to return from get_models().

    Example:
        >>> provider = MockImageProvider(image_urls=["https://example.com/img.png"])
        >>> images = await provider.generate(ImageRequest(prompt="A cat"))
        >>> assert images[0].url == "https://example.com/img.png"
        >>> assert provider.call_count == 1
        >>> assert provider.last_request.prompt == "A cat"
    """

    def __init__(
        self,
        image_urls: list[str] | None = None,
        models: list[str] | None = None,
    ) -> None:
        """Initialize the mock image provider.

        Args:
            image_urls: List of image URLs to return. Defaults to a single
                mock URL. URLs are cycled through for multi-image requests.
            models: List of model names for get_models(). Defaults to
                ["mock-model-v1", "mock-model-v2"].
        """
        self.image_urls = image_urls or ["https://mock.example.com/image.png"]
        self.models = models or ["mock-model-v1", "mock-model-v2"]
        self.call_count = 0
        self.last_request: ImageRequest | None = None
        self.last_modify_request: ImageModifyRequest | None = None

    async def generate(self, request: ImageRequest) -> list[GeneratedImage]:
        """Generate mock images from a text prompt.

        Records the request for later assertion and returns generated images
        with the configured URLs.

        Args:
            request: The image generation request.

        Returns:
            A list of GeneratedImage objects. The list length matches
            request.num_images, cycling through configured URLs if needed.
        """
        self.call_count += 1
        self.last_request = request

        images = []
        for i in range(request.num_images):
            url_idx = i % len(self.image_urls)
            images.append(
                GeneratedImage(
                    url=self.image_urls[url_idx],
                    width=request.width,
                    height=request.height,
                    seed=12345 + i,
                    content_type="image/png",
                )
            )
        return images

    async def modify(self, request: ImageModifyRequest) -> list[GeneratedImage]:
        """Modify a mock image based on a text prompt.

        Records the request for later assertion and returns a modified image
        with the first configured URL.

        Args:
            request: The image modification request.

        Returns:
            A list containing a single GeneratedImage with the modified result.
        """
        self.call_count += 1
        self.last_modify_request = request

        return [
            GeneratedImage(
                url=self.image_urls[0],
                width=1024,
                height=1024,
                seed=54321,
                content_type="image/png",
            )
        ]

    async def get_models(self) -> list[str]:
        """Get the list of available mock models.

        Returns:
            The configured list of model names.
        """
        return self.models
