"""Tests for the HTTP API module."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import AppState, get_app_state


class TestAppState:
    """Tests for AppState class."""

    def test_initial_state(self) -> None:
        """Should start uninitialized."""
        state = AppState()
        assert state.is_initialized is False

    def test_repository_raises_before_init(self) -> None:
        """Should raise when accessing repository before init."""
        state = AppState()
        with pytest.raises(RuntimeError, match="App state not initialized"):
            _ = state.repository

    def test_ai_provider_raises_before_init(self) -> None:
        """Should raise when accessing ai_provider before init."""
        state = AppState()
        with pytest.raises(RuntimeError, match="App state not initialized"):
            _ = state.ai_provider

    def test_image_provider_raises_before_init(self) -> None:
        """Should raise when accessing image_provider before init."""
        state = AppState()
        with pytest.raises(RuntimeError, match="App state not initialized"):
            _ = state.image_provider

    def test_rate_limiter_raises_before_init(self) -> None:
        """Should raise when accessing rate_limiter before init."""
        state = AppState()
        with pytest.raises(RuntimeError, match="App state not initialized"):
            _ = state.rate_limiter

    def test_gcs_adapter_raises_before_init(self) -> None:
        """Should raise when accessing gcs_adapter before init."""
        state = AppState()
        with pytest.raises(RuntimeError, match="App state not initialized"):
            _ = state.gcs_adapter


class TestCreateApp:
    """Tests for create_app factory."""

    def test_creates_app_with_defaults(self) -> None:
        """Should create app with default configuration."""
        app = create_app()
        assert app.title == "Apex Mage API"
        assert app.version is not None

    def test_creates_app_with_custom_title(self) -> None:
        """Should create app with custom title."""
        app = create_app(title="Custom API")
        assert app.title == "Custom API"

    def test_creates_app_with_custom_cors(self) -> None:
        """Should create app with custom CORS origins."""
        app = create_app(cors_origins=["http://localhost:3000"])
        # CORS middleware is added
        assert len(app.user_middleware) > 0

    def test_includes_health_router(self) -> None:
        """Should include health check routes."""
        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/health" in routes
        assert "/ready" in routes
        assert "/live" in routes


class TestHealthRoutes:
    """Tests for health check routes without full initialization."""

    def test_liveness_endpoint(self) -> None:
        """Should return alive status without initialization."""
        app = create_app()

        # Override lifespan to skip initialization
        from contextlib import asynccontextmanager

        from src.core.health import HealthChecker

        @asynccontextmanager
        async def test_lifespan(app):
            app.state.health_checker = HealthChecker(version="test")
            yield

        app.router.lifespan_context = test_lifespan

        with TestClient(app) as client:
            response = client.get("/live")
            assert response.status_code == 200
            assert response.json() == {"alive": True}

    def test_readiness_endpoint_with_no_checks(self) -> None:
        """Should return ready when no checks registered."""
        app = create_app()

        from contextlib import asynccontextmanager

        from src.core.health import HealthChecker

        @asynccontextmanager
        async def test_lifespan(app):
            app.state.health_checker = HealthChecker(version="test")
            yield

        app.router.lifespan_context = test_lifespan

        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["status"] == "healthy"

    def test_health_endpoint_with_no_checks(self) -> None:
        """Should return healthy when no checks registered."""
        app = create_app()

        from contextlib import asynccontextmanager

        from src.core.health import HealthChecker

        @asynccontextmanager
        async def test_lifespan(app):
            app.state.health_checker = HealthChecker(version="test")
            yield

        app.router.lifespan_context = test_lifespan

        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["version"] == "test"
            assert data["checks"] == []


class TestGetAppState:
    """Tests for get_app_state function."""

    def test_returns_singleton(self) -> None:
        """Should return the same instance on multiple calls."""
        state1 = get_app_state()
        state2 = get_app_state()
        assert state1 is state2
