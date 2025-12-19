"""Health check endpoint and service status monitoring.

This module provides health check functionality for monitoring the status
of all external services and the application itself.

Example:
    from src.core.health import HealthChecker, start_health_server

    # Create checker with service checkers
    checker = HealthChecker()
    checker.add_check("database", check_database)
    checker.add_check("anthropic", check_anthropic)

    # Start HTTP server on port 8080
    await start_health_server(checker, port=8080)
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from aiohttp import web

from src.core.logging import get_logger

logger = get_logger(__name__)


class ServiceStatus(Enum):
    """Status of an individual service."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ServiceCheck:
    """Result of a single service health check."""

    name: str
    status: ServiceStatus
    latency_ms: float | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """Aggregated health report for all services."""

    status: ServiceStatus
    timestamp: str
    checks: list[ServiceCheck]
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "version": self.version,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "latency_ms": check.latency_ms,
                    "message": check.message,
                    "details": check.details,
                }
                for check in self.checks
            ],
        }


# Type alias for health check functions
HealthCheckFunc = Callable[[], Coroutine[Any, Any, ServiceCheck]]


class HealthChecker:
    """Manages health checks for multiple services.

    Example:
        checker = HealthChecker(version="1.0.0")

        async def check_db():
            # Check database connectivity
            return ServiceCheck(name="database", status=ServiceStatus.HEALTHY)

        checker.add_check("database", check_db)
        report = await checker.check_all()
    """

    def __init__(self, version: str | None = None) -> None:
        """Initialize the health checker.

        Args:
            version: Application version to include in health reports.
        """
        self._checks: dict[str, HealthCheckFunc] = {}
        self._version = version

    def add_check(self, name: str, check_func: HealthCheckFunc) -> None:
        """Register a health check function.

        Args:
            name: Name of the service to check.
            check_func: Async function that returns a ServiceCheck.
        """
        self._checks[name] = check_func

    def remove_check(self, name: str) -> None:
        """Remove a registered health check.

        Args:
            name: Name of the service check to remove.
        """
        self._checks.pop(name, None)

    async def check_one(self, name: str) -> ServiceCheck:
        """Run a single health check.

        Args:
            name: Name of the service to check.

        Returns:
            ServiceCheck result.

        Raises:
            KeyError: If no check is registered with that name.
        """
        if name not in self._checks:
            raise KeyError(f"No health check registered for: {name}")

        check_func = self._checks[name]
        start = asyncio.get_event_loop().time()

        try:
            result = await asyncio.wait_for(check_func(), timeout=10.0)
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            if result.latency_ms is None:
                result.latency_ms = round(elapsed, 2)
            return result
        except TimeoutError:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return ServiceCheck(
                name=name,
                status=ServiceStatus.UNHEALTHY,
                latency_ms=round(elapsed, 2),
                message="Health check timed out",
            )
        except Exception as ex:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return ServiceCheck(
                name=name,
                status=ServiceStatus.UNHEALTHY,
                latency_ms=round(elapsed, 2),
                message=str(ex),
            )

    async def check_all(self) -> HealthReport:
        """Run all registered health checks.

        Returns:
            HealthReport with aggregated results.
        """
        timestamp = datetime.now(UTC).isoformat()

        if not self._checks:
            return HealthReport(
                status=ServiceStatus.HEALTHY,
                timestamp=timestamp,
                checks=[],
                version=self._version,
            )

        # Run all checks concurrently
        check_tasks = [self.check_one(name) for name in self._checks]
        results = await asyncio.gather(*check_tasks, return_exceptions=True)

        checks: list[ServiceCheck] = []
        for name, result in zip(self._checks.keys(), results, strict=True):
            if isinstance(result, BaseException):
                checks.append(
                    ServiceCheck(
                        name=name,
                        status=ServiceStatus.UNHEALTHY,
                        message=str(result),
                    )
                )
            else:
                checks.append(result)

        # Determine overall status
        if all(c.status == ServiceStatus.HEALTHY for c in checks):
            overall = ServiceStatus.HEALTHY
        elif any(c.status == ServiceStatus.UNHEALTHY for c in checks):
            overall = ServiceStatus.UNHEALTHY
        elif any(c.status == ServiceStatus.DEGRADED for c in checks):
            overall = ServiceStatus.DEGRADED
        else:
            overall = ServiceStatus.UNKNOWN

        return HealthReport(
            status=overall,
            timestamp=timestamp,
            checks=checks,
            version=self._version,
        )


class HealthServer:
    """HTTP server for health check endpoints.

    Provides /health and /ready endpoints for container orchestration.
    """

    def __init__(
        self,
        checker: HealthChecker,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        """Initialize the health server.

        Args:
            checker: The HealthChecker instance to use.
            host: Host to bind to.
            port: Port to listen on.
        """
        self._checker = checker
        self._host = host
        self._port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle /health endpoint - full health check."""
        report = await self._checker.check_all()
        status_code = 200 if report.status == ServiceStatus.HEALTHY else 503

        logger.info(
            "health_check",
            status=report.status.value,
            checks={c.name: c.status.value for c in report.checks},
        )

        return web.json_response(report.to_dict(), status=status_code)

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """Handle /ready endpoint - simple readiness check."""
        report = await self._checker.check_all()
        is_ready = report.status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)

        return web.json_response(
            {"ready": is_ready, "status": report.status.value},
            status=200 if is_ready else 503,
        )

    async def _handle_live(self, request: web.Request) -> web.Response:
        """Handle /live endpoint - simple liveness check."""
        return web.json_response({"alive": True}, status=200)

    async def start(self) -> None:
        """Start the health server."""
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/ready", self._handle_ready)
        self._app.router.add_get("/live", self._handle_live)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        logger.info("health_server_started", host=self._host, port=self._port)

    async def stop(self) -> None:
        """Stop the health server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("health_server_stopped")


async def start_health_server(
    checker: HealthChecker,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> HealthServer:
    """Start a health check HTTP server.

    Args:
        checker: The HealthChecker instance to use.
        host: Host to bind to.
        port: Port to listen on.

    Returns:
        The running HealthServer instance.
    """
    server = HealthServer(checker, host, port)
    await server.start()
    return server
