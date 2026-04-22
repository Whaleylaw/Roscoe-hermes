# Inter-Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `inter_agent` toolset (`list_agents`, `ask_agent`, `dispatch_agent_task`, `check_agent_task`) so one Hermes profile can discover and message peer profiles via the existing `a2a-bridge`.

**Architecture:** Pure client-side. Each tool is an HTTP call against `a2a-bridge` (ports `1880{0..4}`). No changes to the bridge. Config by env var only (`A2A_REGISTRY_PATH`, `HERMES_TOKEN`, `HERMES_A2A_SELF`, optional `INTER_AGENT_TIMEOUT`).

**Tech Stack:** Python 3, `urllib.request`, `concurrent.futures.ThreadPoolExecutor`, `threading.Thread`, existing `tools.registry` + `toolsets.py` patterns. Tests use `pytest` with `unittest.mock.patch` for `urlopen` (mirrors `tests/tools/test_discord_tool.py`).

**Spec:** `docs/superpowers/specs/2026-04-22-inter-agent-tools-design.md`

---

## File Structure

**Create:**
- `tools/inter_agent_tool.py` — module containing all 4 tools + shared helpers (`_load_registry`, `_resolve_agent`, `_get_self_id`, `_rpc_post`, `_check_inter_agent_available`), schemas, and registry registrations.
- `tests/tools/test_inter_agent.py` — pytest-style unit tests, mocked `urlopen`.

**Modify:**
- `toolsets.py` — add `"inter_agent"` entry to `TOOLSETS` dict.
- `tools/delegate_tool.py` — extend `DELEGATE_BLOCKED_TOOLS`.
- `tests/tools/test_delegate.py` — assert blocked-tools extension.

---

## Task 1: Module skeleton, registry loader, `check_fn`

