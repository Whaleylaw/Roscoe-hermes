#!/usr/bin/env python3
"""
Inter-Agent Tool — cross-profile A2A messaging.

Exposes four tools that let one Hermes profile discover and talk to peer
profiles via the existing a2a-bridge JSON-RPC endpoints:

  - list_agents
  - ask_agent (synchronous)
  - dispatch_agent_task (asynchronous)
  - check_agent_task

Config is env-var driven (no config.yaml additions):
  A2A_REGISTRY_PATH    required — path to agents.registry.json
  HERMES_TOKEN         required — bearer token matching the bridge
  HERMES_A2A_SELF      recommended — this profile's id; enables self-filter
  INTER_AGENT_TIMEOUT  optional — per-call HTTP timeout (default 120s)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120
HEALTH_FANOUT_TIMEOUT_SECONDS = 3
HEALTH_FANOUT_WORKERS = 4


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_token() -> Optional[str]:
    val = os.getenv("HERMES_TOKEN")
    return val.strip() if val and val.strip() else None


def _get_registry_path() -> Optional[str]:
    val = os.getenv("A2A_REGISTRY_PATH")
    return val.strip() if val and val.strip() else None


def _get_self_id() -> Optional[str]:
    val = os.getenv("HERMES_A2A_SELF")
    return val.strip() if val and val.strip() else None


def _get_timeout() -> int:
    raw = os.getenv("INTER_AGENT_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid INTER_AGENT_TIMEOUT=%r; using default %d",
                       raw, DEFAULT_TIMEOUT_SECONDS)
        return DEFAULT_TIMEOUT_SECONDS


def _check_inter_agent_available() -> bool:
    """Toolset gate: require token + readable registry file."""
    if not _get_token():
        return False
    path = _get_registry_path()
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Registry + agent resolution
# ---------------------------------------------------------------------------

def _load_registry() -> List[Dict[str, Any]]:
    """Load registry entries whose source == 'hermes'. Empty list on failure."""
    path = _get_registry_path()
    if not path:
        return []
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read A2A registry at %s: %s", path, exc)
        return []
    agents = data.get("agents") or []
    return [a for a in agents if a.get("source") == "hermes"]


def _resolve_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    for entry in _load_registry():
        if entry.get("id") == agent_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _rpc_post(base_url: str, method: str, params: Dict[str, Any],
              timeout: Optional[int] = None) -> tuple[Optional[dict], Optional[str]]:
    """POST a JSON-RPC 2.0 request to an a2a-bridge endpoint.

    Returns (result, None) on success or (None, error_message) on failure.
    Handles network errors, 401s, malformed bodies, and JSON-RPC error objects.
    """
    token = _get_token()
    if not token:
        return None, "HERMES_TOKEN not set"

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }).encode("utf-8")

    req = urllib.request.Request(
        base_url.rstrip("/") + "/",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout or _get_timeout()) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return None, "Auth rejected by bridge. Check HERMES_TOKEN matches bridge config."
        return None, f"Bridge HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        # Real urlopen timeouts arrive wrapped in URLError(reason=TimeoutError(...)).
        if isinstance(exc.reason, TimeoutError):
            return None, "timeout"
        return None, f"Bridge not reachable at {base_url}: {exc.reason}"
    except TimeoutError:
        # Defensive: direct TimeoutError (e.g. tests mocking urlopen with side_effect=TimeoutError).
        return None, "timeout"

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        preview = body[:200].decode("utf-8", errors="replace")
        return None, f"Bridge returned malformed response: {preview}"

    if "error" in data and data["error"]:
        err = data["error"]
        return None, f"JSON-RPC {err.get('code')}: {err.get('message')}"

    return data.get("result"), None


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------

def _probe_health(a2a_url: str) -> bool:
    """GET {a2a_url}/health with a 3s timeout; return True iff body is {'ok': true}.

    /health is unauthenticated per the bridge design — no Authorization header.
    Any exception (network, timeout, bad JSON, ok=false) returns False.
    """
    health_url = a2a_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=HEALTH_FANOUT_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception:
        return False


def list_agents() -> str:
    """Return registered peer agents with live online/offline status."""
    self_id = _get_self_id()
    # When HERMES_A2A_SELF is unset, self_id is None and != None keeps all
    # entries (degraded mode — spec calls this out as expected).
    entries = [e for e in _load_registry() if e.get("id") != self_id]

    urls = [e.get("a2a_url", "") for e in entries]
    with ThreadPoolExecutor(max_workers=HEALTH_FANOUT_WORKERS) as pool:
        online_flags = list(pool.map(_probe_health, urls))

    agents_out = []
    for entry, online in zip(entries, online_flags):
        agents_out.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "description": entry.get("description", ""),
            "a2a_url": entry.get("a2a_url"),
            "skills": entry.get("skills", []),
            "online": online,
        })
    return json.dumps({"agents": agents_out}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Message composition + validation helpers
# ---------------------------------------------------------------------------

def _compose_text(goal: str, context: Optional[str]) -> str:
    goal = (goal or "").strip()
    if context and context.strip():
        return f"{goal}\n\nCONTEXT:\n{context.strip()}"
    return goal


def _validate_target(agent_id: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not agent_id or not str(agent_id).strip():
        return None, "agent_id is required"
    self_id = _get_self_id()
    if self_id and agent_id == self_id:
        return None, (
            f"Cannot send to yourself (agent_id={self_id}). "
            "Use delegate_task for in-process subagents."
        )
    entry = _resolve_agent(agent_id)
    if entry is None:
        return None, (
            f"Unknown agent_id: '{agent_id}'. Call list_agents to see available agents."
        )
    return entry, None


def _extract_reply_text(task: Dict[str, Any]) -> str:
    artifacts = task.get("artifacts") or []
    if not artifacts:
        return ""
    parts = artifacts[0].get("parts") or []
    for p in parts:
        if p.get("type") == "text":
            return p.get("text", "")
    return ""


# ---------------------------------------------------------------------------
# ask_agent
# ---------------------------------------------------------------------------

def ask_agent(agent_id: str, goal: str,
              context: Optional[str] = None,
              timeout: Optional[int] = None) -> str:
    """Synchronously send a message to agent_id and return the reply."""
    entry, err = _validate_target(agent_id)
    if err:
        return tool_error(err)

    text = _compose_text(goal, context)
    if not text:
        return tool_error("goal is required")

    task_id = str(uuid.uuid4())
    effective_timeout = timeout or _get_timeout()
    params = {
        "id": task_id,
        "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
    }

    try:
        result, err = _rpc_post(entry["a2a_url"], "tasks/send", params,
                                timeout=effective_timeout)
    except TimeoutError:
        err = "timeout"
        result = None

    if err == "timeout" or (err and "timeout" in err.lower()):
        return json.dumps({
            "agent_id": agent_id,
            "task_id": task_id,
            "status": "timeout",
            "hint": (
                "Task may still complete on the bridge. "
                "Call check_agent_task with this task_id."
            ),
        })

    if err:
        return json.dumps({
            "agent_id": agent_id,
            "task_id": task_id,
            "status": "error",
            "error": err,
        })

    task = result or {}
    state = (task.get("status") or {}).get("state", "unknown")
    out = {
        "agent_id": agent_id,
        "task_id": task.get("id", task_id),
        "status": state,
    }
    if state == "completed":
        out["reply"] = _extract_reply_text(task)
    elif state in ("failed", "canceled"):
        out["error"] = _extract_reply_text(task) or f"task ended in state {state}"
    return json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------------------
# dispatch_agent_task
# ---------------------------------------------------------------------------

def _dispatch_fire_and_forget(a2a_url: str, params: Dict[str, Any],
                               agent_id: str, task_id: str) -> None:
    """Runs in a daemon thread. Logs outcome; does not raise."""
    result, err = _rpc_post(a2a_url, "tasks/send", params)
    if err:
        logger.warning(
            "dispatch_agent_task(%s task=%s) failed: %s", agent_id, task_id, err,
        )


def dispatch_agent_task(agent_id: str, goal: str,
                        context: Optional[str] = None) -> str:
    """Fire a task at agent_id and return a task_id immediately."""
    entry, err = _validate_target(agent_id)
    if err:
        return tool_error(err)

    text = _compose_text(goal, context)
    if not text:
        return tool_error("goal is required")

    task_id = str(uuid.uuid4())
    params = {
        "id": task_id,
        "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
    }

    thread = threading.Thread(
        target=_dispatch_fire_and_forget,
        args=(entry["a2a_url"], params, agent_id, task_id),
        daemon=True,
        name=f"inter-agent-dispatch-{agent_id}-{task_id[:8]}",
    )
    thread.start()

    return json.dumps({
        "agent_id": agent_id,
        "task_id": task_id,
        "status": "dispatched",
    })


# ---------------------------------------------------------------------------
# check_agent_task
# ---------------------------------------------------------------------------

def _extract_status_message(task: Dict[str, Any]) -> str:
    msg = (task.get("status") or {}).get("message") or {}
    parts = msg.get("parts") or []
    for p in parts:
        if p.get("type") == "text":
            return p.get("text", "")
    return ""


def check_agent_task(agent_id: str, task_id: str) -> str:
    """Poll a previously dispatched task and return its current state."""
    entry = _resolve_agent(agent_id)
    if entry is None:
        return tool_error(
            f"Unknown agent_id: '{agent_id}'. Call list_agents to see available agents."
        )

    result, err = _rpc_post(entry["a2a_url"], "tasks/get", {"id": task_id})

    if err and "-32001" in err:
        return json.dumps({
            "agent_id": agent_id,
            "task_id": task_id,
            "status": "unknown",
            "error": (
                "task not found on bridge — may have been lost to bridge restart"
            ),
        })
    if err:
        return json.dumps({
            "agent_id": agent_id,
            "task_id": task_id,
            "status": "error",
            "error": err,
        })

    task = result or {}
    state = (task.get("status") or {}).get("state", "unknown")
    out = {"agent_id": agent_id, "task_id": task_id, "status": state}
    if state == "completed":
        out["reply"] = _extract_reply_text(task)
    elif state in ("failed", "canceled"):
        out["error"] = _extract_status_message(task) or f"task ended in state {state}"
    return json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

LIST_AGENTS_SCHEMA = {
    "name": "list_agents",
    "description": (
        "List peer Hermes agents available over the A2A bridge, with live "
        "online/offline status. Use this before ask_agent or "
        "dispatch_agent_task to pick a target."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="list_agents",
    toolset="inter_agent",
    schema=LIST_AGENTS_SCHEMA,
    handler=lambda args, **kw: list_agents(),
    check_fn=_check_inter_agent_available,
    emoji="👥",
)

ASK_AGENT_SCHEMA = {
    "name": "ask_agent",
    "description": (
        "Synchronously send a message to a peer Hermes agent and wait for its "
        "reply. Each peer agent has its own profile, model, and context. "
        "Use list_agents first to pick a target. Blocks up to INTER_AGENT_TIMEOUT "
        "seconds (default 120). If the call times out, the returned task_id can "
        "be polled with check_agent_task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Peer agent id from list_agents (e.g. 'paralegal').",
            },
            "goal": {
                "type": "string",
                "description": "What you want the peer agent to do or answer.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional background the peer needs (file paths, prior findings, "
                    "constraints). Peers don't share your conversation."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Optional per-call timeout in seconds. Defaults to INTER_AGENT_TIMEOUT.",
            },
        },
        "required": ["agent_id", "goal"],
    },
}

registry.register(
    name="ask_agent",
    toolset="inter_agent",
    schema=ASK_AGENT_SCHEMA,
    handler=lambda args, **kw: ask_agent(
        agent_id=args.get("agent_id"),
        goal=args.get("goal"),
        context=args.get("context"),
        timeout=args.get("timeout"),
    ),
    check_fn=_check_inter_agent_available,
    emoji="💬",
)

DISPATCH_AGENT_TASK_SCHEMA = {
    "name": "dispatch_agent_task",
    "description": (
        "Asynchronously dispatch a task to a peer Hermes agent. Returns a "
        "task_id immediately without waiting for completion. Use "
        "check_agent_task with the returned task_id to poll for results. "
        "Prefer ask_agent for quick Q&A; use this for jobs expected to take "
        "longer than a single response (e.g. document analysis, multi-step "
        "research)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Peer agent id."},
            "goal": {"type": "string", "description": "What to do."},
            "context": {
                "type": "string",
                "description": "Optional background for the peer.",
            },
        },
        "required": ["agent_id", "goal"],
    },
}

registry.register(
    name="dispatch_agent_task",
    toolset="inter_agent",
    schema=DISPATCH_AGENT_TASK_SCHEMA,
    handler=lambda args, **kw: dispatch_agent_task(
        agent_id=args.get("agent_id"),
        goal=args.get("goal"),
        context=args.get("context"),
    ),
    check_fn=_check_inter_agent_available,
    emoji="📤",
)

CHECK_AGENT_TASK_SCHEMA = {
    "name": "check_agent_task",
    "description": (
        "Poll the status of a peer agent task previously returned by "
        "dispatch_agent_task (or ask_agent when it returned 'timeout'). "
        "Returns current state: 'working', 'completed' (with reply), 'failed' "
        "or 'canceled' (with error), or 'unknown' if the bridge no longer "
        "holds the task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Peer agent id."},
            "task_id": {"type": "string", "description": "Task id to check."},
        },
        "required": ["agent_id", "task_id"],
    },
}

registry.register(
    name="check_agent_task",
    toolset="inter_agent",
    schema=CHECK_AGENT_TASK_SCHEMA,
    handler=lambda args, **kw: check_agent_task(
        agent_id=args.get("agent_id"),
        task_id=args.get("task_id"),
    ),
    check_fn=_check_inter_agent_available,
    emoji="🔎",
)
