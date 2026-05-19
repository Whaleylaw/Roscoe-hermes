from __future__ import annotations

"""High-level launcher for temporary peer-agent teams.

This module lets a foreground chat agent start a bounded peer team without the
user opening terminals by hand.  It composes the existing primitives:

1. create a temporary team row,
2. start temporary runner processes for selected agents,
3. optionally seed the team with an initial peer message.

It is intentionally not an always-on daemon.  All runners are tied to a team id
and are stopped by ``peer_team_stop`` or by TTL/team expiry.
"""

import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_default_hermes_root
from .runner import start_runner_process
from .store import PeerCommsStore, default_db_path, get_peer_comms_dir


DEFAULT_AGENT_TOOLSETS = "peer_comms,file,terminal"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _profile_home(profile: str = "", profile_home: str = "") -> str:
    """Resolve a profile name/home to a HERMES_HOME path.

    ``profile_home`` is accepted for tests and custom deployments.  For normal
    named profiles this mirrors hermes_cli.profiles.get_profile_dir without
    requiring the profile CLI to be imported at module load time.
    """
    if profile_home:
        return str(Path(profile_home).expanduser())
    profile = (profile or "").strip().lower()
    if not profile:
        return ""
    if profile == "default":
        return str(get_default_hermes_root())
    return str(get_default_hermes_root() / "profiles" / profile)


def _build_hermes_command(agent: Dict[str, Any]) -> str:
    """Build a safe argv-style command template for one launched agent."""
    if agent.get("command"):
        return str(agent["command"])

    repo = _repo_root()
    cli_path = repo / "cli.py"
    profile_home = _profile_home(str(agent.get("profile") or ""), str(agent.get("profile_home") or ""))
    toolsets = str(agent.get("toolsets") or DEFAULT_AGENT_TOOLSETS)

    argv: List[str] = ["/usr/bin/env"]
    if profile_home:
        argv.append(f"HERMES_HOME={profile_home}")
    # Keep the child agent bound to this shared peer hub even when it uses a
    # different profile HERMES_HOME.  Otherwise each profile would get an
    # isolated peer_comms DB and never see the team's messages.
    argv.append(f"HERMES_PEER_COMMS_DIR={get_peer_comms_dir()}")
    argv.append(f"HERMES_PEER_AGENT_ID={agent.get('agent_id') or agent.get('name') or ''}")
    argv.extend([
        sys.executable,
        str(cli_path),
        "--quiet",
        "--toolsets",
        toolsets,
        "-q",
        "{prompt}",
    ])
    return shlex.join(argv)


def normalize_launch_agents(agents: Any) -> List[Dict[str, Any]]:
    if not isinstance(agents, list):
        raise ValueError("agents must be a list of agent objects")
    normalized: List[Dict[str, Any]] = []
    for raw in agents:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("agent_id") or "").strip()
        agent_id = str(raw.get("agent_id") or name.lower().replace(" ", "-")).strip()
        if not name or not agent_id:
            raise ValueError("each agent needs a name or agent_id")
        item = dict(raw)
        item["name"] = name
        item["agent_id"] = agent_id
        item.setdefault("role", "")
        item.setdefault("cwd", "")
        item.setdefault("metadata", {})
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one valid agent is required")
    return normalized


def launch_team(
    *,
    name: str,
    agents: List[Dict[str, Any]],
    project: str = "",
    coordinator_id: str = "",
    initial_task: str = "",
    initial_target: str = "",
    initial_subject: str = "Initial peer-team task",
    sender_id: str = "user",
    metadata: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 6 * 60 * 60,
    poll_seconds: float = 1.0,
    command_timeout_seconds: int = 1800,
    await_initial_response: bool = False,
    await_timeout_seconds: int = 0,
    store: Optional[PeerCommsStore] = None,
) -> Dict[str, Any]:
    """Create a temporary team, start runners, and optionally seed a task."""
    if not name:
        raise ValueError("name is required")
    store = store or PeerCommsStore()
    normalized_agents = normalize_launch_agents(agents)
    project = project or name
    coordinator_id = coordinator_id or (normalized_agents[0]["agent_id"] if normalized_agents else "")

    team_result = store.start_team(
        name=name,
        project=project,
        coordinator_id=coordinator_id,
        agents=normalized_agents,
        metadata={**(metadata or {}), "launched_from_chat": True},
        ttl_seconds=ttl_seconds,
    )
    team = team_result["team"]
    team_id = team["team_id"]

    runners: List[Dict[str, Any]] = []
    for agent in normalized_agents:
        if agent.get("run") is False:
            continue
        runner = start_runner_process(
            agent_id=agent["agent_id"],
            project=project,
            team_id=team_id,
            name=agent["name"],
            role=str(agent.get("role") or ""),
            command=_build_hermes_command(agent),
            cwd=str(agent.get("cwd") or ""),
            poll_seconds=float(agent.get("poll_seconds") or poll_seconds),
            ttl_seconds=int(agent.get("ttl_seconds") or ttl_seconds),
            command_timeout_seconds=int(agent.get("command_timeout_seconds") or command_timeout_seconds),
        )
        runners.append({"agent_id": agent["agent_id"], **runner})

    message = None
    awaited = None
    if initial_task:
        target = initial_target or next(
            (a["agent_id"] for a in normalized_agents if a["agent_id"] != sender_id),
            normalized_agents[0]["agent_id"],
        )
        message = store.send_message(
            sender_id=sender_id,
            target=target,
            project=project,
            subject=initial_subject or "Initial peer-team task",
            prompt=initial_task,
            metadata={"team_id": team_id, "launched_from_chat": True},
            ttl_seconds=ttl_seconds,
        )
        if await_initial_response:
            awaited = store.await_message(
                message["msg_id"],
                timeout_seconds=max(1, int(await_timeout_seconds or command_timeout_seconds)),
                poll_interval=0.25,
            )

    return {
        "team": team,
        "agents": normalized_agents,
        "runners": runners,
        "initial_message": message,
        "awaited_initial_response": awaited,
        "hub_dir": str(get_peer_comms_dir()),
        "db_path": str(default_db_path()),
    }
