from __future__ import annotations

"""Temporary peer-team inbound runner.

This module is intentionally *not* an always-on A2A daemon.  It is a small
session-scoped worker that runs while a peer team is active, polls one agent's
peer inbox, dispatches each message to a configured command, and writes the
command's stdout/stderr back as the peer response.
"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .store import PeerCommsStore, get_peer_comms_dir

DEFAULT_POLL_SECONDS = 1.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 1800
DEFAULT_RUNNER_TTL_SECONDS = 6 * 60 * 60


def runners_dir() -> Path:
    path = get_peer_comms_dir() / "runners"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runner_state_path(*, team_id: str, agent_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in f"{team_id}__{agent_id}")
    return runners_dir() / f"{safe}.json"


def _utc_now() -> float:
    return time.time()


def _json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def _json_load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def build_default_command() -> List[str]:
    """Return the default one-shot Hermes command template.

    The final prompt is appended as the last argv element by run_command_for_message().
    """
    repo_root = Path(__file__).resolve().parents[1]
    cli_path = repo_root / "cli.py"
    return [sys.executable, str(cli_path), "--quiet", "-q", "{prompt}"]


def parse_command_template(command: str | Iterable[str] | None) -> List[str]:
    if command is None or command == "":
        return build_default_command()
    if isinstance(command, str):
        return shlex.split(command)
    return [str(part) for part in command]


def render_command(template: List[str], msg: Dict[str, Any]) -> List[str]:
    values = {
        "prompt": msg.get("prompt", ""),
        "msg_id": msg.get("msg_id", ""),
        "subject": msg.get("subject", ""),
        "sender_id": msg.get("sender_id", ""),
        "target_id": msg.get("target_id", ""),
        "project": msg.get("project", ""),
    }
    return [part.format(**values) for part in template]


def run_command_for_message(
    *,
    command_template: List[str],
    msg: Dict[str, Any],
    cwd: str = "",
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    extra_env: Optional[Dict[str, str]] = None,
) -> tuple[str, str]:
    argv = render_command(command_template, msg)
    if not argv:
        raise ValueError("command template is empty")
    env = os.environ.copy()
    env.update(extra_env or {})
    env.update(
        {
            "HERMES_PEER_MSG_ID": msg.get("msg_id", ""),
            "HERMES_PEER_SENDER_ID": msg.get("sender_id", ""),
            "HERMES_PEER_TARGET_ID": msg.get("target_id", ""),
            "HERMES_PEER_PROJECT": msg.get("project", ""),
            "HERMES_PEER_SUBJECT": msg.get("subject", ""),
        }
    )
    proc = subprocess.run(
        argv,
        cwd=cwd or None,
        env=env,
        text=True,
        capture_output=True,
        timeout=max(1, int(timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS)),
    )
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode == 0:
        return "completed", stdout or "[peer runner completed with empty output]"
    body = stderr or stdout or f"command exited with code {proc.returncode}"
    return "failed", body


class PeerTeamRunner:
    def __init__(
        self,
        *,
        agent_id: str,
        project: str,
        team_id: str = "",
        name: str = "",
        role: str = "",
        command: str | Iterable[str] | None = None,
        cwd: str = "",
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        ttl_seconds: int = DEFAULT_RUNNER_TTL_SECONDS,
        command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        once: bool = False,
        store: Optional[PeerCommsStore] = None,
    ):
        self.store = store or PeerCommsStore()
        self.agent_id = agent_id
        self.name = name or agent_id
        self.project = project
        self.team_id = team_id
        self.role = role
        self.command_template = parse_command_template(command)
        self.cwd = cwd
        self.poll_seconds = max(0.1, float(poll_seconds or DEFAULT_POLL_SECONDS))
        self.ttl_seconds = max(60, int(ttl_seconds or DEFAULT_RUNNER_TTL_SECONDS))
        self.command_timeout_seconds = max(1, int(command_timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS))
        self.once = once
        self._stop = False

    def stop(self, *_args: object) -> None:
        self._stop = True

    def _team_is_active(self) -> bool:
        if not self.team_id:
            return True
        team = self.store.get_team(self.team_id)
        return bool(team and team.get("status") == "active")

    def _heartbeat(self) -> None:
        metadata: Dict[str, Any] = {"peer_runner": True, "command": self.command_template}
        if self.team_id:
            metadata["team_id"] = self.team_id
        self.store.register_agent(
            name=self.name,
            agent_id=self.agent_id,
            role=self.role,
            project=self.project,
            cwd=self.cwd or os.getcwd(),
            metadata=metadata,
            ttl_seconds=self.ttl_seconds,
        )

    def _process_one(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        claimed = self.store.claim_message(msg_id=msg["msg_id"], agent_id=self.agent_id)
        if claimed.get("status") != "in_progress":
            return claimed
        try:
            status, response = run_command_for_message(
                command_template=self.command_template,
                msg=claimed,
                cwd=self.cwd,
                timeout_seconds=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            status = "failed"
            response = f"peer runner command timed out after {self.command_timeout_seconds}s: {exc}"
        except Exception as exc:  # noqa: BLE001 - response should go back to sender
            status = "failed"
            response = f"peer runner command failed: {exc}"
        return self.store.reply_message(msg_id=claimed["msg_id"], agent_id=self.agent_id, response=response, status=status)

    def run(self) -> Dict[str, Any]:
        state_path = runner_state_path(team_id=self.team_id or "standalone", agent_id=self.agent_id)
        started = _utc_now()
        _json_dump(
            state_path,
            {
                "pid": os.getpid(),
                "agent_id": self.agent_id,
                "project": self.project,
                "team_id": self.team_id,
                "status": "running",
                "started_at": started,
                "updated_at": started,
                "command": self.command_template,
            },
        )
        processed = 0
        try:
            self._heartbeat()
            while not self._stop:
                if not self._team_is_active():
                    break
                self._heartbeat()
                inbox = self.store.list_inbox(agent_id=self.agent_id, status="queued", project=self.project, limit=1, mark_seen=False)
                if not inbox:
                    if self.once:
                        break
                    time.sleep(self.poll_seconds)
                    continue
                self._process_one(inbox[0])
                processed += 1
                _json_dump(
                    state_path,
                    {
                        **_json_load(state_path),
                        "status": "running",
                        "processed": processed,
                        "updated_at": _utc_now(),
                    },
                )
                if self.once:
                    break
        finally:
            self.store.mark_offline(self.agent_id)
            _json_dump(
                state_path,
                {
                    **_json_load(state_path),
                    "status": "stopped",
                    "processed": processed,
                    "updated_at": _utc_now(),
                },
            )
        return {"agent_id": self.agent_id, "project": self.project, "team_id": self.team_id, "processed": processed}


def start_runner_process(
    *,
    agent_id: str,
    project: str,
    team_id: str = "",
    name: str = "",
    role: str = "",
    command: str = "",
    cwd: str = "",
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    ttl_seconds: int = DEFAULT_RUNNER_TTL_SECONDS,
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    if not agent_id:
        raise ValueError("agent_id is required")
    if not project:
        raise ValueError("project is required")
    state_path = runner_state_path(team_id=team_id or "standalone", agent_id=agent_id)
    existing = _json_load(state_path)
    if existing.get("pid") and existing.get("status") == "running" and _pid_alive(int(existing["pid"])):
        return {"already_running": True, "runner": existing, "state_path": str(state_path)}

    argv = [
        sys.executable,
        "-m",
        "peer_comms.runner",
        "run",
        "--agent-id",
        agent_id,
        "--project",
        project,
        "--poll-seconds",
        str(poll_seconds),
        "--ttl-seconds",
        str(ttl_seconds),
        "--command-timeout-seconds",
        str(command_timeout_seconds),
    ]
    if team_id:
        argv += ["--team-id", team_id]
    if name:
        argv += ["--name", name]
    if role:
        argv += ["--role", role]
    if command:
        argv += ["--command", command]
    if cwd:
        argv += ["--cwd", cwd]

    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    log_path = state_path.with_suffix(".log")
    log_fh = log_path.open("ab")
    proc = subprocess.Popen(
        argv,
        cwd=repo_root,
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    state = {
        "pid": proc.pid,
        "agent_id": agent_id,
        "project": project,
        "team_id": team_id,
        "status": "running",
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "command": command or build_default_command(),
        "state_path": str(state_path),
        "log_path": str(log_path),
    }
    _json_dump(state_path, state)
    return {"already_running": False, "runner": state, "state_path": str(state_path), "log_path": str(log_path)}


def runner_status(*, team_id: str = "", agent_id: str = "") -> Dict[str, Any]:
    paths: List[Path]
    if agent_id:
        paths = [runner_state_path(team_id=team_id or "standalone", agent_id=agent_id)]
    else:
        paths = sorted(runners_dir().glob("*.json"))
    runners = []
    for path in paths:
        state = _json_load(path)
        if not state:
            continue
        if team_id and state.get("team_id") != team_id:
            continue
        pid = int(state.get("pid") or 0)
        alive = _pid_alive(pid)
        if state.get("status") == "running" and not alive:
            state["status"] = "exited"
            state["updated_at"] = _utc_now()
            _json_dump(path, state)
        runners.append({**state, "alive": alive, "state_path": str(path)})
    return {"runners": runners}


def stop_runner(*, team_id: str = "", agent_id: str = "", timeout_seconds: float = 5.0) -> Dict[str, Any]:
    status = runner_status(team_id=team_id, agent_id=agent_id)
    stopped = []
    for state in status["runners"]:
        pid = int(state.get("pid") or 0)
        if pid and state.get("alive"):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
        deadline = _utc_now() + max(0.1, timeout_seconds)
        while pid and _pid_alive(pid) and _utc_now() < deadline:
            time.sleep(0.05)
        if pid and _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
        path = Path(state["state_path"])
        final = {**_json_load(path), "status": "stopped", "updated_at": _utc_now()}
        _json_dump(path, final)
        stopped.append({**final, "alive": _pid_alive(pid), "state_path": str(path)})
    return {"stopped": stopped}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m peer_comms.runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run one temporary inbound peer-team worker")
    run_p.add_argument("--agent-id", required=True)
    run_p.add_argument("--project", required=True)
    run_p.add_argument("--team-id", default="")
    run_p.add_argument("--name", default="")
    run_p.add_argument("--role", default="")
    run_p.add_argument("--command", default="")
    run_p.add_argument("--cwd", default="")
    run_p.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    run_p.add_argument("--ttl-seconds", type=int, default=DEFAULT_RUNNER_TTL_SECONDS)
    run_p.add_argument("--command-timeout-seconds", type=int, default=DEFAULT_COMMAND_TIMEOUT_SECONDS)
    run_p.add_argument("--once", action="store_true")

    status_p = sub.add_parser("status")
    status_p.add_argument("--team-id", default="")
    status_p.add_argument("--agent-id", default="")

    stop_p = sub.add_parser("stop")
    stop_p.add_argument("--team-id", default="")
    stop_p.add_argument("--agent-id", default="")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        runner = PeerTeamRunner(
            agent_id=args.agent_id,
            project=args.project,
            team_id=args.team_id,
            name=args.name,
            role=args.role,
            command=args.command,
            cwd=args.cwd,
            poll_seconds=args.poll_seconds,
            ttl_seconds=args.ttl_seconds,
            command_timeout_seconds=args.command_timeout_seconds,
            once=args.once,
        )
        signal.signal(signal.SIGTERM, runner.stop)
        signal.signal(signal.SIGINT, runner.stop)
        print(json.dumps(runner.run(), ensure_ascii=False), flush=True)
        return 0
    if args.cmd == "status":
        print(json.dumps(runner_status(team_id=args.team_id, agent_id=args.agent_id), ensure_ascii=False))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop_runner(team_id=args.team_id, agent_id=args.agent_id), ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
