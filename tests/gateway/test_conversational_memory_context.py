import json
import sys

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB


def _source():
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat-1",
        chat_type="dm",
        user_id="u1",
        user_name="Alice",
    )


def test_load_agent_context_prepends_optional_conversational_memory_context(
    tmp_path,
    monkeypatch,
):
    bridge_script = tmp_path / "inject.py"
    bridge_script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request['profile_id'] == 'default'\n"
        "assert request['session_id'] == 'profile:default'\n"
        "assert request['query'] == 'Can we resume Smith PIP demand timing?'\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'packet': {'id': 'inject_1'},\n"
        "  'contextBlock': '<memory-context>Smith PIP memory</memory-context>'\n"
        "}))\n"
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND",
        f"{sys.executable} {bridge_script}",
    )

    db = SessionDB(db_path=tmp_path / "state.db")
    timeline = UnifiedTimeline(db=db, profile_id="default")
    timeline.record_inbound(
        source=_source(),
        content="Can we resume Smith PIP demand timing?",
        message_id="m1",
    )

    store = SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())
    store._db = db

    messages = store.load_agent_context(source=_source())

    assert messages[0] == {
        "role": "system",
        "content": "<memory-context>Smith PIP memory</memory-context>",
    }
    assert messages[1:] == [
        {"role": "user", "content": "Can we resume Smith PIP demand timing?"}
    ]
    db.close()


def test_load_agent_context_omits_conversational_memory_when_command_returns_no_context(
    tmp_path,
    monkeypatch,
):
    bridge_script = tmp_path / "inject.py"
    bridge_script.write_text(
        "import json\n"
        "print(json.dumps({'ok': True, 'packet': None, 'contextBlock': None}))\n"
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND",
        f"{sys.executable} {bridge_script}",
    )

    db = SessionDB(db_path=tmp_path / "state.db")
    timeline = UnifiedTimeline(db=db, profile_id="default")
    timeline.record_inbound(source=_source(), content="No matching memory", message_id="m1")

    store = SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())
    store._db = db

    assert store.load_agent_context(source=_source()) == [
        {"role": "user", "content": "No matching memory"}
    ]
    db.close()
