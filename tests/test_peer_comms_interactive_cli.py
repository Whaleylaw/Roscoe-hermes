from __future__ import annotations

import queue
import time

from peer_comms.store import PeerCommsStore


def _bare_cli():
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli.session_id = "cli-session"
    cli.model = "test-model"
    cli._pending_input = queue.Queue()
    cli._should_exit = False
    cli._peer_watch_thread = None
    cli._peer_watch_stop = None
    cli._peer_watch_config = {}
    return cli


def test_interactive_peer_watch_claims_and_queues_inbound_message(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    cli = _bare_cli()
    store = PeerCommsStore()
    store.register_agent(name="builder", agent_id="builder", project="demo")

    cli._start_peer_watch(
        agent_id="tester",
        name="tester",
        project="demo",
        team_id="team-demo",
        poll_seconds=0.1,
        ttl_seconds=600,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not store.resolve_agent("tester", project="demo"):
            time.sleep(0.05)
        sent = store.send_message(sender_id="builder", target="tester", project="demo", prompt="Run the focused tests.")
        payload = cli._pending_input.get(timeout=5)
    finally:
        cli._stop_peer_watch(quiet=True)

    assert "_hermes_peer_message" in payload
    queued_msg = payload["_hermes_peer_message"]
    assert queued_msg["msg_id"] == sent["msg_id"]
    assert queued_msg["status"] == "in_progress"
    assert "Run the focused tests" in cli._format_peer_message_for_turn(queued_msg)


def test_interactive_peer_reply_marks_message_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    cli = _bare_cli()
    store = PeerCommsStore()
    store.register_agent(name="builder", agent_id="builder", project="demo")
    store.register_agent(name="tester", agent_id="tester", project="demo")
    msg = store.send_message(sender_id="builder", target="tester", project="demo", prompt="Please review this.")
    claimed = store.claim_message(msg_id=msg["msg_id"], agent_id="tester")

    cli._reply_to_peer_message(claimed, "Reviewed and approved.")

    completed = store.get_message(msg["msg_id"], include_prompt=True, include_response=True)
    assert completed["status"] == "completed"
    assert completed["response"] == "Reviewed and approved."


def test_interactive_peer_watch_stop_marks_agent_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PEER_COMMS_DIR", str(tmp_path / "hub"))
    cli = _bare_cli()
    cli._start_peer_watch(agent_id="tester", name="tester", project="demo", poll_seconds=0.1, ttl_seconds=600)
    time.sleep(0.2)

    cli._stop_peer_watch(quiet=True)

    agent = PeerCommsStore().get_agent("tester")
    assert agent["status"] == "offline"
