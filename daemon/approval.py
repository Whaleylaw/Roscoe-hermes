"""Approval routing — ensures results go to review, never auto-accepted."""

from __future__ import annotations

import logging

from daemon.adapters.base import ApprovalRouter, TaskResult, TaskStatus

logger = logging.getLogger("daemon.approval")


class LocalApprovalRouter(ApprovalRouter):
    """Fallback approval router that logs results locally.

    Used when Mission Control is not yet configured.  Results are written
    to the daemon log at WARNING level so they're impossible to miss.
    In production this should be replaced by MissionControlAdapter which
    implements the same ApprovalRouter interface.
    """

    async def submit_for_review(self, result: TaskResult) -> bool:
        # Force status to pending_review regardless of input.
        result.status = TaskStatus.PENDING_REVIEW
        logger.warning(
            "APPROVAL REQUIRED — task=%s worker=%s status=%s output=%r",
            result.task_id,
            result.worker_id,
            result.status.value,
            result.output,
        )
        return True
