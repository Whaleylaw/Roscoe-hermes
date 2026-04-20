#!/usr/bin/env python3
"""Ingest OpenClaw JSONL session transcripts into Hermes state.db.

Converts OpenClaw's nested message schema to Hermes' flat schema, drops
session-level and message-level noise, preserves original timestamps,
and tags imported sessions with source=openclaw-{agent} so they can be
filtered or pruned separately.

Usage:
  python3 ingest_openclaw_sessions.py --dry-run
  python3 ingest_openclaw_sessions.py
  python3 ingest_openclaw_sessions.py --agent main,paralegal
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_AGENTS = ("main", "coder", "paralegal")
OPENCLAW_ROOT = Path.home() / ".openclaw" / "agents"
HERMES_DB = Path.home() / ".hermes" / "state.db"

# Regexes for noise detection
BOILERPLATE_STARTUP = re.compile(
    r"A new session was started via /(new|reset)\.\s*Execute your Session Startup"
)
SENDER_METADATA_ONLY = re.compile(
    r"^Sender \(untrusted metadata\):\s*```json\s*\{[^`]+\}\s*```\s*$",
    re.DOTALL,
)
UNTRUSTED_META_PREFIX = re.compile(
    r"^Sender \(untrusted metadata\):\s*```json\s*\{[^`]+\}\s*```\s*\n+",
    re.DOTALL,
)


@dataclass
class Stats:
    files_seen: int = 0
    files_skipped_empty: int = 0
    files_skipped_delivery_mirror: int = 0
    files_skipped_too_short: int = 0
    sessions_imported: int = 0
    messages_inserted: int = 0
    messages_skipped_boilerplate: int = 0
    messages_skipped_empty: int = 0
    per_agent: dict = field(default_factory=dict)

    def bump(self, agent: str, **kwargs) -> None:
        d = self.per_agent.setdefault(agent, {"sessions": 0, "messages": 0})
        for k, v in kwargs.items():
            d[k] = d.get(k, 0) + v


def iso_to_epoch(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def make_session_id(meta_ts: str, original_id: str) -> str:
    dt = datetime.fromisoformat(meta_ts[:-1] + "+00:00") if meta_ts.endswith("Z") else datetime.now(timezone.utc)
    stamp = dt.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short = (original_id or uuid.uuid4().hex)[:8]
    return f"oc_{stamp}_{short}"


def flatten_content(content) -> tuple[str, str | None, list | None]:
    """Return (text_content, thinking_text, tool_calls_list)."""
    if content is None:
        return "", None, None
    if isinstance(content, str):
        return content, None, None
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[dict] = []
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                text_parts.append(str(c))
                continue
            ct = c.get("type")
            if ct == "text":
                text_parts.append(c.get("text", ""))
            elif ct == "thinking":
                thinking_parts.append(c.get("thinking", "") or "")
            elif ct == "tool_use":
                tool_calls.append({
                    "id": c.get("id"),
                    "type": "function",
                    "function": {
                        "name": c.get("name"),
                        "arguments": json.dumps(c.get("input", {})) if isinstance(c.get("input"), (dict, list)) else str(c.get("input", "")),
                    },
                })
            elif ct == "tool_result":
                inner = c.get("content")
                if isinstance(inner, list):
                    for ic in inner:
                        if isinstance(ic, dict) and ic.get("type") == "text":
                            text_parts.append(ic.get("text", ""))
                        else:
                            text_parts.append(str(ic))
                else:
                    text_parts.append(str(inner) if inner else "")
            elif ct == "image":
                src = c.get("source", {})
                text_parts.append(f"[image: {src.get('media_type', 'unknown')}]")
            else:
                text_parts.append(f"[{ct}]")
    return (
        "\n".join(p for p in text_parts if p).strip(),
        "\n".join(p for p in thinking_parts if p).strip() or None,
        tool_calls or None,
    )


def is_noise_message(role: str, text: str) -> bool:
    if not text or not text.strip():
        return True
    if role == "user":
        stripped = text.strip()
        if BOILERPLATE_STARTUP.search(stripped):
            return True
        if SENDER_METADATA_ONLY.match(stripped):
            return True
        # Message was pure metadata prefix with nothing after
        cleaned = UNTRUSTED_META_PREFIX.sub("", stripped).strip()
        if not cleaned:
            return True
    if role == "assistant":
        # Drop session-startup greetings that begin with generic openings after a boilerplate prompt
        if len(text) < 400 and text.lower().startswith(("hey aaron", "hi aaron", "hello aaron")) and "fresh session" in text.lower():
            return True
    return False


def strip_untrusted_meta(text: str) -> str:
    return UNTRUSTED_META_PREFIX.sub("", text).strip()


def process_file(path: Path, agent: str, stats: Stats) -> dict | None:
    """Parse one OpenClaw session file. Return dict ready for DB insert, or None if filtered."""
    stats.files_seen += 1
    stats.bump(agent, sessions=0)

    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [json.loads(ln) for ln in f if ln.strip()]
    except Exception as e:
        print(f"[parse-fail] {path.name}: {e}", file=sys.stderr)
        return None

    if not lines:
        stats.files_skipped_empty += 1
        return None

    meta = None
    raw_messages = []
    for d in lines:
        if d.get("type") == "session":
            meta = d
        elif d.get("type") == "message":
            raw_messages.append(d)

    if not meta:
        stats.files_skipped_empty += 1
        return None

    if not raw_messages:
        stats.files_skipped_empty += 1
        return None

    # Delivery-mirror one-shot detection: every assistant uses model=delivery-mirror
    assistant_msgs = [m for m in raw_messages if m.get("message", {}).get("role") == "assistant"]
    if assistant_msgs and all(m.get("model") == "delivery-mirror" for m in assistant_msgs):
        stats.files_skipped_delivery_mirror += 1
        return None

    # Convert messages
    converted: list[dict] = []
    primary_model = None
    for rm in raw_messages:
        m = rm.get("message", {})
        role = m.get("role", "")
        if role == "toolResult":
            role = "tool"
        text, thinking, tool_calls = flatten_content(m.get("content"))

        if is_noise_message(role, text):
            stats.messages_skipped_boilerplate += 1
            continue

        cleaned_text = strip_untrusted_meta(text) if role == "user" else text
        if not cleaned_text.strip() and not tool_calls and not thinking:
            stats.messages_skipped_empty += 1
            continue

        usage = rm.get("usage") or {}
        total_tokens = usage.get("totalTokens") or (usage.get("input", 0) + usage.get("output", 0)) or None
        if role == "assistant" and rm.get("model") and not primary_model:
            primary_model = rm.get("model")

        converted.append({
            "role": role,
            "content": cleaned_text,
            "tool_calls": tool_calls,
            "reasoning": thinking,
            "timestamp": iso_to_epoch(rm.get("timestamp")),
            "token_count": total_tokens,
        })

    # Drop sessions with too little substance
    non_tool = [m for m in converted if m["role"] in ("user", "assistant")]
    if len(non_tool) < 2:
        stats.files_skipped_too_short += 1
        return None

    session_id = make_session_id(meta.get("timestamp", ""), meta.get("id", ""))
    started_at = iso_to_epoch(meta.get("timestamp", ""))
    if not started_at:
        started_at = converted[0]["timestamp"] or 0.0

    stats.bump(agent, sessions=1, messages=len(converted))
    stats.sessions_imported += 1
    stats.messages_inserted += len(converted)

    # Title: first user message, first 70 chars + session-id suffix so the
    # unique index on (title) never collides across imported rows
    first_user = next((m["content"] for m in converted if m["role"] == "user"), "")
    base = first_user.strip().split("\n")[0][:70] if first_user.strip() else ""
    suffix = session_id.rsplit("_", 1)[-1]
    title = f"{base} [{suffix}]" if base else None

    return {
        "id": session_id,
        "original_id": meta.get("id"),
        "source": f"openclaw-{agent}",
        "model": primary_model,
        "started_at": started_at,
        "ended_at": converted[-1]["timestamp"] or started_at,
        "message_count": len(converted),
        "title": title,
        "cwd": meta.get("cwd"),
        "messages": converted,
    }


def insert_session(conn: sqlite3.Connection, s: dict) -> None:
    tool_call_count = sum(len(m["tool_calls"] or []) for m in s["messages"])
    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (id, source, user_id, model, model_config, system_prompt,
            parent_session_id, started_at, ended_at, end_reason,
            message_count, tool_call_count, title)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            s["id"], s["source"], None, s["model"],
            json.dumps({"imported_from": "openclaw", "original_id": s["original_id"], "cwd": s["cwd"]}),
            None, None,
            s["started_at"], s["ended_at"], "imported",
            s["message_count"], tool_call_count, s["title"],
        ),
    )
    for m in s["messages"]:
        conn.execute(
            """INSERT INTO messages
               (session_id, role, content, tool_call_id, tool_calls, tool_name,
                timestamp, token_count, finish_reason, reasoning,
                reasoning_details, codex_reasoning_items)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s["id"], m["role"], m["content"], None,
                json.dumps(m["tool_calls"]) if m["tool_calls"] else None,
                None, m["timestamp"], m["token_count"], None, m["reasoning"],
                None, None,
            ),
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", default=",".join(DEFAULT_AGENTS), help="Comma-separated agent names (default: main,coder,paralegal)")
    ap.add_argument("--dry-run", action="store_true", help="Don't write to DB; print stats only")
    ap.add_argument("--source-root", default=str(OPENCLAW_ROOT), help="Path to ~/.openclaw/agents (default)")
    ap.add_argument("--db", default=str(HERMES_DB), help="Path to Hermes state.db")
    args = ap.parse_args()

    agents = [a.strip() for a in args.agent.split(",") if a.strip()]
    root = Path(args.source_root)
    stats = Stats()
    sessions: list[dict] = []

    for agent in agents:
        sess_dir = root / agent / "sessions"
        if not sess_dir.exists():
            print(f"[skip] {sess_dir} not found")
            continue
        files = sorted(sess_dir.glob("*.jsonl"))
        print(f"[scan] {agent}: {len(files)} files")
        for f in files:
            result = process_file(f, agent, stats)
            if result:
                sessions.append(result)

    print()
    print("=" * 60)
    print(f"Files seen:                 {stats.files_seen}")
    print(f"Files skipped (empty):      {stats.files_skipped_empty}")
    print(f"Files skipped (too short):  {stats.files_skipped_too_short}")
    print(f"Files skipped (auto-post):  {stats.files_skipped_delivery_mirror}")
    print(f"Sessions to import:         {stats.sessions_imported}")
    print(f"Messages to insert:         {stats.messages_inserted}")
    print(f"Messages dropped (boiler):  {stats.messages_skipped_boilerplate}")
    print(f"Messages dropped (empty):   {stats.messages_skipped_empty}")
    print()
    print("Per agent:")
    for a in sorted(stats.per_agent):
        d = stats.per_agent[a]
        print(f"  {a:10s}  sessions={d.get('sessions', 0):4d}  messages={d.get('messages', 0):5d}")
    print()

    if args.dry_run:
        print("DRY RUN — no database writes performed.")
        return 0

    print(f"Writing to {args.db} ...")
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("BEGIN")
        for s in sessions:
            insert_session(conn, s)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Done. Inserted {stats.sessions_imported} sessions / {stats.messages_inserted} messages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
