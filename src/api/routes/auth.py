"""Authentication routes for the HTTP API.

These routes provide endpoints for authentication and token management.
"""

import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.api.auth import (
    JWT_EXPIRATION_HOURS,
    TokenResponse,
    create_access_token,
)
from src.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# Simple API key storage (in production, use a database)
# Format: {"api_key": {"user_id": int, "scopes": list}}
_API_KEYS: dict[str, dict] = {}

# Load API keys from environment variable if provided
# Format: "key1:user_id1:scope1,scope2;key2:user_id2:scope1"
_api_keys_env = os.getenv("API_KEYS", "")
if _api_keys_env:
    for entry in _api_keys_env.split(";"):
        parts = entry.strip().split(":")
        if len(parts) >= 2:
            key = parts[0]
            user_id = int(parts[1])
            scopes = parts[2].split(",") if len(parts) > 2 else []
            _API_KEYS[key] = {"user_id": user_id, "scopes": scopes}


class ApiKeyAuth(BaseModel):
    """Request schema for API key authentication."""

    api_key: str = Field(..., min_length=16)

    model_config = {
        "json_schema_extra": {
            "example": {"api_key": "your-api-key-here"}
        }
    }


class ApiKeyCreate(BaseModel):
    """Request schema for creating a new API key."""

    user_id: int = Field(..., description="User ID for the API key")
    scopes: list[str] = Field(
        default_factory=list,
        description="Permission scopes for this key",
    )

    model_config = {
        "json_schema_extra": {
            "example": {"user_id": 12345, "scopes": ["chat", "images"]}
        }
    }


class ApiKeyResponse(BaseModel):
    """Response schema for API key creation."""

    api_key: str
    user_id: int
    scopes: list[str]


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={
        200: {"description": "Token generated successfully"},
        401: {"description": "Invalid API key"},
    },
)
async def get_token(request: ApiKeyAuth) -> TokenResponse:
    """Exchange an API key for a JWT access token.

    The returned token can be used in the Authorization header
    for subsequent requests.
    """
    # Look up API key
    key_data = _API_KEYS.get(request.api_key)
    if key_data is None:
        logger.warning("invalid_api_key_attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid API key", "code": "INVALID_API_KEY"},
        )

    # Create access token
    user_id = key_data["user_id"]
    scopes = key_data.get("scopes", [])

    token = create_access_token(
        user_id=user_id,
        api_key_id=request.api_key[:8],  # Store truncated key ID
        scopes=scopes,
    )

    logger.info("token_issued", user_id=user_id, scopes=scopes)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRATION_HOURS * 3600,
    )


@router.post(
    "/keys",
    response_model=ApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "API key created successfully"},
        403: {"description": "API key creation not allowed"},
    },
)
async def create_api_key(request: ApiKeyCreate) -> ApiKeyResponse:
    """Create a new API key.

    Note: In production, this endpoint should be protected with admin
    authentication. For development, it's open but can be disabled
    via the ALLOW_API_KEY_CREATION environment variable.
    """
    # Check if API key creation is allowed
    allow_creation = os.getenv("ALLOW_API_KEY_CREATION", "true").lower() == "true"
    if not allow_creation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "API key creation is disabled",
                "code": "KEY_CREATION_DISABLED",
            },
        )

    # Generate a secure API key
    api_key = secrets.token_urlsafe(32)

    # Store the key
    _API_KEYS[api_key] = {
        "user_id": request.user_id,
        "scopes": request.scopes,
    }

    logger.info("api_key_created", user_id=request.user_id, scopes=request.scopes)

    return ApiKeyResponse(
        api_key=api_key,
        user_id=request.user_id,
        scopes=request.scopes,
    )


def register_api_key(api_key: str, user_id: int, scopes: list[str] | None = None):
    """Register an API key programmatically.

    This is useful for testing or initialization scripts.

    Args:
        api_key: The API key string.
        user_id: The user ID for this key.
        scopes: Optional list of permission scopes.
    """
    _API_KEYS[api_key] = {
        "user_id": user_id,
        "scopes": scopes or [],
    }
