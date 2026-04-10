"""OpenClaw gateway adapter — delegation and agent management.

Hermes is the orchestrator; OpenClaw agents are the workers.  This adapter
talks to the OpenClaw gateway to:

  1. Check gateway health.
  2. List available OpenClaw agents and their status.
  3. Delegate tasks TO agents.
  4. Collect results FROM agents.

OpenClaw already has its own heartbeat for agent liveness — Hermes does
not need to heartbeat individual agents.  It only needs to query status
and dispatch work.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from daemon.adapters.base import (
    HealthCheckable,
    HealthStatus,
    Task,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger("daemon.adapters.openclaw")


@dataclass
class AgentInfo:
    """Status of a single OpenClaw agent as reported by the gateway."""
    agent_id: str
    name: str
    status: str = "unknown"  # e.g. "idle", "busy", "offline"
    specialization: str = ""
    metadata: dict = field(default_factory=dict)


class OpenClawAdapter(HealthCheckable):
    """Client for the OpenClaw gateway — used by the Hermes orchestrator
    to delegate work to OpenClaw agents and collect their results."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ── Health ────────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        """Probe the OpenClaw gateway health endpoint."""
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
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

    # ── Agent management ──────────────────────────────────────────────
    # TODO: Wire to real OpenClaw API endpoints once they exist.

    async def list_agents(self) -> list[AgentInfo]:
        """List all registered OpenClaw agents and their current status.

        TODO: GET {self._base_url}/api/agents
              Returns list of agent objects with id, name, status, specialization.
        """
        logger.debug("list_agents: no endpoint configured yet — returning empty list")
        return []

    async def get_agent_status(self, agent_id: str) -> Optional[AgentInfo]:
        """Get the status of a specific OpenClaw agent.

        TODO: GET {self._base_url}/api/agents/{agent_id}
        """
        logger.debug("get_agent_status(%s): stub — not yet implemented", agent_id)
        return None

    # ── Task delegation ───────────────────────────────────────────────

    async def delegate_task(self, task: Task, agent_id: str) -> bool:
        """Assign a task to a specific OpenClaw agent.

        TODO: POST {self._base_url}/api/agents/{agent_id}/tasks
              body: {"task_id": task.id, "type": task.type, "payload": task.payload}
        """
        logger.debug(
            "delegate_task: task=%s → agent=%s (stub — not yet implemented)",
            task.id, agent_id,
        )
        return False

    async def collect_results(self) -> list[TaskResult]:
        """Collect completed task results from OpenClaw agents.

        OpenClaw agents push results to the gateway when done.  This method
        pulls any results that haven't been collected yet by this orchestrator.

        TODO: GET {self._base_url}/api/results?status=completed&uncollected=true
        """
        logger.debug("collect_results: stub — not yet implemented")
        return []

    async def acknowledge_result(self, task_id: str) -> bool:
        """Mark a result as collected so it isn't returned again.

        TODO: POST {self._base_url}/api/results/{task_id}/acknowledge
        """
        logger.debug("acknowledge_result(%s): stub — not yet implemented", task_id)
        return False
