"""Daemon configuration — parsed exclusively from environment variables."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("daemon.config")


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("true", "1", "yes")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r, using default %d", name, raw, default)
        return default


@dataclass(frozen=True)
class DaemonConfig:
    """Immutable snapshot of daemon configuration at startup."""

    # ── Master toggle ────────────────────────────────────────────────
    enabled: bool = field(default_factory=lambda: _bool_env("DAEMON_ENABLED", False))

    # ── Timing ───────────────────────────────────────────────────────
    heartbeat_seconds: int = field(
        default_factory=lambda: _int_env("DAEMON_HEARTBEAT_SECONDS", 60)
    )
    initial_delay_seconds: int = field(
        default_factory=lambda: _int_env("DAEMON_INITIAL_DELAY_SECONDS", 10)
    )

    # ── Safety ───────────────────────────────────────────────────────
    # When True (the default), all worker outputs are routed to
    # approval/review and NEVER auto-accepted.  This is the safe
    # mode for testing.
    approval_only: bool = field(
        default_factory=lambda: _bool_env("DAEMON_APPROVAL_ONLY", True)
    )

    # ── Upstream service URLs ────────────────────────────────────────
    openclaw_gateway_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENCLAW_GATEWAY_URL",
            "https://openclaw-gateway-dfdi.onrender.com",
        )
    )
    mission_control_url: str = field(
        default_factory=lambda: os.getenv(
            "MISSION_CONTROL_URL",
            os.getenv("MC_URL", ""),
        )
    )
    firmvault_url: str = field(
        default_factory=lambda: os.getenv("FIRMVAULT_URL", "")
    )

    # ── Worker identity ──────────────────────────────────────────────
    # Used to prevent duplicate claiming and to tag results.
    # Defaults to a random UUID per process so each Railway container
    # gets a unique id automatically.
    worker_id: str = field(
        default_factory=lambda: os.getenv("DAEMON_WORKER_ID", str(uuid.uuid4())[:12])
    )

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = field(
        default_factory=lambda: os.getenv("DAEMON_LOG_LEVEL", "INFO").upper()
    )

    # ── Health check ─────────────────────────────────────────────────
    health_check_timeout_seconds: int = field(
        default_factory=lambda: _int_env("DAEMON_HEALTH_TIMEOUT_SECONDS", 10)
    )

    def configure_logging(self) -> None:
        """Apply log_level to the daemon logger hierarchy."""
        level = getattr(logging, self.log_level, logging.INFO)
        logging.getLogger("daemon").setLevel(level)

    def summary(self) -> dict:
        """Return a safe-to-log dict (no secrets)."""
        return {
            "enabled": self.enabled,
            "heartbeat_seconds": self.heartbeat_seconds,
            "initial_delay_seconds": self.initial_delay_seconds,
            "approval_only": self.approval_only,
            "openclaw_gateway_url": self.openclaw_gateway_url,
            "mission_control_url": self.mission_control_url or "(not configured)",
            "firmvault_url": self.firmvault_url or "(not configured)",
            "worker_id": self.worker_id,
            "log_level": self.log_level,
        }
