"""
Regression test for the bug this design fixes: a conversation started
in Telegram is invisible when the user switches to Open WebUI.

The test drives the two record paths at the service level (below the
adapter plumbing) to assert the unified timeline yields a single
cross-channel conversation for the same profile.
"""
from pathlib import Path

from gateway.config import Platform, GatewayConfig
from gateway.session import SessionSource, SessionStore
from gateway.unified_timeline import UnifiedTimeline
from hermes_state import SessionDB


def test_telegram_turn_visible_in_open_webui_context(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")

    # 1. User messages agent on Telegram, agent replies.
    tg = SessionSource(
        platform=Platform.TELEGRAM, chat_id="tg-1", chat_type="dm",
        user_id="u1", user_name="alice",
    )
    h1 = ut.record_inbound(source=tg, content="my dog's name is Fig", message_id="t1")
    ut.record_outbound(turn=h1, content="Noted — Fig.")

    # 2. Same user opens Open WebUI and continues the conversation.
    web = SessionSource(
        platform=Platform.API_SERVER, chat_id="openai-default", chat_type="dm",
        user_id="u1", user_name=None,
    )
    h2 = ut.record_inbound(source=web, content="what's my dog's name?", message_id=None)

    # 3. The profile's timeline context, loaded from Open WebUI's entry
    # point, must contain the Telegram exchange.
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())
    store._db = db
    history = store.load_timeline_conversation(profile_id="default")
    contents = [m["content"] for m in history]
    assert "my dog's name is Fig" in contents
    assert "Noted — Fig." in contents
    assert "what's my dog's name?" in contents
    # Order is preserved: Telegram turn precedes the Open WebUI turn.
    assert contents.index("my dog's name is Fig") < contents.index("what's my dog's name?")
    db.close()


def test_interleaved_three_platforms_preserve_order(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    def src(p):
        return SessionSource(platform=p, chat_id=f"{p.value}-1",
                             chat_type="dm", user_id="u", user_name="u")
    ut.record_inbound(source=src(Platform.TELEGRAM), content="A", message_id="a")
    ut.record_inbound(source=src(Platform.DISCORD),  content="B", message_id="b")
    ut.record_inbound(source=src(Platform.API_SERVER), content="C", message_id="c")
    rows = db.get_timeline_messages(profile_id="default")
    assert [r["content"] for r in rows] == ["A", "B", "C"]
    db.close()
