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
        "Expand a compacted conversational memory summary, trace, box, or injection "
        "packet into verbatim source turns. Use when the user asks to resume, pick "
        "up where we left off, show the original conversation, or dig into a "
        "recalled memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary_id": {
                "type": "string",
                "description": "Summary id to expand into verbatim source turns.",
            },
            "trace_id": {
                "type": "string",
                "description": "Trace id to expand into verbatim source turns.",
            },
            "box_id": {
                "type": "string",
                "description": "Box id to expand into verbatim source turns.",
            },
            "max_turn_ranges": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of turn ranges to include. Only valid with box_id.",
            },
            "include_child_boxes": {
                "type": "boolean",
                "description": "Whether to include child boxes when expanding a box_id.",
            },
            "injection_packet": {
                "type": "object",
                "description": "Full InjectionPacket object returned by conversational memory injection/search.",
            },
        },
        "required": [],
    },
}


CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA = {
    "name": "conversational_memory_sleep_review",
    "description": (
        "Run standalone conversational memory sleep review. Use when the user asks "
        "what memory organization changed, wants proposed boxes/traces reviewed, "
        "or asks to organize compacted conversation memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reviewed_at": {
                "type": "string",
                "description": "Optional ISO timestamp to use as the review time.",
            },
            "proposal_mode": {
                "type": "string",
                "enum": ["deterministic", "openrouter", "hybrid"],
                "description": "Proposal planner mode. Defaults to deterministic in the memory service.",
            },
            "include_proposals": {
                "type": "boolean",
                "description": "Whether sleep review should create proposal records.",
            },
            "minimum_summaries_per_box": {
                "type": "integer",
                "minimum": 1,
                "description": "Minimum summaries needed before proposing a box.",
            },
            "minimum_trace_summaries": {
                "type": "integer",
                "minimum": 1,
                "description": "Minimum summaries needed before proposing a trace.",
            },
            "minimum_box_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Minimum confidence for proposed boxes.",
            },
            "minimum_trace_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Minimum confidence for proposed traces.",
            },
            "stale_strength_threshold": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Summary strength threshold below which summaries can become stale.",
            },
        },
        "required": [],
    },
}


CONVERSATIONAL_MEMORY_PROPOSAL_REVIEW_SCHEMA = {
    "name": "conversational_memory_proposal_review",
    "description": (
        "List, approve, or reject standalone conversational memory sleep-review "
        "proposals. Use after sleep review finds proposed boxes, child boxes, or traces."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "approve", "reject"],
                "description": "Proposal review action to perform.",
            },
            "proposal_id": {
                "type": "string",
                "description": "Proposal id required for approve and reject actions.",
            },
            "state": {
                "type": "string",
                "enum": ["proposed", "approved", "rejected"],
                "description": "Proposal state filter for list.",
            },
            "proposal_type": {
                "type": "string",
                "enum": ["box", "box_parent_child", "trace"],
                "description": "Proposal type filter for list.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum proposals to return for list.",
            },
            "include_payload": {
                "type": "boolean",
                "description": "Whether list should include full proposal payloads.",
            },
            "decided_at": {
                "type": "string",
                "description": "Optional ISO timestamp for approve or reject decisions.",
            },
            "reviewer": {
                "type": "string",
                "description": "Optional reviewer label for approve or reject decisions.",
            },
            "note": {
                "type": "string",
                "description": "Optional decision note for approve or reject decisions.",
            },
        },
        "required": ["action"],
    },
}


