"""Abstract base classes and shared data types for service adapters."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Shared data types ────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"       # Delegated to an OpenClaw agent
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"  # Approval-only output state
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Task:
    """A unit of work to be delegated to an OpenClaw agent."""
    id: str
    type: str  # e.g. "document_review", "research", "drafting"
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: Optional[str] = None


@dataclass
class TaskResult:
    """Output collected from an OpenClaw agent after task completion."""
    task_id: str
    agent_id: str  # The OpenClaw agent that produced this result
    orchestrator_id: str = ""  # Hermes worker_id that orchestrated
    output: Any = None
    error: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING_REVIEW  # Safe default


@dataclass
class HealthStatus:
    """Health of an upstream service."""
    service_name: str
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# ── Abstract adapters ────────────────────────────────────────────────

class TaskSource(abc.ABC):
    """Interface for pulling orchestration tasks (from Mission Control)."""

    @abc.abstractmethod
    async def poll_tasks(self) -> list[Task]:
        """Return available tasks that need orchestration."""

    @abc.abstractmethod
    async def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update the status of a task in the source system."""


class HealthCheckable(abc.ABC):
    """Interface for services that support a health probe."""

    @abc.abstractmethod
    async def health_check(self) -> HealthStatus:
        """Probe the service and return its health."""


class ApprovalRouter(abc.ABC):
    """Interface for routing task results to review/approval."""

    @abc.abstractmethod
    async def submit_for_review(self, result: TaskResult) -> bool:
        """Route *result* into the approval pipeline.  Return True on success."""
