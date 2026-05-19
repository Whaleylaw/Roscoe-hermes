from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from peer_comms.launcher import launch_team
from peer_comms.runner import runner_status, start_runner_process, stop_runner
from peer_comms.store import PeerCommsStore, default_db_path, get_peer_comms_dir
from tools.registry import registry


def _ok(**kwargs: Any) -> str:
    return json.dumps({"success": True, **kwargs}, ensure_ascii=False)


def _err(message: str, **kwargs: Any) -> str:
    return json.dumps({"success": False, "error": message, **kwargs}, ensure_ascii=False)


def _store() -> PeerCommsStore:
    return PeerCommsStore()


def _parse_metadata(metadata: Optional[Dict[str, Any] | str]) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str) and metadata.strip():
        try:
            data = json.loads(metadata)
            return data if isinstance(data, dict) else {"value": data}
        except json.JSONDecodeError:
            return {"note": metadata}
    return {}


def _parse_agents(agents: Optional[list[Dict[str, Any]] | str]) -> list[Dict[str, Any]]:
    if agents is None:
        return []
    if isinstance(agents, list):
        return [a for a in agents if isinstance(a, dict)]
    if isinstance(agents, str) and agents.strip():
        data = json.loads(agents)
        if isinstance(data, list):
            return [a for a in data if isinstance(a, dict)]
    return []


def _self_id(agent_id: str = "") -> str:
    agent_id = (agent_id or "").strip()
    if agent_id:
        return agent_id
    env_id = os.environ.get("HERMES_PEER_AGENT_ID", "").strip()
    if env_id:
        return env_id
    session_id = os.environ.get("HERMES_SESSION_ID", "").strip()
    if session_id:
        return session_id
    raise ValueError("agent_id is required. Call peer_register first, pass agent_id, or set HERMES_PEER_AGENT_ID.")


PEER_REGISTER_SCHEMA = {
    "name": "peer_register",
    "description": (
        "Register or refresh this Hermes agent in the local peer-comms hub. "
        "Use this at the start of a builder/tester/reviewer session so other agents can send work directly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human-friendly agent name, e.g. builder, tester, reviewer."},
            "agent_id": {"type": "string", "description": "Stable unique id. Defaults to name if omitted."},
            "role": {"type": "string", "description": "Agent role/capability summary."},
            "project": {"type": "string", "description": "Project/case namespace, e.g. roscoe-hermes."},
            "cwd": {"type": "string", "description": "Working directory for this agent."},
            "profile": {"type": "string", "description": "Hermes profile name. Auto-detected if omitted."},
            "session_id": {"type": "string", "description": "Optional Hermes session id."},
            "model": {"type": "string", "description": "Optional model/provider label."},
            "metadata": {"type": "object", "description": "Optional extra agent card metadata."},
            "ttl_seconds": {"type": "integer", "description": "How long this registration stays online without refresh. Default 6 hours."},
        },
        "required": ["name"],
    },
}


def peer_register(
    name: str,
    agent_id: str = "",
    role: str = "",
    project: str = "",
    cwd: str = "",
    profile: str = "",
    session_id: str = "",
    model: str = "",
    metadata: Optional[Dict[str, Any] | str] = None,
    ttl_seconds: int = 6 * 60 * 60,
) -> str:
    try:
        agent = _store().register_agent(
            name=name,
            agent_id=agent_id,
            role=role,
            project=project,
            cwd=cwd,
            profile=profile,
            session_id=session_id,
            model=model,
            metadata=_parse_metadata(metadata),
            ttl_seconds=ttl_seconds,
        )
        return _ok(agent=agent, hub_dir=str(get_peer_comms_dir()), db_path=str(default_db_path()))
    except Exception as exc:
        return _err(str(exc))


PEER_LIST_SCHEMA = {
    "name": "peer_list",
    "description": "List registered local peer agents, optionally scoped by project.",
    "parameters": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "Only show agents for this project namespace."},
            "include_offline": {"type": "boolean", "description": "Include offline/stale agents."},
            "exclude_id": {"type": "string", "description": "Hide this agent id from results."},
        },
    },
}


