import time
from pathlib import Path

from hermes_state import SessionDB


def _seed_legacy_session(db: SessionDB, session_id: str, source: str):
    db._conn.execute(
        "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
        (session_id, source, time.time()),
    )
    db._conn.commit()
    db.append_message(session_id=session_id, role="user", content="hello-user")
    db.append_message(session_id=session_id, role="assistant", content="hello-agent")


def test_migrator_copies_legacy_messages_to_timeline(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    db = SessionDB(db_path=db_path)
    _seed_legacy_session(db, session_id="s1", source="telegram")
    _seed_legacy_session(db, session_id="s2", source="openai_api")
    db.close()

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    from scripts.migrate_to_unified_timeline import migrate
    migrate(db_path=db_path, profile_id="default")

    db = SessionDB(db_path=db_path)
    rows = db.get_timeline_messages(profile_id="default")
    contents = [r["content"] for r in rows]
    assert contents == ["hello-user", "hello-agent", "hello-user", "hello-agent"]
    # Rerun: idempotent, no duplicates.
    db.close()
    from scripts.migrate_to_unified_timeline import migrate as m2
    m2(db_path=db_path, profile_id="default")
    db = SessionDB(db_path=db_path)
    rows = db.get_timeline_messages(profile_id="default")
    assert len(rows) == 4
    db.close()


def test_migrator_writes_flag_file(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    db = SessionDB(db_path=db_path)
    db.close()
    hermes_home = tmp_path / "home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    from scripts.migrate_to_unified_timeline import migrate
    migrate(db_path=db_path, profile_id="default")
    assert (hermes_home / ".unified_timeline_migrated").exists()
