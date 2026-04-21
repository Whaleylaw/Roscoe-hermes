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
