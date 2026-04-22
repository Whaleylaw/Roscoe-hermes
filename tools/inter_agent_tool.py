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