def check_conversational_memory_resume_requirements() -> bool:
    return bool(os.environ.get("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "").strip())


def check_conversational_memory_sleep_review_requirements() -> bool:
    return bool(os.environ.get("HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND", "").strip())


def check_conversational_memory_proposal_review_requirements() -> bool:
    return all(
        os.environ.get(name, "").strip()
        for name in (
            "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
            "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND",
            "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND",
        )
    )


def conversational_memory_resume(
    summary_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    box_id: Optional[str] = None,
    injection_packet: Optional[Dict[str, Any]] = None,
    max_turn_ranges: Optional[int] = None,
    include_child_boxes: Optional[bool] = None,
) -> str:
    source_count = sum(bool(value) for value in (summary_id, trace_id, box_id, injection_packet))
    if source_count != 1:
        return tool_error(
            "Provide exactly one of summary_id, trace_id, box_id, or injection_packet.",
            success=False,
        )
    if not box_id and (max_turn_ranges is not None or include_child_boxes is not None):
        return tool_error("Box resume options require box_id.", success=False)

    request: Dict[str, Any]
    if summary_id:
        request = {"summary_id": summary_id}
    elif trace_id:
        request = {"trace_id": trace_id}
    elif box_id:
        request = {"box_id": box_id}
        if max_turn_ranges is not None:
            request["max_turn_ranges"] = max_turn_ranges
        if include_child_boxes is not None:
            request["include_child_boxes"] = include_child_boxes
    else:
        request = {"injection_packet": injection_packet}

    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "").strip()
    if not command:
        return tool_error(
            "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND is not configured.",
            success=False,
        )

    try:
        payload = _run_json_command(command, request)
    except Exception as exc:
        logger.warning("Conversational memory resume failed: %s", exc)
        return tool_error(f"Conversational memory resume failed: {exc}", success=False)

    return json.dumps({
        "success": True,
        "turn_count": payload.get("turnCount"),
        "source_summary_ids": payload.get("sourceSummaryIds", []),
        "source_trace_ids": payload.get("sourceTraceIds", []),
        "source_box_ids": payload.get("sourceBoxIds", []),
        "source_turn_ranges": payload.get("sourceTurnRanges", []),
        "disclosure_text": payload.get("disclosureText"),
        "context_block": payload.get("contextBlock"),
        "turns": [
            _compact_turn(turn)
            for turn in payload.get("turns", [])
            if isinstance(turn, dict)
        ],
    })


def conversational_memory_sleep_review(
    reviewed_at: Optional[str] = None,
    proposal_mode: Optional[str] = None,
    include_proposals: Optional[bool] = None,
    minimum_summaries_per_box: Optional[int] = None,
    minimum_trace_summaries: Optional[int] = None,
    minimum_box_confidence: Optional[float] = None,
    minimum_trace_confidence: Optional[float] = None,
    stale_strength_threshold: Optional[float] = None,
) -> str:
    command = os.environ.get("HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND", "").strip()
    if not command:
        return tool_error(
            "HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND is not configured.",
            success=False,
        )

    request = _drop_none({
        "reviewed_at": reviewed_at,
        "proposal_mode": proposal_mode,
        "include_proposals": include_proposals,
        "minimum_summaries_per_box": minimum_summaries_per_box,
        "minimum_trace_summaries": minimum_trace_summaries,
        "minimum_box_confidence": minimum_box_confidence,
        "minimum_trace_confidence": minimum_trace_confidence,
        "stale_strength_threshold": stale_strength_threshold,
    })

    try:
        payload = _run_json_command(command, request)
    except Exception as exc:
        logger.warning("Conversational memory sleep review failed: %s", exc)
        return tool_error(f"Conversational memory sleep review failed: {exc}", success=False)

    return json.dumps({
        "success": True,
        "reviewed_at": payload.get("reviewedAt"),
        "updated_summary_ids": payload.get("updatedSummaryIds", []),
        "updated_box_ids": payload.get("updatedBoxIds", []),
        "proposed_box_ids": payload.get("proposedBoxIds", []),
        "proposal_ids": payload.get("proposalIds", []),
        "proposed_trace_ids": payload.get("proposedTraceIds", []),
        "noop_reason": payload.get("noopReason"),
    })


def conversational_memory_proposal_review(
    action: str,
    proposal_id: Optional[str] = None,
    state: Optional[str] = None,
    proposal_type: Optional[str] = None,
    limit: Optional[int] = None,
    include_payload: Optional[bool] = None,
    decided_at: Optional[str] = None,
    reviewer: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    if action not in {"list", "approve", "reject"}:
        return tool_error(f"Unknown proposal review action: {action}", success=False)
    if action in {"approve", "reject"} and not proposal_id:
        return tool_error("proposal_id is required for approve and reject actions.", success=False)

    env_name = {
        "list": "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
        "approve": "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND",
        "reject": "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND",
    }[action]
    command = os.environ.get(env_name, "").strip()
    if not command:
        return tool_error(f"{env_name} is not configured.", success=False)

    if action == "list":
        request = _drop_none({
            "state": state,
            "proposal_type": proposal_type,
            "limit": limit,
            "include_payload": include_payload,
        })
    else:
        request = _drop_none({
            "proposal_id": proposal_id,
            "decided_at": decided_at,
            "reviewer": reviewer,
            "note": note,
        })

    try:
        payload = _run_json_command(command, request)
    except Exception as exc:
        logger.warning("Conversational memory proposal review failed: %s", exc)
        return tool_error(f"Conversational memory proposal review failed: {exc}", success=False)

    if action == "list":
        return json.dumps({
            "success": True,
            "count": payload.get("count", 0),
            "proposals": [
                _compact_proposal(proposal)
                for proposal in payload.get("proposals", [])
                if isinstance(proposal, dict)
            ],
        })

    return json.dumps({
        "success": True,
        "proposal_id": payload.get("proposalId"),
        "proposal_type": payload.get("proposalType"),
        "approved_at": payload.get("approvedAt"),
        "rejected_at": payload.get("rejectedAt"),
        "created_box_ids": payload.get("createdBoxIds", []),
        "updated_box_ids": payload.get("updatedBoxIds", []),
        "created_trace_ids": payload.get("createdTraceIds", []),
        "updated_proposal_ids": payload.get("updatedProposalIds", []),
    })


def _compact_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "role": turn.get("role"),
        "content": turn.get("content"),
        "created_at": turn.get("createdAt"),
        "sequence": turn.get("sequence"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _compact_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "id": proposal.get("id"),
        "proposal_type": proposal.get("proposalType"),
        "state": proposal.get("state"),
        "title": proposal.get("title"),
        "rationale": proposal.get("rationale"),
        "confidence": proposal.get("confidence"),
        "created_at": proposal.get("createdAt"),
        "reviewed_at": proposal.get("reviewedAt"),
        "source_summary_ids": proposal.get("sourceSummaryIds", []),
        "target_box_ids": proposal.get("targetBoxIds", []),
        "target_trace_ids": proposal.get("targetTraceIds", []),
    }
    if "payload" in proposal:
        result["payload"] = proposal.get("payload")
    return {key: value for key, value in result.items() if value is not None}


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _run_json_command(command: str, request: Dict[str, Any]) -> Dict[str, Any]:
    completed = subprocess.run(
        shlex.split(command),
        input=json.dumps(request, sort_keys=True),
        text=True,
        capture_output=True,
        timeout=_timeout_seconds(),
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Command returned non-object JSON.")
    return payload


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
        trace_id=args.get("trace_id"),
        box_id=args.get("box_id"),
        injection_packet=args.get("injection_packet"),
        max_turn_ranges=args.get("max_turn_ranges"),
        include_child_boxes=args.get("include_child_boxes"),
    ),
    check_fn=check_conversational_memory_resume_requirements,
    emoji="🧠",
)


registry.register(
    name="conversational_memory_sleep_review",
    toolset="memory",
    schema=CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA,
    handler=lambda args, **_kw: conversational_memory_sleep_review(
        reviewed_at=args.get("reviewed_at"),
        proposal_mode=args.get("proposal_mode"),
        include_proposals=args.get("include_proposals"),
        minimum_summaries_per_box=args.get("minimum_summaries_per_box"),
        minimum_trace_summaries=args.get("minimum_trace_summaries"),
        minimum_box_confidence=args.get("minimum_box_confidence"),
        minimum_trace_confidence=args.get("minimum_trace_confidence"),
        stale_strength_threshold=args.get("stale_strength_threshold"),
    ),
    check_fn=check_conversational_memory_sleep_review_requirements,
    emoji="🧠",
)


registry.register(
    name="conversational_memory_proposal_review",
    toolset="memory",
    schema=CONVERSATIONAL_MEMORY_PROPOSAL_REVIEW_SCHEMA,
    handler=lambda args, **_kw: conversational_memory_proposal_review(
        action=args.get("action"),
        proposal_id=args.get("proposal_id"),
        state=args.get("state"),
        proposal_type=args.get("proposal_type"),
        limit=args.get("limit"),
        include_payload=args.get("include_payload"),
        decided_at=args.get("decided_at"),
        reviewer=args.get("reviewer"),
        note=args.get("note"),
    ),
    check_fn=check_conversational_memory_proposal_review_requirements,
    emoji="🧠",
)
