"""Supervisor — the Hermes orchestrator daemon loop.

Hermes is the orchestrator; OpenClaw agents are the workers.  On each
heartbeat tick this supervisor:

  1. Health-checks upstream services (OpenClaw gateway, Mission Control, FirmVault).
  2. Polls Mission Control for tasks that need orchestrating.
  3. Delegates tasks to available OpenClaw agents via the gateway.
  4. Collects completed results from OpenClaw agents.
  5. Routes results to approval/review (never auto-accepts during testing).

Runs in a daemon thread alongside the Hermes gateway.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from daemon.adapters.base import ApprovalRouter, HealthCheckable, TaskSource
from daemon.adapters.firmvault_pipeline import FirmVaultAdapter
from daemon.adapters.gsd import GSDAdapter
from daemon.adapters.mission_control import MissionControlAdapter
from daemon.adapters.openclaw import OpenClawAdapter
from daemon.approval import LocalApprovalRouter
from daemon.config import DaemonConfig
from daemon.health import check_all, log_health
from daemon.poller import collect_and_route_results, delegate_task, poll_for_tasks

logger = logging.getLogger("daemon.supervisor")

# Module-level lock to prevent duplicate concurrent loops within the same
# process.  A second call to start() while the first is still running will
# be rejected immediately.
_instance_lock = threading.Lock()
_running_instance: Optional["Supervisor"] = None


class Supervisor:
    """Hermes orchestrator daemon — runs in a background thread."""

    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self._stop_event = threading.Event()
        self._tick_count = 0

        # ── Build adapters ────────────────────────────────────────────
        self._openclaw = OpenClawAdapter(
            config.openclaw_gateway_url,
            timeout=config.health_check_timeout_seconds,
        )
        self._mission_control = MissionControlAdapter(
            config.mission_control_url,
            timeout=config.health_check_timeout_seconds,
        )
        # Lane 1: FirmVault case pipeline (engine → MC → OpenClaw → vault)
        self._firmvault = FirmVaultAdapter()

        # GSD adapter — drives plan lifecycle from project workspaces.
        self._gsd = GSDAdapter()

        # Services to health-check (skip unconfigured ones to avoid noise).
        self._health_targets: list[HealthCheckable] = [self._openclaw]
        if self._mission_control.configured:
            self._health_targets.append(self._mission_control)
        if self._firmvault.configured:
            self._health_targets.append(self._firmvault)
        if self._gsd.configured:
            self._health_targets.append(self._gsd)

        # Task sources to poll for orchestration work.
        self._task_sources: list[TaskSource] = []
        if self._mission_control.configured:
            self._task_sources.append(self._mission_control)
        if self._gsd.configured:
            self._task_sources.append(self._gsd)

        # Approval router: prefer Mission Control if configured, otherwise
        # fall back to local logging-based router.
        self._approval_router: ApprovalRouter
        if self._mission_control.configured:
            self._approval_router = self._mission_control
        else:
            self._approval_router = LocalApprovalRouter()

    # ── Lifecycle ─────────────────────────────────────────────────────

    def request_stop(self) -> None:
        """Signal the supervisor loop to stop at the next opportunity."""
        self._stop_event.set()

    @property
    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    # ── Main loop (runs in a daemon thread) ───────────────────────────

    def run(self) -> None:
        """Blocking entry point.  Call from a daemon thread."""
        logger.info(
            "orchestrator started — worker_id=%s heartbeat=%ds approval_only=%s",
            self.config.worker_id,
            self.config.heartbeat_seconds,
            self.config.approval_only,
        )
        logger.info("orchestrator config: %s", self.config.summary())

        # Initial delay to let the gateway finish booting.
        if self.config.initial_delay_seconds > 0:
            logger.info(
                "orchestrator: initial delay %ds before first tick",
                self.config.initial_delay_seconds,
            )
            if self._stop_event.wait(timeout=self.config.initial_delay_seconds):
                logger.info("orchestrator: stop requested during initial delay")
                return

        # Create a dedicated event loop for this thread (the gateway owns
        # the main loop; we must not share it).
        loop = asyncio.new_event_loop()
        try:
            while not self._stop_event.is_set():
                self._tick_count += 1
                t0 = time.monotonic()
                try:
                    loop.run_until_complete(self._tick())
                except Exception as exc:
                    logger.error(
                        "orchestrator: unhandled error in tick %d — %s",
                        self._tick_count, exc,
                        exc_info=True,
                    )
                elapsed = time.monotonic() - t0
                logger.debug(
                    "orchestrator: tick %d completed in %.1fs",
                    self._tick_count, elapsed,
                )

                # Sleep until the next heartbeat, but wake early on stop.
                remaining = max(0, self.config.heartbeat_seconds - elapsed)
                if remaining > 0:
                    self._stop_event.wait(timeout=remaining)
        finally:
            loop.close()
            logger.info(
                "orchestrator stopped after %d ticks — worker_id=%s",
                self._tick_count, self.config.worker_id,
            )

    # ── Single tick ───────────────────────────────────────────────────

    async def _tick(self) -> None:
        """One heartbeat cycle.

        Two lanes run in parallel:
          Lane 1: FirmVault case pipeline (engine → MC → OpenClaw → vault)
          Lane 2: GSD ad-hoc projects (poll → dispatch → collect)
        """
        logger.info(
            "heartbeat tick=%d orchestrator=%s",
            self._tick_count, self.config.worker_id,
        )

        # ── Lane 1: FirmVault case pipeline ──────────────────────────
        # Runs the deterministic engine + MC bridge. Self-contained loop.
        if self._firmvault.configured:
            try:
                await self._firmvault.tick()
            except Exception as exc:
                logger.error("lane1: FirmVault tick error — %s", exc, exc_info=True)

        # ── MC heartbeat ──────────────────────────────────────────────
        if self._mission_control.configured:
            try:
                await self._mission_control.send_heartbeat()
            except Exception as exc:
                logger.debug("mc heartbeat error: %s", exc)

        # ── Lane 2: GSD + OpenClaw orchestration ────────────────────
        # 1. Health check upstream services.
        statuses = await check_all(self._health_targets)
        all_healthy = log_health(statuses)

        openclaw_healthy = any(
            s.healthy for s in statuses if s.service_name == "openclaw"
        )
        if not openclaw_healthy:
            logger.warning("heartbeat: OpenClaw unhealthy — skipping orchestration")
            return

        # 2. Poll task sources (Mission Control, GSD) for work to orchestrate.
        tasks = await poll_for_tasks(self._task_sources)

        # 3. Route tasks — GSD tasks dispatch through GSD, others through OpenClaw.
        gsd_tasks = [t for t in tasks if t.metadata.get("source") == "gsd"]
        openclaw_tasks = [t for t in tasks if t.metadata.get("source") != "gsd"]

        # 3a. GSD tasks: dispatch via GSD dispatcher (which routes to
        #     OpenClaw relay or Hermes directly).
        if gsd_tasks:
            await self._dispatch_gsd_tasks(gsd_tasks)

        # 3b. Non-GSD tasks: delegate to OpenClaw agents directly.
        for task in openclaw_tasks:
            await delegate_task(task, self._openclaw, self.config.worker_id)

        # 4. Collect completed results from OpenClaw agents.
        processed = await collect_and_route_results(
            self._openclaw,
            self._approval_router,
            self.config.worker_id,
            approval_only=self.config.approval_only,
        )
        if processed > 0:
            logger.info("heartbeat: processed %d result(s) from OpenClaw agents", processed)


    # ── GSD dispatch ────────────────────────────────────────────────────

    async def _dispatch_gsd_tasks(self, tasks: list) -> None:
        """Dispatch GSD-sourced tasks via the GSD bridge.

        GSD tasks carry their full task definition in metadata['gsd_task'].
        We group by project and dispatch via the bridge, which routes each
        task to the correct platform (OpenClaw relay or Hermes).
        """
        # Group by project
        by_project: dict[str, list] = {}
        for task in tasks:
            project = task.metadata.get("project", "unknown")
            by_project.setdefault(project, []).append(task)

        for project, project_tasks in by_project.items():
            # Separate approval tasks from dispatch tasks
            approval_tasks = [t for t in project_tasks if t.status == TaskStatus.PENDING_REVIEW]
            dispatch_tasks = [t for t in project_tasks if t.status != TaskStatus.PENDING_REVIEW]

            # Handle approval notifications
            for task in approval_tasks:
                gsd_task = task.metadata.get("gsd_task", {})
                logger.warning(
                    "GSD APPROVAL NEEDED: project=%s task=%s title='%s' — "
                    "awaiting Aaron's approval",
                    project, gsd_task.get("id"), gsd_task.get("title"),
                )
                # TODO: Send Telegram notification to Aaron
                # This will be wired once we have the gateway's send_message hook

            # Dispatch ready tasks via GSD bridge
            if dispatch_tasks:
                wave = dispatch_tasks[0].metadata.get("wave", 1)
                gsd_payloads = [t.metadata.get("gsd_task", {}) for t in dispatch_tasks]

                try:
                    result = self._gsd._run_gsd_script("dispatch_wave", {
                        "project": project,
                        "wave": wave,
                        "tasks": gsd_payloads,
                        "dryRun": False,
                    })

                    if result.get("ok"):
                        logger.info(
                            "gsd: dispatched wave %d for project %s — %d tasks",
                            wave, project, len(dispatch_tasks),
                        )
                        # Update statuses
                        for task in dispatch_tasks:
                            gsd_task_id = task.metadata.get("gsd_task", {}).get("id")
                            if gsd_task_id:
                                await self._gsd.update_task_status(
                                    f"{project}:{gsd_task_id}",
                                    TaskStatus.ASSIGNED,
                                )
                    else:
                        logger.error(
                            "gsd: dispatch failed for project %s wave %d — %s",
                            project, wave, result.get("error"),
                        )
                except Exception as exc:
                    logger.error(
                        "gsd: error dispatching wave %d for project %s — %s",
                        wave, project, exc,
                    )


# ── Module-level start/stop helpers ──────────────────────────────────

def start(config: Optional[DaemonConfig] = None) -> Optional[threading.Thread]:
    """Start the orchestrator in a daemon thread.

    Returns the thread, or None if the daemon is disabled or already running.
    Prevents duplicate concurrent loops via a module-level lock.
    """
    global _running_instance

    if config is None:
        config = DaemonConfig()

    if not config.enabled:
        logger.info("daemon disabled (DAEMON_ENABLED != true) — not starting")
        return None

    config.configure_logging()

    if not _instance_lock.acquire(blocking=False):
        logger.warning("daemon already running — refusing duplicate start")
        return None

    try:
        if _running_instance is not None:
            logger.warning("daemon already running — refusing duplicate start")
            _instance_lock.release()
            return None

        supervisor = Supervisor(config)
        _running_instance = supervisor

        thread = threading.Thread(
            target=_run_and_cleanup,
            args=(supervisor,),
            name="hermes-orchestrator",
            daemon=True,
        )
        thread.start()
        return thread
    except Exception:
        _running_instance = None
        _instance_lock.release()
        raise


def stop(timeout: float = 5.0) -> None:
    """Signal the running supervisor to stop and wait up to *timeout* seconds."""
    global _running_instance
    if _running_instance is not None:
        _running_instance.request_stop()
        _running_instance = None


def _run_and_cleanup(supervisor: Supervisor) -> None:
    """Thread target — runs the supervisor and releases the lock on exit."""
    global _running_instance
    try:
        supervisor.run()
    except Exception:
        logger.exception("orchestrator: fatal error in daemon thread")
    finally:
        _running_instance = None
        try:
            _instance_lock.release()
        except RuntimeError:
            pass
