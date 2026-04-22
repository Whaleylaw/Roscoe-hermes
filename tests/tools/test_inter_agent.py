"""Tests for the inter-agent toolset."""

import json
import urllib.error
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
        from tools.inter_agent_tool import _rpc_post
        result, err = _rpc_post("http://127.0.0.1:18801", "tasks/send", {})
        assert result is None
        assert "auth" in err.lower()

    @patch("tools.inter_agent_tool.urllib.request.urlopen")
    def test_network_error(self, mock_fn, monkeypatch):
        monkeypatch.setenv("HERMES_TOKEN", "t")
        mock_fn.side_effect = urllib.error.URLError("Connection refused")
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
        assert len(ids) == 2, f"expected only hermes peers, got {ids}"
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
        req = mock_fn.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        text = body["params"]["message"]["parts"][0]["text"]
        assert "Summarize" in text
        assert "CONTEXT" in text
        assert "file X has Y" in text
