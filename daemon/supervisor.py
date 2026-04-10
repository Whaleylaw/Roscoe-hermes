"""Supervisor — the main daemon loop.

Manages the heartbeat-driven pull cycle: health check → poll → claim →
execute → route to approval.  Designed to run in a daemon thread alongside
the Hermes gateway.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from daemon.adapters.base import ApprovalRouter, HealthCheckable, QueueAdapter
from daemon.adapters.firmvault import FirmVaultAdapter
from daemon.adapters.mission_control import MissionControlAdapter
from daemon.adapters.openclaw import OpenClawAdapter
from daemon.approval import LocalApprovalRouter
from daemon.config import DaemonConfig
from daemon.health import check_all, log_health
from daemon.poller import claim_task, execute_task, poll_for_work, route_result

logger = logging.getLogger("daemon.supervisor")

# Module-level lock to prevent duplicate concurrent loops within the same
# process.  A second call to start() while the first is still running will
# be rejected immediately.
_instance_lock = threading.Lock()
_running_instance: Optional[Supervisor] = None


class Supervisor:
    """Daemon supervisor that runs in a background thread."""

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

        # Services to health-check (skip unconfigured ones from the probe
        # to avoid noisy warnings every tick).
        self._health_targets: list[HealthCheckable] = [self._openclaw]
        if self._mission_control.configured:
            self._health_targets.append(self._mission_control)
        if self._firmvault.configured:
            self._health_targets.append(self._firmvault)

        # Queue adapters to poll, in priority order.
        self._queues: list[QueueAdapter] = [self._openclaw]
        if self._mission_control.configured:
            self._queues.append(self._mission_control)

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
            "supervisor started — worker_id=%s heartbeat=%ds approval_only=%s",
            self.config.worker_id,
            self.config.heartbeat_seconds,
            self.config.approval_only,
        )
        logger.info("supervisor config: %s", self.config.summary())

        # Initial delay to let the gateway finish booting.
        if self.config.initial_delay_seconds > 0:
            logger.info(
                "supervisor: initial delay %ds before first tick",
                self.config.initial_delay_seconds,
            )
            if self._stop_event.wait(timeout=self.config.initial_delay_seconds):
                logger.info("supervisor: stop requested during initial delay")
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
                        "supervisor: unhandled error in tick %d — %s",
                        self._tick_count, exc,
                        exc_info=True,
                    )
                elapsed = time.monotonic() - t0
                logger.debug(
                    "supervisor: tick %d completed in %.1fs",
                    self._tick_count, elapsed,
                )

                # Sleep until the next heartbeat, but wake early on stop.
                remaining = max(0, self.config.heartbeat_seconds - elapsed)
                if remaining > 0:
                    self._stop_event.wait(timeout=remaining)
        finally:
            loop.close()
            logger.info(
                "supervisor stopped after %d ticks — worker_id=%s",
                self._tick_count, self.config.worker_id,
            )

    # ── Single tick ───────────────────────────────────────────────────

    async def _tick(self) -> None:
        """One heartbeat cycle: health → poll → claim → execute → route."""
        logger.info(
            "heartbeat tick=%d worker=%s",
            self._tick_count, self.config.worker_id,
        )

        # 1. Health check upstream services.
        statuses = await check_all(self._health_targets)
        all_healthy = log_health(statuses)

        # Don't poll if the primary queue (OpenClaw) is unhealthy.
        openclaw_healthy = any(
            s.healthy for s in statuses if s.service_name == "openclaw"
        )
        if not openclaw_healthy:
            logger.warning("heartbeat: OpenClaw unhealthy — skipping poll")
            return

        # 2. Poll for available work.
        result = await poll_for_work(self._queues)
        if result is None:
            logger.info("heartbeat: no work available — sleeping")
            return

        source_queue, task = result

        # 3. Claim the task.
        claimed = await claim_task(source_queue, task, self.config.worker_id)
        if not claimed:
            logger.info("heartbeat: claim failed for task %s — skipping", task.id)
            return

        # 4. Execute.
        task_result = await execute_task(task, self.config.worker_id)

        # 5. Route to approval.
        await route_result(
            task_result,
            source_queue,
            self._approval_router,
            approval_only=self.config.approval_only,
        )


# ── Module-level start/stop helpers ──────────────────────────────────

def start(config: Optional[DaemonConfig] = None) -> Optional[threading.Thread]:
    """Start the supervisor in a daemon thread.

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
            name="worker-daemon",
            daemon=True,  # Won't block gateway exit
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
        logger.exception("supervisor: fatal error in daemon thread")
    finally:
        _running_instance = None
        try:
            _instance_lock.release()
        except RuntimeError:
            pass
