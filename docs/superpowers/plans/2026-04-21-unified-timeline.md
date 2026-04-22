# Unified Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each Hermes agent profile one unified conversation timeline spanning every channel, so a conversation started in Telegram continues seamlessly in Open WebUI (and vice versa) for the same agent.

**Architecture:** Add a new `unified_timeline` table to the existing per-profile SQLite state DB, wrap writes with a small `UnifiedTimeline` service, migrate platform adapters to record inbound/outbound through it, and swap context assembly to read from this table instead of per-channel sessions. Migration is additive — existing `sessions` table keeps its routing role, `session_funnel` config gets a deprecation shim.

**Tech Stack:** Python 3.11, SQLite with FTS5 (via existing `SessionDB`), pytest, aiohttp (gateway/api_server).

**Spec:** `docs/superpowers/specs/2026-04-21-unified-timeline-design.md`

---

## File Structure

**Created:**
- `gateway/unified_timeline.py` — `UnifiedTimeline` service wrapping inbound/outbound writes and profile locking.
- `tests/gateway/test_unified_timeline.py` — unit tests for the service.
- `tests/test_hermes_state_unified_timeline.py` — unit tests for the new DB methods and schema v7 migration.
- `tests/gateway/test_cross_channel_continuity.py` — integration test for the headline behavior (Telegram ↔ Open WebUI).
- `scripts/migrate_to_unified_timeline.py` — one-shot migration runner.
- `docs/user-guide/features/unified-timeline.md` — user-facing feature doc.

**Modified:**
- `hermes_state.py` — schema v7 (add `unified_timeline` + FTS5 + indexes), add `append_timeline_message`, `get_timeline_messages`, `timeline_next_seq`.
- `gateway/config.py` — add `UnifiedTimelineConfig`, deprecation warning path for `session_funnel`.
- `gateway/session.py` — new `load_timeline_conversation()` used by context assembly.
- `gateway/run.py` — route context assembly through unified timeline when enabled (default on).
- `gateway/platforms/telegram.py` — call `UnifiedTimeline.record_inbound` / `record_outbound` at the right points.
- `gateway/platforms/api_server.py` — same, and make `X-Hermes-Session-Id` advisory rather than authoritative.
- `gateway/platforms/ADDING_A_PLATFORM.md` — canonical "adapters plug into `UnifiedTimeline`" section.
- `RELEASE_*.md` (new file) — migration + deprecation notes.

**Left alone:**
- Existing `sessions` / `messages` tables remain for routing, reset policy, token counters, resume state.
- `gateway/session.py` `SessionStore` keeps its current responsibilities.

---

## Task 1: Add `unified_timeline` schema (v7 migration)

**Files:**
- Modify: `hermes_state.py:34` (bump `SCHEMA_VERSION`), `hermes_state.py:36-91` (`SCHEMA_SQL`), `hermes_state.py:93-112` (`FTS_SQL`), `hermes_state.py:252-339` (`_init_schema` migrations block)
- Test: `tests/test_hermes_state_unified_timeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hermes_state_unified_timeline.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/test_hermes_state_unified_timeline.py -q`
Expected: FAIL — `no such table: unified_timeline` and `schema_version` row is 6.

- [ ] **Step 3: Bump schema version and add creation SQL**

In `hermes_state.py:34`, change `SCHEMA_VERSION = 6` to:

```python
SCHEMA_VERSION = 7
```

In `hermes_state.py:36-91` (`SCHEMA_SQL` string), append before the closing `"""`:

```sql

CREATE TABLE IF NOT EXISTS unified_timeline (
    profile_id         TEXT NOT NULL,
    seq                INTEGER NOT NULL,
    ts                 REAL NOT NULL,
    direction          TEXT NOT NULL,
    platform           TEXT NOT NULL,
    source_chat_id     TEXT,
    source_thread_id   TEXT,
    author             TEXT,
    content            TEXT,
    message_id         TEXT,
    salience           TEXT NOT NULL DEFAULT 'primary',
    PRIMARY KEY (profile_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_unified_timeline_lookup
    ON unified_timeline(profile_id, platform, source_chat_id, source_thread_id, message_id, ts);
```

In `hermes_state.py:93-112` (`FTS_SQL` string), append before the closing `"""`:

```sql

CREATE VIRTUAL TABLE IF NOT EXISTS unified_timeline_fts USING fts5(
    content,
    content=unified_timeline,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS unified_timeline_fts_insert AFTER INSERT ON unified_timeline BEGIN
    INSERT INTO unified_timeline_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS unified_timeline_fts_delete AFTER DELETE ON unified_timeline BEGIN
    INSERT INTO unified_timeline_fts(unified_timeline_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS unified_timeline_fts_update AFTER UPDATE ON unified_timeline BEGIN
    INSERT INTO unified_timeline_fts(unified_timeline_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO unified_timeline_fts(rowid, content) VALUES (new.rowid, new.content);
END;
```

In `hermes_state.py:252-339` (`_init_schema`), extend the migration chain. Find the existing `if current_version < 6:` block and append after it:

