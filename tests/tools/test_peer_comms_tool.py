from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from peer_comms.store import PeerCommsStore


def test_register_list_send_inbox_reply_await(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    store = PeerCommsStore()

    builder = store.register_agent(name="builder", agent_id="builder-1", role="implementation", project="demo")
    tester = store.register_agent(name="tester", agent_id="tester-1", role="testing", project="demo")

    assert builder["status"] == "online"
    assert tester["project"] == "demo"
    assert [a["id"] for a in store.list_agents(project="demo")] == ["builder-1", "tester-1"]

    msg = store.send_message(
        sender_id="builder-1",
        target="tester-1",
        project="demo",
        subject="Run tests",
        prompt="Please run pytest and report exact failures.",
    )
    assert msg["status"] == "queued"
    assert msg["target_id"] == "tester-1"

    inbox = store.list_inbox(agent_id="tester-1", mark_seen=True)
    assert len(inbox) == 1
    assert inbox[0]["prompt"].startswith("Please run")
    assert inbox[0]["status"] == "seen"

    claimed = store.claim_message(msg_id=msg["msg_id"], agent_id="tester-1")
    assert claimed["status"] == "in_progress"

    completed = store.reply_message(msg_id=msg["msg_id"], agent_id="tester-1", response="pytest passed")
    assert completed["status"] == "completed"
    assert completed["response"] == "pytest passed"

    awaited = store.await_message(msg["msg_id"], timeout_seconds=1)
    assert awaited["status"] == "completed"
    assert awaited["response"] == "pytest passed"


def test_await_times_out_then_later_receives_response(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    store = PeerCommsStore()
    store.register_agent(name="builder", agent_id="builder", project="demo")
    store.register_agent(name="tester", agent_id="tester", project="demo")
    msg = store.send_message(sender_id="builder", target="tester", project="demo", prompt="slow task")

    timed_out = store.await_message(msg["msg_id"], timeout_seconds=1, poll_interval=0.1)
    assert timed_out["await_timed_out"] is True
    assert timed_out["status"] == "queued"

    store.reply_message(msg_id=msg["msg_id"], agent_id="tester", response="done")
    assert store.await_message(msg["msg_id"], timeout_seconds=1)["response"] == "done"


def test_target_name_resolution_is_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    store = PeerCommsStore()
    store.register_agent(name="tester", agent_id="tester-a", project="alpha")
    store.register_agent(name="tester", agent_id="tester-b", project="beta")
    store.register_agent(name="builder", agent_id="builder-a", project="alpha")

    msg = store.send_message(sender_id="builder-a", target="tester", project="alpha", prompt="alpha only")
    assert msg["target_id"] == "tester-a"

    with pytest.raises(ValueError, match="ambiguous"):
        store.send_message(sender_id="builder-a", target="tester", prompt="ambiguous")


def test_tool_wrappers_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    monkeypatch.setenv("HERMES_PEER_AGENT_ID", "builder")

    from tools import peer_comms_tool as tool

    reg_builder = json.loads(tool.peer_register(name="builder", agent_id="builder", project="demo"))
    reg_tester = json.loads(tool.peer_register(name="tester", agent_id="tester", project="demo"))
    assert reg_builder["success"] is True
    assert reg_tester["success"] is True

    sent = json.loads(tool.peer_send(target="tester", project="demo", prompt="Please test this."))
    assert sent["success"] is True
    msg_id = sent["message"]["msg_id"]

    inbox = json.loads(tool.peer_inbox(agent_id="tester", mark_seen=True))
    assert inbox["messages"][0]["msg_id"] == msg_id

    reply = json.loads(tool.peer_reply(agent_id="tester", msg_id=msg_id, response="Looks good."))
    assert reply["message"]["status"] == "completed"

    got = json.loads(tool.peer_get(msg_id=msg_id))
    assert got["message"]["response"] == "Looks good."


def test_peer_team_session_is_temporary_and_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    store = PeerCommsStore()

    started = store.start_team(
        name="coder-paralegal",
        project="abby-case",
        coordinator_id="coder",
        agents=[
            {"name": "coder", "agent_id": "coder", "role": "implementation"},
            {"name": "paralegal", "agent_id": "paralegal", "role": "legal records review"},
        ],
        ttl_seconds=3600,
    )
    team_id = started["team"]["team_id"]
    assert started["team"]["status"] == "active"
    assert started["team"]["agent_ids"] == ["coder", "paralegal"]
    assert store.get_agent("paralegal")["metadata"]["team_id"] == team_id

    sent = store.send_message(sender_id="coder", target="paralegal", project="abby-case", prompt="Review these records.")
    assert sent["target_id"] == "paralegal"
    assert store.list_inbox(agent_id="paralegal", project="abby-case")[0]["msg_id"] == sent["msg_id"]

    stopped = store.stop_team(team_id=team_id, reason="work complete")
    assert stopped["status"] == "stopped"
    assert stopped["metadata"]["stop_reason"] == "work complete"
    assert store.get_agent("coder")["status"] == "offline"
    assert store.get_agent("paralegal")["status"] == "offline"


def test_peer_team_tool_wrappers(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))

    from tools import peer_comms_tool as tool

    started = json.loads(tool.peer_team_start(
        name="builder-tester",
        project="demo",
        agents=[
            {"name": "builder", "agent_id": "builder", "role": "build"},
            {"name": "tester", "agent_id": "tester", "role": "test"},
        ],
    ))
    assert started["success"] is True
    team_id = started["team"]["team_id"]

    status = json.loads(tool.peer_team_status(team_id=team_id))
    assert status["team"]["status"] == "active"
    assert [a["id"] for a in status["agents"]] == ["builder", "tester"]

    stopped = json.loads(tool.peer_team_stop(team_id=team_id, reason="done"))
    assert stopped["team"]["status"] == "stopped"


@pytest.mark.live_system_guard_bypass
def test_peer_team_runner_auto_claims_and_replies(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    from peer_comms.runner import start_runner_process, stop_runner

    store = PeerCommsStore()
    started = store.start_team(
        name="builder-tester",
        project="demo",
        agents=[
            {"name": "builder", "agent_id": "builder"},
            {"name": "tester", "agent_id": "tester"},
        ],
    )
    team_id = started["team"]["team_id"]
    command = f"{sys.executable} -c \"import sys; print('auto:' + sys.argv[1])\" {{prompt}}"
    runner = start_runner_process(
        agent_id="tester",
        project="demo",
        team_id=team_id,
        command=command,
        poll_seconds=0.1,
        command_timeout_seconds=5,
    )
    assert runner["runner"]["pid"]
    try:
        msg = store.send_message(sender_id="builder", target="tester", project="demo", prompt="run focused tests")
        awaited = store.await_message(msg["msg_id"], timeout_seconds=10, poll_interval=0.1)
        assert awaited["status"] == "completed"
        assert awaited["response"] == "auto:run focused tests"
    finally:
        stopped = stop_runner(team_id=team_id, agent_id="tester")
        assert stopped["stopped"]


@pytest.mark.live_system_guard_bypass
def test_peer_team_launch_starts_runners_and_sends_initial_task(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))

    from peer_comms.runner import stop_runner
    from tools import peer_comms_tool as tool

    command = f"{sys.executable} -c \"import sys; print('launched:' + sys.argv[1])\" {{prompt}}"
    launched = json.loads(tool.peer_team_launch(
        name="chat-started-team",
        project="demo",
        sender_id="user",
        initial_target="paralegal",
        initial_task="summarize records",
        await_initial_response=True,
        await_timeout_seconds=10,
        agents=[
            {"name": "Coder", "agent_id": "coder", "role": "coordinator", "command": command},
            {"name": "Paralegal", "agent_id": "paralegal", "role": "records review", "command": command},
        ],
        poll_seconds=0.1,
        command_timeout_seconds=5,
    ))
    assert launched["success"] is True
    team_id = launched["team"]["team_id"]
    try:
        assert {r["agent_id"] for r in launched["runners"]} == {"coder", "paralegal"}
        assert launched["initial_message"]["target_id"] == "paralegal"
        assert launched["awaited_initial_response"]["status"] == "completed"
        assert launched["awaited_initial_response"]["response"] == "launched:summarize records"
    finally:
        stop_runner(team_id=team_id)


def test_tool_schemas_are_discoverable():
    from tools.registry import registry
    import tools.peer_comms_tool  # noqa: F401

    tool_names = registry.get_tool_to_toolset_map()
    assert tool_names["peer_register"] == "peer_comms"
    assert tool_names["peer_send"] == "peer_comms"
    assert tool_names["peer_inbox"] == "peer_comms"
    assert tool_names["peer_reply"] == "peer_comms"
    assert tool_names["peer_team_start"] == "peer_comms"
    assert tool_names["peer_team_status"] == "peer_comms"
    assert tool_names["peer_team_launch"] == "peer_comms"
    assert tool_names["peer_team_stop"] == "peer_comms"
    assert tool_names["peer_runner_start"] == "peer_comms"
    assert tool_names["peer_runner_status"] == "peer_comms"
    assert tool_names["peer_runner_stop"] == "peer_comms"
