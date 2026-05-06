"""Optional context injection from the standalone conversational memory system."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def maybe_prepend_conversational_memory_context(
    *,
    messages: List[Dict[str, Any]],
    profile_id: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    if not _inject_enabled() or not messages:
        return messages

    query = _latest_user_query(messages)
    if not query:
        return messages

    context_block = _load_context_block(
        profile_id=profile_id,
        session_id=session_id,
        query=query,
    )
    if not context_block:
        return messages

    return [{"role": "system", "content": context_block}, *messages]


def _inject_enabled() -> bool:
    value = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _latest_user_query(messages: List[Dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _load_context_block(*, profile_id: str, session_id: str, query: str) -> Optional[str]:
    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND", "").strip()
    if not command:
        logger.debug("Conversational memory injection enabled without a command")
        return None

    request = {
        "profile_id": profile_id,
        "session_id": session_id,
        "query": query,
    }
    max_tokens = _max_memory_tokens()
    if max_tokens is not None:
        request["max_memory_tokens"] = max_tokens

    try:
        completed = subprocess.run(
            shlex.split(command),
            input=json.dumps(request, sort_keys=True),
            text=True,
            capture_output=True,
            timeout=_timeout_seconds(),
            check=True,
        )
        payload = json.loads(completed.stdout)
    except Exception as exc:
        logger.warning("Conversational memory injection failed: %s", exc)
        return None

    context_block = payload.get("contextBlock") if isinstance(payload, dict) else None
    if isinstance(context_block, str) and context_block.strip():
        return context_block
    return None


def _timeout_seconds() -> float:
    raw = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_INJECT_TIMEOUT", "2")
    try:
        return max(0.1, min(float(raw), 30.0))
    except (TypeError, ValueError):
        return 2.0


def _max_memory_tokens() -> Optional[int]:
    raw = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_MAX_TOKENS")
    if raw is None or not raw.strip():
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None
