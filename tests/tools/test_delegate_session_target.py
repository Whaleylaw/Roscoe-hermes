"""Unit tests: _build_child_agent uses session_target to override session_id."""

from unittest.mock import MagicMock
import pytest

from gateway.cross_session import SessionTarget


@pytest.fixture
def fake_parent():
    parent = MagicMock()
    parent.session_id = "sess-perry"
    parent._session_db = MagicMock()
    parent.platform = "slack"
    parent.max_tokens = 4096
    parent.prefill_messages = None
    parent.tool_progress_callback = None
    parent.providers_allowed = None
    parent.providers_ignored = None
    parent.providers_order = None
    parent.provider_sort = None
    parent.cwd = None
    parent.terminal_cwd = None
    parent._delegate_depth = 0
    parent._delegate_spinner = None
    parent._print_fn = None
    parent._active_children = []
    parent._subdirectory_hints = None
    parent._credential_pool = None
    parent._active_children_lock = None
    parent.enabled_toolsets = ["file_ops"]
    parent.model = "test-model"
    parent.provider = "test-provider"
    parent.base_url = "https://example.invalid"
    parent.api_key = "test-key"
    parent.api_mode = "chat_completions"
    parent.acp_command = None
    parent.acp_args = []
    parent.reasoning_config = None
    parent._client_kwargs = {}
    parent._subagent_id = None
    parent.valid_tool_names = ["read_file"]
    return parent


def test_build_child_uses_target_session_id(fake_parent, monkeypatch):
    """When session_target is provided, child AIAgent is constructed with session_id=target.session_id."""
    from tools import delegate_tool

    target = SessionTarget(
        session_id="sess-abby",
        cwd="/cases/abby-sitgraves",
        platform="slack",
        chat_id="C0AH0V6G2Q1",
        channel_name="abby-sitgraves",
    )

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def __setattr__(self, k, v):
            captured.setdefault("post_init", {})[k] = v

    # Stub run_agent.AIAgent (imported lazily inside _build_child_agent).
    import run_agent
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)

    delegate_tool._build_child_agent(
        task_index=0,
        goal="Draft complaint",
        context=None,
        toolsets=["file_ops"],
        model=None,
        max_iterations=5,
        task_count=1,
        parent_agent=fake_parent,
        role="leaf",
        session_target=target,
    )

    assert captured["init_kwargs"].get("session_id") == "sess-abby"
    assert captured["init_kwargs"].get("parent_session_id") == "sess-perry"


def test_build_child_no_target_session_id_is_none(fake_parent, monkeypatch):
    """When session_target is omitted, session_id passed to AIAgent is None (auto-generate)."""
    from tools import delegate_tool

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def __setattr__(self, k, v):
            pass

    import run_agent
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)

    delegate_tool._build_child_agent(
        task_index=0,
        goal="Draft complaint",
        context=None,
        toolsets=["file_ops"],
        model=None,
        max_iterations=5,
        task_count=1,
        parent_agent=fake_parent,
        role="leaf",
    )

    assert captured["init_kwargs"].get("session_id") is None
