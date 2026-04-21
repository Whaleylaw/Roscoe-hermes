"""Smoke test: Telegram-sourced messages land in unified_timeline."""
from pathlib import Path

from gateway.config import Platform
from gateway.session import SessionSource
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB


def test_telegram_inbound_routes_through_unified_timeline(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")

    # Simulate the call the telegram adapter will make after this task.
    src = SessionSource(
        platform=Platform.TELEGRAM, chat_id="tg-42", chat_type="dm",
        user_id="user-7", user_name="alice",
    )
    handle = ut.record_inbound(source=src, content="ping", message_id="tg-msg-1")
    ut.record_outbound(turn=handle, content="pong")

    rows = db.get_timeline_messages(profile_id="default")
    assert [r["platform"] for r in rows] == ["telegram", "telegram"]
    assert [r["direction"] for r in rows] == ["inbound", "outbound"]
    db.close()
