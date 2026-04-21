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
