"""Orchestration loop — polls for tasks, delegates to OpenClaw agents, collects results."""

from __future__ import annotations

import logging
from typing import Optional

from daemon.adapters.base import (
    ApprovalRouter,
    Task,
    TaskResult,
    TaskSource,
    TaskStatus,
)
from daemon.adapters.openclaw import OpenClawAdapter

logger = logging.getLogger("daemon.poller")


async def poll_for_tasks(sources: list[TaskSource]) -> list[Task]:
    """Poll task sources (e.g. Mission Control) for work that needs orchestrating."""
    tasks: list[Task] = []
    for source in sources:
        try:
            batch = await source.poll_tasks()
            if batch:
                logger.info("poll: got %d task(s) from %s", len(batch), type(source).__name__)
                tasks.extend(batch)
        except Exception as exc:
            logger.error("poll: error from %s — %s", type(source).__name__, exc)
    if not tasks:
        logger.info("poll: no tasks available from any source")
    return tasks


async def delegate_task(
    task: Task,
    openclaw: OpenClawAdapter,
    orchestrator_id: str,
) -> bool:
    """Pick an available OpenClaw agent and delegate the task to it.

    TODO: Implement agent selection logic (by specialization, availability, etc.).
    For now this attempts to delegate to the first idle agent, or logs that
    no agents are available.
    """
    agents = await openclaw.list_agents()
    idle_agents = [a for a in agents if a.status == "idle"]

    if not idle_agents:
        logger.warning("delegate: no idle OpenClaw agents available for task %s", task.id)
        return False

    # Simple selection: pick the first idle agent.
    # TODO: Match task.type to agent specialization.
    target = idle_agents[0]
    logger.info("delegate: assigning task %s → agent %s (%s)",
                task.id, target.agent_id, target.name)

    ok = await openclaw.delegate_task(task, target.agent_id)
    if ok:
        task.status = TaskStatus.ASSIGNED
        task.assigned_agent = target.agent_id
        logger.info("delegate: task %s assigned to agent %s", task.id, target.agent_id)
    else:
        logger.warning("delegate: failed to assign task %s to agent %s",
                        task.id, target.agent_id)
    return ok


async def collect_and_route_results(
    openclaw: OpenClawAdapter,
    approval_router: Optional[ApprovalRouter],
    orchestrator_id: str,
    *,
    approval_only: bool = True,
) -> int:
    """Collect completed results from OpenClaw agents and route to approval.

    Returns the number of results processed.
    """
    results = await openclaw.collect_results()
    if not results:
        return 0

    logger.info("collect: %d result(s) from OpenClaw agents", len(results))
    processed = 0

    for result in results:
        result.orchestrator_id = orchestrator_id

        # Enforce approval-only mode.
        if approval_only:
            result.status = TaskStatus.PENDING_REVIEW

        # Route to approval pipeline.
        if approval_router is not None:
            try:
                ok = await approval_router.submit_for_review(result)
                if ok:
                    logger.info("route: task %s submitted for review", result.task_id)
                else:
                    logger.warning("route: failed to submit task %s for review", result.task_id)
            except Exception as exc:
                logger.error("route: error submitting task %s — %s", result.task_id, exc)
        else:
            logger.warning(
                "route: no approval router — task %s result logged but not routed",
                result.task_id,
            )

        # Acknowledge collection so OpenClaw doesn't return it again.
        try:
            await openclaw.acknowledge_result(result.task_id)
        except Exception as exc:
            logger.error("route: error acknowledging result %s — %s", result.task_id, exc)

        processed += 1

    return processed
