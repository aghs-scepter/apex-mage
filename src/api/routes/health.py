"""Health check routes for the HTTP API.

These routes provide health, readiness, and liveness endpoints
for container orchestration and monitoring systems.
"""

from typing import Any

from fastapi import APIRouter, Request, Response

from src.core.health import ServiceStatus
from src.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request, response: Response) -> dict[str, Any]:
    """Full health check with all service statuses.

    Returns 200 if all services are healthy, 503 otherwise.
    """
    health_checker = request.app.state.health_checker
    report = await health_checker.check_all()

    response.status_code = 200 if report.status == ServiceStatus.HEALTHY else 503

    logger.info(
        "health_check",
        status=report.status.value,
        checks={c.name: c.status.value for c in report.checks},
    )

    return report.to_dict()


@router.get("/ready")
async def readiness_check(request: Request, response: Response) -> dict[str, Any]:
    """Readiness probe for Kubernetes/container orchestration.

    Returns 200 if the service is ready to receive traffic, 503 otherwise.
    """
    health_checker = request.app.state.health_checker
    report = await health_checker.check_all()
    is_ready = report.status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)

    response.status_code = 200 if is_ready else 503

    return {"ready": is_ready, "status": report.status.value}


@router.get("/live")
async def liveness_check() -> dict[str, bool]:
    """Liveness probe for Kubernetes/container orchestration.

    Returns 200 if the service is alive (not deadlocked).
    """
    return {"alive": True}
