import json
import sys

from gateway.config import Platform
from gateway.conversational_memory import emit_conversational_memory_compression_boundary
from gateway.session import SessionSource
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB


def _source():
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat-1",
        chat_type="dm",
        thread_id="thread-1",
        user_id="u1",
        user_name="Alice",
    )


def test_unified_timeline_emits_rows_to_optional_conversational_memory_bridge(
    tmp_path,
    monkeypatch,
):
    sink = tmp_path / "rows.jsonl"
    bridge_script = tmp_path / "bridge.py"
    bridge_script.write_text(
        "import pathlib, sys\n"
        f"path = pathlib.Path({str(sink)!r})\n"
        "path.write_text(path.read_text() + sys.stdin.read() + '\\n' if path.exists() else sys.stdin.read() + '\\n')\n"
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_COMMAND",
        f"{sys.executable} {bridge_script}",
    )

    db = SessionDB(db_path=tmp_path / "state.db")
    timeline = UnifiedTimeline(db=db, profile_id="default")

    handle = timeline.record_inbound(
        source=_source(),
        content="Let's talk about Smith PIP.",
        message_id="m1",
        ts=1714826400.0,
    )
    timeline.record_outbound(
        turn=handle,
        content="The Smith PIP deadline is June 1.",
        message_id="m2",
        ts=1714826410.0,
    )

    emitted = [json.loads(line) for line in sink.read_text().splitlines()]
    assert [row["role"] for row in emitted] == ["user", "assistant"]
    assert emitted[0] == {
        "id": "default:1",
        "profile_id": "default",
        "session_id": "profile:default",
        "sequence": 1,
        "role": "user",
        "content": "Let's talk about Smith PIP.",
        "created_at": "2024-05-04T12:40:00.000Z",
        "channel": "telegram",
        "metadata_json": json.dumps(
            {
                "direction": "inbound",
                "platform": "telegram",
                "source_chat_id": "chat-1",
                "source_thread_id": "thread-1",
                "author": "Alice",
                "message_id": "m1",
            },
            sort_keys=True,
        ),
    }
    assert emitted[1]["id"] == "default:2"
    assert emitted[1]["sequence"] == 2
    assert emitted[1]["role"] == "assistant"
    assert emitted[1]["content"] == "The Smith PIP deadline is June 1."
    db.close()


def test_conversational_memory_compression_boundary_emits_synthetic_control_row(
    tmp_path,
    monkeypatch,
):
    sink = tmp_path / "rows.jsonl"
    bridge_script = tmp_path / "bridge.py"
    bridge_script.write_text(
        "import pathlib, sys\n"
        f"path = pathlib.Path({str(sink)!r})\n"
        "path.write_text(path.read_text() + sys.stdin.read() + '\\n' if path.exists() else sys.stdin.read() + '\\n')\n"
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_COMMAND",
        f"{sys.executable} {bridge_script}",
    )

    assert emit_conversational_memory_compression_boundary(
        profile_id="coder",
        seq=42,
        ts=1714826420.0,
        reason="gateway_hygiene",
    ) is True

    emitted = [json.loads(line) for line in sink.read_text().splitlines()]
    assert emitted == [{
        "id": "coder:42",
        "profile_id": "coder",
        "session_id": "profile:coder",
        "sequence": 42,
        "role": "system",
        "content": "/compress",
        "created_at": "2024-05-04T12:40:20.000Z",
        "channel": "gateway",
        "metadata_json": json.dumps(
            {
                "direction": "system",
                "platform": "gateway",
                "source_chat_id": None,
                "source_thread_id": None,
                "author": "native-compression",
                "message_id": "memory-boundary:gateway_hygiene:42",
            },
            sort_keys=True,
        ),
    }]