```python
            if current_version < 7:
                # v7: add unified_timeline table + FTS + lookup index.
                # CREATE TABLE IF NOT EXISTS is idempotent, so executing
                # SCHEMA_SQL again at this point is safe — and the simplest
                # way to guarantee the new table exists on upgrade paths.
                cursor.executescript(SCHEMA_SQL)
                cursor.executescript(FTS_SQL)
                cursor.execute("UPDATE schema_version SET version = 7")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_hermes_state_unified_timeline.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full state test file to guard against regressions**

Run: `python3.11 -m pytest tests/test_hermes_state.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hermes_state.py tests/test_hermes_state_unified_timeline.py
git commit -m "feat(hermes_state): add unified_timeline table (schema v7)"
```

---

## Task 2: Add timeline read/write methods to `SessionDB`

**Files:**
- Modify: `hermes_state.py` — after the `append_message` method (~line 987), add three new methods.
- Test: `tests/test_hermes_state_unified_timeline.py` (append to file from Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hermes_state_unified_timeline.py`:

```python
import time

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/test_hermes_state_unified_timeline.py -q`
Expected: FAIL — `AttributeError: 'SessionDB' object has no attribute 'append_timeline_message'`.

- [ ] **Step 3: Implement the methods**

Add to `hermes_state.py`, after the end of `append_message` (~line 987):

```python
    # =========================================================================
    # Unified timeline storage (profile-scoped, cross-channel)
    # =========================================================================

    def timeline_next_seq(self, profile_id: str) -> int:
        """Return the next monotonic seq value for a profile's timeline."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM unified_timeline "
                "WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return int(row[0])

    def append_timeline_message(
        self,
        profile_id: str,
        direction: str,
        platform: str,
        source_chat_id: Optional[str],
        source_thread_id: Optional[str],
        author: Optional[str],
        content: Optional[str],
        message_id: Optional[str],
        ts: float,
        salience: str = "primary",
    ) -> int:
        """Append one row to unified_timeline. Returns the assigned seq."""
        def _do(conn):
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM unified_timeline "
                "WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
            seq = int(row[0])
            conn.execute(
                "INSERT INTO unified_timeline (profile_id, seq, ts, direction, "
                "platform, source_chat_id, source_thread_id, author, content, "
                "message_id, salience) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (profile_id, seq, ts, direction, platform, source_chat_id,
                 source_thread_id, author, content, message_id, salience),
            )
            return seq
        return self._execute_write(_do)

    def get_timeline_messages(
        self,
        profile_id: str,
        limit: Optional[int] = None,
        salience: str = "primary",
    ) -> List[Dict[str, Any]]:
        """Load timeline messages for a profile, ordered by seq ascending.

        When ``limit`` is given, returns the most recent N messages, still
        ordered seq-ascending (oldest of the N first).
        """
        with self._lock:
            if limit is None:
                cursor = self._conn.execute(
                    "SELECT profile_id, seq, ts, direction, platform, "
                    "source_chat_id, source_thread_id, author, content, "
                    "message_id, salience FROM unified_timeline "
                    "WHERE profile_id = ? AND salience = ? ORDER BY seq ASC",
                    (profile_id, salience),
                )
                rows = cursor.fetchall()
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM (SELECT profile_id, seq, ts, direction, "
                    "platform, source_chat_id, source_thread_id, author, "
                    "content, message_id, salience FROM unified_timeline "
                    "WHERE profile_id = ? AND salience = ? "
                    "ORDER BY seq DESC LIMIT ?) ORDER BY seq ASC",
                    (profile_id, salience, limit),
                )
                rows = cursor.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_hermes_state_unified_timeline.py -q`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add hermes_state.py tests/test_hermes_state_unified_timeline.py
git commit -m "feat(hermes_state): add timeline read/write methods to SessionDB"
```

---

## Task 3: `UnifiedTimeline` service (profile resolution + inbound/outbound API)

**Files:**
- Create: `gateway/unified_timeline.py`
- Test: `tests/gateway/test_unified_timeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/gateway/test_unified_timeline.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.unified_timeline'`.

- [ ] **Step 3: Implement the service**

Create `gateway/unified_timeline.py`:

```python
"""
Unified Timeline service.

Single source of truth for the agent's cross-channel conversation history
within one profile. Platform adapters call ``record_inbound`` and
``record_outbound`` instead of writing transcripts into per-channel
sessions; context assembly reads from the same table to produce one
continuous agent experience across Telegram, Open WebUI, Discord, etc.

See ``docs/superpowers/specs/2026-04-21-unified-timeline-design.md``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from hermes_state import SessionDB
from gateway.session import SessionSource


@dataclass
class TurnHandle:
    """Opaque handle tying an outbound response to its inbound turn."""
    profile_id: str
    platform: str
    source_chat_id: Optional[str]
    source_thread_id: Optional[str]
    seq: int


# Per-profile locks serialize writes within one process.  Keyed by
# profile_id, not session_key — simultaneous inbound messages from
# multiple channels must converge in order.
_profile_locks: Dict[str, threading.Lock] = {}
_profile_locks_guard = threading.Lock()


def _get_profile_lock(profile_id: str) -> threading.Lock:
    with _profile_locks_guard:
        lock = _profile_locks.get(profile_id)
        if lock is None:
            lock = threading.Lock()
            _profile_locks[profile_id] = lock
        return lock


class UnifiedTimeline:
    """Thin wrapper around SessionDB's timeline methods, plus profile scoping."""

    def __init__(self, db: SessionDB, profile_id: str):
        self.db = db
        self.profile_id = profile_id
        self._lock = _get_profile_lock(profile_id)

    @classmethod
    def for_active_profile(cls, db: SessionDB) -> "UnifiedTimeline":
        """Resolve the current profile from HERMES_HOME and build a service."""
        from hermes_cli.profiles import get_active_profile_name
        return cls(db=db, profile_id=get_active_profile_name())

    def record_inbound(
        self,
        source: SessionSource,
        content: str,
        message_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> TurnHandle:
        """Append an inbound message and return a handle for the reply."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            seq = self.db.append_timeline_message(
                profile_id=self.profile_id,
                direction="inbound",
                platform=source.platform.value,
                source_chat_id=source.chat_id,
                source_thread_id=source.thread_id,
                author=source.user_name or source.user_id,
                content=content,
                message_id=message_id,
                ts=ts,
            )
        return TurnHandle(
            profile_id=self.profile_id,
            platform=source.platform.value,
            source_chat_id=source.chat_id,
            source_thread_id=source.thread_id,
            seq=seq,
        )

    def record_outbound(
        self,
        turn: TurnHandle,
        content: str,
        message_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> int:
        """Append an outbound message tied to an inbound turn handle."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            return self.db.append_timeline_message(
                profile_id=turn.profile_id,
                direction="outbound",
                platform=turn.platform,
                source_chat_id=turn.source_chat_id,
                source_thread_id=turn.source_thread_id,
                author="agent",
                content=content,
                message_id=message_id,
                ts=ts,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/unified_timeline.py tests/gateway/test_unified_timeline.py
git commit -m "feat(gateway): add UnifiedTimeline service"
```