def peer_list(project: str = "", include_offline: bool = False, exclude_id: str = "") -> str:
    try:
        return _ok(agents=_store().list_agents(project=project, include_offline=include_offline, exclude_id=exclude_id))
    except Exception as exc:
        return _err(str(exc))


PEER_TEAM_START_SCHEMA = {
    "name": "peer_team_start",
    "description": (
        "Start a temporary peer-to-peer agent team session. This is not always-on A2A: it creates a session-scoped "
        "team with a TTL, registers the named peers, and lets them use peer_send/peer_inbox/peer_reply until "
        "peer_team_stop is called or the TTL expires."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human name for the temporary team session, e.g. roscoe builder+tester."},
            "project": {"type": "string", "description": "Project namespace shared by the team. Defaults to name."},
            "coordinator_id": {"type": "string", "description": "Optional coordinator/primary agent id."},
            "agents": {
                "type": "array",
                "description": "Agents to register for this team session.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "role": {"type": "string"},
                        "profile": {"type": "string"},
                        "cwd": {"type": "string"},
                        "model": {"type": "string"},
                        "session_id": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["name"],
                },
            },
            "metadata": {"type": "object", "description": "Optional team metadata."},
            "ttl_seconds": {"type": "integer", "description": "How long the temporary team stays active without refresh. Default 6 hours."},
        },
        "required": ["name", "agents"],
    },
}


def peer_team_start(
    name: str,
    agents: Optional[list[Dict[str, Any]] | str] = None,
    project: str = "",
    coordinator_id: str = "",
    metadata: Optional[Dict[str, Any] | str] = None,
    ttl_seconds: int = 6 * 60 * 60,
) -> str:
    try:
        result = _store().start_team(
            name=name,
            project=project,
            coordinator_id=coordinator_id,
            agents=_parse_agents(agents),
            metadata=_parse_metadata(metadata),
            ttl_seconds=ttl_seconds,
        )
        return _ok(**result, hub_dir=str(get_peer_comms_dir()), db_path=str(default_db_path()))
    except Exception as exc:
        return _err(str(exc))


PEER_TEAM_STATUS_SCHEMA = {
    "name": "peer_team_status",
    "description": "Show active/stopped/expired temporary peer team sessions and their registered peers.",
    "parameters": {
        "type": "object",
        "properties": {
            "team_id": {"type": "string", "description": "Specific team id to inspect."},
            "project": {"type": "string", "description": "Only show teams for this project namespace."},
            "include_inactive": {"type": "boolean", "description": "Include stopped/expired teams."},
        },
    },
}


def peer_team_status(team_id: str = "", project: str = "", include_inactive: bool = False) -> str:
    try:
        store = _store()
        if team_id:
            team = store.get_team(team_id)
            if not team:
                return _err(f"team not found: {team_id}")
            agents = [store.get_agent(agent_id) for agent_id in team.get("agent_ids", [])]
            return _ok(team=team, agents=[a for a in agents if a])
        teams = store.list_teams(project=project, include_inactive=include_inactive)
        return _ok(teams=teams)
    except Exception as exc:
        return _err(str(exc))


