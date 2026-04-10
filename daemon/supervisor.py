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
from daemon.adapters.firmvault import FirmVaultAdapter
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
        self._firmvault = FirmVaultAdapter(
            config.firmvault_url,
            timeout=config.health_check_timeout_seconds,
        )

        # Services to health-check (skip unconfigured ones to avoid noise).
        self._health_targets: list[HealthCheckable] = [self._openclaw]
        if self._mission_control.configured:
            self._health_targets.append(self._mission_control)
        if self._firmvault.configured:
            self._health_targets.append(self._firmvault)

        # Task sources to poll for orchestration work.
        self._task_sources: list[TaskSource] = []
        if self._mission_control.configured:
            self._task_sources.append(self._mission_control)

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
        """One heartbeat cycle: health → poll → delegate → collect → route."""
        logger.info(
            "heartbeat tick=%d orchestrator=%s",
            self._tick_count, self.config.worker_id,
        )

        # 1. Health check upstream services.
        statuses = await check_all(self._health_targets)
        all_healthy = log_health(statuses)

        openclaw_healthy = any(
            s.healthy for s in statuses if s.service_name == "openclaw"
        )
        if not openclaw_healthy:
            logger.warning("heartbeat: OpenClaw unhealthy — skipping orchestration")
            return

        # 2. Poll task sources (Mission Control) for work to orchestrate.
        tasks = await poll_for_tasks(self._task_sources)

        # 3. Delegate tasks to available OpenClaw agents.
        for task in tasks:
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
