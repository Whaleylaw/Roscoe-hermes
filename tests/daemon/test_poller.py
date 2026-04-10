"""Tests for daemon.poller."""

import pytest

from daemon.adapters.base import (
    ApprovalRouter,
    QueueAdapter,
    Task,
    TaskResult,
    TaskStatus,
)
from daemon.poller import claim_task, execute_task, poll_for_work, route_result


# ── Fakes ────────────────────────────────────────────────────────────

class FakeQueue(QueueAdapter):
    """In-memory queue for testing."""

    def __init__(self, tasks=None, claim_ok=True, report_ok=True):
        self._tasks = list(tasks or [])
        self._claim_ok = claim_ok
        self._report_ok = report_ok
        self.reported: list[TaskResult] = []

    async def poll(self):
        return self._tasks.pop(0) if self._tasks else None

    async def claim(self, task, worker_id):
        return self._claim_ok

    async def report(self, result):
        self.reported.append(result)
        return self._report_ok


class FakeApprovalRouter(ApprovalRouter):
    """Captures submissions for assertions."""

    def __init__(self, ok=True):
        self._ok = ok
        self.submitted: list[TaskResult] = []

    async def submit_for_review(self, result):
        self.submitted.append(result)
        return self._ok


class FailingQueue(QueueAdapter):
    """Always raises on poll."""

    async def poll(self):
        raise ConnectionError("service down")

    async def claim(self, task, worker_id):
        return False

    async def report(self, result):
        return False


# ── Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPollForWork:

    async def test_returns_none_when_all_empty(self):
        result = await poll_for_work([FakeQueue(), FakeQueue()])
        assert result is None

    async def test_returns_first_available_task(self):
        task = Task(id="t1", type="review")
        result = await poll_for_work([FakeQueue(), FakeQueue([task])])
        assert result is not None
        _, found = result
        assert found.id == "t1"

    async def test_skips_failing_queue(self):
        task = Task(id="t2", type="draft")
        result = await poll_for_work([FailingQueue(), FakeQueue([task])])
        assert result is not None
        _, found = result
        assert found.id == "t2"


@pytest.mark.asyncio
class TestClaimTask:

    async def test_claim_success(self):
        q = FakeQueue(claim_ok=True)
        task = Task(id="t1", type="review")
        assert await claim_task(q, task, "w1") is True

    async def test_claim_failure(self):
        q = FakeQueue(claim_ok=False)
        task = Task(id="t1", type="review")
        assert await claim_task(q, task, "w1") is False


@pytest.mark.asyncio
class TestExecuteTask:

    async def test_returns_pending_review(self):
        task = Task(id="t1", type="review")
        result = await execute_task(task, "w1")
        assert result.task_id == "t1"
        assert result.worker_id == "w1"
        assert result.status == TaskStatus.PENDING_REVIEW


@pytest.mark.asyncio
class TestRouteResult:

    async def test_approval_only_forces_pending_review(self):
        q = FakeQueue()
        router = FakeApprovalRouter()
        result = TaskResult(
            task_id="t1", worker_id="w1",
            output="done", status=TaskStatus.APPROVED,
        )
        await route_result(result, q, router, approval_only=True)
        assert result.status == TaskStatus.PENDING_REVIEW
        assert len(router.submitted) == 1

    async def test_no_router_still_reports_to_queue(self):
        q = FakeQueue()
        result = TaskResult(task_id="t1", worker_id="w1")
        await route_result(result, q, None, approval_only=True)
        assert len(q.reported) == 1

    async def test_router_failure_does_not_crash(self):
        q = FakeQueue()
        router = FakeApprovalRouter(ok=False)
        result = TaskResult(task_id="t1", worker_id="w1")
        ok = await route_result(result, q, router, approval_only=True)
        assert ok is False  # Failure is propagated as return value, not exception