PEER_TEAM_LAUNCH_SCHEMA = {
    "name": "peer_team_launch",
    "description": (
        "Start a complete temporary peer-agent team directly from chat: create the team, spawn bounded "
        "runner processes for the requested agents, and optionally send an initial task. This is the "
        "one-call path for 'start a team with Coder and Paralegal and give them this task' without the "
        "user opening terminal windows. It is still bounded: peer_team_stop stops the team and runners."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human name for the temporary team session."},
            "project": {"type": "string", "description": "Project/case namespace. Defaults to name."},
            "coordinator_id": {"type": "string", "description": "Optional coordinator id. Defaults to first agent."},
            "agents": {
                "type": "array",
                "description": "Agents to register and start. Each agent may specify profile/cwd/toolsets/command/run=false.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "role": {"type": "string"},
                        "profile": {"type": "string", "description": "Named Hermes profile, e.g. coder or paralegal."},
                        "profile_home": {"type": "string", "description": "Explicit HERMES_HOME override for custom/test profiles."},
                        "cwd": {"type": "string"},
                        "toolsets": {"type": "string", "description": "Comma-separated toolsets for the spawned Hermes command."},
                        "command": {"type": "string", "description": "Optional command template override; supports {prompt}."},
                        "run": {"type": "boolean", "description": "Set false to register but not spawn a runner."},
                        "metadata": {"type": "object"},
                    },
                    "required": ["name"],
                },
            },
            "initial_task": {"type": "string", "description": "Optional first task/message to send after launch."},
            "initial_target": {"type": "string", "description": "Agent id/name to receive initial_task. Defaults to first agent not sender_id."},
            "initial_subject": {"type": "string", "description": "Subject for initial task."},
            "sender_id": {"type": "string", "description": "Sender id for initial_task. Defaults to user."},
            "metadata": {"type": "object"},
            "ttl_seconds": {"type": "integer", "description": "Team/runner TTL. Default 6 hours."},
            "poll_seconds": {"type": "number", "description": "Runner inbox polling interval. Default 1.0."},
            "command_timeout_seconds": {"type": "integer", "description": "Timeout for each one-shot agent command. Default 1800."},
            "await_initial_response": {"type": "boolean", "description": "If true, wait for initial_task to complete before returning."},
            "await_timeout_seconds": {"type": "integer", "description": "Max wait when await_initial_response is true."},
        },
        "required": ["name", "agents"],
    },
}


def peer_team_launch(
    name: str,
    agents: Optional[list[Dict[str, Any]] | str] = None,
    project: str = "",
    coordinator_id: str = "",
    initial_task: str = "",
    initial_target: str = "",
    initial_subject: str = "Initial peer-team task",
    sender_id: str = "user",
    metadata: Optional[Dict[str, Any] | str] = None,
    ttl_seconds: int = 6 * 60 * 60,
    poll_seconds: float = 1.0,
    command_timeout_seconds: int = 1800,
    await_initial_response: bool = False,
    await_timeout_seconds: int = 0,
) -> str:
    try:
        result = launch_team(
            name=name,
            project=project,
            coordinator_id=coordinator_id,
            agents=_parse_agents(agents),
            initial_task=initial_task,
            initial_target=initial_target,
            initial_subject=initial_subject,
            sender_id=sender_id,
            metadata=_parse_metadata(metadata),
            ttl_seconds=ttl_seconds,
            poll_seconds=poll_seconds,
            command_timeout_seconds=command_timeout_seconds,
            await_initial_response=await_initial_response,
            await_timeout_seconds=await_timeout_seconds,
        )
        return _ok(**result)
    except Exception as exc:
        return _err(str(exc))


PEER_TEAM_STOP_SCHEMA = {
    "name": "peer_team_stop",
    "description": "Stop a temporary peer team session and mark its registered agents offline.",
    "parameters": {
        "type": "object",
        "properties": {
            "team_id": {"type": "string", "description": "Team id returned by peer_team_start."},
            "reason": {"type": "string", "description": "Optional stop reason."},
        },
        "required": ["team_id"],
    },
}


def peer_team_stop(team_id: str, reason: str = "") -> str:
    try:
        # Stop any temporary inbound runners tied to this team before marking
        # the room closed. This keeps peer-team sessions bounded instead of
        # becoming an always-on background mesh.
        stopped_runners = stop_runner(team_id=team_id)
        team = _store().stop_team(team_id=team_id, reason=reason)
        return _ok(team=team, stopped_runners=stopped_runners.get("stopped", []))
    except Exception as exc:
        return _err(str(exc))


