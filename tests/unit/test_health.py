"""Tests for health check functionality."""

import asyncio

import pytest

from src.core.health import (
    HealthChecker,
    HealthReport,
    ServiceCheck,
    ServiceStatus,
)


class TestServiceStatus:
    """Tests for ServiceStatus enum."""

    def test_all_statuses_defined(self) -> None:
        """Should have all expected statuses."""
        assert ServiceStatus.HEALTHY
        assert ServiceStatus.UNHEALTHY
        assert ServiceStatus.DEGRADED
        assert ServiceStatus.UNKNOWN

    def test_status_values(self) -> None:
        """Should have correct string values."""
        assert ServiceStatus.HEALTHY.value == "healthy"
        assert ServiceStatus.UNHEALTHY.value == "unhealthy"
        assert ServiceStatus.DEGRADED.value == "degraded"
        assert ServiceStatus.UNKNOWN.value == "unknown"


class TestServiceCheck:
    """Tests for ServiceCheck dataclass."""

    def test_basic_check(self) -> None:
        """Should store basic attributes."""
        check = ServiceCheck(name="test", status=ServiceStatus.HEALTHY)
        assert check.name == "test"
        assert check.status == ServiceStatus.HEALTHY
        assert check.latency_ms is None
        assert check.message is None
        assert check.details == {}

    def test_full_check(self) -> None:
        """Should store all attributes."""
        check = ServiceCheck(
            name="database",
            status=ServiceStatus.HEALTHY,
            latency_ms=5.2,
            message="Connection successful",
            details={"pool_size": 10},
        )
        assert check.name == "database"
        assert check.status == ServiceStatus.HEALTHY
        assert check.latency_ms == 5.2
        assert check.message == "Connection successful"
        assert check.details == {"pool_size": 10}


class TestHealthReport:
    """Tests for HealthReport dataclass."""

    def test_to_dict(self) -> None:
        """Should convert to dictionary correctly."""
        report = HealthReport(
            status=ServiceStatus.HEALTHY,
            timestamp="2025-01-01T00:00:00Z",
            checks=[
                ServiceCheck(
                    name="db",
                    status=ServiceStatus.HEALTHY,
                    latency_ms=5.0,
                ),
                ServiceCheck(
                    name="api",
                    status=ServiceStatus.HEALTHY,
                    latency_ms=10.0,
                    message="OK",
                ),
            ],
            version="1.0.0",
        )

        result = report.to_dict()

        assert result["status"] == "healthy"
        assert result["timestamp"] == "2025-01-01T00:00:00Z"
        assert result["version"] == "1.0.0"
        assert len(result["checks"]) == 2
        assert result["checks"][0]["name"] == "db"
        assert result["checks"][0]["status"] == "healthy"
        assert result["checks"][0]["latency_ms"] == 5.0
        assert result["checks"][1]["name"] == "api"
        assert result["checks"][1]["message"] == "OK"


