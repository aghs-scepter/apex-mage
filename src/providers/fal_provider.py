"""Fal.AI image generation provider implementation.

This module provides an implementation of the ImageProvider protocol
for Fal.AI's image generation API (Flux, Stable Diffusion, etc.).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Callable
from typing import Any

import fal_client

from src.core.errors import classify_error, is_retryable
from src.core.providers import (
    GeneratedImage,
    ImageModifyRequest,
    ImageProvider,
    ImageRequest,
)

logger = logging.getLogger(__name__)


class FalAIError(Exception):
    """Exception raised for Fal.AI API errors."""

    pass


class FalAIProvider:
    """Fal.AI image generation provider implementing ImageProvider protocol.

    This provider wraps the fal_client SDK to provide image generation
    and modification functionality. It supports both text-to-image generation
    and image-to-image modification using Flux models.

    The API key is injected via the constructor to support dependency
    injection and avoid direct environment variable access.

    Attributes:
        _api_key: The Fal.AI API key for authentication.
        _create_model: The model to use for image generation.
        _modify_model: The model to use for image modification.
        _max_retries: Maximum retry attempts for transient errors.
        _base_delay: Base delay for exponential backoff (seconds).
    """

    # Default models - these are the production models from allowed_vendors.json
    DEFAULT_CREATE_MODEL = "fal-ai/nano-banana-pro"
    DEFAULT_MODIFY_MODEL = "fal-ai/nano-banana-pro/edit"

    def __init__(
        self,
        api_key: str,
        create_model: str | None = None,
        modify_model: str | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        """Initialize the Fal.AI provider.

        Note on API Key Handling:
            This provider sets the FAL_KEY environment variable as a side effect.
            This is INTENTIONAL for the following reasons:

            1. **Single-bill design**: All Fal.AI API calls are consolidated
               under a single API key for simplified billing management.

            2. **fal_client limitation**: The fal_client library reads credentials
               exclusively from the FAL_KEY environment variable and does not
               support passing the API key directly to API calls.

            3. **No concurrent key support**: Multiple FalAIProvider instances
               with different API keys are NOT supported. The last instantiated
               provider's key will be used for all calls.

            This is a known architectural limitation. If your use case requires
            multiple concurrent API keys, consider using separate processes or
            a different client library.

        Args:
            api_key: The Fal.AI API key for authentication.
            create_model: The model to use for image generation.
                Defaults to "fal-ai/nano-banana-pro".
            modify_model: The model to use for image modification.
                Defaults to "fal-ai/nano-banana-pro/edit".
            max_retries: Maximum number of retries for transient errors.
                Defaults to 3.
            base_delay: Base delay in seconds for exponential backoff.
                Defaults to 1.0.
        """
        self._api_key = api_key
        self._create_model = create_model or self.DEFAULT_CREATE_MODEL
        self._modify_model = modify_model or self.DEFAULT_MODIFY_MODEL
        self._max_retries = max_retries
        self._base_delay = base_delay

        # Set the API key for fal_client
        # See docstring above for explanation of why this env var mutation
        # is intentional and necessary.
        import os
        os.environ["FAL_KEY"] = api_key

    async def _upload_image(self, image_data: bytes, filename: str) -> str:
        """Upload an image to Fal.AI for use in image modification.

        Args:
            image_data: The raw image bytes.
            filename: The filename for the uploaded image.

        Returns:
            The URL of the uploaded image.

        Raises:
            FalAIError: If the upload fails.
        """
        logger.debug("Uploading image to Fal.AI...")

        def do_upload() -> str:
            return fal_client.upload(
                data=image_data,
                content_type="image/jpeg",
                file_name=filename,
            )

        try:
            url = await asyncio.to_thread(do_upload)
            logger.debug("Image uploaded successfully.")
            return url
        except Exception as ex:
            logger.error("Failed to upload image to Fal.AI: %s", ex)
            raise FalAIError(f"Failed to upload image: {ex}") from ex

    def _on_queue_update(self, update: Any) -> None:
        """Callback for queue status updates.

        Args:
            update: The queue update information from Fal.AI.
        """
        logger.debug("Fal.AI queue update: still waiting...")

    async def _call_with_retry(
        self,
        sync_func: Callable[[], Any],
        operation_name: str,
    ) -> Any:
        """Execute a synchronous function with retry logic for transient errors.

        This method wraps synchronous fal_client calls with exponential backoff
        retry logic for transient errors (network issues, rate limits, server
        overload, etc.).

        Args:
            sync_func: A callable that performs the synchronous API operation.
            operation_name: Human-readable name for logging (e.g., "image generation").

        Returns:
            The result of the sync_func call.

        Raises:
            FalAIError: If all retries are exhausted or a permanent error occurs.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await asyncio.to_thread(sync_func)
            except Exception as ex:
                last_error = ex
                category = classify_error(ex)

                if not is_retryable(category):
                    logger.error(
                        "Fal.AI %s failed with permanent error: %s",
                        operation_name,
                        ex,
                    )
                    raise FalAIError(
                        f"{operation_name.capitalize()} failed: {ex}"
                    ) from ex

                if attempt >= self._max_retries:
                    logger.error(
                        "Fal.AI %s failed after %d attempts: %s",
                        operation_name,
                        attempt + 1,
                        ex,
                    )
                    raise FalAIError(
                        f"{operation_name.capitalize()} failed after "
                        f"{attempt + 1} attempts: {ex}"
                    ) from ex

                # Calculate delay with exponential backoff
                delay = self._base_delay * (2.0 ** attempt)
                logger.warning(
                    "Fal.AI %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    operation_name,
                    attempt + 1,
                    self._max_retries + 1,
                    delay,
                    ex,
                )
                await asyncio.sleep(delay)

        # Should never reach here, but just in case
        if last_error:
            raise FalAIError(
                f"{operation_name.capitalize()} failed: {last_error}"
            ) from last_error
        raise RuntimeError("Unexpected state in _call_with_retry")

    async def generate(
        self,
        request: ImageRequest,
    ) -> list[GeneratedImage]:
        """Generate images from a text prompt.

        Creates images based on the provided request parameters using
        Fal.AI's nano-banana-pro model.

        Args:
            request: An ImageRequest containing the prompt and generation
                parameters.

        Returns:
            A list of GeneratedImage objects containing the generated images.

        Raises:
            FalAIError: If the API call fails.
        """
        logger.debug("Generating image for prompt: %s", request.prompt)

        # Build arguments for Fal.AI nano-banana-pro API
        arguments: dict[str, Any] = {
            "prompt": request.prompt,
            "aspect_ratio": "1:1",
            "resolution": "1K",
            "output_format": "png",
            "sync_mode": True,
        }

        # Add optional parameters if provided
        if request.num_images > 1:
            arguments["num_images"] = request.num_images

        def subscribe() -> dict[str, Any]:
            return fal_client.subscribe(
                application=self._create_model,
                arguments=arguments,
                with_logs=True,
                on_queue_update=self._on_queue_update,
            )

        # Call with retry logic for transient errors
        result = await self._call_with_retry(subscribe, "image generation")
        logger.debug("Image generation completed.")

        # Convert response to GeneratedImage list
        images = []
        result_images = result.get("images", [])
        has_nsfw_list = result.get("has_nsfw_concepts", [])

        for i, img_data in enumerate(result_images):
            has_nsfw = (
                has_nsfw_list[i] if i < len(has_nsfw_list) else None
            )

            # Fal.AI returns images with url and optionally width/height
            image = GeneratedImage(
                url=img_data.get("url"),
                width=img_data.get("width", request.width),
                height=img_data.get("height", request.height),
                content_type=img_data.get("content_type", "image/png"),
                has_nsfw_content=has_nsfw,
            )
            images.append(image)

        return images

    async def modify(
        self,
        request: ImageModifyRequest,
    ) -> list[GeneratedImage]:
        """Modify an existing image based on a text prompt.

        Uses Fal.AI's nano-banana-pro/edit model to transform the input
        image according to the prompt.

        Args:
            request: An ImageModifyRequest containing the source image
                and modification prompt. Note: guidance_scale is ignored
                as the nano-banana-pro/edit API does not support it.

        Returns:
            A list of GeneratedImage objects containing the modified images.

        Raises:
            FalAIError: If the API call fails.
        """
        logger.debug("Modifying image with prompt: %s", request.prompt)

        # Decode base64 image data and upload to Fal.AI
        try:
            image_bytes = base64.b64decode(request.image_data)
        except Exception as ex:
            raise FalAIError(f"Invalid base64 image data: {ex}") from ex

        image_url = await self._upload_image(image_bytes, "image.jpeg")

        # Build arguments for the nano-banana-pro/edit endpoint
        # Note: guidance_scale and num_inference_steps are NOT supported
        # by this API, so we don't include them
        arguments: dict[str, Any] = {
            "image_urls": [image_url],
            "prompt": request.prompt,
            "aspect_ratio": "auto",
            "resolution": "1K",
            "output_format": "jpeg",
            "sync_mode": True,
        }

        def subscribe() -> dict[str, Any]:
            return fal_client.subscribe(
                application=self._modify_model,
                arguments=arguments,
                with_logs=True,
                on_queue_update=self._on_queue_update,
            )

        # Call with retry logic for transient errors
        result = await self._call_with_retry(subscribe, "image modification")
        logger.debug("Image modification completed.")

        # Convert response to GeneratedImage list
        images = []
        result_images = result.get("images", [])
        has_nsfw_list = result.get("has_nsfw_concepts", [])

        for i, img_data in enumerate(result_images):
            has_nsfw = (
                has_nsfw_list[i] if i < len(has_nsfw_list) else None
            )

            image = GeneratedImage(
                url=img_data.get("url"),
                width=img_data.get("width", 0),
                height=img_data.get("height", 0),
                content_type=img_data.get("content_type", "image/jpeg"),
                has_nsfw_content=has_nsfw,
            )
            images.append(image)

        return images

    async def get_models(self) -> list[str]:
        """Get the list of available image generation models.

        Returns the model identifiers currently configured for this provider.

        Returns:
            A list of model identifier strings.
        """
        return [self._create_model, self._modify_model]


# Protocol compliance verification
def _verify_protocol_compliance() -> None:
    """Verify that FalAIProvider implements ImageProvider protocol.

    This function is not called at runtime but serves as a static
    type check to ensure protocol compliance.
    """
    _: ImageProvider = FalAIProvider(api_key="test")  # noqa: F841
