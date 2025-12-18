"""JWT-based authentication for the HTTP API.

This module provides authentication middleware and utilities for
protecting API endpoints with JWT tokens.

Example:
    from src.api.auth import get_current_user, AuthUser

    @router.get("/protected")
    async def protected_route(user: AuthUser = Depends(get_current_user)):
        return {"user_id": user.user_id}
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.core.logging import get_logger

logger = get_logger(__name__)

# Security scheme for OpenAPI docs
security = HTTPBearer(auto_error=False)

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))


@dataclass
class AuthUser:
    """Authenticated user information extracted from JWT token.

    Attributes:
        user_id: Unique identifier for the user.
        api_key_id: Optional ID of the API key used for authentication.
        scopes: List of permission scopes granted to this token.
    """

    user_id: int
    api_key_id: str | None = None
    scopes: list[str] | None = None


class TokenData(BaseModel):
    """Schema for token payload."""

    sub: str  # Subject (user_id)
    exp: datetime  # Expiration time
    iat: datetime  # Issued at
    api_key_id: str | None = None
    scopes: list[str] = []


class TokenResponse(BaseModel):
    """Schema for token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until expiration


class AuthError(Exception):
    """Authentication error."""

    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


def create_access_token(
    user_id: int,
    api_key_id: str | None = None,
    scopes: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: The user ID to encode in the token.
        api_key_id: Optional API key ID.
        scopes: Optional list of permission scopes.
        expires_delta: Optional custom expiration time.

    Returns:
        Encoded JWT token string.
    """
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    expire = now + expires_delta

    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
    }

    if api_key_id:
        payload["api_key_id"] = api_key_id

    if scopes:
        payload["scopes"] = scopes

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def decode_access_token(token: str) -> TokenData:
    """Decode and validate a JWT access token.

    Args:
        token: The JWT token string.

    Returns:
        Decoded token data.

    Raises:
        AuthError: If the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return TokenData(
            sub=payload["sub"],
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
            iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
            api_key_id=payload.get("api_key_id"),
            scopes=payload.get("scopes", []),
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token has expired", "TOKEN_EXPIRED") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid token: {e}", "INVALID_TOKEN") from e


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> AuthUser:
    """FastAPI dependency to get the current authenticated user.

    Args:
        credentials: The HTTP Bearer credentials from the request.

    Returns:
        The authenticated user.

    Raises:
        HTTPException: If authentication fails.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Authentication required", "code": "AUTH_REQUIRED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_data = decode_access_token(credentials.credentials)
        user = AuthUser(
            user_id=int(token_data.sub),
            api_key_id=token_data.api_key_id,
            scopes=token_data.scopes,
        )
        logger.debug("user_authenticated", user_id=user.user_id)
        return user
    except AuthError as e:
        logger.warning("authentication_failed", error=e.message, code=e.code)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": e.message, "code": e.code},
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> AuthUser | None:
    """FastAPI dependency to get the current user if authenticated.

    Unlike get_current_user, this doesn't raise an exception if no
    credentials are provided. Useful for endpoints that work with
    or without authentication.

    Args:
        credentials: The HTTP Bearer credentials from the request.

    Returns:
        The authenticated user, or None if not authenticated.
    """
    if credentials is None:
        return None

    try:
        token_data = decode_access_token(credentials.credentials)
        return AuthUser(
            user_id=int(token_data.sub),
            api_key_id=token_data.api_key_id,
            scopes=token_data.scopes,
        )
    except AuthError:
        return None


def require_scope(required_scope: str):
    """Create a dependency that requires a specific scope.

    Args:
        required_scope: The scope that must be present in the token.

    Returns:
        A FastAPI dependency function.

    Example:
        @router.post("/admin")
        async def admin_route(
            user: AuthUser = Depends(require_scope("admin"))
        ):
            ...
    """

    async def scope_checker(
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        if user.scopes is None or required_scope not in user.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": f"Scope '{required_scope}' required",
                    "code": "INSUFFICIENT_SCOPE",
                },
            )
        return user

    return scope_checker
