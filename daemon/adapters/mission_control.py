"""Mission Control adapter — interface only.

Mission Control is the orchestration/task-queue layer.  Hermes polls it for
tasks that need orchestrating, then delegates them to OpenClaw agents.
Completed results are routed back through Mission Control for approval.

TODO: Implement once the Mission Control API is defined.
"""

from __future__ import annotations

import logging
from typing import Optional

from daemon.adapters.base import (
    ApprovalRouter,
    HealthCheckable,
    HealthStatus,
    Task,
    TaskResult,
    TaskSource,
    TaskStatus,
)

logger = logging.getLogger("daemon.adapters.mission_control")


class MissionControlAdapter(HealthCheckable, TaskSource, ApprovalRouter):
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

    # ── Task source ───────────────────────────────────────────────────

    async def poll_tasks(self) -> list[Task]:
        """Pull tasks that Hermes needs to orchestrate.

        TODO: GET {self._base_url}/api/tasks?status=pending&orchestrator=hermes
        """
        if not self.configured:
            return []
        logger.debug("poll_tasks: stub — not yet implemented")
        return []

    async def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update task status in Mission Control.

        TODO: PATCH {self._base_url}/api/tasks/{task_id}
              body: {"status": status.value}
        """
        if not self.configured:
            return False
        logger.debug("update_task_status(%s, %s): stub", task_id, status.value)
        return False

    # ── Approval ──────────────────────────────────────────────────────

    async def submit_for_review(self, result: TaskResult) -> bool:
        """Route a result into Mission Control's approval queue.

        TODO: POST {self._base_url}/api/reviews
              body: {"task_id": result.task_id, "agent_id": result.agent_id,
                     "orchestrator_id": result.orchestrator_id,
                     "output": result.output, "status": "pending_review"}
        """
        if not self.configured:
            logger.warning("Cannot submit for review — Mission Control not configured")
            return False
        logger.info(
            "submit_for_review: task=%s (stub — not yet implemented)",
            result.task_id,
        )
        return False
