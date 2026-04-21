import time
from pathlib import Path
from hermes_state import SessionDB


def test_unified_timeline_table_created(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    cols = {
        row[1]
        for row in db._conn.execute("PRAGMA table_info(unified_timeline)")
    }
    assert cols == {
        "profile_id",
        "seq",
        "ts",
        "direction",
        "platform",
        "source_chat_id",
        "source_thread_id",
        "author",
        "content",
        "message_id",
        "salience",
    }
    db.close()


def test_unified_timeline_indexes_created(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    indexes = {
        row[0]
        for row in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='unified_timeline'"
        )
    }
    assert "idx_unified_timeline_lookup" in indexes
    db.close()


def test_unified_timeline_fts_created(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    tables = {
        row[0]
        for row in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='unified_timeline_fts'"
        )
    }
    assert "unified_timeline_fts" in tables
    db.close()


def test_schema_version_is_7(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    row = db._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row[0] == 7
    db.close()


def test_append_timeline_assigns_monotonic_seq(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ts1 = time.time()
    s1 = db.append_timeline_message(
        profile_id="default", direction="inbound", platform="telegram",
        source_chat_id="tg123", source_thread_id=None,
        author="alice", content="hello", message_id="m1", ts=ts1,
    )
    s2 = db.append_timeline_message(
        profile_id="default", direction="outbound", platform="telegram",
        source_chat_id="tg123", source_thread_id=None,
        author="agent", content="hi", message_id=None, ts=ts1 + 0.1,
    )
    assert s2 == s1 + 1
    db.close()


def test_append_timeline_profile_scoping(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.append_timeline_message(
        profile_id="default", direction="inbound", platform="telegram",
        source_chat_id="tg1", source_thread_id=None,
        author="u", content="A", message_id="m1", ts=time.time(),
    )
    db.append_timeline_message(
        profile_id="coder", direction="inbound", platform="telegram",
        source_chat_id="tg1", source_thread_id=None,
        author="u", content="B", message_id="m2", ts=time.time(),
    )
    default_msgs = db.get_timeline_messages(profile_id="default")
    coder_msgs = db.get_timeline_messages(profile_id="coder")
    assert [m["content"] for m in default_msgs] == ["A"]
    assert [m["content"] for m in coder_msgs] == ["B"]
    db.close()


def test_get_timeline_messages_returns_in_seq_order(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ts = time.time()
    for i, text in enumerate(["first", "second", "third"]):
        db.append_timeline_message(
            profile_id="default", direction="inbound", platform="telegram",
            source_chat_id="tg1", source_thread_id=None,
            author="u", content=text, message_id=f"m{i}", ts=ts + i,
        )
    msgs = db.get_timeline_messages(profile_id="default")
    assert [m["content"] for m in msgs] == ["first", "second", "third"]
    assert [m["seq"] for m in msgs] == [1, 2, 3]
    db.close()


def test_get_timeline_messages_limit(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    ts = time.time()
    for i in range(5):
        db.append_timeline_message(
            profile_id="default", direction="inbound", platform="telegram",
            source_chat_id="tg1", source_thread_id=None,
            author="u", content=f"m{i}", message_id=f"m{i}", ts=ts + i,
        )
    msgs = db.get_timeline_messages(profile_id="default", limit=3)
    # Limit returns the most recent N, still in seq order ascending
    assert [m["content"] for m in msgs] == ["m2", "m3", "m4"]
    db.close()


def test_timeline_next_seq_returns_1_for_empty_profile(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    assert db.timeline_next_seq(profile_id="default") == 1
    db.close()
