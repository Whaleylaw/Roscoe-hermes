"""Per-turn context overrides shared across the gateway and agent tools.

Exposes a ``turn_cwd_var`` ContextVar that lets the gateway pin a working
directory for a single agent turn without racing the process-wide
``TERMINAL_CWD`` env var across concurrent sessions.

Used by Slack's ``channel_cwds`` feature so a message in a case-specific
channel scopes terminal/file tools and AGENTS.md auto-loading to that
case's folder — without spawning a separate gateway per case.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

turn_cwd_var: ContextVar[Optional[str]] = ContextVar("turn_cwd", default=None)


def get_turn_cwd() -> Optional[str]:
    """Return the per-turn cwd override, or None when not set."""
    return turn_cwd_var.get()