PEER_RUNNER_START_SCHEMA = {
    "name": "peer_runner_start",
    "description": (
        "Start a temporary inbound watcher/runner for one peer agent. While it is running, queued peer messages "
        "for that agent are claimed automatically, sent to a one-shot command (default: Hermes CLI -q), and the "
        "command output is written back with peer_reply. Use this only for an active peer team session; stop it "
        "with peer_runner_stop or peer_team_stop when the work is done."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Peer agent id to run, e.g. paralegal or tester."},
            "project": {"type": "string", "description": "Project/team namespace to poll."},
            "team_id": {"type": "string", "description": "Optional peer team id; runner exits when the team stops/expires."},
            "name": {"type": "string", "description": "Human-friendly name for registration refresh."},
            "role": {"type": "string", "description": "Role/capability summary for registration refresh."},
            "command": {"type": "string", "description": "Optional command template. Supports {prompt}, {msg_id}, {subject}, {sender_id}, {project}. Defaults to Hermes CLI --quiet -q {prompt}."},
            "cwd": {"type": "string", "description": "Working directory for the runner command."},
            "poll_seconds": {"type": "number", "description": "Inbox polling interval. Default 1.0."},
            "ttl_seconds": {"type": "integer", "description": "Agent heartbeat TTL. Default 6 hours."},
            "command_timeout_seconds": {"type": "integer", "description": "Timeout for each one-shot command. Default 1800 seconds."},
        },
        "required": ["agent_id", "project"],
    },
}


def peer_runner_start(
    agent_id: str,
    project: str,
    team_id: str = "",
    name: str = "",
    role: str = "",
    command: str = "",
    cwd: str = "",
    poll_seconds: float = 1.0,
    ttl_seconds: int = 6 * 60 * 60,
    command_timeout_seconds: int = 1800,
) -> str:
    try:
        result = start_runner_process(
            agent_id=agent_id,
            project=project,
            team_id=team_id,
            name=name,
            role=role,
            command=command,
            cwd=cwd,
            poll_seconds=poll_seconds,
            ttl_seconds=ttl_seconds,
            command_timeout_seconds=command_timeout_seconds,
        )
        return _ok(**result)
    except Exception as exc:
        return _err(str(exc))


PEER_RUNNER_STATUS_SCHEMA = {
    "name": "peer_runner_status",
    "description": "Show temporary peer-team inbound runner processes and whether they are alive.",
    "parameters": {
        "type": "object",
        "properties": {
            "team_id": {"type": "string", "description": "Optional team id filter."},
            "agent_id": {"type": "string", "description": "Optional agent id filter."},
        },
    },
}


def peer_runner_status(team_id: str = "", agent_id: str = "") -> str:
    try:
        return _ok(**runner_status(team_id=team_id, agent_id=agent_id))
    except Exception as exc:
        return _err(str(exc))


PEER_RUNNER_STOP_SCHEMA = {
    "name": "peer_runner_stop",
    "description": "Stop one or more temporary peer-team inbound runner processes.",
    "parameters": {
        "type": "object",
        "properties": {
            "team_id": {"type": "string", "description": "Optional team id filter."},
            "agent_id": {"type": "string", "description": "Optional agent id filter."},
        },
    },
}


def peer_runner_stop(team_id: str = "", agent_id: str = "") -> str:
    try:
        return _ok(**stop_runner(team_id=team_id, agent_id=agent_id))
    except Exception as exc:
        return _err(str(exc))


PEER_SEND_SCHEMA = {
    "name": "peer_send",
    "description": (
        "Send a task/prompt to another registered local peer agent. The target agent receives it via peer_inbox, "
        "then answers with peer_reply. Use peer_get or peer_await to retrieve the result. Do not use this to reply "
        "to an inbound peer message; use peer_reply instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sender_id": {"type": "string", "description": "Your registered agent id. Defaults to env/session if available."},
            "target": {"type": "string", "description": "Target agent id or unique target name."},
            "prompt": {"type": "string", "description": "The task or message for the peer agent."},
            "subject": {"type": "string", "description": "Short subject/title for the message."},
            "project": {"type": "string", "description": "Project namespace used to resolve target names."},
            "metadata": {"type": "object", "description": "Optional structured metadata."},
            "parent_msg_id": {"type": "string", "description": "Optional parent peer message id."},
            "ttl_seconds": {"type": "integer", "description": "Message expiry TTL. Default 7 days."},
        },
        "required": ["target", "prompt"],
    },
}


