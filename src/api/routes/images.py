"""Image generation API routes.

These routes provide endpoints for generating and modifying images.
"""

import asyncio
import base64
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from src.adapters import GCSAdapter
from src.api.dependencies import get_gcs_adapter, get_image_provider, get_rate_limiter
from src.core.image_utils import compress_image, format_image_response, image_strip_headers
from src.core.logging import bind_contextvars, clear_contextvars, get_logger
from src.core.providers import ImageModifyRequest, ImageProvider, ImageRequest
from src.core.rate_limit import SlidingWindowRateLimiter

logger = get_logger(__name__)

router = APIRouter(prefix="/images", tags=["images"])


class ImageGenerateRequest(BaseModel):
    """Request schema for image generation."""

    prompt: str = Field(..., min_length=1, max_length=10000)
    width: int | None = Field(None, ge=256, le=2048)
    height: int | None = Field(None, ge=256, le=2048)

    model_config = {
        "json_schema_extra": {
            "example": {
                "prompt": "A serene mountain landscape at sunset",
                "width": 1024,
                "height": 1024,
            }
        }
    }


class ImageModifyRequestSchema(BaseModel):
    """Request schema for image modification."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    prompt: str = Field(..., min_length=1, max_length=10000)
    guidance_scale: float = Field(
        7.5,
        ge=1.0,
        le=20.0,
        description="How closely to follow the prompt (1.0-20.0)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "image_base64": "base64encodeddata...",
                "prompt": "Add more trees to the landscape",
                "guidance_scale": 7.5,
            }
        }
    }


class ImageResponse(BaseModel):
    """Response schema for generated/modified images."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    filename: str = Field(..., description="Suggested filename")
    has_nsfw_content: bool = Field(False, description="Whether NSFW content detected")
    cloud_url: str | None = Field(None, description="GCS URL if uploaded")
    created_at: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "image_base64": "base64encodeddata...",
                "filename": "generated_image.jpeg",
                "has_nsfw_content": False,
                "cloud_url": "https://storage.googleapis.com/...",
                "created_at": "2025-01-01T12:00:00Z",
            }
        }
    }


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    error: str
    detail: str | None = None
    code: str | None = None


@router.post(
    "/generate",
    response_model=ImageResponse,
    responses={
        200: {"description": "Image generated successfully"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_image(
    request: ImageGenerateRequest,
    image_provider: ImageProvider = Depends(get_image_provider),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    gcs_adapter: GCSAdapter = Depends(get_gcs_adapter),
    user_id: int = 0,  # In production, get from auth
) -> ImageResponse:
    """Generate a new image from a text prompt.

    The generated image is compressed and optionally uploaded to cloud storage.
    """
    bind_contextvars(user_id=user_id)

    try:
        logger.info("generating_image", prompt_length=len(request.prompt))

        # Check rate limit
        rate_check = await rate_limiter.check(user_id, "image")
        if not rate_check.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "wait_seconds": rate_check.wait_seconds,
                },
            )

        # Generate image
        image_request = ImageRequest(
            prompt=request.prompt,
            width=request.width,
            height=request.height,
        )
        generated_images = await image_provider.generate(image_request)
        generated_image = generated_images[0]

        # Process image
        image_data = image_strip_headers(generated_image.url, "jpeg")
        image_data = await asyncio.to_thread(compress_image, image_data)

        # Format response
        has_nsfw = generated_image.has_nsfw_content or False
        filename, _ = format_image_response(image_data, "jpeg", has_nsfw)

        # Upload to GCS (optional - may fail if not configured)
        cloud_url = None
        try:
            cloud_url = await asyncio.to_thread(
                gcs_adapter.upload_image,
                "generated",
                user_id,
                image_data,
                "jpeg",
            )
        except Exception as ex:
            logger.warning("gcs_upload_failed", error=str(ex))

        # Record rate limit usage
        await rate_limiter.record(user_id, "image")

        logger.info("image_generated", has_nsfw=has_nsfw)

        return ImageResponse(
            image_base64=image_data,
            filename=filename,
            has_nsfw_content=has_nsfw,
            cloud_url=cloud_url,
            created_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as ex:
        logger.exception("image_generation_failed", error=str(ex))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Image generation failed", "detail": str(ex)},
        )
    finally:
        clear_contextvars()


@router.post(
    "/modify",
    response_model=ImageResponse,
    responses={
        200: {"description": "Image modified successfully"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Modification failed"},
    },
)
async def modify_image(
    request: ImageModifyRequestSchema,
    image_provider: ImageProvider = Depends(get_image_provider),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    gcs_adapter: GCSAdapter = Depends(get_gcs_adapter),
    user_id: int = 0,  # In production, get from auth
) -> ImageResponse:
    """Modify an existing image based on a prompt.

    Supports variations, inpainting, and outpainting operations.
    """
    bind_contextvars(user_id=user_id)

    try:
        logger.info(
            "modifying_image",
            guidance_scale=request.guidance_scale,
            prompt_length=len(request.prompt),
        )

        # Check rate limit
        rate_check = await rate_limiter.check(user_id, "image")
        if not rate_check.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "wait_seconds": rate_check.wait_seconds,
                },
            )

        # Modify image
        modify_request = ImageModifyRequest(
            image_data=request.image_base64,
            prompt=request.prompt,
            guidance_scale=request.guidance_scale,
        )
        modified_images = await image_provider.modify(modify_request)
        modified_image = modified_images[0]

        # Process image
        image_data = image_strip_headers(modified_image.url, "jpeg")
        image_data = await asyncio.to_thread(compress_image, image_data)

        # Format response
        has_nsfw = modified_image.has_nsfw_content or False
        filename, _ = format_image_response(image_data, "jpeg", has_nsfw)

        # Upload to GCS (optional)
        cloud_url = None
        try:
            cloud_url = await asyncio.to_thread(
                gcs_adapter.upload_image,
                "modified",
                user_id,
                image_data,
                "jpeg",
            )
        except Exception as ex:
            logger.warning("gcs_upload_failed", error=str(ex))

        # Record rate limit usage
        await rate_limiter.record(user_id, "image")

        logger.info("image_modified", has_nsfw=has_nsfw)

        return ImageResponse(
            image_base64=image_data,
            filename=filename,
            has_nsfw_content=has_nsfw,
            cloud_url=cloud_url,
            created_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as ex:
        logger.exception("image_modification_failed", error=str(ex))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Image modification failed", "detail": str(ex)},
        )
    finally:
        clear_contextvars()
