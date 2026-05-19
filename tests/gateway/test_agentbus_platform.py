import asyncio
import json

import pytest

from gateway.config import Platform, PlatformConfig
from plugins.platforms.agentbus.adapter import AgentBusAdapter, AgentBusStore, _standalone_send
from tools.send_message_tool import _parse_target_ref


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes" / "profiles" / "coder"
    home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("AGENTBUS_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    return home


def test_agentbus_platform_is_dynamic_plugin_platform():
    assert Platform("agentbus").value == "agentbus"


def test_send_message_target_parser_treats_agentbus_profile_as_explicit():
    chat_id, thread_id, explicit = _parse_target_ref("agentbus", "paralegal")
    assert chat_id == "paralegal"
    assert thread_id is None
    assert explicit is True


def test_agentbus_send_enqueues_to_target_profile(hermes_home, tmp_path):
    db_path = tmp_path / "agentbus.sqlite"
    adapter = AgentBusAdapter(PlatformConfig(enabled=True, extra={"profile": "coder", "db_path": str(db_path)}))

    result = asyncio.run(adapter.send("paralegal", "hello from coder"))

    assert result.success is True
    store = AgentBusStore(db_path)
    rows = store.claim_pending("paralegal")
    assert len(rows) == 1
    assert rows[0]["id"] == result.message_id
    assert rows[0]["to_profile"] == "paralegal"
    assert rows[0]["from_profile"] == "coder"
    assert rows[0]["text"] == "hello from coder"


def test_agentbus_emit_row_creates_normal_message_event(hermes_home, tmp_path):
    db_path = tmp_path / "agentbus.sqlite"
    store = AgentBusStore(db_path)
    msg_id = store.enqueue(to_profile="paralegal", from_profile="coder", text="review this")
    row = store.claim_pending("paralegal")[0]

    adapter = AgentBusAdapter(PlatformConfig(enabled=True, extra={"profile": "paralegal", "db_path": str(db_path)}))
    seen = []

    async def capture(event):
        seen.append(event)

    adapter.handle_message = capture
    asyncio.run(adapter._emit_row(row))

    assert len(seen) == 1
    event = seen[0]
    assert event.text == "review this"
    assert event.internal is True
    assert event.message_id == msg_id
    assert event.source.platform.value == "agentbus"
    assert event.source.chat_id == "coder"
    assert event.source.user_name == "coder"

    assert store.claim_pending("paralegal") == []


def test_agentbus_standalone_send_uses_shared_store(hermes_home, monkeypatch):
    monkeypatch.setenv("AGENTBUS_PROFILE", "coder")
    cfg = PlatformConfig(enabled=True, extra={})

    result = asyncio.run(_standalone_send(cfg, "paralegal", "standalone hello"))

    assert result["success"] is True
    store = AgentBusStore()
    rows = store.claim_pending("paralegal")
    assert len(rows) == 1
    assert rows[0]["id"] == result["message_id"]
    assert rows[0]["from_profile"] == "coder"
    assert rows[0]["text"] == "standalone hello"


def test_agentbus_allows_multi_turn_replies_by_default(hermes_home, tmp_path):
    db_path = tmp_path / "agentbus.sqlite"
    coder = AgentBusAdapter(PlatformConfig(enabled=True, extra={"profile": "coder", "db_path": str(db_path)}))
    paralegal = AgentBusAdapter(PlatformConfig(enabled=True, extra={"profile": "paralegal", "db_path": str(db_path)}))

    first = asyncio.run(coder.send("paralegal", "question"))
    assert first.success is True
    reply = asyncio.run(paralegal.send("coder", "answer", reply_to=first.message_id))
    assert reply.success is True
    followup = asyncio.run(coder.send("paralegal", "thanks", reply_to=reply.message_id))
    assert followup.success is True
    assert followup.message_id != reply.message_id

    store = AgentBusStore(db_path)
    paralegal_rows = store.claim_pending("paralegal", limit=10)
    coder_rows = store.claim_pending("coder", limit=10)
    assert [row["text"] for row in paralegal_rows] == ["question", "thanks"]
    assert [row["text"] for row in coder_rows] == ["answer"]
    assert json.loads(coder_rows[0]["metadata_json"])["hops"] == 1
    assert json.loads(paralegal_rows[1]["metadata_json"])["hops"] == 2
    assert json.loads(paralegal_rows[1]["metadata_json"])["max_hops"] == 8


def test_agentbus_suppresses_after_configured_hop_budget(hermes_home, tmp_path):
    db_path = tmp_path / "agentbus.sqlite"
    coder = AgentBusAdapter(
        PlatformConfig(enabled=True, extra={"profile": "coder", "db_path": str(db_path), "max_hops": 2})
    )
    paralegal = AgentBusAdapter(
        PlatformConfig(enabled=True, extra={"profile": "paralegal", "db_path": str(db_path), "max_hops": 2})
    )

    first = asyncio.run(coder.send("paralegal", "question"))
    reply = asyncio.run(paralegal.send("coder", "answer", reply_to=first.message_id))
    followup = asyncio.run(coder.send("paralegal", "thanks", reply_to=reply.message_id))
    suppressed = asyncio.run(paralegal.send("coder", "done", reply_to=followup.message_id))

    assert suppressed.success is True
    assert suppressed.message_id == followup.message_id

    store = AgentBusStore(db_path)
    paralegal_rows = store.claim_pending("paralegal", limit=10)
    coder_rows = store.claim_pending("coder", limit=10)
    assert [row["text"] for row in paralegal_rows] == ["question", "thanks"]
    assert [row["text"] for row in coder_rows] == ["answer"]
