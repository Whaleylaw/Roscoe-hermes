"""
Unified Timeline service.

Single source of truth for the agent's cross-channel conversation history
within one profile. Platform adapters call ``record_inbound`` and
``record_outbound`` instead of writing transcripts into per-channel
sessions; context assembly reads from the same table to produce one
continuous agent experience across Telegram, Open WebUI, Discord, etc.

See ``docs/superpowers/specs/2026-04-21-unified-timeline-design.md``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from hermes_state import SessionDB
from hermes_cli.profiles import get_active_profile_name

from gateway.session import SessionSource


@dataclass
class TurnHandle:
    """Opaque handle tying an outbound response to its inbound turn."""
    profile_id: str
    platform: str
    source_chat_id: Optional[str]
    source_thread_id: Optional[str]
    seq: int


# Per-profile locks serialize writes within one process.  Keyed by
# profile_id, not session_key — simultaneous inbound messages from
# multiple channels must converge in order.
_profile_locks: Dict[str, threading.Lock] = {}
_profile_locks_guard = threading.Lock()


def _get_profile_lock(profile_id: str) -> threading.Lock:
    with _profile_locks_guard:
        lock = _profile_locks.get(profile_id)
        if lock is None:
            lock = threading.Lock()
            _profile_locks[profile_id] = lock
        return lock


class UnifiedTimeline:
    """Thin wrapper around SessionDB's timeline methods, plus profile scoping."""

    def __init__(self, db: SessionDB, profile_id: str):
        self.db = db
        self.profile_id = profile_id
        self._lock = _get_profile_lock(profile_id)

    @classmethod
    def for_active_profile(cls, db: SessionDB) -> "UnifiedTimeline":
        """Resolve the current profile from HERMES_HOME and build a service."""
        return cls(db=db, profile_id=get_active_profile_name())

    def record_inbound(
        self,
        source: SessionSource,
        content: str,
        message_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> TurnHandle:
        """Append an inbound message and return a handle for the reply."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            seq = self.db.append_timeline_message(
                profile_id=self.profile_id,
                direction="inbound",
                platform=source.platform.value,
                source_chat_id=source.chat_id,
                source_thread_id=source.thread_id,
                author=source.user_name or source.user_id,
                content=content,
                message_id=message_id,
                ts=ts,
            )
        return TurnHandle(
            profile_id=self.profile_id,
            platform=source.platform.value,
            source_chat_id=source.chat_id,
            source_thread_id=source.thread_id,
            seq=seq,
        )

    def record_outbound(
        self,
        turn: TurnHandle,
        content: str,
        message_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> int:
        """Append an outbound message tied to an inbound turn handle."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            return self.db.append_timeline_message(
                profile_id=turn.profile_id,
                direction="outbound",
                platform=turn.platform,
                source_chat_id=turn.source_chat_id,
                source_thread_id=turn.source_thread_id,
                author="agent",
                content=content,
                message_id=message_id,
                ts=ts,
            )
