"""Authentication routes for the HTTP API.

These routes provide endpoints for authentication and token management.
Supports both in-memory (fallback) and database-backed API key storage.
"""

import hashlib
import hmac
import os
import secrets
import warnings
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.api.auth import (
    JWT_EXPIRATION_HOURS,
    TokenResponse,
    create_access_token,
)
from src.core.logging import get_logger
from src.ports.repositories import ApiKey

if TYPE_CHECKING:
    pass


class ApiKeyRepositoryProtocol(Protocol):
    """Protocol for API key repository operations."""

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Retrieve an API key by its hash."""
        ...

    async def create(self, api_key: ApiKey) -> ApiKey:
        """Create a new API key record."""
        ...

    async def update_last_used(self, key_hash: str) -> None:
        """Update the last_used_at timestamp for an API key."""
        ...

    async def revoke(self, key_hash: str) -> bool:
        """Revoke an API key."""
        ...

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


# =============================================================================
# API Key Storage
# =============================================================================

# In-memory fallback storage (for testing and when no database is configured)
# Format: {"key_hash": {"user_id": int, "scopes": list, "name": str | None}}
_API_KEYS_MEMORY: dict[str, dict[str, Any]] = {}

# Database repository (set by configure_api_key_repository)
_api_key_repository: ApiKeyRepositoryProtocol | None = None

# Flag to track if we've warned about in-memory mode
_warned_about_memory_mode = False


def _hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256.

    Args:
        api_key: The plaintext API key.

    Returns:
        The hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks.

    Args:
        a: First string.
        b: Second string.

    Returns:
        True if the strings are equal, False otherwise.
    """
    return hmac.compare_digest(a.encode(), b.encode())


def configure_api_key_repository(repository: ApiKeyRepositoryProtocol | None) -> None:
    """Configure the API key repository for database-backed storage.

    Call this during application startup to enable persistent API key storage.
    If not called or called with None, API keys will be stored in-memory only.

    Args:
        repository: The SQLite repository to use, or None for in-memory only.
    """
    global _api_key_repository
    _api_key_repository = repository
    if repository is not None:
        logger.info("api_key_repository_configured", storage="database")
    else:
        logger.info("api_key_repository_configured", storage="memory")


def _warn_memory_mode() -> None:
    """Log a warning if using in-memory mode (only once)."""
    global _warned_about_memory_mode
    if not _warned_about_memory_mode and _api_key_repository is None:
        warnings.warn(
            "API keys are stored in-memory only. Keys will be lost on restart. "
            "Configure a database repository for persistent storage.",
            UserWarning,
            stacklevel=3,
        )
        logger.warning(
            "api_keys_memory_mode",
            message="API keys stored in-memory only - will be lost on restart",
        )
        _warned_about_memory_mode = True


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
            key_hash = _hash_api_key(key)
            _API_KEYS_MEMORY[key_hash] = {
                "user_id": user_id,
                "scopes": scopes,
                "name": None,
            }