def peer_send(
    target: str,
    prompt: str,
    sender_id: str = "",
    subject: str = "",
    project: str = "",
    metadata: Optional[Dict[str, Any] | str] = None,
    parent_msg_id: str = "",
    ttl_seconds: int = 7 * 24 * 60 * 60,
) -> str:
    try:
        msg = _store().send_message(
            sender_id=_self_id(sender_id),
            target=target,
            prompt=prompt,
            subject=subject,
            project=project,
            metadata=_parse_metadata(metadata),
            parent_msg_id=parent_msg_id,
            ttl_seconds=ttl_seconds,
        )
        return _ok(message=msg)
    except Exception as exc:
        return _err(str(exc))


PEER_INBOX_SCHEMA = {
    "name": "peer_inbox",
    "description": (
        "Check inbound messages for this agent. A tester/reviewer agent should call this to receive tasks sent by a builder."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Your registered agent id. Defaults to env/session if available."},
            "status": {"type": "string", "enum": ["queued", "seen", "in_progress", "completed", "failed", "all"], "description": "Message status filter."},
            "project": {"type": "string", "description": "Project namespace filter."},
            "limit": {"type": "integer", "description": "Max messages to return, capped at 100."},
            "mark_seen": {"type": "boolean", "description": "Mark queued returned messages as seen."},
        },
    },
}


def peer_inbox(agent_id: str = "", status: str = "queued", project: str = "", limit: int = 20, mark_seen: bool = False) -> str:
    try:
        return _ok(messages=_store().list_inbox(agent_id=_self_id(agent_id), status=status, project=project, limit=limit, mark_seen=mark_seen))
    except Exception as exc:
        return _err(str(exc))


PEER_CLAIM_SCHEMA = {
    "name": "peer_claim",
    "description": "Claim an inbound peer message as in-progress before working on it.",
    "parameters": {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Peer message id."},
            "agent_id": {"type": "string", "description": "Your registered agent id. Defaults to env/session if available."},
        },
        "required": ["msg_id"],
    },
}


def peer_claim(msg_id: str, agent_id: str = "") -> str:
    try:
        return _ok(message=_store().claim_message(msg_id=msg_id, agent_id=_self_id(agent_id)))
    except Exception as exc:
        return _err(str(exc))


PEER_REPLY_SCHEMA = {
    "name": "peer_reply",
    "description": "Reply to an inbound peer message. This completes/fails the message so the sender can retrieve it with peer_get/peer_await.",
    "parameters": {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Peer message id being answered."},
            "agent_id": {"type": "string", "description": "Your registered agent id. Defaults to env/session if available."},
            "response": {"type": "string", "description": "Final response for the sender."},
            "status": {"type": "string", "enum": ["completed", "failed"], "description": "Whether the task completed or failed."},
        },
        "required": ["msg_id", "response"],
    },
}


def peer_reply(msg_id: str, response: str, agent_id: str = "", status: str = "completed") -> str:
    try:
        return _ok(message=_store().reply_message(msg_id=msg_id, agent_id=_self_id(agent_id), response=response, status=status))
    except Exception as exc:
        return _err(str(exc))


PEER_GET_SCHEMA = {
    "name": "peer_get",
    "description": "Get a peer message by id, including current status and response if available.",
    "parameters": {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Peer message id."},
            "include_prompt": {"type": "boolean", "description": "Include original prompt in output."},
            "include_response": {"type": "boolean", "description": "Include peer response in output."},
        },
        "required": ["msg_id"],
    },
}


def peer_get(msg_id: str, include_prompt: bool = True, include_response: bool = True) -> str:
    try:
        msg = _store().get_message(msg_id, include_prompt=include_prompt, include_response=include_response)
        if not msg:
            return _err(f"message not found: {msg_id}")
        return _ok(message=msg)
    except Exception as exc:
        return _err(str(exc))


PEER_AWAIT_SCHEMA = {
    "name": "peer_await",
    "description": "Wait for a peer message to complete/fail, returning early on timeout with await_timed_out=true.",
    "parameters": {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Peer message id."},
            "timeout_seconds": {"type": "integer", "description": "Maximum seconds to wait."},
        },
        "required": ["msg_id"],
    },
}


def peer_await(msg_id: str, timeout_seconds: int = 60) -> str:
    try:
        return _ok(message=_store().await_message(msg_id, timeout_seconds=timeout_seconds))
    except Exception as exc:
        return _err(str(exc))