**Files:**
- Create: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/tools/test_inter_agent.py`:

```python
"""Tests for the inter-agent toolset."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Registry fixture
# ---------------------------------------------------------------------------

REGISTRY_FIXTURE = {
    "version": 2,
    "agents": [
        {
            "id": "roscoe",
            "name": "Roscoe",
            "source": "hermes",
            "hermes_profile": "default",
            "hermes_port": 8642,
            "hermes_model": "Roscoe",
            "a2a_url": "http://127.0.0.1:18800",
            "a2a_port": 18800,
            "auth_env": "HERMES_TOKEN",
            "description": "Roscoe default profile.",
            "skills": [{"id": "legal", "name": "Legal"}],
        },
        {
            "id": "paralegal",
            "name": "Paralegal",
            "source": "hermes",
            "hermes_profile": "paralegal",
            "hermes_port": 8643,
            "hermes_model": "paralegal",
            "a2a_url": "http://127.0.0.1:18801",
            "a2a_port": 18801,
            "auth_env": "HERMES_TOKEN",
            "description": "Paralegal profile.",
            "skills": [{"id": "case-support", "name": "Case Support"}],
        },
        {
            "id": "not-hermes",
            "source": "other",
            "a2a_url": "http://127.0.0.1:9999",
        },
    ],
}


@pytest.fixture
def registry_file(tmp_path):
    path = tmp_path / "agents.registry.json"
    path.write_text(json.dumps(REGISTRY_FIXTURE))
    return str(path)


# ---------------------------------------------------------------------------
# check_fn
# ---------------------------------------------------------------------------

class TestCheckAvailable:
    def test_false_when_token_missing(self, monkeypatch, registry_file):
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        monkeypatch.delenv("HERMES_TOKEN", raising=False)
        from tools.inter_agent_tool import _check_inter_agent_available
        assert _check_inter_agent_available() is False

    def test_false_when_registry_path_missing(self, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.delenv("A2A_REGISTRY_PATH", raising=False)
        from tools.inter_agent_tool import _check_inter_agent_available
        assert _check_inter_agent_available() is False

    def test_false_when_registry_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", str(tmp_path / "nope.json"))
        from tools.inter_agent_tool import _check_inter_agent_available
        assert _check_inter_agent_available() is False

    def test_true_when_all_set(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import _check_inter_agent_available
        assert _check_inter_agent_available() is True


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------

class TestLoadRegistry:
    def test_filters_to_hermes_source(self, monkeypatch, registry_file):
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import _load_registry
        agents = _load_registry()
        ids = [a["id"] for a in agents]
        assert "roscoe" in ids
        assert "paralegal" in ids
        assert "not-hermes" not in ids

    def test_returns_empty_when_unreadable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("A2A_REGISTRY_PATH", str(tmp_path / "missing.json"))
        from tools.inter_agent_tool import _load_registry
        assert _load_registry() == []


# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------

class TestResolveAgent:
    def test_found(self, monkeypatch, registry_file):
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import _resolve_agent
        entry = _resolve_agent("paralegal")
        assert entry is not None
        assert entry["a2a_url"] == "http://127.0.0.1:18801"

    def test_unknown(self, monkeypatch, registry_file):
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import _resolve_agent
        assert _resolve_agent("nope") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/aaronwhaley/Github/Roscoe-hermes && python -m pytest tests/tools/test_inter_agent.py -v`
Expected: all tests FAIL with `ModuleNotFoundError: No module named 'tools.inter_agent_tool'`.

- [ ] **Step 3: Write the module skeleton**

Create `tools/inter_agent_tool.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): inter_agent module skeleton + registry loader"
```

---

## Task 2: Shared HTTP helper `_rpc_post`

**Files:**
- Modify: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# _rpc_post
# ---------------------------------------------------------------------------

def _mock_urlopen(body_json, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(body_json).encode("utf-8")
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


class TestRpcPost:
    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_success_returns_result(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "secret-token")
        mock_fn.return_value = _mock_urlopen(
            {"jsonrpc": "2.0", "id": "req-1", "result": {"ok": True}}
        )
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/get", {"id": "t"})
        assert err is None
        assert result == {"ok": True}
        # Verify auth header
        req = mock_fn.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret-token"

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_401_returns_auth_error(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "bad")
        mock_fn.side_effect = urllib.error.HTTPError(
            "u", 401, "Unauthorized", {}, None,
        )
        import urllib.error
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/send", {})
        assert result is None
        assert "auth" in err.lower()

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_network_error(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        mock_fn.side_effect = urllib.error.URLError("Connection refused")
        import urllib.error
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/get", {})
        assert result is None
        assert "not reachable" in err.lower()

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_jsonrpc_error_passthrough(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        mock_fn.return_value = _mock_urlopen(
            {"jsonrpc": "2.0", "id": "r", "error": {"code": -32001, "message": "Task not found"}}
        )
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/get", {"id": "x"})
        assert result is None
        assert "-32001" in err or "not found" in err.lower()

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_malformed_response(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        mock = MagicMock()
        mock.read.return_value = b"not-json"
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        mock_fn.return_value = mock
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/get", {})
        assert result is None
        assert "malformed" in err.lower()
```

Also add at the top of `test_inter_agent.py`:

```python
import urllib.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestRpcPost -v`
Expected: all fail with `ImportError: cannot import name '_rpc_post'`.

- [ ] **Step 3: Implement `_rpc_post`**

Append to `tools/inter_agent_tool.py` after the registry helpers:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestRpcPost -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): inter_agent _rpc_post helper with structured errors"
```

---

## Task 3: `list_agents` tool

**Files:**
- Modify: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------

class TestListAgents:
    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_happy_path_marks_online(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        monkeypatch.delenv("HERMES_A2A_SELF", raising=False)
        mock_fn.return_value = _mock_urlopen({"ok": True, "agent": "paralegal"})
        from tools.inter_agent_tool import list_agents
        result = json.loads(list_agents())
        assert "agents" in result
        ids = [a["id"] for a in result["agents"]]
        assert "roscoe" in ids
        assert "paralegal" in ids
        for a in result["agents"]:
            assert a["online"] is True

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_offline_peer(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.side_effect = urllib.error.URLError("refused")
        from tools.inter_agent_tool import list_agents
        result = json.loads(list_agents())
        for a in result["agents"]:
            assert a["online"] is False

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_self_filter(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        monkeypatch.setenv("HERMES_A2A_SELF", "roscoe")
        mock_fn.return_value = _mock_urlopen({"ok": True})
        from tools.inter_agent_tool import list_agents
        result = json.loads(list_agents())
        ids = [a["id"] for a in result["agents"]]
        assert "roscoe" not in ids
        assert "paralegal" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestListAgents -v`
Expected: FAIL with `ImportError: cannot import name 'list_agents'`.

- [ ] **Step 3: Implement `list_agents`**

Append to `tools/inter_agent_tool.py`:

```python
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
```

Also add at the bottom of the file the schema + registration (will stay as-is through later tasks):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestListAgents -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): list_agents — discover peers with live health"
```

---

## Task 4: `ask_agent` tool (synchronous)

**Files:**
- Modify: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# ask_agent
# ---------------------------------------------------------------------------

def _task_completed(task_id="tid", reply_text="hello back"):
    return _mock_urlopen({
        "jsonrpc": "2.0",
        "id": "r",
        "result": {
            "id": task_id,
            "status": {"state": "completed", "timestamp": "2026-04-22T00:00:00Z"},
            "artifacts": [{
                "parts": [{"type": "text", "text": reply_text}],
                "metadata": {},
            }],
            "history": [],
            "metadata": {},
        },
    })


class TestAskAgent:
    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_happy_path(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _task_completed(reply_text="paralegal reply")
        from tools.inter_agent_tool import ask_agent
        out = json.loads(ask_agent("paralegal", "hello"))
        assert out["status"] == "completed"
        assert out["reply"] == "paralegal reply"
        assert out["agent_id"] == "paralegal"
        assert "task_id" in out

    def test_self_call_rejected(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        monkeypatch.setenv("HERMES_A2A_SELF", "paralegal")
        from tools.inter_agent_tool import ask_agent
        out = json.loads(ask_agent("paralegal", "hi"))
        assert "error" in out
        assert "yourself" in out["error"].lower()

    def test_unknown_agent(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import ask_agent
        out = json.loads(ask_agent("ghost", "hi"))
        assert "error" in out
        assert "ghost" in out["error"]

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_timeout_returns_recoverable_hint(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.side_effect = TimeoutError("read timed out")
        from tools.inter_agent_tool import ask_agent
        out = json.loads(ask_agent("paralegal", "hi"))
        assert out["status"] == "timeout"
        assert out["agent_id"] == "paralegal"
        assert "task_id" in out
        assert "check_agent_task" in out["hint"]

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_context_is_appended(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _task_completed()
        from tools.inter_agent_tool import ask_agent
        ask_agent("paralegal", "Summarize", context="file X has Y")
        # Inspect the POSTed payload
        req = mock_fn.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        text = body["params"]["message"]["parts"][0]["text"]
        assert "Summarize" in text
        assert "CONTEXT" in text
        assert "file X has Y" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestAskAgent -v`
Expected: FAIL with import error for `ask_agent`.

- [ ] **Step 3: Implement `ask_agent`**

Insert before the "Schemas" section of `tools/inter_agent_tool.py`:

```python
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
```

Note: `_rpc_post` currently maps `TimeoutError` to an error string `"Bridge timeout at ..."`. Update that branch so `ask_agent` can detect it:

Change the `_rpc_post` timeout branch from

```python
    except TimeoutError as exc:
        return None, f"Bridge timeout at {base_url}: {exc}"
```

to

```python
    except (TimeoutError, OSError) as exc:
        if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
            return None, "timeout"
        return None, f"Bridge error at {base_url}: {exc}"
```

Also add the schema + registration at the bottom:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestAskAgent -v`
Expected: PASS.
Also re-run `TestRpcPost` to confirm the timeout branch still works:
`python -m pytest tests/tools/test_inter_agent.py::TestRpcPost -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): ask_agent — synchronous peer Q&A with timeout recovery"
```

---

## Task 5: `dispatch_agent_task` tool (asynchronous)

**Files:**
- Modify: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# dispatch_agent_task
# ---------------------------------------------------------------------------

class TestDispatchAgentTask:
    @patch("tools.inter_agent_tool.threading.Thread")
    def test_happy_path_returns_immediately(self, mock_thread, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        t_instance = MagicMock()
        mock_thread.return_value = t_instance
        from tools.inter_agent_tool import dispatch_agent_task
        out = json.loads(dispatch_agent_task("paralegal", "long job"))
        assert out["status"] == "dispatched"
        assert out["agent_id"] == "paralegal"
        assert "task_id" in out
        # Thread was created and started
        mock_thread.assert_called_once()
        t_instance.start.assert_called_once()
        # Thread is daemon
        assert mock_thread.call_args.kwargs.get("daemon") is True

    def test_self_call_rejected(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        monkeypatch.setenv("HERMES_A2A_SELF", "paralegal")
        from tools.inter_agent_tool import dispatch_agent_task
        out = json.loads(dispatch_agent_task("paralegal", "x"))
        assert "error" in out
        assert "yourself" in out["error"].lower()

    def test_unknown_agent(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import dispatch_agent_task
        out = json.loads(dispatch_agent_task("ghost", "x"))
        assert "error" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestDispatchAgentTask -v`
Expected: FAIL with import error for `dispatch_agent_task`.

- [ ] **Step 3: Implement `dispatch_agent_task`**

Insert before the "Schemas" section:

```python
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
```

Add the schema + registration at the bottom:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestDispatchAgentTask -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): dispatch_agent_task — async peer task with task_id handoff"
```

---

## Task 6: `check_agent_task` tool

**Files:**
- Modify: `tools/inter_agent_tool.py`
- Test: `tests/tools/test_inter_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# check_agent_task
# ---------------------------------------------------------------------------

def _task_in_state(state, task_id="tid", reply_text="", error_text=""):
    artifacts = []
    if reply_text:
        artifacts = [{"parts": [{"type": "text", "text": reply_text}], "metadata": {}}]
    status = {"state": state, "timestamp": "2026-04-22T00:00:00Z"}
    if error_text:
        status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": error_text}],
        }
    return _mock_urlopen({
        "jsonrpc": "2.0",
        "id": "r",
        "result": {
            "id": task_id,
            "status": status,
            "artifacts": artifacts,
            "history": [],
            "metadata": {},
        },
    })


class TestCheckAgentTask:
    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_working(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _task_in_state("working")
        from tools.inter_agent_tool import check_agent_task
        out = json.loads(check_agent_task("paralegal", "tid"))
        assert out["status"] == "working"

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_completed_returns_reply(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _task_in_state("completed", reply_text="done!")
        from tools.inter_agent_tool import check_agent_task
        out = json.loads(check_agent_task("paralegal", "tid"))
        assert out["status"] == "completed"
        assert out["reply"] == "done!"

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_failed_returns_error(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _task_in_state("failed", error_text="boom")
        from tools.inter_agent_tool import check_agent_task
        out = json.loads(check_agent_task("paralegal", "tid"))
        assert out["status"] == "failed"
        assert "boom" in out["error"]

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_task_not_found(self, mock_fn, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        mock_fn.return_value = _mock_urlopen({
            "jsonrpc": "2.0", "id": "r",
            "error": {"code": -32001, "message": "Task not found: tid"},
        })
        from tools.inter_agent_tool import check_agent_task
        out = json.loads(check_agent_task("paralegal", "tid"))
        assert out["status"] == "unknown"
        assert "not found" in out["error"].lower()

    def test_unknown_agent(self, monkeypatch, registry_file):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        monkeypatch.setenv("A2A_REGISTRY_PATH", registry_file)
        from tools.inter_agent_tool import check_agent_task
        out = json.loads(check_agent_task("ghost", "tid"))
        assert "error" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestCheckAgentTask -v`
Expected: FAIL with import error for `check_agent_task`.

- [ ] **Step 3: Implement `check_agent_task`**

Insert before the "Schemas" section:

```python
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
```

Add the schema + registration at the bottom:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestCheckAgentTask -v`
Expected: PASS.

Also run the whole file to confirm nothing regressed:
`python -m pytest tests/tools/test_inter_agent.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inter_agent_tool.py tests/tools/test_inter_agent.py
git commit -m "feat(tools): check_agent_task — poll dispatched peer task state"
```

---

## Task 7: Register `inter_agent` toolset

**Files:**
- Modify: `toolsets.py`
- Test: existing test suite (no new tests — the registration is exercised by any tool load path)

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_inter_agent.py`:

```python
# ---------------------------------------------------------------------------
# Toolset registration
# ---------------------------------------------------------------------------

class TestToolsetRegistration:
    def test_inter_agent_toolset_listed(self):
        from toolsets import TOOLSETS
        assert "inter_agent" in TOOLSETS
        tools = set(TOOLSETS["inter_agent"]["tools"])
        assert tools == {
            "list_agents", "ask_agent",
            "dispatch_agent_task", "check_agent_task",
        }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestToolsetRegistration -v`
Expected: FAIL (toolset not yet defined).

- [ ] **Step 3: Add the toolset entry**

Open `toolsets.py`. Locate the `"delegation"` entry (around line 189) and add the new entry directly after it:

```python
    "inter_agent": {
        "description": "Discover and message peer Hermes agents via the A2A bridge",
        "tools": [
            "list_agents",
            "ask_agent",
            "dispatch_agent_task",
            "check_agent_task",
        ],
        "includes": []
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/tools/test_inter_agent.py::TestToolsetRegistration -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add toolsets.py tests/tools/test_inter_agent.py
git commit -m "feat(toolsets): register inter_agent toolset"
```

---

## Task 8: Block subagents from using inter_agent tools

**Files:**
- Modify: `tools/delegate_tool.py:32-38`
- Test: `tests/tools/test_delegate.py`

- [ ] **Step 1: Write the failing test**

Open `tests/tools/test_delegate.py`. Find the class `TestDelegateRequirements` (around line 58) and add a new test method directly below `test_schema_valid`:

```python
    def test_inter_agent_tools_are_blocked(self):
        blocked = DELEGATE_BLOCKED_TOOLS
        for name in (
            "list_agents",
            "ask_agent",
            "dispatch_agent_task",
            "check_agent_task",
        ):
            assert name in blocked, f"{name} should be in DELEGATE_BLOCKED_TOOLS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tools/test_delegate.py::TestDelegateRequirements::test_inter_agent_tools_are_blocked -v`
Expected: FAIL with `AssertionError: list_agents should be in DELEGATE_BLOCKED_TOOLS`.

- [ ] **Step 3: Extend the blocked set**

Open `tools/delegate_tool.py`. Replace lines 32-38:

```python
# Tools that children must never have access to
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",   # no recursive delegation
    "clarify",         # no user interaction
    "memory",          # no writes to shared MEMORY.md
    "send_message",    # no cross-platform side effects
    "execute_code",    # children should reason step-by-step, not write scripts
])
```

with:

```python
# Tools that children must never have access to
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",         # no recursive delegation
    "clarify",               # no user interaction
    "memory",                # no writes to shared MEMORY.md
    "send_message",          # no cross-platform side effects
    "execute_code",          # children should reason step-by-step, not write scripts
    # inter_agent toolset — subagents must not bypass depth limits via A2A
    "list_agents",
    "ask_agent",
    "dispatch_agent_task",
    "check_agent_task",
])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/tools/test_delegate.py::TestDelegateRequirements::test_inter_agent_tools_are_blocked -v`
Expected: PASS.

Also run the full delegate test file to confirm no regression:
`python -m pytest tests/tools/test_delegate.py -v`
Expected: all previously-passing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/delegate_tool.py tests/tools/test_delegate.py
git commit -m "fix(delegate): block inter_agent tools in subagents"
```

---

## Task 9: Full regression + wire it up

**Files:** (no source changes — verification only)

- [ ] **Step 1: Run the full inter_agent suite**

Run: `python -m pytest tests/tools/test_inter_agent.py tests/tools/test_delegate.py -v`
Expected: all PASS.

- [ ] **Step 2: Verify module loads via the registry's discovery path**

Run:

```bash
python -c "
from tools.registry import discover_builtin_tools, registry
discover_builtin_tools()
for name in ['list_agents', 'ask_agent', 'dispatch_agent_task', 'check_agent_task']:
    entry = registry.get(name) if hasattr(registry, 'get') else None
    # Fall back to internal dict if 'get' is not defined
    entry = entry or registry._tools.get(name)
    assert entry is not None, f'{name} not registered'
    assert entry.toolset == 'inter_agent', f'{name} wrong toolset: {entry.toolset}'
print('OK: all 4 inter_agent tools registered under toolset \\'inter_agent\\'')
"
```

Expected output: `OK: all 4 inter_agent tools registered under toolset 'inter_agent'`

- [ ] **Step 3: (Optional) Live integration smoke test**

Only run if the `a2a-bridge` is up on this machine. This exercises `ask_agent` end-to-end against a live peer:

```bash
INTER_AGENT_LIVE_TEST=1 \
A2A_REGISTRY_PATH=/Users/aaronwhaley/Github/a2a-bridge/agents.registry.json \
HERMES_TOKEN=hermes-roscoe-bridge-2026 \
HERMES_A2A_SELF=roscoe \
python -c "
import json
from tools.inter_agent_tool import list_agents, ask_agent
print('list_agents:', list_agents()[:400])
print('ask_agent  :', ask_agent('paralegal', 'Reply with exactly: paralegal-ok')[:400])
"
```

Expected: `list_agents` reports ≥4 peers with `online: true`; `ask_agent` returns a JSON blob with `"status": "completed"` and `"reply"` containing `paralegal-ok`.

If bridge is not running, skip this step.

- [ ] **Step 4: Commit nothing (verification-only task)**

No commit for Task 9 unless something needed fixing. If verification revealed a bug, fix in-place with a standalone commit following the same TDD loop.

---

## Self-Review

**Spec coverage:**
- ✅ `list_agents` with online/offline — Task 3.
- ✅ `ask_agent` synchronous with context composition, timeout recovery hint — Task 4.
- ✅ `dispatch_agent_task` async with daemon thread — Task 5.
- ✅ `check_agent_task` covering working/completed/failed/unknown — Task 6.
- ✅ `check_fn` gating on `A2A_REGISTRY_PATH` + `HERMES_TOKEN` — Task 1.
- ✅ `HERMES_A2A_SELF` self-filter and self-call rejection — Tasks 1, 3, 4.
- ✅ Bearer auth + JSON-RPC error passthrough — Task 2.
- ✅ Subagent block via `DELEGATE_BLOCKED_TOOLS` — Task 8.
- ✅ Toolset registration — Task 7.
- ✅ Unit tests covering happy + error paths — each tool task.
- ✅ Optional live integration smoke — Task 9.

**Placeholder scan:** no `TBD`/`TODO` strings; every step contains concrete code or a concrete command.

**Type/signature consistency:**
- `_rpc_post(base_url, method, params, timeout=None) -> (result, err)` — used consistently in Tasks 2, 4, 5, 6.
- `_resolve_agent(agent_id) -> Optional[dict]` — same signature everywhere.
- `_compose_text(goal, context)` — used by `ask_agent` and `dispatch_agent_task`.
- `_extract_reply_text(task)` — used by `ask_agent` and `check_agent_task`.
- Timeout branch in `_rpc_post` returns the sentinel `"timeout"` — picked up verbatim by `ask_agent`.

**Ambiguity check:** none; schemas explicitly declare `required` fields; env-var precedence is stated.
