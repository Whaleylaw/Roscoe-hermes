from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AgentRecord:
    id: str
    name: str
    role: str = ""
    project: str = ""
    cwd: str = ""
    profile: str = ""
    session_id: str = ""
    model: str = ""
    status: str = "online"
    metadata: Optional[Dict[str, Any]] = None
    created_at: str = ""
    updated_at: str = ""
    expires_at: Optional[str] = None


@dataclass(frozen=True)
class PeerMessage:
    msg_id: str
    sender_id: str
    target_id: str
    project: str = ""
    subject: str = ""
    prompt: str = ""
    response: str = ""
    status: str = "queued"
    hops: int = 0
    parent_msg_id: str = ""
    metadata: Optional[Dict[str, Any]] = None
    created_at: str = ""
    updated_at: str = ""
    expires_at: Optional[str] = None
