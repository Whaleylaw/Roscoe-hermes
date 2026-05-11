"""Optional bridge from Hermes unified timeline rows to external memory systems."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def conversational_memory_enabled() -> bool:
    value = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_ENABLED", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def emit_unified_timeline_row(
    *,
    profile_id: str,
    seq: int,
    ts: float,
    direction: str,
    platform: str,
    source_chat_id: Optional[str],
    source_thread_id: Optional[str],
    author: Optional[str],
    content: Optional[str],
    message_id: Optional[str],
) -> None:
    """Best-effort handoff of a timeline row to a configured memory bridge.

    The payload matches the standalone conversational-memory-system
    ``HermesTimelineRow`` contract. The bridge is off by default and failures
    are logged rather than allowed to interrupt chat delivery.
    """
    if not conversational_memory_enabled():
        return

    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_COMMAND", "").strip()
    if not command:
        logger.debug("Conversational memory bridge enabled without a command")
        return

    row = build_hermes_timeline_row(
        profile_id=profile_id,
        seq=seq,
        ts=ts,
        direction=direction,
        platform=platform,
        source_chat_id=source_chat_id,
        source_thread_id=source_thread_id,
        author=author,
        content=content,
        message_id=message_id,
    )
    timeout = _bridge_timeout_seconds()

    try:
        subprocess.run(
            shlex.split(command),
            input=json.dumps(row, sort_keys=True),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except Exception as exc:
        logger.warning("Conversational memory bridge emit failed: %s", exc)


def emit_conversational_memory_compression_boundary(
    *,
    profile_id: str,
    seq: Optional[int] = None,
    ts: Optional[float] = None,
    reason: str = "native_compression",
) -> bool:
    """Emit a synthetic /compress control row so CMS compacts before native shrink.

    This does not write to Roscoe's unified timeline. It only hands a control
    signal to the external memory bridge using a sequence greater than the
    already-ingested rows, allowing CMS to summarize the uncompacted tail while
    Roscoe's native compressor remains a prompt-size safety fallback.
    """
    if not conversational_memory_enabled():
        return False

    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_COMMAND", "").strip()
    if not command:
        logger.debug("Conversational memory boundary requested without a command")
        return False

    boundary_seq = seq if seq is not None else int(time.time() * 1000)
    boundary_ts = ts if ts is not None else time.time()
    message_id = f"memory-boundary:{reason}:{boundary_seq}"
    emit_unified_timeline_row(
        profile_id=profile_id,
        seq=boundary_seq,
        ts=boundary_ts,
        direction="system",
        platform="gateway",
        source_chat_id=None,
        source_thread_id=None,
        author="native-compression",
        content="/compress",
        message_id=message_id,
    )
    return True


def build_hermes_timeline_row(
    *,
    profile_id: str,
    seq: int,
    ts: float,
    direction: str,
    platform: str,
    source_chat_id: Optional[str],
    source_thread_id: Optional[str],
    author: Optional[str],
    content: Optional[str],
    message_id: Optional[str],
) -> Dict[str, Any]:
    metadata = {
        "direction": direction,
        "platform": platform,
        "source_chat_id": source_chat_id,
        "source_thread_id": source_thread_id,
        "author": author,
        "message_id": message_id,
    }

    return {
        "id": f"{profile_id}:{seq}",
        "profile_id": profile_id,
        "session_id": f"profile:{profile_id}",
        "sequence": seq,
        "role": _role_for_direction(direction),
        "content": content or "",
        "created_at": _format_created_at(ts),
        "channel": platform,
        "metadata_json": json.dumps(metadata, sort_keys=True),
    }


def _role_for_direction(direction: str) -> str:
    if direction == "inbound":
        return "user"
    if direction == "outbound":
        return "assistant"
    return "system"


def _format_created_at(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _bridge_timeout_seconds() -> float:
    raw = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_TIMEOUT", "2")
    try:
        return max(0.1, min(float(raw), 30.0))
    except (TypeError, ValueError):
        return 2.0
