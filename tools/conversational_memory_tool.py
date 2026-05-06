"""Tools for interacting with the standalone conversational memory system."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from typing import Any, Dict, Optional

from tools.registry import registry, tool_error


logger = logging.getLogger(__name__)


CONVERSATIONAL_MEMORY_RESUME_SCHEMA = {
    "name": "conversational_memory_resume",
    "description": (
        "Expand a compacted conversational memory summary or injection packet into "
        "verbatim source turns. Use when the user asks to resume, pick up where "
        "we left off, show the original conversation, or dig into a recalled memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary_id": {
                "type": "string",
                "description": "Summary id to expand into verbatim source turns.",
            },
            "injection_packet": {
                "type": "object",
                "description": "Full InjectionPacket object returned by conversational memory injection/search.",
            },
        },
        "required": [],
    },
}


def check_conversational_memory_resume_requirements() -> bool:
    return bool(os.environ.get("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "").strip())


def conversational_memory_resume(
    summary_id: Optional[str] = None,
    injection_packet: Optional[Dict[str, Any]] = None,
) -> str:
    if bool(summary_id) == bool(injection_packet):
        return tool_error(
            "Provide exactly one of summary_id or injection_packet, not both.",
            success=False,
        )

    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "").strip()
    if not command:
        return tool_error(
            "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND is not configured.",
            success=False,
        )

    request: Dict[str, Any]
    if summary_id:
        request = {"summary_id": summary_id}
    else:
        request = {"injection_packet": injection_packet}

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
        logger.warning("Conversational memory resume failed: %s", exc)
        return tool_error(f"Conversational memory resume failed: {exc}", success=False)

    return json.dumps({
        "success": True,
        "turn_count": payload.get("turnCount"),
        "source_summary_ids": payload.get("sourceSummaryIds", []),
        "source_turn_ranges": payload.get("sourceTurnRanges", []),
        "disclosure_text": payload.get("disclosureText"),
        "context_block": payload.get("contextBlock"),
        "turns": [
            _compact_turn(turn)
            for turn in payload.get("turns", [])
            if isinstance(turn, dict)
        ],
    })


def _compact_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "role": turn.get("role"),
        "content": turn.get("content"),
        "created_at": turn.get("createdAt"),
        "sequence": turn.get("sequence"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _timeout_seconds() -> float:
    raw = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_RESUME_TIMEOUT", "10")
    try:
        return max(0.1, min(float(raw), 60.0))
    except (TypeError, ValueError):
        return 10.0


registry.register(
    name="conversational_memory_resume",
    toolset="memory",
    schema=CONVERSATIONAL_MEMORY_RESUME_SCHEMA,
    handler=lambda args, **_kw: conversational_memory_resume(
        summary_id=args.get("summary_id"),
        injection_packet=args.get("injection_packet"),
    ),
    check_fn=check_conversational_memory_resume_requirements,
    emoji="🧠",
)
