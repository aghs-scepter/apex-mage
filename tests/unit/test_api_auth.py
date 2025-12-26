"""Tests for the authentication module."""

import importlib
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
from src.api.routes.auth import (
    _constant_time_compare,
    _hash_api_key,
    clear_memory_keys,
    configure_api_key_repository,
    register_api_key,
    router,
    validate_api_key,
)


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
        time_diff = decoded.exp - datetime.now(UTC)
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


class TestApiKeyHashing:
    """Tests for API key hashing functions."""

    def test_hash_api_key_produces_hex_string(self):
        """Should produce a hex-encoded SHA-256 hash."""
        result = _hash_api_key("my-secret-key")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 produces 32 bytes = 64 hex chars

    def test_hash_api_key_is_deterministic(self):
        """Same input should produce same hash."""
        hash1 = _hash_api_key("same-key")
        hash2 = _hash_api_key("same-key")
        assert hash1 == hash2

    def test_hash_api_key_different_inputs(self):
        """Different inputs should produce different hashes."""
        hash1 = _hash_api_key("key-one")
        hash2 = _hash_api_key("key-two")
        assert hash1 != hash2

    def test_constant_time_compare_equal(self):
        """Should return True for equal strings."""
        assert _constant_time_compare("abc123", "abc123") is True

    def test_constant_time_compare_not_equal(self):
        """Should return False for different strings."""
        assert _constant_time_compare("abc123", "xyz789") is False

    def test_constant_time_compare_different_lengths(self):
        """Should return False for different length strings."""
        assert _constant_time_compare("short", "longerstring") is False


class TestApiKeyStorage:
    """Tests for API key storage integration."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up in-memory keys before and after each test."""
        clear_memory_keys()
        configure_api_key_repository(None)  # Ensure memory mode
        yield
        clear_memory_keys()
        configure_api_key_repository(None)

    @pytest.mark.asyncio
    async def test_validate_api_key_returns_data(self):
        """Should return key data for valid key."""
        register_api_key("valid-key-123456", user_id=100, scopes=["chat"])

        result = await validate_api_key("valid-key-123456")

        assert result is not None
        assert result["user_id"] == 100
        assert result["scopes"] == ["chat"]

    @pytest.mark.asyncio
    async def test_validate_api_key_returns_none_for_invalid(self):
        """Should return None for invalid key."""
        result = await validate_api_key("nonexistent-key-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_memory_keys_removes_all(self):
        """Should clear all in-memory keys."""
        register_api_key("key-to-clear-12", user_id=1, scopes=[])

        clear_memory_keys()

        result = await validate_api_key("key-to-clear-12")
        assert result is None


class TestJWTSecretEnforcement:
    """Tests for JWT secret key enforcement in production."""

    def test_production_requires_jwt_secret_key(self):
        """Should raise RuntimeError in production without JWT_SECRET_KEY."""
        # Remove the module from cache to allow reimport
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Mock production environment without JWT_SECRET_KEY
        env_vars = {
            "ENVIRONMENT": "production",
            "APP_ENV": "production",
        }
        with patch.dict("os.environ", env_vars, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                importlib.import_module("src.api.auth")

            assert "JWT_SECRET_KEY" in str(exc_info.value)
            assert "production" in str(exc_info.value).lower()

        # Restore the module for other tests
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]
        # Re-import with default (development) settings
        importlib.import_module("src.api.auth")

    def test_development_allows_default_key(self):
        """Should allow default key in development mode."""
        # Remove the module from cache
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Mock development environment without JWT_SECRET_KEY
        env_vars = {
            "ENVIRONMENT": "development",
        }
        with patch.dict("os.environ", env_vars, clear=True):
            # Should not raise, but may warn
            import warnings

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                auth_module = importlib.import_module("src.api.auth")
                # Check that the module loaded and has the expected fallback
                assert hasattr(auth_module, "JWT_SECRET_KEY")
                assert auth_module.JWT_SECRET_KEY == "dev-secret-key-change-in-production"
                # Should have issued a warning
                assert len(w) >= 1
                assert any("JWT_SECRET_KEY" in str(warning.message) for warning in w)

        # Restore the module for other tests
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]
        importlib.import_module("src.api.auth")

    def test_production_with_jwt_secret_key_succeeds(self):
        """Should succeed in production when JWT_SECRET_KEY is set."""
        # Remove the module from cache
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Mock production environment WITH JWT_SECRET_KEY
        env_vars = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "super-secure-production-key-123",
        }
        with patch.dict("os.environ", env_vars, clear=True):
            # Should not raise
            auth_module = importlib.import_module("src.api.auth")
            assert auth_module.JWT_SECRET_KEY == "super-secure-production-key-123"

        # Restore the module for other tests
        modules_to_remove = [
            key for key in sys.modules if key.startswith("src.api.auth")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]
        importlib.import_module("src.api.auth")
