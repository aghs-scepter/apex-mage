"""AI Provider protocols for text and image generation.

This module defines the interfaces (Protocols) for AI provider operations.
Implementations can use Anthropic, OpenAI, or any other AI service backend.
All types are platform-agnostic (no Discord, Slack, or other client types).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ChatMessage:
    """Represents a single message in a conversation.

    This is a platform-agnostic representation of a chat message that can be
    used with any AI provider.

    Attributes:
        role: The role of the message sender. One of "user", "assistant", or
            "system". Note that some providers handle system messages via a
            separate parameter rather than in the message list.
        content: The text content of the message.
    """

    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class ChatResponse:
    """Represents a response from an AI chat completion.

    Contains the generated text along with metadata about the request.

    Attributes:
        content: The generated text response from the AI.
        model: The model identifier that generated the response (e.g.,
            "claude-3-sonnet-20240229").
        usage: Token usage statistics for the request. Typically contains
            "input_tokens" and "output_tokens" keys.
    """

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ImageRequest:
    """Request parameters for image generation.

    This is a platform-agnostic representation of image generation parameters
    that can be used with any image generation provider (Fal.AI, DALL-E,
    Stable Diffusion, etc.).

    Attributes:
        prompt: The text description of the image to generate. Should be
            descriptive and specific for best results.
        negative_prompt: Optional text describing elements to avoid in the
            generated image. Not all providers support this.
        width: Width of the generated image in pixels. Defaults to 1024.
            Actual supported dimensions vary by provider and model.
        height: Height of the generated image in pixels. Defaults to 1024.
            Actual supported dimensions vary by provider and model.
        num_images: Number of images to generate. Defaults to 1.
            Maximum supported count varies by provider.
        guidance_scale: How closely to follow the prompt (higher = more strict).
            Typical range is 1.0-20.0, default varies by provider.
            Not all providers support this parameter.
    """

    prompt: str
    negative_prompt: str | None = None
    width: int = 1024
    height: int = 1024
    num_images: int = 1
    guidance_scale: float | None = None


@dataclass
class ImageModifyRequest:
    """Request parameters for image modification/transformation.

    Used for operations like img2img, inpainting, or style transfer where
    an existing image is modified based on a prompt.

    Attributes:
        image_data: Base64-encoded image data to modify.
        prompt: Text description of how to modify the image.
        guidance_scale: How closely to follow the prompt vs preserve the
            original image. Higher values follow the prompt more closely.
            Typical range is 1.0-20.0, with lower values preserving more
            of the original image.
    """

    image_data: str
    prompt: str
    guidance_scale: float = 7.5


@dataclass
class GeneratedImage:
    """Represents a generated or modified image.

    Contains the image data or URL along with metadata about the generation.

    Attributes:
        url: URL where the image can be accessed, if the provider hosts images.
            May be None if only base64 data is provided.
        data: Base64-encoded image data. May be None if only URL is provided.
        width: Width of the generated image in pixels.
        height: Height of the generated image in pixels.
        seed: The random seed used for generation, if available. Useful for
            reproducing specific generations.
        content_type: MIME type of the image (e.g., "image/jpeg", "image/png").
        has_nsfw_content: Whether the image was flagged as potentially NSFW
            by the provider's safety checker. None if not checked.
    """

    url: str | None = None
    data: str | None = None
    width: int = 0
    height: int = 0
    seed: int | None = None
    content_type: str = "image/jpeg"
    has_nsfw_content: bool | None = None


# =============================================================================
# Provider Protocols
# =============================================================================


class AIProvider(Protocol):
    """Protocol for AI chat completion providers.

    Defines the interface for AI services that can generate text responses
    from conversations. Implementations should handle provider-specific
    details like API authentication, rate limiting, and error handling.

    This protocol intentionally excludes:
    - Image generation (see ImageProvider)
    - Embeddings
    - Fine-tuning operations

    Implementations are expected to be async-first for I/O efficiency.
    """

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Generate a chat completion from a conversation.

        Sends the conversation history to the AI provider and returns
        the generated response.

        Args:
            messages: The conversation history as a list of ChatMessage
                objects. Should be in chronological order (oldest first).
            system_prompt: Optional system prompt that sets the AI's behavior
                and context. How this is handled varies by provider (e.g.,
                Anthropic uses a separate system parameter, while OpenAI
                includes it in the messages list).
            max_tokens: Maximum number of tokens to generate in the response.
                Defaults to 4096.

        Returns:
            A ChatResponse containing the generated text, model identifier,
            and token usage statistics.

        Raises:
            ProviderError: If the API call fails (network error, rate limit,
                invalid request, etc.). Implementations should wrap
                provider-specific exceptions.
        """
        ...

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Generate a streaming chat completion.

        Similar to chat(), but yields response chunks as they are generated.
        This allows for real-time display of responses in interactive
        applications.

        Args:
            messages: The conversation history as a list of ChatMessage
                objects. Should be in chronological order (oldest first).
            system_prompt: Optional system prompt that sets the AI's behavior.

        Yields:
            String chunks of the generated response as they become available.

        Raises:
            ProviderError: If the API call fails.

        Example:
            >>> provider = AnthropicProvider(api_key="...")
            >>> async for chunk in provider.chat_stream(messages):
            ...     print(chunk, end="", flush=True)
        """
        ...


class ImageProvider(Protocol):
    """Protocol for image generation providers.

    Defines the interface for AI services that can generate and modify images.
    Implementations should handle provider-specific details like API
    authentication, rate limiting, and error handling.

    Typical providers include:
    - Fal.AI (Flux, Stable Diffusion)
    - OpenAI (DALL-E)
    - Stability AI (Stable Diffusion)

    Implementations are expected to be async-first for I/O efficiency.
    """

    async def generate(
        self,
        request: ImageRequest,
    ) -> list[GeneratedImage]:
        """Generate images from a text prompt.

        Creates one or more images based on the provided request parameters.
        The number of images returned matches request.num_images.

        Args:
            request: An ImageRequest containing the prompt and generation
                parameters (dimensions, number of images, etc.).

        Returns:
            A list of GeneratedImage objects containing the generated images
            and their metadata. The list length matches request.num_images.

        Raises:
            ProviderError: If the API call fails (network error, rate limit,
                invalid request, content policy violation, etc.).

        Example:
            >>> provider = FalAIProvider(api_key="...")
            >>> images = await provider.generate(
            ...     ImageRequest(prompt="A sunset over mountains")
            ... )
            >>> print(images[0].url)
        """
        ...

    async def modify(
        self,
        request: ImageModifyRequest,
    ) -> list[GeneratedImage]:
        """Modify an existing image based on a text prompt.

        Transforms the input image according to the prompt while preserving
        some aspects of the original image. The degree of transformation
        is controlled by the guidance_scale parameter.

        Args:
            request: An ImageModifyRequest containing the source image,
                modification prompt, and guidance scale.

        Returns:
            A list of GeneratedImage objects containing the modified images.
            Typically returns a single image unless the implementation
            supports batch modifications.

        Raises:
            ProviderError: If the API call fails (network error, rate limit,
                invalid request, content policy violation, etc.).

        Example:
            >>> provider = FalAIProvider(api_key="...")
            >>> images = await provider.modify(
            ...     ImageModifyRequest(
            ...         image_data=base64_image,
            ...         prompt="Add a rainbow to the sky",
            ...         guidance_scale=7.5,
            ...     )
            ... )
        """
        ...

    async def get_models(self) -> list[str]:
        """Get the list of available image generation models.

        Returns the model identifiers that can be used with this provider.
        Useful for displaying options to users or validating model selection.

        Returns:
            A list of model identifier strings (e.g., ["flux-pro",
            "stable-diffusion-xl", "dall-e-3"]).

        Raises:
            ProviderError: If the API call fails.
        """
        ...
