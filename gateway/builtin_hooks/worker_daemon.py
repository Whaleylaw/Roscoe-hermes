"""Built-in hook — start the worker daemon on gateway startup.

Follows the same pattern as boot_md.py: spawns a daemon thread that runs
alongside the gateway without blocking startup.  The daemon is only started
when DAEMON_ENABLED=true is set in the environment.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("daemon.hook")


async def handle(event_type: str, context: dict) -> None:
    """``gateway:startup`` handler — conditionally starts the worker daemon."""
    # Late import so the daemon package is only loaded when the hook fires.
    from daemon.config import DaemonConfig
    from daemon.supervisor import start

    config = DaemonConfig()

    if not config.enabled:
        logger.debug("worker daemon hook: DAEMON_ENABLED is not true — skipping")
        return

    logger.info("worker daemon hook: starting supervisor (worker_id=%s)", config.worker_id)
    thread = start(config)
    if thread is None:
        logger.warning("worker daemon hook: supervisor did not start (already running or disabled)")
    else:
        logger.info("worker daemon hook: supervisor thread started — name=%s", thread.name)
