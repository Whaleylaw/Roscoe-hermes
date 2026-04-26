"""End-to-end: delegate_task with session_target writes to the target session."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
def test_delegate_with_session_target_appends_to_existing_session(tmp_path, monkeypatch):
    """Stand up a minimal sessions.json + case_channels.yaml, run delegate_task
    with a session_target spec, and assert the target session's JSONL transcript
    received the inbound mirror plus the assistant entry the stub child writes."""

    # --- Stage the on-disk session index + case_channels mapping --------------
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "sessions.json").write_text(json.dumps({
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        }
    }))
    # Empty starting transcript
    (sessions_dir / "sess-abby.jsonl").write_text("")

    case_channels = tmp_path / "case_channels.yaml"
    case_channels.write_text(
        "channel_to_cwd:\n"
        "  C0AH0V6G2Q1: /tmp/cases/abby-sitgraves\n"
        "channel_to_slug:\n"
        "  C0AH0V6G2Q1: abby-sitgraves\n"
        "slug_to_channel:\n"
        "  abby-sitgraves: C0AH0V6G2Q1\n"
    )

    # Point gateway.mirror at our temp sessions dir/index.
    monkeypatch.setattr("gateway.mirror._SESSIONS_INDEX",
                        sessions_dir / "sessions.json")
    monkeypatch.setattr("gateway.mirror._SESSIONS_DIR", sessions_dir)

    # Point gateway.cross_session at our temp case_channels.yaml.
    # resolve_session_target accepts a path argument, but delegate_task calls
    # it without one — so override the default.
    from gateway import cross_session
    monkeypatch.setattr(cross_session, "_default_case_channels_path",
                        lambda: case_channels)

    # Skip the SQLite mirror call (no SessionDB schema in tmp).
    monkeypatch.setattr("gateway.mirror._append_to_sqlite", lambda *_a, **_kw: None)

    # --- Stub the child AIAgent so no real API calls happen ------------------
    from gateway.mirror import _append_to_jsonl

    class StubAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs.get("session_id") or "stub-sess"
            self._session_db = kwargs.get("session_db")
            self.platform = kwargs.get("platform")
            # Mirror the attrs delegate_tool reaches for after construction
            self._delegate_role = "leaf"
            self._delegate_depth = 1
            self._subagent_id = None
            self._parent_subagent_id = None
            self._subagent_goal = None
            self._session_target = None
            self._delegate_saved_tool_names = []
            self._credential_pool = None
            self._print_fn = None
            self.tool_progress_callback = None
            self.model = "stub-model"

        def run_conversation(self, user_message, task_id=None):
            _append_to_jsonl(self.session_id, {
                "role": "assistant",
                "content": "Drafted complaint.",
            })
            return {"final_response": "Drafted complaint."}

        def get_activity_summary(self):
            return {"current_tool": None, "api_call_count": 0,
                    "max_iterations": 1, "last_activity_desc": ""}

        def interrupt(self):
            pass

    # _build_child_agent does `from run_agent import AIAgent` lazily, so patch
    # the source module attribute.
    monkeypatch.setattr("run_agent.AIAgent", StubAgent)

    # --- Stub credential resolution -----------------------------------------
    monkeypatch.setattr(
        "tools.delegate_tool._resolve_delegation_credentials",
        lambda *_a, **_kw: {
            "model": "stub-model",
            "provider": None,
            "base_url": None,
            "api_key": None,
            "api_mode": None,
        },
    )

    # --- Build a bare parent agent ------------------------------------------
    parent = SimpleNamespace(
        session_id="sess-perry",
        platform="slack",
        model="stub-model",
        base_url=None,
        _session_db=None,
        providers_allowed=None,
        providers_ignored=None,
        providers_order=None,
        provider_sort=None,
        max_tokens=4096,
        prefill_messages=None,
        tool_progress_callback=None,
        _active_children=[],
        _active_children_lock=None,
        _delegate_depth=0,
        _delegate_spinner=None,
        _print_fn=None,
        _subdirectory_hints=None,
        _credential_pool=None,
        cwd=None,
        terminal_cwd=None,
        _current_task_id=None,
        _interrupt_requested=False,
        _touch_activity=None,
    )

    # --- Invoke delegate_task -----------------------------------------------
    from tools import delegate_tool
    out = delegate_tool.delegate_task(
        goal="Draft a complaint.",
        toolsets=["file_ops"],
        session_target="case:abby-sitgraves",
        parent_agent=parent,
    )

    # --- Assert -------------------------------------------------------------
    transcript = (sessions_dir / "sess-abby.jsonl").read_text().splitlines()
    parsed = [json.loads(line) for line in transcript]
    roles = [m["role"] for m in parsed]
    assert "user" in roles, f"expected user-mirror entry, got {parsed!r}"
    assert "assistant" in roles, f"expected assistant entry, got {parsed!r}"

    # The user mirror should reference the source.
    user_msg = next(m for m in parsed if m["role"] == "user")
    assert user_msg.get("mirror") is True
    assert "Draft a complaint" in user_msg["content"]