---

## Task 4: Add timeline-based conversation loader to `SessionStore`

**Files:**
- Modify: `gateway/session.py` — add `load_timeline_conversation` method on `SessionStore` (alongside existing `load_transcript` at line 1196).
- Test: `tests/gateway/test_unified_timeline.py` (append).

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_unified_timeline.py`:

```python
from gateway.config import GatewayConfig
from gateway.session import SessionStore


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py::test_load_timeline_conversation_returns_openai_shape -q`
Expected: FAIL — `AttributeError: 'SessionStore' object has no attribute 'load_timeline_conversation'`.

- [ ] **Step 3: Implement `load_timeline_conversation`**

Add this method to `SessionStore` in `gateway/session.py`, immediately after `load_transcript` (~line 1242):

```python
    def load_timeline_conversation(
        self, profile_id: str, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Load the profile's unified timeline in OpenAI conversation format.

        Returns a list of ``{"role": "user"|"assistant", "content": str}``
        dicts in chronological order. This is the cross-channel analog of
        :meth:`load_transcript` and is the new source of truth for agent
        context when the unified timeline is enabled.
        """
        if not self._db:
            return []
        try:
            rows = self._db.get_timeline_messages(
                profile_id=profile_id, limit=limit,
            )
        except Exception as e:
            logger.warning("Failed to load unified timeline for %s: %s",
                           profile_id, e)
            return []
        return [
            {
                "role": "assistant" if r["direction"] == "outbound" else "user",
                "content": r["content"] or "",
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/session.py tests/gateway/test_unified_timeline.py
git commit -m "feat(gateway): SessionStore.load_timeline_conversation loader"
```

---

## Task 5: Add `UnifiedTimelineConfig` with deprecation shim for `session_funnel`

**Files:**
- Modify: `gateway/config.py` — add `UnifiedTimelineConfig` dataclass alongside `SessionFunnelConfig` (~line 220), wire it into `GatewayConfig`, add deprecation warning.
- Test: `tests/gateway/test_config.py` (append).

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_config.py`:

```python
import logging

from gateway.config import GatewayConfig, UnifiedTimelineConfig


def test_unified_timeline_enabled_by_default():
    cfg = GatewayConfig()
    assert cfg.unified_timeline.enabled is True


def test_unified_timeline_round_trip():
    cfg = GatewayConfig(unified_timeline=UnifiedTimelineConfig(enabled=False))
    restored = GatewayConfig.from_dict(cfg.to_dict())
    assert restored.unified_timeline.enabled is False


def test_session_funnel_enabled_maps_to_unified_timeline_with_warning(caplog):
    data = {"session_funnel": {"enabled": True, "strategy": "single-agent-main"}}
    with caplog.at_level(logging.WARNING):
        cfg = GatewayConfig.from_dict(data)
    assert cfg.unified_timeline.enabled is True
    assert any("session_funnel" in rec.message and "deprecated" in rec.message.lower()
               for rec in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/gateway/test_config.py -q -k unified_timeline`
Expected: FAIL — `ImportError: cannot import name 'UnifiedTimelineConfig'`.

- [ ] **Step 3: Add the config dataclass + deprecation shim**

In `gateway/config.py`, add this dataclass immediately after `SessionFunnelConfig` (~line 220):

```python
@dataclass
class UnifiedTimelineConfig:
    """Config for the cross-channel unified timeline.

    Default-on. Replaces the older ``session_funnel`` feature, which is
    parsed for backwards compatibility but emits a deprecation warning.
    """
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedTimelineConfig":
        return cls(enabled=bool(data.get("enabled", True)))
```

In the `GatewayConfig` dataclass (~line 285, next to `session_funnel`), add:

```python
    unified_timeline: UnifiedTimelineConfig = field(default_factory=UnifiedTimelineConfig)
```

In `GatewayConfig.to_dict` (~line 401), add:

```python
            "unified_timeline": self.unified_timeline.to_dict(),
```

In `GatewayConfig.from_dict` (~line 450, right after the existing `session_funnel_data` handling block), add:

```python
        unified_timeline_data = data.get("unified_timeline")
        # Backwards-compat shim: if session_funnel.enabled is True and
        # unified_timeline is not explicitly configured, treat session_funnel
        # as a request for unified timeline behavior and warn.
        if unified_timeline_data is None and session_funnel_data:
            if bool(session_funnel_data.get("enabled", False)):
                logger.warning(
                    "gateway.session_funnel is deprecated; use "
                    "gateway.unified_timeline.enabled=true instead."
                )
                unified_timeline_data = {"enabled": True}
```

Then in the `return cls(...)` call (~line 475) add:

```python
            unified_timeline=UnifiedTimelineConfig.from_dict(unified_timeline_data or {}),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/gateway/test_config.py -q`
Expected: PASS (including existing `session_funnel` tests — the shim must not break them).

- [ ] **Step 5: Commit**

```bash
git add gateway/config.py tests/gateway/test_config.py
git commit -m "feat(gateway): UnifiedTimelineConfig with session_funnel deprecation"
```

---

## Task 6: Wire Telegram adapter to record inbound/outbound through UnifiedTimeline

> **Implementation note (post-investigation):** The plan's per-adapter code snippets were architecturally incorrect. The wiring lives in `gateway/run.py._handle_message_with_agent`, which every runner-backed platform goes through (Telegram, Discord, Slack, iMessage, Matrix, WhatsApp, Feishu, WeCom, …). One hook site covers them all. `gateway/platforms/telegram.py` is not modified. api_server (T7) still needs its own wiring because it has a separate endpoint handler.

**Files:**
- Modify: `gateway/platforms/telegram.py` — at the inbound message handling path, call `UnifiedTimeline.record_inbound` before (or alongside) the existing `SessionStore` write; at outbound, call `record_outbound` after the agent reply is produced.
- Test: `tests/gateway/test_unified_timeline_telegram.py` (new).

> Note: inspect the telegram adapter to find the exact handler functions for inbound messages and outbound replies. Search for the existing `SessionStore.get_or_create_session` call site; `UnifiedTimeline.record_inbound` should be called in the same place with the same `SessionSource`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/gateway/test_unified_timeline_telegram.py
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
```

- [ ] **Step 2: Run test to verify it passes as a ratchet (before wiring)**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline_telegram.py -q`
Expected: PASS — this test doesn't touch the telegram adapter, it just asserts the service contract the adapter will use.

- [ ] **Step 3: Find the inbound handler in `gateway/platforms/telegram.py`**

Open `gateway/platforms/telegram.py`. Locate where inbound text messages call into the gateway's session pipeline. Grep for `get_or_create_session` or `SessionSource(` to find the hook. Note the surrounding function name (likely `_handle_message` or similar) and the variable holding the message text and source.

- [ ] **Step 4: Wire `UnifiedTimeline.record_inbound` into the inbound path**

Add imports at the top of `gateway/platforms/telegram.py`:

```python
from gateway.unified_timeline import UnifiedTimeline
```

In the inbound handler, after the `SessionSource` is constructed and before (or alongside) the existing session-store write, add:

```python
        if self._gateway_config.unified_timeline.enabled:
            ut = UnifiedTimeline.for_active_profile(db=self._session_db)
            turn_handle = ut.record_inbound(
                source=source,
                content=message_text,
                message_id=str(update.message.message_id),
            )
            # Stash the handle on the per-turn context so the outbound
            # path can close the loop.
            turn_context["unified_turn_handle"] = turn_handle
```

> Adapt variable names (`self._gateway_config`, `self._session_db`, `source`, `message_text`, `update.message.message_id`, `turn_context`) to match the telegram adapter's actual conventions.

- [ ] **Step 5: Wire `UnifiedTimeline.record_outbound` into the outbound path**

Find where the telegram adapter sends the agent's reply back to the user. After the send succeeds, add:

```python
        handle = turn_context.get("unified_turn_handle")
        if handle is not None:
            ut = UnifiedTimeline.for_active_profile(db=self._session_db)
            ut.record_outbound(turn=handle, content=reply_text)
```

- [ ] **Step 6: Run tests**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline_telegram.py tests/gateway/test_session.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add gateway/platforms/telegram.py tests/gateway/test_unified_timeline_telegram.py
git commit -m "feat(telegram): record inbound/outbound via UnifiedTimeline"
```

---

## Task 7: Wire OpenAI-compatible API server (Open WebUI path) to UnifiedTimeline

**Files:**
- Modify: `gateway/platforms/api_server.py` — at the chat completions / responses endpoints, call `UnifiedTimeline.record_inbound` and `record_outbound`; make `X-Hermes-Session-Id` advisory only.
- Test: `tests/gateway/test_api_server.py` (append).

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_api_server.py`:

```python
def test_api_server_records_through_unified_timeline(tmp_path, aiohttp_client, monkeypatch):
    """POSTing a chat completion writes to unified_timeline regardless of header."""
    from gateway.config import GatewayConfig, Platform
    from gateway.platforms.api_server import APIServerPlatformAdapter
    from gateway.unified_timeline import UnifiedTimeline
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))

    # Pre-seed a prior Telegram turn the same profile should carry over.
    ut = UnifiedTimeline(db=db, profile_id="default")
    h = ut.record_inbound(
        source=__import__("gateway.session", fromlist=["SessionSource"]).SessionSource(
            platform=Platform.TELEGRAM, chat_id="tg1", chat_type="dm",
            user_id="u1", user_name="alice",
        ),
        content="remember: my pet's name is Fig",
        message_id="tg-m1",
    )
    ut.record_outbound(turn=h, content="noted — Fig")

    # Hit the API server — its behavior should write new rows to the same
    # unified_timeline, not to a separate session keyed by X-Hermes-Session-Id.
    # (This test is a scaffold; real wiring checks the row count post-POST.)
    rows_before = db.get_timeline_messages(profile_id="default")
    assert len(rows_before) == 2
    db.close()
```

> This test is a scaffold — the implementation step below wires the real code. After wiring, extend the test to issue an actual POST to the API server and assert `len(rows_after) > len(rows_before)`.

- [ ] **Step 2: Inspect `gateway/platforms/api_server.py:857`**

Open the file and read around line 857 (where `db.get_messages_as_conversation(session_id)` loads history today). Note:
- The endpoint handler that loads history from `X-Hermes-Session-Id`.
- Where the inbound message content is available before the agent runs.
- Where the outbound reply is returned / streamed.

- [ ] **Step 3: Wire `record_inbound` at the endpoint**

At the top of `gateway/platforms/api_server.py`, add:

```python
from gateway.unified_timeline import UnifiedTimeline
from gateway.session import SessionSource
from gateway.config import Platform
```

Inside the chat completions endpoint, replace the existing history-load block (around line 857):

**Before:**
```python
                    history = db.get_messages_as_conversation(session_id)
```

**After:**
```python
                    if self._gateway_config.unified_timeline.enabled:
                        history = self._session_store.load_timeline_conversation(
                            profile_id=UnifiedTimeline.for_active_profile(db=db).profile_id,
                        )
                    else:
                        history = db.get_messages_as_conversation(session_id)
```

Immediately before the agent is invoked with the new user message, add:

```python
                    if self._gateway_config.unified_timeline.enabled:
                        source = SessionSource(
                            platform=Platform.OPENAI_API,
                            chat_id=session_id or "openai-default",
                            chat_type="dm",
                            user_id=request.headers.get("X-User-Id"),
                            user_name=None,
                        )
                        ut = UnifiedTimeline.for_active_profile(db=db)
                        turn_handle = ut.record_inbound(
                            source=source,
                            content=user_message_content,
                            message_id=None,
                        )
```

After the agent replies (at the point where the response is about to be returned to the client), add:

```python
                    if self._gateway_config.unified_timeline.enabled and turn_handle is not None:
                        ut.record_outbound(turn=turn_handle, content=assistant_content)
```

- [ ] **Step 4: Note on `X-Hermes-Session-Id`**

Leave the header read path in place but demote it — the header is now used only for *client-side response correlation*, not for server-side memory selection. Add a short comment where the header is read:

```python
    # X-Hermes-Session-Id is advisory as of the unified-timeline rollout —
    # the agent's memory comes from the profile's unified timeline, not
    # from any client-supplied session id. See
    # docs/superpowers/specs/2026-04-21-unified-timeline-design.md.
```

- [ ] **Step 5: Run existing API server tests to catch regressions**

Run: `python3.11 -m pytest tests/gateway/test_api_server.py -q`
Expected: PASS.

- [ ] **Step 6: Extend the test to assert unified-timeline wiring end-to-end**

Update the scaffold test from Step 1 to issue a real POST against the adapter's chat completions handler and assert the row count in `unified_timeline` grew. (Use the existing patterns from `tests/gateway/test_api_server.py` for how other tests drive the endpoint.)

- [ ] **Step 7: Run the new test**

Run: `python3.11 -m pytest tests/gateway/test_api_server.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add gateway/platforms/api_server.py tests/gateway/test_api_server.py
git commit -m "fix(api_server): route memory through unified timeline instead of X-Hermes-Session-Id"
```

---

## Task 7b: Route all adapters' history loads through the unified timeline

**Why this task exists:** Task 7 swaps `api_server.py`'s load, but Telegram and other adapters still call `SessionStore.load_transcript(session_id)` for agent context. Without this task, a user messaging on Telegram would write to the unified timeline but still *read* from the per-channel transcript — so they'd see themselves on Telegram but not the Open WebUI side.

The fix: modify `SessionStore.load_transcript` itself to consult the config flag. When `unified_timeline.enabled` is true, route to `load_timeline_conversation(profile_id=<active>)`. The single method change propagates to every caller.

**Files:**
- Modify: `gateway/session.py` — `SessionStore.load_transcript` (~line 1196-1242).
- Test: `tests/gateway/test_unified_timeline.py` (append).

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_unified_timeline.py`:

```python
def test_load_transcript_routes_through_timeline_when_enabled(tmp_path, monkeypatch):
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

    # load_transcript should return the unified timeline, not the empty
    # per-session transcript.
    msgs = store.load_transcript(session_id="any-legacy-id")
    contents = [m["content"] for m in msgs]
    assert "unified-content" in contents
    assert "agent-reply" in contents
    db.close()


def test_load_transcript_uses_legacy_path_when_flag_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    db = SessionDB(db_path=tmp_path / "state.db")
    ut = UnifiedTimeline(db=db, profile_id="default")
    ut.record_inbound(source=_source(), content="ignored", message_id="m1")

    cfg = GatewayConfig(unified_timeline=UnifiedTimelineConfig(enabled=False))
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=cfg)
    store._db = db
    # No legacy per-session messages exist, so result is empty —
    # importantly, does NOT contain the unified timeline entry.
    msgs = store.load_transcript(session_id="any-legacy-id")
    contents = [m["content"] for m in msgs]
    assert "ignored" not in contents
    db.close()
```

Add the import at the top of the test file if not already present:

```python
from gateway.config import UnifiedTimelineConfig
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py -q`
Expected: FAIL — the first test fails because `load_transcript` currently returns the per-session transcript (empty here), not the timeline.

- [ ] **Step 3: Route `load_transcript` through the timeline when enabled**

In `gateway/session.py`, modify `SessionStore.load_transcript` (starting at line 1196) to check the config first:

```python
    def load_transcript(self, session_id: str) -> List[Dict[str, Any]]:
        """Load messages for the agent to consume.

        When ``unified_timeline`` is enabled (the default), returns the
        profile's unified timeline in OpenAI conversation format — the
        agent has one continuous memory across every channel it is
        reachable on. When disabled, falls back to the legacy per-session
        transcript (SQLite + JSONL fallback).
        """
        if getattr(self.config, "unified_timeline", None) and self.config.unified_timeline.enabled:
            from hermes_cli.profiles import get_active_profile_name
            return self.load_timeline_conversation(
                profile_id=get_active_profile_name(),
            )

        # Legacy path — preserved exactly as before for the disabled case.
        db_messages = []
        if self._db:
            try:
                db_messages = self._db.get_messages_as_conversation(session_id)
            except Exception as e:
                logger.debug("Could not load messages from DB: %s", e)

        transcript_path = self.get_transcript_path(session_id)
        jsonl_messages = []
        if transcript_path.exists():
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            jsonl_messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "Skipping corrupt line in transcript %s: %s",
                                session_id, line[:120],
                            )

        if len(jsonl_messages) > len(db_messages):
            if db_messages:
                logger.debug(
                    "Session %s: JSONL has %d messages vs SQLite %d — "
                    "using JSONL (legacy session not yet fully migrated)",
                    session_id, len(jsonl_messages), len(db_messages),
                )
            return jsonl_messages

        return db_messages
```

> This preserves the existing legacy behavior byte-for-byte when the flag is off; only adds an early return when it is on.

- [ ] **Step 4: Run tests**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline.py tests/gateway/test_session.py -q`
Expected: PASS.

- [ ] **Step 5: ~~Clean up Task 7's now-redundant branching~~ (obviated — see note)**

**Implementation note:** this step is obviated. The T7 fix commit (`456b5196`) already extracted the row-to-OpenAI mapping into `_timeline_rows_to_openai_messages` in `gateway/session.py`, which both `SessionStore.load_timeline_conversation` and `APIServerAdapter._load_unified_timeline_history` call. The adapter's branch in `api_server.py` is not dead weight — it still has to discriminate between the profile timeline and the request-body-supplied `conversation_history` that Open WebUI and LobeChat send. Collapsing to `load_transcript(session_id)` would lose that discrimination. No change to api_server is needed in T7b.

Run the api_server tests to confirm parity:

Run: `.venv/bin/python -m pytest tests/gateway/test_api_server.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/session.py gateway/platforms/api_server.py tests/gateway/test_unified_timeline.py
git commit -m "feat(gateway): route load_transcript through unified timeline"
```

---

## Task 8: Cross-channel continuity integration test

**Files:**
- Create: `tests/gateway/test_cross_channel_continuity.py`

- [ ] **Step 1: Write the headline regression test**

```python
# tests/gateway/test_cross_channel_continuity.py
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
        platform=Platform.OPENAI_API, chat_id="openai-default", chat_type="dm",
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
    ut.record_inbound(source=src(Platform.OPENAI_API), content="C", message_id="c")
    rows = db.get_timeline_messages(profile_id="default")
    assert [r["content"] for r in rows] == ["A", "B", "C"]
    db.close()
```

- [ ] **Step 2: Run the test**

Run: `python3.11 -m pytest tests/gateway/test_cross_channel_continuity.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_cross_channel_continuity.py
git commit -m "test(gateway): cross-channel continuity regression test"
```

---

## Task 9: Migration script for existing per-channel sessions

**Files:**
- Create: `scripts/migrate_to_unified_timeline.py`
- Test: `tests/scripts/test_migrate_to_unified_timeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_migrate_to_unified_timeline.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/scripts/test_migrate_to_unified_timeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.migrate_to_unified_timeline'`.

- [ ] **Step 3: Implement the migrator**

Create `scripts/migrate_to_unified_timeline.py`:

```python
#!/usr/bin/env python3
"""One-shot migration: copy legacy per-channel session transcripts into
``unified_timeline``. Idempotent — safe to rerun.

Usage:
    python3.11 scripts/migrate_to_unified_timeline.py

Reads ``$HERMES_HOME/state.db`` (or the default location) and writes a
``$HERMES_HOME/.unified_timeline_migrated`` flag file on completion so the
gateway does not re-walk on every startup. Rerunning manually is always
safe.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from hermes_constants import get_hermes_home
from hermes_state import SessionDB, DEFAULT_DB_PATH

logger = logging.getLogger("migrate_to_unified_timeline")


def migrate(db_path: Optional[Path] = None, profile_id: str = "default") -> int:
    """Walk legacy ``messages`` + ``sessions`` tables and populate
    ``unified_timeline`` for this profile. Returns the number of rows
    inserted (0 if nothing to migrate)."""
    db_path = db_path or DEFAULT_DB_PATH
    db = SessionDB(db_path=db_path)
    try:
        inserted = 0
        legacy_rows = db._conn.execute(
            "SELECT m.session_id, m.role, m.content, m.timestamp, "
            "s.source AS platform "
            "FROM messages m JOIN sessions s ON m.session_id = s.id "
            "WHERE m.content IS NOT NULL "
            "ORDER BY m.timestamp ASC, m.id ASC"
        ).fetchall()
        for row in legacy_rows:
            direction = "outbound" if row["role"] == "assistant" else "inbound"
            existing = db._conn.execute(
                "SELECT 1 FROM unified_timeline WHERE profile_id = ? "
                "AND platform = ? AND source_chat_id IS ? "
                "AND message_id IS ? AND ts = ? AND direction = ? "
                "AND content IS ? LIMIT 1",
                (profile_id, row["platform"], row["session_id"],
                 None, float(row["timestamp"]), direction, row["content"]),
            ).fetchone()
            if existing:
                continue
            db.append_timeline_message(
                profile_id=profile_id,
                direction=direction,
                platform=row["platform"] or "unknown",
                source_chat_id=row["session_id"],
                source_thread_id=None,
                author="agent" if direction == "outbound" else None,
                content=row["content"],
                message_id=None,
                ts=float(row["timestamp"]),
            )
            inserted += 1
    finally:
        db.close()

    flag = get_hermes_home() / ".unified_timeline_migrated"
    flag.write_text(f"migrated {inserted} rows\n")
    logger.info("Migrated %d rows to unified_timeline (profile=%s)",
                inserted, profile_id)
    return inserted


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--profile-id", default=None,
                        help="Profile id (default: inferred from HERMES_HOME).")
    args = parser.parse_args()

    profile_id = args.profile_id
    if profile_id is None:
        from hermes_cli.profiles import get_active_profile_name
        profile_id = get_active_profile_name()
    migrate(db_path=args.db_path, profile_id=profile_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Ensure `scripts/` is a package (or adjust imports)**

Check whether `scripts/__init__.py` exists:

```bash
ls scripts/__init__.py || touch scripts/__init__.py
```

If `touch` was needed, the file is empty and that is correct.

- [ ] **Step 5: Run tests**

Run: `python3.11 -m pytest tests/scripts/test_migrate_to_unified_timeline.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_to_unified_timeline.py scripts/__init__.py tests/scripts/test_migrate_to_unified_timeline.py
git commit -m "feat(scripts): one-shot migrator for unified_timeline"
```

---

## Task 10: Auto-run migration on gateway startup (once)

**Files:**
- Modify: `gateway/run.py` — on startup, if `unified_timeline.enabled` and the flag file does not exist, run `migrate()` once and create the flag file.
- Test: `tests/gateway/test_unified_timeline_startup.py` (new).

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/test_unified_timeline_startup.py
from pathlib import Path

def test_startup_runs_migration_once(tmp_path, monkeypatch):
    hermes_home = tmp_path / "home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    from gateway.run import maybe_run_unified_timeline_migration
    called = []
    def fake_migrate(*, db_path=None, profile_id="default"):
        called.append(profile_id)
        return 0
    # Monkeypatch the import site.
    import scripts.migrate_to_unified_timeline as m
    monkeypatch.setattr(m, "migrate", fake_migrate)

    # First call runs migration, creates flag file.
    maybe_run_unified_timeline_migration()
    assert called == ["default"]
    assert (hermes_home / ".unified_timeline_migrated").exists()

    # Second call is a no-op because the flag file exists.
    maybe_run_unified_timeline_migration()
    assert called == ["default"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline_startup.py -q`
Expected: FAIL — `ImportError: cannot import name 'maybe_run_unified_timeline_migration' from 'gateway.run'`.

- [ ] **Step 3: Add the startup hook**

In `gateway/run.py`, near the top-level helpers (or wherever startup initializers live), add:

```python
def maybe_run_unified_timeline_migration() -> None:
    """Run the one-shot legacy → unified_timeline migration if needed.

    Writes a flag file to HERMES_HOME on completion so subsequent gateway
    starts skip the walk. Manual reruns via ``scripts/migrate_to_unified_timeline.py``
    are always safe.
    """
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_active_profile_name
    flag = get_hermes_home() / ".unified_timeline_migrated"
    if flag.exists():
        return
    try:
        from scripts.migrate_to_unified_timeline import migrate
        migrate(profile_id=get_active_profile_name())
    except Exception as exc:
        # Migration is best-effort — failure should not block the gateway
        # from starting. The unified_timeline table still works for new
        # messages; legacy history just won't be backfilled.
        import logging
        logging.getLogger(__name__).warning(
            "unified_timeline migration failed: %s — continuing startup", exc,
        )
```

Then, in the gateway's main startup path (find where `SessionDB` is instantiated or where the platform adapters are registered), call it:

```python
    if config.gateway.unified_timeline.enabled:
        maybe_run_unified_timeline_migration()
```

> Adapt `config.gateway` access to match the actual GatewayConfig reference in `gateway/run.py`.

- [ ] **Step 4: Run test**

Run: `python3.11 -m pytest tests/gateway/test_unified_timeline_startup.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/run.py tests/gateway/test_unified_timeline_startup.py
git commit -m "feat(gateway): auto-migrate to unified_timeline on first startup"
```

---

## Task 11: Update `ADDING_A_PLATFORM.md` with the unified-timeline pattern

**Files:**
- Modify: `gateway/platforms/ADDING_A_PLATFORM.md`

- [ ] **Step 1: Append a new canonical section**

Open `gateway/platforms/ADDING_A_PLATFORM.md` and append (after the existing intro sections):

```markdown
## Unified Timeline: the required write pattern

Every new platform adapter MUST route inbound and outbound messages
through `UnifiedTimeline`. This is what gives the agent a single
cross-channel memory. Adapters that skip this step (by writing directly
to a per-channel session or trusting client-supplied session ids) will
see the agent forget context when the user switches channels — exactly
the bug the unified-timeline rollout fixed.

### Inbound

```python
from gateway.unified_timeline import UnifiedTimeline

ut = UnifiedTimeline.for_active_profile(db=self._session_db)
turn_handle = ut.record_inbound(
    source=source,                 # SessionSource built from the platform event
    content=message_text,
    message_id=str(platform_message_id),  # or None if the platform has no stable id
)
# Keep turn_handle available until you send the agent's reply below.
```

### Outbound

```python
ut = UnifiedTimeline.for_active_profile(db=self._session_db)
ut.record_outbound(turn=turn_handle, content=reply_text)
```

### Do NOT

- Write the agent's transcript into a per-channel session. The
  `sessions` table is still used for routing metadata (origin, delivery
  destination, reset policy, token counters), but it is no longer the
  source of truth for agent memory.
- Trust client-supplied session ids (e.g. `X-Hermes-Session-Id`) for
  memory selection. They are advisory only. The agent's memory is
  scoped by profile, not by caller.

### Reference implementations

See `gateway/platforms/telegram.py` and `gateway/platforms/api_server.py`
for the two reference wirings.
```

- [ ] **Step 2: Commit**

```bash
git add gateway/platforms/ADDING_A_PLATFORM.md
git commit -m "docs(platforms): canonical unified-timeline integration pattern"
```

---

## Task 12: User-facing feature doc + release notes

**Files:**
- Create: `docs/user-guide/features/unified-timeline.md`
- Create: `RELEASE_unified_timeline.md`

- [ ] **Step 1: Write the user-guide page**

Create `docs/user-guide/features/unified-timeline.md`:

```markdown
# Unified Timeline

Your agent has one memory across every channel you use to reach it.

When you start a conversation in Telegram and continue it in Open WebUI
(or Discord, iMessage, Slack, or any future platform), the agent picks
up where you left off. Each agent profile has its own timeline; running
multiple profiles keeps them independent.

## Mental model

Think of the agent as its own user: it has accounts on every connected
platform, and a single continuous memory of what was said, regardless
of which app you were using at the time. That's the unified timeline.

## What gets into the timeline

Today, every inbound message to the agent and every message the agent
sends lands in the timeline. Group chats are a future concern — when
the agent participates in busy multi-user chats, tiering will keep
unrelated traffic out of its primary context.

## Configuration

```yaml
gateway:
  unified_timeline:
    enabled: true   # default
```

`session_funnel` (the older, global-only version of this feature) is
deprecated. If present in your config, it is parsed and treated as a
request to enable `unified_timeline`, with a log warning.

## Migration

On first start after the unified-timeline rollout, the gateway walks
your existing per-channel transcripts once and copies them into the
timeline. A flag file (`$HERMES_HOME/.unified_timeline_migrated`)
prevents re-walking. To rerun manually:

```bash
python3 scripts/migrate_to_unified_timeline.py
```

The migration is idempotent — safe to rerun at any time.
```

- [ ] **Step 2: Write release notes**

Create `RELEASE_unified_timeline.md`:

```markdown
# Unified Timeline

Release date: (fill in)

## Summary

Each agent profile now has a single message timeline spanning every
channel: Telegram, Discord, Open WebUI (via the OpenAI-compatible API
server), iMessage, Slack, and any future adapters. A conversation
started on one channel continues seamlessly on another.

## What changed

- New `unified_timeline` table in the per-profile SQLite state DB,
  with FTS5 search and an append-only, monotonic sequence per profile.
- New `UnifiedTimeline` service (`gateway/unified_timeline.py`) that
  platform adapters call for every inbound and outbound message.
- Telegram adapter wired through the new service.
- OpenAI-compatible API server (`gateway/platforms/api_server.py`)
  rewired: `X-Hermes-Session-Id` is now advisory; the agent's memory
  comes from the profile's unified timeline.
- New `gateway.unified_timeline.enabled` config (default true).
- `gateway.session_funnel` is deprecated. Enabled `session_funnel`
  config is transparently mapped to `unified_timeline.enabled = true`
  with a log warning.

## Migration

On first gateway start, existing per-channel transcripts are migrated
into the unified timeline. A flag file
(`$HERMES_HOME/.unified_timeline_migrated`) prevents re-walking.
Rerun manually at any time: `python3 scripts/migrate_to_unified_timeline.py`.

## Validation

```
python3.11 -m pytest -o addopts='' \
  tests/test_hermes_state_unified_timeline.py \
  tests/gateway/test_unified_timeline.py \
  tests/gateway/test_unified_timeline_telegram.py \
  tests/gateway/test_cross_channel_continuity.py \
  tests/scripts/test_migrate_to_unified_timeline.py \
  tests/gateway/test_api_server.py \
  tests/gateway/test_config.py \
  tests/gateway/test_session.py \
  -q
```
```

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide/features/unified-timeline.md RELEASE_unified_timeline.md
git commit -m "docs: unified-timeline user guide + release notes"
```

---

## Self-review checklist (run after completing all tasks)

- [ ] Every spec section has at least one implementing task: schema (T1, T2), ingest path (T3, T6, T7), context assembly (T4, T7, T7b), concurrency/lock (T3), extensibility (T11), config (T5), profile scoping (T3), migration (T9, T10), docs (T11, T12).
- [ ] No `TBD` / `TODO` / `fill in` strings in the plan body outside the one legitimate release-date placeholder in T12.
- [ ] Method names are consistent: `record_inbound`, `record_outbound`, `for_active_profile`, `append_timeline_message`, `get_timeline_messages`, `timeline_next_seq`, `load_timeline_conversation`, `maybe_run_unified_timeline_migration`, `migrate`.
- [ ] Every code step either shows the code or names the exact function/file to inspect.
- [ ] TDD discipline: every task starts with a failing test step before implementation.
