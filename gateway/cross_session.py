"""Resolve a session_target spec to a concrete gateway session + case folder.

Used by tools/delegate_tool.py so a child agent spawned from #perry (or DM,
or Telegram) can write its transcript into a *different* gateway session —
typically the per-case Slack channel session that owns the work.

Spec forms accepted:
    slack:<channel_id>          e.g. slack:C0AH0V6G2Q1
    slack:#<channel_name>        e.g. slack:#abby-sitgraves
    case:<slug>                  e.g. case:abby-sitgraves   (Paralegal only)

Returns a :class:`SessionTarget` with the existing gateway session_id, the
absolute case-folder cwd, and the underlying platform + chat_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from gateway.mirror import find_session_id
from hermes_cli.config import get_hermes_home

logger = logging.getLogger(__name__)


class SessionTargetError(ValueError):
    """Raised when a session_target spec cannot be resolved."""


@dataclass(frozen=True)
class SessionTarget:
    session_id: str
    cwd: Optional[str]
    platform: str
    chat_id: str
    channel_name: Optional[str]


def _default_case_channels_path() -> Path:
    return get_hermes_home() / "case_channels.yaml"


def _load_case_channels(path: Optional[Path]) -> dict:
    p = Path(path) if path else _default_case_channels_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("case_channels load failed (%s): %s", p, e)
        return {}
    return data if isinstance(data, dict) else {}


def resolve_session_target(
    spec: str,
    case_channels_path: Optional[Path] = None,
) -> SessionTarget:
    """Resolve a session_target spec to a SessionTarget.

    Raises SessionTargetError if the spec can't be parsed, the case isn't
    mapped, or no gateway session exists yet for the channel.
    """
    if not spec or ":" not in spec:
        raise SessionTargetError(
            f"session_target must be 'slack:<id|#name>' or 'case:<slug>', got {spec!r}"
        )

    kind, _, value = spec.partition(":")
    kind = kind.strip().lower()
    value = value.strip()

    case_map = _load_case_channels(case_channels_path)
    slug_to_channel = case_map.get("slug_to_channel") or {}
    channel_to_cwd = case_map.get("channel_to_cwd") or {}
    channel_to_slug = case_map.get("channel_to_slug") or {}

    if kind == "case":
        channel_id = slug_to_channel.get(value)
        if not channel_id:
            raise SessionTargetError(f"Unknown case slug: {value}")
        platform = "slack"
        chat_id = channel_id
        channel_name = value
    elif kind == "slack":
        if value.startswith("#"):
            name = value[1:]
            channel_id = slug_to_channel.get(name)
            if not channel_id:
                raise SessionTargetError(
                    f"Slack channel #{name} is not in case_channels.yaml"
                )
            channel_name = name
        else:
            channel_id = value
            channel_name = channel_to_slug.get(channel_id)
        platform = "slack"
        chat_id = channel_id
    else:
        raise SessionTargetError(
            f"Unsupported session_target kind {kind!r} (expected 'slack' or 'case')"
        )

    session_id = find_session_id(platform, chat_id)
    if not session_id:
        raise SessionTargetError(
            f"{platform}:{chat_id} has no gateway session yet — send any "
            "message in that channel first so the gateway records its origin."
        )

    cwd = channel_to_cwd.get(chat_id)
    return SessionTarget(
        session_id=session_id,
        cwd=cwd,
        platform=platform,
        chat_id=chat_id,
        channel_name=channel_name,
    )
