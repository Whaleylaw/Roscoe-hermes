"""Mission Control adapter — interface only.

Mission Control is the orchestration layer that assigns tasks, tracks agent
status, and manages the approval pipeline.  The client code does not exist
yet; this module defines the interface so the supervisor and approval router
can reference it cleanly.

TODO: Implement once the Mission Control API is defined.
"""

from __future__ import annotations

import logging
from typing import Optional

from daemon.adapters.base import (
    ApprovalRouter,
    HealthCheckable,
    HealthStatus,
    QueueAdapter,
    Task,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger("daemon.adapters.mission_control")


class MissionControlAdapter(HealthCheckable, QueueAdapter, ApprovalRouter):
    """Stub adapter for Mission Control.

    All methods return safe no-op values.  Replace the bodies with real
    HTTP calls once the Mission Control API is available.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = timeout
        if not self._base_url:
            logger.info("Mission Control URL not configured — adapter disabled")

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    # ── Health ────────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        if not self.configured:
            return HealthStatus(
                service_name="mission_control",
                healthy=False,
                error="URL not configured",
            )
        # TODO: GET {self._base_url}/health
        return HealthStatus(
            service_name="mission_control",
            healthy=False,
            error="Not implemented",
        )

    # ── Queue ─────────────────────────────────────────────────────────

    async def poll(self) -> Optional[Task]:
        # TODO: GET {self._base_url}/api/tasks?status=pending&limit=1
        return None

    async def claim(self, task: Task, worker_id: str) -> bool:
        # TODO: POST {self._base_url}/api/tasks/{task.id}/claim
        return False

    async def report(self, result: TaskResult) -> bool:
        # TODO: POST {self._base_url}/api/tasks/{result.task_id}/result
        return False

    # ── Approval ──────────────────────────────────────────────────────

    async def submit_for_review(self, result: TaskResult) -> bool:
        """Route a result into Mission Control's approval queue.

        TODO: POST {self._base_url}/api/reviews
              body: {"task_id": result.task_id, "worker_id": result.worker_id,
                     "output": result.output, "status": "pending_review"}
        """
        if not self.configured:
            logger.warning("Cannot submit for review — Mission Control not configured")
            return False
        logger.info(
            "submit_for_review: task=%s status=%s (stub — not yet implemented)",
            result.task_id,
            result.status.value,
        )
        return False
