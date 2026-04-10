"""Abstract base classes for service adapters."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Shared data types ────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"  # Approval-only output state
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Task:
    """A unit of work pulled from the queue."""
    id: str
    type: str  # e.g. "document_review", "research", "drafting"
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class TaskResult:
    """Output produced by executing a Task."""
    task_id: str
    worker_id: str
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

class QueueAdapter(abc.ABC):
    """Interface for polling a work queue and claiming tasks."""

    @abc.abstractmethod
    async def poll(self) -> Optional[Task]:
        """Return the next available task, or None if the queue is empty."""

    @abc.abstractmethod
    async def claim(self, task: Task, worker_id: str) -> bool:
        """Attempt to claim *task* for *worker_id*.  Return True on success."""

    @abc.abstractmethod
    async def report(self, result: TaskResult) -> bool:
        """Submit *result* back to the queue.  Return True on success."""


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
