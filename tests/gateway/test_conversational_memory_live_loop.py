import json
from pathlib import Path

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB
from tools.conversational_memory_tool import conversational_memory_resume


MEMORY_SYSTEM_ROOT = Path(
    "/Users/aaronwhaley/Github/conversational-memory-system"
)


def _source():
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat-1",
        chat_type="dm",
        thread_id="thread-1",
        user_id="u1",
        user_name="Alice",
    )


def _npm_memory_command(script: str, db_path: Path) -> str:
    return (
        f"npm --silent --prefix {MEMORY_SYSTEM_ROOT} "
        f"run {script} -- --db {db_path}"
    )


@pytest.mark.skipif(
    not (MEMORY_SYSTEM_ROOT / "package.json").exists(),
    reason="standalone conversational-memory-system repo is not available",
)
def test_roscoe_live_loop_ingests_injects_and_resumes_standalone_memory(
    tmp_path,
    monkeypatch,
):
    memory_db = tmp_path / "memory.sqlite"
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_COMMAND",
        _npm_memory_command("hermes:ingest", memory_db),
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED", "1")
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND",
        _npm_memory_command("hermes:inject", memory_db),
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND",
        _npm_memory_command("hermes:resume", memory_db),
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_TIMEOUT", "10")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_TIMEOUT", "10")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_TIMEOUT", "10")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_MAX_TOKENS", "80")

    db = SessionDB(db_path=tmp_path / "state.db")
    timeline = UnifiedTimeline(db=db, profile_id="default")
    first = timeline.record_inbound(
        source=_source(),
        content="Let's talk about Smith PIP.",
        message_id="m1",
        ts=1714826400.0,
    )
    timeline.record_outbound(
        turn=first,
        content="The Smith PIP demand deadline is June 1.",
        message_id="m2",
        ts=1714826410.0,
    )
    timeline.record_inbound(
        source=_source(),
        content="/new",
        message_id="m3",
        ts=1714826700.0,
    )
    timeline.record_inbound(
        source=_source(),
        content="Can we resume Smith PIP demand timing?",
        message_id="m4",
        ts=1714827600.0,
    )

    store = SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())
    store._db = db

    messages = store.load_agent_context(source=_source())

    assert messages[0]["role"] == "system"
    assert "<memory-context>" in messages[0]["content"]
    assert "Smith PIP (2 turns, seq 1-2)" in messages[0]["content"]
    assert "The Smith PIP demand deadline is June 1." in messages[0]["content"]

    resumed = json.loads(
        conversational_memory_resume(summary_id="summary_profile:default_1_2")
    )

    assert resumed["success"] is True
    assert resumed["turn_count"] == 2
    assert resumed["context_block"].startswith("<memory-resume>")
    assert [turn["content"] for turn in resumed["turns"]] == [
        "Let's talk about Smith PIP.",
        "The Smith PIP demand deadline is June 1.",
    ]
    db.close()
