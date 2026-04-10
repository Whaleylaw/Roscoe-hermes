"""Worker daemon for the Lawyer Incorporated / AI paralegal stack.

This package implements a pull-model background supervisor that runs alongside
the Hermes gateway.  On each heartbeat tick it:

  1. Checks upstream service health (OpenClaw gateway, Mission Control, FirmVault).
  2. Polls for available work items.
  3. Claims a single task (or no-ops).
  4. Executes the task via Hermes agent capabilities.
  5. Routes the result to approval/review — NEVER auto-accepts during testing.

The daemon is started automatically by a ``gateway:startup`` hook when
``DAEMON_ENABLED=true`` is set in the environment.  See ``config.py`` for the
full list of environment variables.
"""

from daemon.config import DaemonConfig

__all__ = ["DaemonConfig"]