PEER_OFFLINE_SCHEMA = {
    "name": "peer_offline",
    "description": "Mark this agent offline in the local peer-comms registry.",
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Your registered agent id. Defaults to env/session if available."},
        },
    },
}


def peer_offline(agent_id: str = "") -> str:
    try:
        return _ok(offline=_store().mark_offline(_self_id(agent_id)))
    except Exception as exc:
        return _err(str(exc))


registry.register(
    name="peer_register",
    toolset="peer_comms",
    schema=PEER_REGISTER_SCHEMA,
    handler=lambda args, **kw: peer_register(**args),
    description=PEER_REGISTER_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_list",
    toolset="peer_comms",
    schema=PEER_LIST_SCHEMA,
    handler=lambda args, **kw: peer_list(**args),
    description=PEER_LIST_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_team_start",
    toolset="peer_comms",
    schema=PEER_TEAM_START_SCHEMA,
    handler=lambda args, **kw: peer_team_start(**args),
    description=PEER_TEAM_START_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_team_status",
    toolset="peer_comms",
    schema=PEER_TEAM_STATUS_SCHEMA,
    handler=lambda args, **kw: peer_team_status(**args),
    description=PEER_TEAM_STATUS_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_team_launch",
    toolset="peer_comms",
    schema=PEER_TEAM_LAUNCH_SCHEMA,
    handler=lambda args, **kw: peer_team_launch(**args),
    description=PEER_TEAM_LAUNCH_SCHEMA.get("description", ""),
    emoji="🚀",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_team_stop",
    toolset="peer_comms",
    schema=PEER_TEAM_STOP_SCHEMA,
    handler=lambda args, **kw: peer_team_stop(**args),
    description=PEER_TEAM_STOP_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_runner_start",
    toolset="peer_comms",
    schema=PEER_RUNNER_START_SCHEMA,
    handler=lambda args, **kw: peer_runner_start(**args),
    description=PEER_RUNNER_START_SCHEMA.get("description", ""),
    emoji="🏃",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_runner_status",
    toolset="peer_comms",
    schema=PEER_RUNNER_STATUS_SCHEMA,
    handler=lambda args, **kw: peer_runner_status(**args),
    description=PEER_RUNNER_STATUS_SCHEMA.get("description", ""),
    emoji="🏃",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_runner_stop",
    toolset="peer_comms",
    schema=PEER_RUNNER_STOP_SCHEMA,
    handler=lambda args, **kw: peer_runner_stop(**args),
    description=PEER_RUNNER_STOP_SCHEMA.get("description", ""),
    emoji="🏃",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_send",
    toolset="peer_comms",
    schema=PEER_SEND_SCHEMA,
    handler=lambda args, **kw: peer_send(**args),
    description=PEER_SEND_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_inbox",
    toolset="peer_comms",
    schema=PEER_INBOX_SCHEMA,
    handler=lambda args, **kw: peer_inbox(**args),
    description=PEER_INBOX_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_claim",
    toolset="peer_comms",
    schema=PEER_CLAIM_SCHEMA,
    handler=lambda args, **kw: peer_claim(**args),
    description=PEER_CLAIM_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_reply",
    toolset="peer_comms",
    schema=PEER_REPLY_SCHEMA,
    handler=lambda args, **kw: peer_reply(**args),
    description=PEER_REPLY_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_get",
    toolset="peer_comms",
    schema=PEER_GET_SCHEMA,
    handler=lambda args, **kw: peer_get(**args),
    description=PEER_GET_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_await",
    toolset="peer_comms",
    schema=PEER_AWAIT_SCHEMA,
    handler=lambda args, **kw: peer_await(**args),
    description=PEER_AWAIT_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
registry.register(
    name="peer_offline",
    toolset="peer_comms",
    schema=PEER_OFFLINE_SCHEMA,
    handler=lambda args, **kw: peer_offline(**args),
    description=PEER_OFFLINE_SCHEMA.get("description", ""),
    emoji="🤝",
    max_result_size_chars=120_000,
)
