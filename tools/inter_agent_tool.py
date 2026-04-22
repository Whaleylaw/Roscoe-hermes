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
        return None, f"Bridge not reachable at {base_url}: {exc.reason}"
    except TimeoutError as exc:
        return None, f"Bridge timeout at {base_url}: {exc}"

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
