"""Task poller — polls adapters for work, claims, and routes results."""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from daemon.adapters.base import (
    ApprovalRouter,
    QueueAdapter,
    Task,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger("daemon.poller")


async def poll_for_work(queues: Sequence[QueueAdapter]) -> Optional[tuple[QueueAdapter, Task]]:
    """Poll each queue adapter in priority order.  Return the first available task."""
    for queue in queues:
        try:
            task = await queue.poll()
            if task is not None:
                logger.info("poll: found task %s (type=%s) from %s",
                            task.id, task.type, type(queue).__name__)
                return queue, task
        except Exception as exc:
            logger.error("poll: error from %s — %s", type(queue).__name__, exc)
    return None


async def claim_task(queue: QueueAdapter, task: Task, worker_id: str) -> bool:
    """Attempt to claim *task* via its source queue."""
    try:
        ok = await queue.claim(task, worker_id)
        if ok:
            logger.info("claim: task %s claimed by worker %s", task.id, worker_id)
        else:
            logger.warning("claim: failed to claim task %s (already taken?)", task.id)
        return ok
    except Exception as exc:
        logger.error("claim: error claiming task %s — %s", task.id, exc)
        return False


async def execute_task(task: Task, worker_id: str) -> TaskResult:
    """Execute *task* and return a TaskResult.

    TODO: Wire this to Hermes agent capabilities.  For now returns a
    placeholder result so the approval pipeline can be tested end-to-end.
    """
    # TODO: Integrate with Hermes agent loop:
    #   1. Read task.payload for instructions / document references
    #   2. Invoke Hermes agent (or a subagent) to do the work
    #   3. Capture the agent's output
    #   4. Package it into a TaskResult
    logger.info("execute: task %s — stub execution (no agent wired yet)", task.id)
    return TaskResult(
        task_id=task.id,
        worker_id=worker_id,
        output={"note": "Stub execution — agent integration pending"},
        status=TaskStatus.PENDING_REVIEW,
    )


async def route_result(
    result: TaskResult,
    source_queue: QueueAdapter,
    approval_router: Optional[ApprovalRouter],
    *,
    approval_only: bool = True,
) -> bool:
    """Route a task result to approval and/or back to the source queue.

    When *approval_only* is True (the testing default), results are sent
    to the approval router and NEVER marked as accepted automatically.
    """
    if approval_only:
        result.status = TaskStatus.PENDING_REVIEW

    success = True

    # Submit to approval pipeline if available.
    if approval_router is not None:
        try:
            ok = await approval_router.submit_for_review(result)
            if ok:
                logger.info("route: task %s submitted for review", result.task_id)
            else:
                logger.warning("route: failed to submit task %s for review", result.task_id)
                success = False
        except Exception as exc:
            logger.error("route: error submitting task %s for review — %s",
                         result.task_id, exc)
            success = False
    else:
        logger.warning(
            "route: no approval router configured — task %s result logged but not routed",
            result.task_id,
        )

    # Report back to source queue (sets status so the task isn't re-polled).
    try:
        await source_queue.report(result)
    except Exception as exc:
        logger.error("route: error reporting result for task %s — %s",
                     result.task_id, exc)
        success = False

    return success
