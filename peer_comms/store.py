from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_default_hermes_root, get_hermes_home

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_AGENT_TTL_SECONDS = 6 * 60 * 60
DEFAULT_MESSAGE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_PROMPT_CHARS = 200_000
MAX_RESPONSE_CHARS = 200_000
MAX_HOPS = 3


def _utc_now_ts() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    return time.strftime(ISO_FMT, time.gmtime(_utc_now_ts() if ts is None else ts))


def _profile_name() -> str:
    home = get_hermes_home()
    if home.parent.name == "profiles":
        return home.name
    return os.environ.get("HERMES_PROFILE", "default") or "default"


def get_peer_comms_dir() -> Path:
    """Return the shared local peer-comms directory.

    By default this is rooted at the Hermes root (``~/.hermes/peer-comms``),
    not a single profile, so separate local Hermes profiles can still find one
    another. Set ``HERMES_PEER_COMMS_DIR`` to force a custom shared mailbox.
    """
    override = os.environ.get("HERMES_PEER_COMMS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return get_default_hermes_root() / "peer-comms"


def default_db_path() -> Path:
    override = os.environ.get("HERMES_PEER_COMMS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return get_peer_comms_dir() / "peer_comms.sqlite"


class PeerCommsStore:
    """SQLite-backed local mailbox for peer Hermes agents."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path).expanduser() if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    project TEXT NOT NULL DEFAULT '',
                    cwd TEXT NOT NULL DEFAULT '',
                    profile TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'online',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project);
                CREATE INDEX IF NOT EXISTS idx_agents_updated ON agents(updated_at);

                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '',
                    response TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    hops INTEGER NOT NULL DEFAULT 0,
                    parent_msg_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_target_status ON messages(target_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project);

                CREATE TABLE IF NOT EXISTS peer_teams (
                    team_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    coordinator_id TEXT NOT NULL DEFAULT '',
                    agent_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_peer_teams_project ON peer_teams(project);
                CREATE INDEX IF NOT EXISTS idx_peer_teams_status ON peer_teams(status);
                """
            )

    def prune_expired(self) -> Dict[str, int]:
        now = _utc_now_ts()
        with self._connect() as con:
            agent_cur = con.execute("DELETE FROM agents WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            msg_cur = con.execute("DELETE FROM messages WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            return {"agents_deleted": agent_cur.rowcount, "messages_deleted": msg_cur.rowcount}

    def register_agent(
        self,
        *,
        name: str,
        agent_id: str = "",
        role: str = "",
        project: str = "",
        cwd: str = "",
        profile: str = "",
        session_id: str = "",
        model: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = DEFAULT_AGENT_TTL_SECONDS,
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        clean_id = (agent_id or clean_name).strip()
        now = _utc_now_ts()
        expires = now + max(60, int(ttl_seconds or DEFAULT_AGENT_TTL_SECONDS))
        meta = metadata or {}
        with self._connect() as con:
            existing = con.execute("SELECT created_at FROM agents WHERE id = ?", (clean_id,)).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            con.execute(
                """
                INSERT INTO agents(id, name, role, project, cwd, profile, session_id, model, status,
                                   metadata_json, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    role=excluded.role,
                    project=excluded.project,
                    cwd=excluded.cwd,
                    profile=excluded.profile,
                    session_id=excluded.session_id,
                    model=excluded.model,
                    status='online',
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at
                """,
                (
                    clean_id,
                    clean_name,
                    role or "",
                    project or "",
                    cwd or os.getcwd(),
                    profile or _profile_name(),
                    session_id or os.environ.get("HERMES_SESSION_ID", ""),
                    model or os.environ.get("HERMES_MODEL", ""),
                    json.dumps(meta, ensure_ascii=False, sort_keys=True),
                    created_at,
                    now,
                    expires,
                ),
            )
        return self.get_agent(clean_id) or {}

    def mark_offline(self, agent_id: str) -> bool:
        now = _utc_now_ts()
        with self._connect() as con:
            cur = con.execute("UPDATE agents SET status='offline', updated_at=? WHERE id=?", (now, agent_id))
            return cur.rowcount > 0

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        self._mark_stale_agents()
        with self._connect() as con:
            row = con.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return self._agent_to_dict(row) if row else None

    def list_agents(self, *, project: str = "", include_offline: bool = False, exclude_id: str = "") -> List[Dict[str, Any]]:
        self.prune_expired()
        self._mark_stale_agents()
        clauses: List[str] = []
        params: List[Any] = []
        if project:
            clauses.append("project = ?")
            params.append(project)
        if not include_offline:
            clauses.append("status = 'online'")
        if exclude_id:
            clauses.append("id != ?")
            params.append(exclude_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as con:
            rows = con.execute(f"SELECT * FROM agents{where} ORDER BY project, name, id", params).fetchall()
        return [self._agent_to_dict(r) for r in rows]

    def resolve_agent(self, target: str, *, project: str = "") -> Optional[Dict[str, Any]]:
        target = (target or "").strip()
        if not target:
            return None
        with self._connect() as con:
            row = con.execute("SELECT * FROM agents WHERE id = ?", (target,)).fetchone()
            if row:
                return self._agent_to_dict(row)
            if project:
                rows = con.execute(
                    "SELECT * FROM agents WHERE name = ? AND project = ? ORDER BY updated_at DESC",
                    (target, project),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM agents WHERE name = ? ORDER BY updated_at DESC", (target,)).fetchall()
        if len(rows) == 1:
            return self._agent_to_dict(rows[0])
        online = [r for r in rows if r["status"] == "online"]
        if len(online) == 1:
            return self._agent_to_dict(online[0])
        return None

    def send_message(
        self,
        *,
        sender_id: str,
        target: str,
        prompt: str,
        subject: str = "",
        project: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        parent_msg_id: str = "",
        ttl_seconds: int = DEFAULT_MESSAGE_TTL_SECONDS,
        hops: int = 0,
    ) -> Dict[str, Any]:
        sender_id = (sender_id or "").strip()
        if not sender_id:
            raise ValueError("sender_id is required; call peer_register first or pass sender_id")
        target_agent = self.resolve_agent(target, project=project)
        if not target_agent:
            raise ValueError(f"target agent not found or ambiguous: {target!r}")
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise ValueError("prompt is required")
        if len(clean_prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt is too large ({len(clean_prompt)} chars > {MAX_PROMPT_CHARS})")
        hops = int(hops or 0)
        if hops > MAX_HOPS:
            raise ValueError(f"hop limit exceeded ({hops} > {MAX_HOPS})")
        now = _utc_now_ts()
        msg_id = "peer_" + uuid.uuid4().hex[:16]
        expires = now + max(60, int(ttl_seconds or DEFAULT_MESSAGE_TTL_SECONDS))
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO messages(msg_id, sender_id, target_id, project, subject, prompt, response,
                                     status, hops, parent_msg_id, metadata_json, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, '', 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    sender_id,
                    target_agent["id"],
                    project or target_agent.get("project", ""),
                    subject or "",
                    clean_prompt,
                    hops,
                    parent_msg_id or "",
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    expires,
                ),
            )
        return self.get_message(msg_id) or {}

    def list_inbox(self, *, agent_id: str, status: str = "queued", project: str = "", limit: int = 20, mark_seen: bool = False) -> List[Dict[str, Any]]:
        self.prune_expired()
        clauses = ["target_id = ?"]
        params: List[Any] = [agent_id]
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if project:
            clauses.append("project = ?")
            params.append(project)
        params.append(max(1, min(int(limit or 20), 100)))
        with self._connect() as con:
            rows = con.execute(
                f"SELECT * FROM messages WHERE {' AND '.join(clauses)} ORDER BY created_at LIMIT ?",
                params,
            ).fetchall()
            if mark_seen:
                now = _utc_now_ts()
                original_ids = [r["msg_id"] for r in rows]
                queued_ids = [r["msg_id"] for r in rows if r["status"] == "queued"]
                con.executemany("UPDATE messages SET status='seen', updated_at=? WHERE msg_id=?", [(now, mid) for mid in queued_ids])
                if original_ids:
                    rows = con.execute(
                        f"SELECT * FROM messages WHERE msg_id IN ({','.join('?' for _ in original_ids)}) ORDER BY created_at",
                        original_ids,
                    ).fetchall()
        return [self._message_to_dict(r, include_prompt=True, include_response=True) for r in rows]

    def claim_message(self, *, msg_id: str, agent_id: str) -> Dict[str, Any]:
        now = _utc_now_ts()
        with self._connect() as con:
            cur = con.execute(
                "UPDATE messages SET status='in_progress', updated_at=? WHERE msg_id=? AND target_id=? AND status IN ('queued','seen')",
                (now, msg_id, agent_id),
            )
            if cur.rowcount == 0:
                row = con.execute("SELECT * FROM messages WHERE msg_id=?", (msg_id,)).fetchone()
            else:
                row = con.execute("SELECT * FROM messages WHERE msg_id=?", (msg_id,)).fetchone()
        if not row:
            raise ValueError(f"message not found: {msg_id}")
        return self._message_to_dict(row, include_prompt=True, include_response=True)

    def reply_message(self, *, msg_id: str, agent_id: str, response: str, status: str = "completed") -> Dict[str, Any]:
        clean = (response or "").strip()
        if not clean:
            raise ValueError("response is required")
        if len(clean) > MAX_RESPONSE_CHARS:
            raise ValueError(f"response is too large ({len(clean)} chars > {MAX_RESPONSE_CHARS})")
        if status not in {"completed", "failed"}:
            raise ValueError("status must be 'completed' or 'failed'")
        now = _utc_now_ts()
        with self._connect() as con:
            row = con.execute("SELECT * FROM messages WHERE msg_id=?", (msg_id,)).fetchone()
            if not row:
                raise ValueError(f"message not found: {msg_id}")
            if row["target_id"] != agent_id:
                raise ValueError("only the target agent can reply to this message")
            con.execute(
                "UPDATE messages SET response=?, status=?, updated_at=? WHERE msg_id=?",
                (clean, status, now, msg_id),
            )
        return self.get_message(msg_id, include_prompt=True, include_response=True) or {}

    def get_message(self, msg_id: str, *, include_prompt: bool = True, include_response: bool = True) -> Optional[Dict[str, Any]]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM messages WHERE msg_id = ?", (msg_id,)).fetchone()
        return self._message_to_dict(row, include_prompt=include_prompt, include_response=include_response) if row else None

    def await_message(self, msg_id: str, *, timeout_seconds: int = 60, poll_interval: float = 0.5) -> Dict[str, Any]:
        deadline = _utc_now_ts() + max(1, int(timeout_seconds or 60))
        while True:
            msg = self.get_message(msg_id, include_prompt=True, include_response=True)
            if not msg:
                raise ValueError(f"message not found: {msg_id}")
            if msg["status"] in {"completed", "failed"}:
                return msg
            if _utc_now_ts() >= deadline:
                return {**msg, "await_timed_out": True}
            time.sleep(max(0.1, min(float(poll_interval), 5.0)))

    def start_team(
        self,
        *,
        name: str,
        project: str = "",
        coordinator_id: str = "",
        agents: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = DEFAULT_AGENT_TTL_SECONDS,
    ) -> Dict[str, Any]:
        """Create a temporary peer team session and register its named agents.

        This is intentionally session-scoped rather than always-on.  The team is
        active until ``stop_team`` is called or the TTL expires.  Agents are
        registered in the normal peer registry with ``metadata.team_id`` so they
        can use the existing peer_send/peer_inbox/peer_reply mailbox while the
        team session is active.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        now = _utc_now_ts()
        ttl = max(60, int(ttl_seconds or DEFAULT_AGENT_TTL_SECONDS))
        expires = now + ttl
        team_id = "team_" + uuid.uuid4().hex[:12]
        clean_project = (project or clean_name).strip()
        agent_cards: List[Dict[str, Any]] = []
        agent_ids: List[str] = []
        for idx, agent in enumerate(agents or []):
            if not isinstance(agent, dict):
                raise ValueError("agents must be objects with at least a name")
            agent_name = (agent.get("name") or "").strip()
            if not agent_name:
                raise ValueError("each team agent requires a name")
            agent_id = (agent.get("agent_id") or f"{team_id}-{agent_name}").strip()
            agent_meta = dict(agent.get("metadata") or {})
            agent_meta.update({"team_id": team_id, "team_name": clean_name, "temporary_team": True})
            card = self.register_agent(
                name=agent_name,
                agent_id=agent_id,
                role=agent.get("role", ""),
                project=clean_project,
                cwd=agent.get("cwd", ""),
                profile=agent.get("profile", ""),
                session_id=agent.get("session_id", ""),
                model=agent.get("model", ""),
                metadata=agent_meta,
                ttl_seconds=ttl,
            )
            agent_cards.append(card)
            agent_ids.append(card["id"])
            if idx == 0 and not coordinator_id:
                coordinator_id = card["id"]
        team_meta = metadata or {}
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO peer_teams(team_id, name, project, status, coordinator_id, agent_ids_json,
                                       metadata_json, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    team_id,
                    clean_name,
                    clean_project,
                    coordinator_id or "",
                    json.dumps(agent_ids, ensure_ascii=False),
                    json.dumps(team_meta, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    expires,
                ),
            )
        team = self.get_team(team_id) or {}
        return {"team": team, "agents": agent_cards}

    def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        self._mark_stale_teams()
        with self._connect() as con:
            row = con.execute("SELECT * FROM peer_teams WHERE team_id=?", (team_id,)).fetchone()
        return self._team_to_dict(row) if row else None

    def list_teams(self, *, project: str = "", include_inactive: bool = False) -> List[Dict[str, Any]]:
        self._mark_stale_teams()
        clauses: List[str] = []
        params: List[Any] = []
        if project:
            clauses.append("project = ?")
            params.append(project)
        if not include_inactive:
            clauses.append("status = 'active'")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as con:
            rows = con.execute(f"SELECT * FROM peer_teams{where} ORDER BY updated_at DESC", params).fetchall()
        return [self._team_to_dict(r) for r in rows]

    def stop_team(self, *, team_id: str, reason: str = "") -> Dict[str, Any]:
        now = _utc_now_ts()
        with self._connect() as con:
            row = con.execute("SELECT * FROM peer_teams WHERE team_id=?", (team_id,)).fetchone()
            if not row:
                raise ValueError(f"team not found: {team_id}")
            agent_ids = self._safe_json_list(row["agent_ids_json"])
            con.execute(
                "UPDATE peer_teams SET status='stopped', updated_at=?, metadata_json=? WHERE team_id=?",
                (
                    now,
                    json.dumps({**self._safe_json(row["metadata_json"]), "stop_reason": reason or "user stopped"}, ensure_ascii=False, sort_keys=True),
                    team_id,
                ),
            )
            con.executemany(
                "UPDATE agents SET status='offline', updated_at=?, expires_at=? WHERE id=?",
                [(now, now, agent_id) for agent_id in agent_ids],
            )
        return self.get_team(team_id) or {}

    def _mark_stale_agents(self) -> None:
        now = _utc_now_ts()
        with self._connect() as con:
            con.execute(
                "UPDATE agents SET status='stale' WHERE expires_at IS NOT NULL AND expires_at < ? AND status='online'",
                (now,),
            )

    def _mark_stale_teams(self) -> None:
        now = _utc_now_ts()
        with self._connect() as con:
            rows = con.execute(
                "SELECT team_id, agent_ids_json FROM peer_teams WHERE expires_at IS NOT NULL AND expires_at < ? AND status='active'",
                (now,),
            ).fetchall()
            team_ids = [r["team_id"] for r in rows]
            agent_ids: List[str] = []
            for row in rows:
                agent_ids.extend(self._safe_json_list(row["agent_ids_json"]))
            if team_ids:
                con.executemany("UPDATE peer_teams SET status='expired', updated_at=? WHERE team_id=?", [(now, tid) for tid in team_ids])
            if agent_ids:
                con.executemany("UPDATE agents SET status='stale', updated_at=? WHERE id=? AND status='online'", [(now, aid) for aid in agent_ids])

    def _agent_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        metadata = self._safe_json(row["metadata_json"])
        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "project": row["project"],
            "cwd": row["cwd"],
            "profile": row["profile"],
            "session_id": row["session_id"],
            "model": row["model"],
            "status": row["status"],
            "metadata": metadata,
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "expires_at": _iso(row["expires_at"]) if row["expires_at"] else None,
        }

    def _message_to_dict(self, row: sqlite3.Row, *, include_prompt: bool, include_response: bool) -> Dict[str, Any]:
        out = {
            "msg_id": row["msg_id"],
            "sender_id": row["sender_id"],
            "target_id": row["target_id"],
            "project": row["project"],
            "subject": row["subject"],
            "status": row["status"],
            "hops": row["hops"],
            "parent_msg_id": row["parent_msg_id"],
            "metadata": self._safe_json(row["metadata_json"]),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "expires_at": _iso(row["expires_at"]) if row["expires_at"] else None,
        }
        if include_prompt:
            out["prompt"] = row["prompt"]
        if include_response:
            out["response"] = row["response"]
        return out

    def _team_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        agent_ids = self._safe_json_list(row["agent_ids_json"])
        return {
            "team_id": row["team_id"],
            "name": row["name"],
            "project": row["project"],
            "status": row["status"],
            "coordinator_id": row["coordinator_id"],
            "agent_ids": agent_ids,
            "metadata": self._safe_json(row["metadata_json"]),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "expires_at": _iso(row["expires_at"]) if row["expires_at"] else None,
        }

    @staticmethod
    def _safe_json(raw: str) -> Dict[str, Any]:
        try:
            val = json.loads(raw or "{}")
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _safe_json_list(raw: str) -> List[str]:
        try:
            val = json.loads(raw or "[]")
            if isinstance(val, list):
                return [str(item) for item in val]
        except Exception:
            pass
        return []
