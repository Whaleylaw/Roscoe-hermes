"""Tests for daemon.poller — orchestration/delegation logic."""

import pytest

from daemon.adapters.base import (
    ApprovalRouter,
    Task,
    TaskResult,
    TaskSource,
    TaskStatus,
)
from daemon.poller import collect_and_route_results, poll_for_tasks


# ── Fakes ────────────────────────────────────────────────────────────

class FakeTaskSource(TaskSource):
    """In-memory task source for testing."""

    def __init__(self, tasks=None):
        self._tasks = list(tasks or [])

    async def poll_tasks(self):
        return self._tasks

    async def update_task_status(self, task_id, status):
        return True


class FailingTaskSource(TaskSource):
    """Always raises on poll."""

    async def poll_tasks(self):
        raise ConnectionError("service down")

    async def update_task_status(self, task_id, status):
        return False


class FakeApprovalRouter(ApprovalRouter):
    """Captures submissions for assertions."""

    def __init__(self, ok=True):
        self._ok = ok
        self.submitted: list[TaskResult] = []

    async def submit_for_review(self, result):
        self.submitted.append(result)
        return self._ok


# ── Fake OpenClaw for collect_and_route_results ──────────────────────

class FakeOpenClaw:
    """Minimal fake that returns canned results."""

    def __init__(self, results=None):
        self._results = list(results or [])
        self.acknowledged: list[str] = []

    async def collect_results(self):
        return self._results

    async def acknowledge_result(self, task_id):
        self.acknowledged.append(task_id)
        return True


# ── Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPollForTasks:

    async def test_returns_empty_when_no_sources(self):
        result = await poll_for_tasks([])
        assert result == []

    async def test_returns_empty_when_all_empty(self):
        result = await poll_for_tasks([FakeTaskSource(), FakeTaskSource()])
        assert result == []

    async def test_collects_tasks_from_sources(self):
        t1 = Task(id="t1", type="review")
        t2 = Task(id="t2", type="draft")
        result = await poll_for_tasks([FakeTaskSource([t1]), FakeTaskSource([t2])])
        assert len(result) == 2
        assert {t.id for t in result} == {"t1", "t2"}

    async def test_skips_failing_source(self):
        t1 = Task(id="t1", type="review")
        result = await poll_for_tasks([FailingTaskSource(), FakeTaskSource([t1])])
        assert len(result) == 1
        assert result[0].id == "t1"


@pytest.mark.asyncio
class TestCollectAndRouteResults:

    async def test_no_results_returns_zero(self):
        oc = FakeOpenClaw(results=[])
        count = await collect_and_route_results(oc, None, "hermes-1")
        assert count == 0

    async def test_routes_results_to_approval(self):
        result = TaskResult(task_id="t1", agent_id="claw-1", output="done")
        oc = FakeOpenClaw(results=[result])
        router = FakeApprovalRouter()
        count = await collect_and_route_results(
            oc, router, "hermes-1", approval_only=True,
        )
        assert count == 1
        assert len(router.submitted) == 1
        assert router.submitted[0].status == TaskStatus.PENDING_REVIEW
        assert router.submitted[0].orchestrator_id == "hermes-1"

    async def test_acknowledges_collected_results(self):
        result = TaskResult(task_id="t1", agent_id="claw-1")
        oc = FakeOpenClaw(results=[result])
        router = FakeApprovalRouter()
        await collect_and_route_results(oc, router, "hermes-1")
        assert "t1" in oc.acknowledged

    async def test_approval_only_forces_pending_review(self):
        result = TaskResult(
            task_id="t1", agent_id="claw-1",
            status=TaskStatus.APPROVED,  # Agent says approved
        )
        oc = FakeOpenClaw(results=[result])
        router = FakeApprovalRouter()
        await collect_and_route_results(
            oc, router, "hermes-1", approval_only=True,
        )
        # Approval-only overrides to pending_review.
        assert result.status == TaskStatus.PENDING_REVIEW

    async def test_no_router_still_processes(self):
        result = TaskResult(task_id="t1", agent_id="claw-1")
        oc = FakeOpenClaw(results=[result])
        count = await collect_and_route_results(oc, None, "hermes-1")
        assert count == 1
        assert "t1" in oc.acknowledged
