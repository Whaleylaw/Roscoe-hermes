"""OpenClaw gateway adapter.

Provides health checking and (future) queue polling against the existing
OpenClaw backend at https://openclaw-gateway-dfdi.onrender.com.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from daemon.adapters.base import (
    HealthCheckable,
    HealthStatus,
    QueueAdapter,
    Task,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger("daemon.adapters.openclaw")


class OpenClawAdapter(HealthCheckable, QueueAdapter):
    """Client for the OpenClaw gateway."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ── Health ────────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        """Probe the OpenClaw gateway health endpoint."""
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # Try common health endpoints; fall back to root.
                for path in ("/health", "/api/health", "/"):
                    try:
                        resp = await client.get(f"{self._base_url}{path}")
                        if resp.status_code < 500:
                            latency = (time.monotonic() - t0) * 1000
                            return HealthStatus(
                                service_name="openclaw",
                                healthy=True,
                                latency_ms=round(latency, 1),
                            )
                    except httpx.HTTPError:
                        continue
            return HealthStatus(
                service_name="openclaw",
                healthy=False,
                error="All health endpoints unreachable",
            )
        except Exception as exc:
            return HealthStatus(
                service_name="openclaw",
                healthy=False,
                error=str(exc),
            )

    # ── Queue ─────────────────────────────────────────────────────────
    # TODO: Wire to real OpenClaw task/queue endpoints once they exist.
    # The interface is defined here so the supervisor can call it without
    # any conditional import gymnastics.

    async def poll(self) -> Optional[Task]:
        """Poll OpenClaw for available tasks.

        Returns ``None`` until a real queue endpoint is implemented.
        """
        # TODO: Replace with actual API call, e.g.:
        #   GET {self._base_url}/api/tasks?status=pending&limit=1
        logger.debug("poll: no queue endpoint configured yet — returning None")
        return None

    async def claim(self, task: Task, worker_id: str) -> bool:
        """Claim a task from OpenClaw.

        Returns ``False`` until a real claim endpoint is implemented.
        """
        # TODO: Replace with actual API call, e.g.:
        #   POST {self._base_url}/api/tasks/{task.id}/claim
        #   body: {"worker_id": worker_id}
        logger.debug("claim: no claim endpoint configured yet — returning False")
        return False

    async def report(self, result: TaskResult) -> bool:
        """Report a task result back to OpenClaw.

        Returns ``False`` until a real report endpoint is implemented.
        """
        # TODO: Replace with actual API call, e.g.:
        #   POST {self._base_url}/api/tasks/{result.task_id}/result
        #   body: {"worker_id": result.worker_id, "output": result.output,
        #          "status": result.status.value}
        logger.debug("report: no report endpoint configured yet — returning False")
        return False
