from pathlib import Path
from unittest.mock import patch

from gateway.config import GatewayConfig, Platform, UnifiedTimelineConfig
from gateway.session import SessionSource, SessionStore
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


def test_load_timeline_conversation_returns_openai_shape(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    ut.record_inbound(source=_source(), content="hi there", message_id="m1")
    handle = ut.record_inbound(source=_source(), content="how are you", message_id="m2")
    ut.record_outbound(turn=handle, content="I am well")

    store = SessionStore(
        sessions_dir=tmp_path / "sessions",
        config=GatewayConfig(),
    )
    # Inject the same db the timeline wrote to, matching production wiring.
    store._db = db
    msgs = store.load_timeline_conversation(profile_id="default")
    assert msgs == [
        {"role": "user", "content": "hi there"},
        {"role": "user", "content": "how are you"},
        {"role": "assistant", "content": "I am well"},
    ]
    db.close()


def test_load_agent_context_routes_through_timeline_when_enabled(tmp_path, monkeypatch):
    """With unified_timeline enabled, load_agent_context must pull the
    profile's cross-channel timeline rather than the per-session store."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    h = ut.record_inbound(source=_source(), content="unified-content", message_id="m1")
    ut.record_outbound(turn=h, content="agent-reply")

    cfg = GatewayConfig()
    assert cfg.unified_timeline.enabled is True  # default
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=cfg)
    store._db = db

    msgs = store.load_agent_context(source=_source())
    contents = [m["content"] for m in msgs]
    assert "unified-content" in contents
    assert "agent-reply" in contents
    db.close()


def test_load_agent_context_uses_legacy_path_when_flag_disabled(tmp_path, monkeypatch):
    """With unified_timeline disabled, load_agent_context falls back to
    the per-session transcript and ignores timeline rows."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    ut.record_inbound(source=_source(), content="ignored", message_id="m1")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    cfg = GatewayConfig(unified_timeline=UnifiedTimelineConfig(enabled=False))
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=sessions_dir, config=cfg)
    store._db = None
    store._loaded = True

    # Seed a per-session transcript so the legacy reader returns
    # something distinguishable from the timeline row.
    store.append_to_transcript(
        "legacy-session-id",
        {"role": "user", "content": "legacy-content"},
    )

    from datetime import datetime as _dt
    from gateway.session import SessionEntry
    entry = SessionEntry(
        session_key="k",
        session_id="legacy-session-id",
        created_at=_dt.now(),
        updated_at=_dt.now(),
    )
    msgs = store.load_agent_context(source=_source(), session_entry=entry)
    contents = [m["content"] for m in msgs]
    assert "legacy-content" in contents
    assert "ignored" not in contents
    db.close()


def test_load_transcript_is_per_session_regardless_of_flag(tmp_path, monkeypatch):
    """Regression for #Critical-1: load_transcript must ALWAYS return
    the per-session transcript so mutation commands (/retry, /undo,
    /compress, /branch) can truncate and rewrite a specific session."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    ut.record_inbound(source=_source(), content="cross-channel-content", message_id="m1")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    cfg = GatewayConfig()  # unified_timeline default-on
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=sessions_dir, config=cfg)
    store._db = None
    store._loaded = True
    store.append_to_transcript(
        "legacy-session-id",
        {"role": "user", "content": "per-session-content"},
    )

    msgs = store.load_transcript("legacy-session-id")
    contents = [m["content"] for m in msgs]
    assert "per-session-content" in contents
    # The timeline row must not bleed into a per-session read — otherwise
    # /retry would rewrite a phantom session.
    assert "cross-channel-content" not in contents
    db.close()


def test_truncate_timeline_last_exchange_drops_trailing_rows(tmp_path, monkeypatch):
    """Dropping the last exchange must remove the last user message +
    every row that followed it (its assistant reply, cross-channel
    intrusions, etc.)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    h1 = ut.record_inbound(source=_source(), content="turn A", message_id="m1")
    ut.record_outbound(turn=h1, content="reply A")
    h2 = ut.record_inbound(source=_source(), content="turn B", message_id="m2")
    ut.record_outbound(turn=h2, content="reply B")

    cfg = GatewayConfig()
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=cfg)
    store._db = db

    removed = store.truncate_timeline_last_exchange(profile_id="default")
    assert removed == 2  # turn B + reply B

    rows = db.get_timeline_messages(profile_id="default")
    contents = [r["content"] for r in rows]
    assert contents == ["turn A", "reply A"]
    db.close()


def test_retry_truncates_cross_channel_timeline_and_per_session_transcript(
    tmp_path, monkeypatch,
):
    """Regression for Critical #1 fallout:

    Scenario: user sends turn A on Telegram, agent replies; user
    sends turn B on Telegram; then user issues /retry.  After /retry,
    both the per-session transcript *and* the unified timeline must
    reflect only turn A + turn A's reply — otherwise the next turn's
    cross-channel context resurrects turn B.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    cfg = GatewayConfig()  # unified_timeline default-on
    db = SessionDB(db_path=tmp_path / "state.db")
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=tmp_path, config=cfg)
    store._db = db
    store._loaded = True

    session_id = "tg-session"
    # Seed per-session transcript: turn A, reply A, turn B, reply B.
    for msg in [
        {"role": "user", "content": "turn A"},
        {"role": "assistant", "content": "reply A"},
        {"role": "user", "content": "turn B"},
        {"role": "assistant", "content": "reply B"},
    ]:
        store.append_to_transcript(session_id, msg)

    # Seed unified timeline with the same pair of exchanges.
    ut = UnifiedTimeline(db=db, profile_id="default")
    src = _source()
    h1 = ut.record_inbound(source=src, content="turn A", message_id="m1")
    ut.record_outbound(turn=h1, content="reply A")
    h2 = ut.record_inbound(source=src, content="turn B", message_id="m2")
    ut.record_outbound(turn=h2, content="reply B")
    assert len(db.get_timeline_messages(profile_id="default")) == 4

    gw = GatewayRunner.__new__(GatewayRunner)
    gw.config = cfg
    gw.session_store = store

    session_entry = MagicMock(session_id=session_id)
    session_entry.last_prompt_tokens = 99
    gw.session_store.get_or_create_session = MagicMock(return_value=session_entry)

    async def fake_handle_message(event):
        assert event.text == "turn B"
        # Re-do the pair so the session looks just like it did before
        # the retry — per-session + timeline should both reflect A and B.
        store.append_to_transcript(session_id, {"role": "user", "content": event.text})
        store.append_to_transcript(session_id, {"role": "assistant", "content": "reply B'"})
        return "reply B'"

    gw._handle_message = AsyncMock(side_effect=fake_handle_message)

    asyncio.run(
        gw._handle_retry_command(
            MessageEvent(text="/retry", message_type=MessageType.TEXT, source=MagicMock()),
        )
    )

    # After /retry: next-turn agent context (load_agent_context) must
    # include turn A + reply A + the replayed turn B + new reply — NOT
    # the stale pre-retry "reply B".
    rows = db.get_timeline_messages(profile_id="default")
    contents = [r["content"] for r in rows]
    # Truncation removed the stale last exchange...
    assert "reply B" not in contents, (
        "unified timeline still contains pre-retry assistant reply — "
        "truncate_timeline_last_exchange did not run"
    )
    # ...and turn A survived.
    assert contents[:2] == ["turn A", "reply A"]

    # Per-session store mirrors the same truncation.
    per_session = store.load_transcript(session_id)
    per_session_contents = [m["content"] for m in per_session]
    assert per_session_contents[-1] == "reply B'"
    assert "reply B" not in per_session_contents
    db.close()
