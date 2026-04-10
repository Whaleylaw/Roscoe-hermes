"""Health-check aggregator for upstream services."""

from __future__ import annotations

import logging
from typing import Sequence

from daemon.adapters.base import HealthCheckable, HealthStatus

logger = logging.getLogger("daemon.health")


async def check_all(services: Sequence[HealthCheckable]) -> list[HealthStatus]:
    """Probe every service and return all results.

    Individual failures are caught so one broken service doesn't prevent
    the rest from being checked.
    """
    results: list[HealthStatus] = []
    for svc in services:
        try:
            status = await svc.health_check()
        except Exception as exc:
            status = HealthStatus(
                service_name=type(svc).__name__,
                healthy=False,
                error=f"Unhandled exception: {exc}",
            )
        results.append(status)
    return results


def log_health(statuses: list[HealthStatus]) -> bool:
    """Log each health result and return True if ALL services are healthy."""
    all_healthy = True
    for s in statuses:
        if s.healthy:
            extra = f" ({s.latency_ms:.0f}ms)" if s.latency_ms is not None else ""
            logger.info("health: %s OK%s", s.service_name, extra)
        else:
            logger.warning("health: %s UNHEALTHY — %s", s.service_name, s.error)
            all_healthy = False
    return all_healthy
