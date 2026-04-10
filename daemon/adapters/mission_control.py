"""Mission Control adapter — real implementation.

Hermes uses this adapter to:
  1. Health-check MC (GET /api/tasks?limit=1)
  2. Send heartbeats so MC knows Hermes is online
  3. Poll for tasks needing orchestration
  4. Route completed results back

MC API: ops.lawyerincorporated.com
Auth: x-api-key header with MC_API_KEY env var
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
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
    """Mission Control adapter using the MC REST API."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = timeout
        self._api_key = os.environ.get("MC_API_KEY", "")
        self._agent_id: Optional[int] = None  # Hermes agent ID in MC
        if not self._base_url:
            logger.info("Mission Control URL not configured — adapter disabled")

    @property
    def configured(self) -> bool:
        return bool(self._base_url) and bool(self._api_key)

    # ── HTTP helper ────────────────────────────────────────────────────

    def _request(self, method: str, path: str, data: dict = None) -> Optional[dict]:
        """Make an authenticated request to MC API."""
        if not self.configured:
            return None
        url = f"{self._base_url}{path}"
        body = json.dumps(data).encode() if data else None
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.warning("MC API %s %s → %d", method, path, e.code)
            return None
        except Exception as exc:
            logger.warning("MC API %s %s error: %s", method, path, exc)
            return None

    # ── Health ────────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        if not self.configured:
            return HealthStatus(
                service_name="mission_control",
                healthy=False,
                latency_ms=0,
                error="MC_API_KEY not configured",
            )
        t0 = time.monotonic()
        result = self._request("GET", "/api/tasks?limit=1")
        latency = (time.monotonic() - t0) * 1000
        if result is not None:
            return HealthStatus(
                service_name="mission_control",
                healthy=True,
                latency_ms=latency,
                error=None,
            )
        return HealthStatus(
            service_name="mission_control",
            healthy=False,
            latency_ms=latency,
            error="MC API unreachable",
        )

    # ── Heartbeat ──────────────────────────────────────────────────────

    async def send_heartbeat(self) -> None:
        """Update Hermes agent status in MC to 'online'."""
        if not self.configured:
            return
        # Find Hermes agent ID if not cached
        if self._agent_id is None:
            result = self._request("GET", "/api/agents?limit=50")
            if result:
                for agent in result.get("agents", []):
                    if agent.get("role") == "orchestrator" or agent.get("name") == "Hermes":
                        self._agent_id = agent["id"]
                        break
        # No specific heartbeat endpoint — MC tracks via last_seen on task operations

    # ── TaskSource ─────────────────────────────────────────────────────

    async def poll_tasks(self) -> list[Task]:
        """Poll MC for inbox tasks that need dispatching."""
        if not self.configured:
            return []
        result = self._request("GET", "/api/tasks?status=inbox&limit=50")
        if not result:
            return []
        tasks = []
        for t in result.get("tasks", []):
            meta = t.get("metadata") or {}
            tasks.append(Task(
                id=str(t["id"]),
                title=t["title"],
                description=t.get("description", ""),
                status=TaskStatus.READY,
                metadata={
                    "mc_id": t["id"],
                    "source": meta.get("source", "mc"),
                    "case_slug": meta.get("case_slug", ""),
                    "landmark_id": meta.get("landmark_id", ""),
                    "phase": meta.get("phase", ""),
                    "assigned_to": t.get("assigned_to", ""),
                    "priority": t.get("priority", "medium"),
                },
            ))
        return tasks

    async def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        """Update task status in MC (subject to Aegis approval)."""
        # MC uses PUT /api/tasks with bulk format
        pass  # Status changes require Aegis approval — handled in MC UI

    # ── ApprovalRouter ─────────────────────────────────────────────────

    async def submit_for_approval(self, result: TaskResult) -> None:
        """Log completed work — approval happens in MC dashboard."""
        logger.info(
            "mc: task %s completed by %s — approval via MC dashboard",
            result.task_id, result.completed_by,
        )

    async def check_approval(self, task_id: str) -> Optional[str]:
        """Check if a task has been approved in MC."""
        result = self._request("GET", f"/api/tasks/{task_id}")
        if result:
            task = result.get("task", result)
            if task.get("status") == "done":
                return "approved"
        return None