# =============================================================================
# Request/Response Schemas
# =============================================================================


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
    name: str | None = Field(
        default=None,
        description="Optional friendly name for the key",
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


# =============================================================================
# API Key Lookup/Storage Functions
# =============================================================================


async def _lookup_api_key(api_key: str) -> dict[str, Any] | None:
    """Look up an API key and return its data if valid.

    Checks both database (if configured) and in-memory storage.

    Args:
        api_key: The plaintext API key.

    Returns:
        Dict with user_id and scopes if found, None otherwise.
    """
    key_hash = _hash_api_key(api_key)

    # Try database first if configured
    if _api_key_repository is not None:
        db_key = await _api_key_repository.get_by_hash(key_hash)
        if db_key is not None:
            # Update last_used timestamp (fire and forget)
            try:
                await _api_key_repository.update_last_used(key_hash)
            except Exception as e:
                logger.warning("failed_to_update_last_used", error=str(e))

            return {
                "user_id": db_key.user_id,
                "scopes": db_key.scopes,
                "name": db_key.name,
            }

    # Fall back to in-memory storage
    for stored_hash, data in _API_KEYS_MEMORY.items():
        if _constant_time_compare(key_hash, stored_hash):
            return data

    return None


async def _store_api_key(
    api_key: str,
    user_id: int,
    scopes: list[str],
    name: str | None = None,
) -> None:
    """Store an API key.

    Stores in database if configured, otherwise in-memory with a warning.

    Args:
        api_key: The plaintext API key (will be hashed before storage).
        user_id: The user ID for this key.
        scopes: Permission scopes for this key.
        name: Optional friendly name.
    """
    key_hash = _hash_api_key(api_key)

    # Store in database if configured
    if _api_key_repository is not None:
        db_key = ApiKey(
            key_hash=key_hash,
            user_id=user_id,
            scopes=scopes,
            name=name,
        )
        await _api_key_repository.create(db_key)
        logger.info(
            "api_key_created",
            user_id=user_id,
            scopes=scopes,
            storage="database",
        )
    else:
        # Fall back to in-memory storage with warning
        _warn_memory_mode()
        _API_KEYS_MEMORY[key_hash] = {
            "user_id": user_id,
            "scopes": scopes,
            "name": name,
        }
        logger.info(
            "api_key_created",
            user_id=user_id,
            scopes=scopes,
            storage="memory",
        )


# =============================================================================
# Routes
# =============================================================================


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
    key_data = await _lookup_api_key(request.api_key)
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
        api_key_id=_hash_api_key(request.api_key)[:8],  # Store truncated hash
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

    # Store the key (never log the actual key)
    await _store_api_key(
        api_key=api_key,
        user_id=request.user_id,
        scopes=request.scopes,
        name=request.name,
    )

    return ApiKeyResponse(
        api_key=api_key,
        user_id=request.user_id,
        scopes=request.scopes,
    )


# =============================================================================
# Programmatic API Key Management
# =============================================================================


def register_api_key(
    api_key: str,
    user_id: int,
    scopes: list[str] | None = None,
    name: str | None = None,
) -> None:
    """Register an API key programmatically (synchronous, in-memory only).

    This is useful for testing or initialization scripts.
    For production use, call the async version or use the API endpoint.

    Note: This always uses in-memory storage for backwards compatibility
    with existing tests. For database storage, use register_api_key_async.

    Args:
        api_key: The API key string.
        user_id: The user ID for this key.
        scopes: Optional list of permission scopes.
        name: Optional friendly name for the key.
    """
    key_hash = _hash_api_key(api_key)
    _API_KEYS_MEMORY[key_hash] = {
        "user_id": user_id,
        "scopes": scopes or [],
        "name": name,
    }


async def register_api_key_async(
    api_key: str,
    user_id: int,
    scopes: list[str] | None = None,
    name: str | None = None,
) -> None:
    """Register an API key programmatically (async, uses configured storage).

    This function will use database storage if configured, otherwise in-memory.

    Args:
        api_key: The API key string.
        user_id: The user ID for this key.
        scopes: Optional list of permission scopes.
        name: Optional friendly name for the key.
    """
    await _store_api_key(
        api_key=api_key,
        user_id=user_id,
        scopes=scopes or [],
        name=name,
    )


async def validate_api_key(api_key: str) -> dict[str, Any] | None:
    """Validate an API key and return its data.

    This is a public async function for use outside of HTTP routes.

    Args:
        api_key: The plaintext API key to validate.

    Returns:
        Dict with user_id and scopes if valid, None otherwise.
    """
    return await _lookup_api_key(api_key)


def clear_memory_keys() -> None:
    """Clear all in-memory API keys.

    This is primarily useful for testing to reset state between tests.
    Does not affect keys stored in the database.
    """
    global _warned_about_memory_mode
    _API_KEYS_MEMORY.clear()
    _warned_about_memory_mode = False
