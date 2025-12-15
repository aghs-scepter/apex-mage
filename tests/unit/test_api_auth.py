"""Tests for the authentication module."""

from datetime import timedelta, timezone
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.auth import (
    AuthError,
    AuthUser,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_optional_user,
    require_scope,
)
from src.api.routes.auth import router, register_api_key


class TestCreateAccessToken:
    """Tests for create_access_token function."""

    def test_creates_token(self):
        """Should create a valid JWT token."""
        token = create_access_token(user_id=123)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_user_id(self):
        """Should encode user_id in token."""
        token = create_access_token(user_id=456)
        decoded = decode_access_token(token)
        assert decoded.sub == "456"

    def test_token_contains_api_key_id(self):
        """Should encode api_key_id if provided."""
        token = create_access_token(user_id=123, api_key_id="key123")
        decoded = decode_access_token(token)
        assert decoded.api_key_id == "key123"

    def test_token_contains_scopes(self):
        """Should encode scopes if provided."""
        token = create_access_token(
            user_id=123, scopes=["chat", "images"]
        )
        decoded = decode_access_token(token)
        assert decoded.scopes == ["chat", "images"]

    def test_custom_expiration(self):
        """Should use custom expiration if provided."""
        token = create_access_token(
            user_id=123,
            expires_delta=timedelta(minutes=5),
        )
        decoded = decode_access_token(token)
        # Should expire within ~5 minutes
        time_diff = decoded.exp - datetime.now(timezone.utc)
        assert time_diff.total_seconds() <= 300
        assert time_diff.total_seconds() > 0


class TestDecodeAccessToken:
    """Tests for decode_access_token function."""

    def test_decodes_valid_token(self):
        """Should decode a valid token."""
        token = create_access_token(user_id=789)
        decoded = decode_access_token(token)
        assert decoded.sub == "789"

    def test_raises_on_expired_token(self):
        """Should raise AuthError for expired tokens."""
        # Create a token that's already expired
        token = create_access_token(
            user_id=123,
            expires_delta=timedelta(seconds=-10),
        )
        with pytest.raises(AuthError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.code == "TOKEN_EXPIRED"

    def test_raises_on_invalid_token(self):
        """Should raise AuthError for invalid tokens."""
        with pytest.raises(AuthError) as exc_info:
            decode_access_token("not-a-valid-token")
        assert exc_info.value.code == "INVALID_TOKEN"


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.fixture
    def mock_credentials(self):
        """Create mock credentials with a valid token."""

        class MockCredentials:
            credentials: str

        creds = MockCredentials()
        creds.credentials = create_access_token(
            user_id=123, scopes=["chat"]
        )
        return creds

    @pytest.mark.asyncio
    async def test_returns_user_with_valid_token(self, mock_credentials):
        """Should return AuthUser with valid credentials."""
        user = await get_current_user(mock_credentials)
        assert isinstance(user, AuthUser)
        assert user.user_id == 123
        assert user.scopes == ["chat"]

    @pytest.mark.asyncio
    async def test_raises_without_credentials(self):
        """Should raise HTTPException without credentials."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_with_invalid_token(self):
        """Should raise HTTPException with invalid token."""

        class MockCredentials:
            credentials = "invalid-token"

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(MockCredentials())
        assert exc_info.value.status_code == 401


class TestGetOptionalUser:
    """Tests for get_optional_user dependency."""

    @pytest.fixture
    def mock_credentials(self):
        """Create mock credentials with a valid token."""

        class MockCredentials:
            credentials: str

        creds = MockCredentials()
        creds.credentials = create_access_token(user_id=456)
        return creds

    @pytest.mark.asyncio
    async def test_returns_user_with_valid_token(self, mock_credentials):
        """Should return AuthUser with valid credentials."""
        user = await get_optional_user(mock_credentials)
        assert user is not None
        assert user.user_id == 456

    @pytest.mark.asyncio
    async def test_returns_none_without_credentials(self):
        """Should return None without credentials."""
        user = await get_optional_user(None)
        assert user is None

    @pytest.mark.asyncio
    async def test_returns_none_with_invalid_token(self):
        """Should return None with invalid token."""

        class MockCredentials:
            credentials = "invalid-token"

        user = await get_optional_user(MockCredentials())
        assert user is None


class TestRequireScope:
    """Tests for require_scope dependency factory."""

    @pytest.mark.asyncio
    async def test_allows_user_with_scope(self):
        """Should allow user with required scope."""
        user = AuthUser(user_id=123, scopes=["admin", "chat"])
        checker = require_scope("admin")

        # Mock the get_current_user dependency
        with patch("src.api.auth.get_current_user") as mock_get_user:
            mock_get_user.return_value = user
            # The checker is a dependency function
            result = await checker(user)
            assert result == user

    @pytest.mark.asyncio
    async def test_rejects_user_without_scope(self):
        """Should reject user without required scope."""
        user = AuthUser(user_id=123, scopes=["chat"])
        checker = require_scope("admin")

        with pytest.raises(HTTPException) as exc_info:
            await checker(user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_user_with_no_scopes(self):
        """Should reject user with no scopes."""
        user = AuthUser(user_id=123, scopes=None)
        checker = require_scope("admin")

        with pytest.raises(HTTPException) as exc_info:
            await checker(user)
        assert exc_info.value.status_code == 403


class TestAuthRoutes:
    """Tests for authentication routes."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app."""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_create_api_key(self, client):
        """Should create a new API key."""
        response = client.post(
            "/auth/keys",
            json={"user_id": 123, "scopes": ["chat"]},
        )
        assert response.status_code == 201
        data = response.json()
        assert "api_key" in data
        assert data["user_id"] == 123
        assert data["scopes"] == ["chat"]

    def test_get_token_with_valid_key(self, client):
        """Should exchange valid API key for token."""
        # First create an API key
        create_response = client.post(
            "/auth/keys",
            json={"user_id": 456, "scopes": ["images"]},
        )
        api_key = create_response.json()["api_key"]

        # Then exchange for token
        response = client.post(
            "/auth/token",
            json={"api_key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_get_token_with_invalid_key(self, client):
        """Should reject invalid API key."""
        response = client.post(
            "/auth/token",
            json={"api_key": "invalid-key-12345678"},
        )
        assert response.status_code == 401

    def test_register_api_key_function(self):
        """Should register API key programmatically."""
        register_api_key("test-key-12345678", user_id=789, scopes=["test"])

        # Verify key works
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/auth/token",
            json={"api_key": "test-key-12345678"},
        )
        assert response.status_code == 200
