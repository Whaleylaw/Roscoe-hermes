from pathlib import Path
from unittest.mock import patch

from gateway.config import Platform
from gateway.session import SessionSource
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB


def _source(platform=Platform.TELEGRAM, chat_id="tg1", user_name="alice"):
    return SessionSource(
        platform=platform, chat_id=chat_id, chat_type="dm",
        user_id="u1", user_name=user_name,
    )


def test_record_inbound_writes_row_and_returns_handle(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    handle = ut.record_inbound(
        source=_source(), content="hello", message_id="m1",
    )
    assert handle.profile_id == "default"
    assert handle.platform == "telegram"
    assert handle.source_chat_id == "tg1"
    assert handle.seq == 1
    rows = db.get_timeline_messages(profile_id="default")
    assert len(rows) == 1
    assert rows[0]["direction"] == "inbound"
    assert rows[0]["content"] == "hello"
    assert rows[0]["author"] == "alice"
    db.close()


def test_record_outbound_writes_row_tied_to_handle(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    handle = ut.record_inbound(
        source=_source(), content="hello", message_id="m1",
    )
    ut.record_outbound(turn=handle, content="hi")
    rows = db.get_timeline_messages(profile_id="default")
    assert [r["direction"] for r in rows] == ["inbound", "outbound"]
    assert [r["platform"] for r in rows] == ["telegram", "telegram"]
    assert [r["source_chat_id"] for r in rows] == ["tg1", "tg1"]
    assert rows[1]["author"] == "agent"
    db.close()


def test_profile_lock_serializes_records(tmp_path: Path):
    """Two record_inbound calls assign strictly increasing seq."""
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    h1 = ut.record_inbound(source=_source(chat_id="a"), content="1", message_id="ma")
    h2 = ut.record_inbound(source=_source(chat_id="b"), content="2", message_id="mb")
    assert h2.seq == h1.seq + 1
    db.close()


def test_from_active_profile_uses_profile_name(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    db = SessionDB(db_path=tmp_path / "state.db")
    with patch("gateway.unified_timeline.get_active_profile_name", return_value="coder"):
        ut = UnifiedTimeline.for_active_profile(db=db)
    assert ut.profile_id == "coder"
    db.close()