class TestHealthChecker:
    """Tests for HealthChecker class."""

    async def test_add_check(self) -> None:
        """Should register health check functions."""
        checker = HealthChecker()

        async def check_db():
            return ServiceCheck(name="database", status=ServiceStatus.HEALTHY)

        checker.add_check("database", check_db)

        result = await checker.check_one("database")
        assert result.name == "database"
        assert result.status == ServiceStatus.HEALTHY

    async def test_remove_check(self) -> None:
        """Should remove registered health check."""
        checker = HealthChecker()

        async def check_db():
            return ServiceCheck(name="database", status=ServiceStatus.HEALTHY)

        checker.add_check("database", check_db)
        checker.remove_check("database")

        with pytest.raises(KeyError):
            await checker.check_one("database")

    async def test_check_one_unknown_raises(self) -> None:
        """Should raise KeyError for unknown check."""
        checker = HealthChecker()

        with pytest.raises(KeyError, match="No health check registered for: unknown"):
            await checker.check_one("unknown")

    async def test_check_one_adds_latency(self) -> None:
        """Should add latency if not provided by check."""
        checker = HealthChecker()

        async def check_slow():
            await asyncio.sleep(0.01)
            return ServiceCheck(name="slow", status=ServiceStatus.HEALTHY)

        checker.add_check("slow", check_slow)

        result = await checker.check_one("slow")
        assert result.latency_ms is not None
        assert result.latency_ms >= 10  # At least 10ms

    async def test_check_one_preserves_latency(self) -> None:
        """Should preserve latency if provided by check."""
        checker = HealthChecker()

        async def check_with_latency():
            return ServiceCheck(
                name="custom",
                status=ServiceStatus.HEALTHY,
                latency_ms=42.0,
            )

        checker.add_check("custom", check_with_latency)

        result = await checker.check_one("custom")
        assert result.latency_ms == 42.0

    async def test_check_one_handles_timeout(self) -> None:
        """Should mark as unhealthy on timeout."""
        checker = HealthChecker()

        # Test that regular exceptions in checks are caught and marked unhealthy
        async def check_error():
            raise TimeoutError("Connection timed out")

        checker.add_check("timeout", check_error)
        result = await checker.check_one("timeout")
        assert result.status == ServiceStatus.UNHEALTHY
        assert "timed out" in result.message.lower()

    async def test_check_one_handles_exception(self) -> None:
        """Should mark as unhealthy on exception."""
        checker = HealthChecker()

        async def check_error():
            raise RuntimeError("Connection failed")

        checker.add_check("failing", check_error)

        result = await checker.check_one("failing")
        assert result.status == ServiceStatus.UNHEALTHY
        assert "Connection failed" in result.message
        assert result.latency_ms is not None

    async def test_check_all_empty(self) -> None:
        """Should return healthy report with no checks."""
        checker = HealthChecker()

        report = await checker.check_all()
        assert report.status == ServiceStatus.HEALTHY
        assert report.checks == []
        assert report.timestamp is not None

    async def test_check_all_all_healthy(self) -> None:
        """Should return healthy when all checks pass."""
        checker = HealthChecker()

        async def check_a():
            return ServiceCheck(name="a", status=ServiceStatus.HEALTHY)

        async def check_b():
            return ServiceCheck(name="b", status=ServiceStatus.HEALTHY)

        checker.add_check("a", check_a)
        checker.add_check("b", check_b)

        report = await checker.check_all()
        assert report.status == ServiceStatus.HEALTHY
        assert len(report.checks) == 2

    async def test_check_all_one_unhealthy(self) -> None:
        """Should return unhealthy when any check fails."""
        checker = HealthChecker()

        async def check_healthy():
            return ServiceCheck(name="healthy", status=ServiceStatus.HEALTHY)

        async def check_unhealthy():
            return ServiceCheck(name="unhealthy", status=ServiceStatus.UNHEALTHY)

        checker.add_check("healthy", check_healthy)
        checker.add_check("unhealthy", check_unhealthy)

        report = await checker.check_all()
        assert report.status == ServiceStatus.UNHEALTHY

    async def test_check_all_degraded(self) -> None:
        """Should return degraded when some checks degraded but none unhealthy."""
        checker = HealthChecker()

        async def check_healthy():
            return ServiceCheck(name="healthy", status=ServiceStatus.HEALTHY)

        async def check_degraded():
            return ServiceCheck(name="degraded", status=ServiceStatus.DEGRADED)

        checker.add_check("healthy", check_healthy)
        checker.add_check("degraded", check_degraded)

        report = await checker.check_all()
        assert report.status == ServiceStatus.DEGRADED

    async def test_check_all_includes_version(self) -> None:
        """Should include version in report."""
        checker = HealthChecker(version="2.0.0")

        report = await checker.check_all()
        assert report.version == "2.0.0"

    async def test_check_all_runs_concurrently(self) -> None:
        """Should run all checks concurrently."""
        checker = HealthChecker()
        start_times = {}

        async def check_a():
            start_times["a"] = asyncio.get_event_loop().time()
            await asyncio.sleep(0.05)
            return ServiceCheck(name="a", status=ServiceStatus.HEALTHY)

        async def check_b():
            start_times["b"] = asyncio.get_event_loop().time()
            await asyncio.sleep(0.05)
            return ServiceCheck(name="b", status=ServiceStatus.HEALTHY)

        checker.add_check("a", check_a)
        checker.add_check("b", check_b)

        start = asyncio.get_event_loop().time()
        await checker.check_all()
        elapsed = asyncio.get_event_loop().time() - start

        # If run sequentially, would take ~100ms
        # If run concurrently, should take ~50ms
        assert elapsed < 0.1  # Allow some margin

    async def test_check_all_handles_exception_in_check(self) -> None:
        """Should handle exceptions in individual checks."""
        checker = HealthChecker()

        async def check_ok():
            return ServiceCheck(name="ok", status=ServiceStatus.HEALTHY)

        async def check_fail():
            raise RuntimeError("Boom")

        checker.add_check("ok", check_ok)
        checker.add_check("fail", check_fail)

        report = await checker.check_all()
        assert report.status == ServiceStatus.UNHEALTHY

        ok_check = next(c for c in report.checks if c.name == "ok")
        fail_check = next(c for c in report.checks if c.name == "fail")

        assert ok_check.status == ServiceStatus.HEALTHY
        assert fail_check.status == ServiceStatus.UNHEALTHY
        assert "Boom" in fail_check.message
