"""GSD (Get Shit Done) adapter — scans GSD project workspaces and drives
the plan-parse → dispatch → state-update lifecycle from the daemon heartbeat.

Unlike the other adapters that talk to remote APIs, this one shells out to
the Node.js GSD library (gsd-lawyerinc) which lives on disk.  The daemon
calls into it on each tick to:

  1. Discover active projects (dirs with .planning/STATE.md).
  2. Read state to find which wave/phase is current.
  3. Check if the current wave is complete.
  4. Dispatch the next wave if ready (via GSD's dispatcher).
  5. Update STATE.md with results.
  6. Flag tasks that need Aaron's approval for Telegram notification.

Environment variables:
  GSD_PROJECTS_DIR — root directory containing GSD project workspaces.
                     Default: ~/projects  (or /opt/data/projects on Railway)
  GSD_PACKAGE_DIR  — path to the gsd-lawyerinc package.
                     Default: /opt/data/gsd-lawyerinc
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from daemon.adapters.base import (
    HealthCheckable,
    HealthStatus,
    Task,
    TaskSource,
    TaskStatus,
)

logger = logging.getLogger("daemon.gsd")


@dataclass
class GSDProject:
    """Represents a discovered GSD project workspace."""
    name: str
    path: Path
    lifecycle: str = ""
    phase: str = ""
    wave: int = 0
    tasks_total: int = 0
    tasks_done: int = 0
    needs_approval: list[str] = field(default_factory=list)
    wave_complete: bool = False


class GSDAdapter(TaskSource, HealthCheckable):
    """Adapter that drives GSD project lifecycle from the daemon heartbeat."""

    def __init__(
        self,
        projects_dir: Optional[str] = None,
        package_dir: Optional[str] = None,
    ) -> None:
        self.projects_dir = Path(
            projects_dir
            or os.environ.get("GSD_PROJECTS_DIR", "/opt/data/projects")
        )
        self.package_dir = Path(
            package_dir
            or os.environ.get("GSD_PACKAGE_DIR", "/opt/data/gsd-lawyerinc")
        )
        # Track which projects we've already dispatched for this tick
        # to avoid double-dispatching
        self._last_dispatch: dict[str, int] = {}  # project_name -> wave

    @property
    def configured(self) -> bool:
        """True if GSD package and at least one project directory exist."""
        return self.package_dir.exists() and self.projects_dir.exists()

    # ── HealthCheckable ────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        if not self.configured:
            return HealthStatus(
                service_name="gsd",
                healthy=False,
                latency_ms=0,
                error="GSD not configured — package or projects dir missing",
            )

        # Quick check: can we run the GSD node script?
        try:
            result = self._run_gsd_script("health_check", timeout=5)
            return HealthStatus(
                service_name="gsd",
                healthy=result.get("ok", False),
                latency_ms=result.get("latency_ms", 0),
                error=result.get("error"),
            )
        except Exception as exc:
            return HealthStatus(
                service_name="gsd",
                healthy=False,
                latency_ms=0,
                error=str(exc),
            )

    # ── TaskSource ─────────────────────────────────────────────────────

    async def poll_tasks(self) -> list[Task]:
        """Scan GSD projects for tasks ready to dispatch.

        This is called on every daemon tick.  It:
          1. Scans projects_dir for .planning/STATE.md dirs.
          2. For each active project (lifecycle == EXECUTE), reads the state.
          3. If the current wave is complete, returns tasks from the next wave
             as Task objects for the daemon to process.
        """
        if not self.configured:
            return []

        tasks: list[Task] = []

        try:
            projects = self._discover_projects()
        except Exception as exc:
            logger.error("gsd: error discovering projects — %s", exc)
            return []

        for project in projects:
            try:
                project_tasks = await self._poll_project(project)
                tasks.extend(project_tasks)
            except Exception as exc:
                logger.error(
                    "gsd: error polling project %s — %s", project.name, exc
                )

        return tasks

    async def update_task_status(
        self, task_id: str, status: TaskStatus
    ) -> bool:
        """Update a GSD task's status in STATE.md."""
        # task_id format: "project_name:TASK-ID"
        parts = task_id.split(":", 1)
        if len(parts) != 2:
            logger.warning("gsd: invalid task_id format: %s", task_id)
            return False

        project_name, gsd_task_id = parts

        gsd_status_map = {
            TaskStatus.PENDING: "planned",
            TaskStatus.ASSIGNED: "dispatched",
            TaskStatus.IN_PROGRESS: "in_progress",
            TaskStatus.PENDING_REVIEW: "reviewing",
            TaskStatus.APPROVED: "done",
            TaskStatus.REJECTED: "blocked",
            TaskStatus.ERROR: "blocked",
        }

        gsd_status = gsd_status_map.get(status, "planned")

        try:
            result = self._run_gsd_script("update_status", {
                "project": project_name,
                "taskId": gsd_task_id,
                "status": gsd_status,
            })
            return result.get("ok", False)
        except Exception as exc:
            logger.error(
                "gsd: error updating status for %s — %s", task_id, exc
            )
            return False

    # ── Internal ───────────────────────────────────────────────────────

    def _discover_projects(self) -> list[GSDProject]:
        """Find all directories under projects_dir that have .planning/STATE.md."""
        projects = []
        if not self.projects_dir.exists():
            return projects

        for entry in sorted(self.projects_dir.iterdir()):
            state_file = entry / ".planning" / "STATE.md"
            if entry.is_dir() and state_file.exists():
                projects.append(GSDProject(name=entry.name, path=entry))

        return projects

    async def _poll_project(self, project: GSDProject) -> list[Task]:
        """Check a single project and return dispatchable tasks."""
        result = self._run_gsd_script("poll_project", {
            "project": project.name,
            "projectPath": str(project.path),
        })

        if not result.get("ok"):
            if result.get("lifecycle") not in ("EXECUTE",):
                logger.debug(
                    "gsd: project %s lifecycle=%s — skipping",
                    project.name,
                    result.get("lifecycle", "unknown"),
                )
            else:
                logger.warning(
                    "gsd: poll failed for %s — %s",
                    project.name,
                    result.get("error", "unknown"),
                )
            return []

        action = result.get("action")
        tasks: list[Task] = []

        if action == "dispatch_wave":
            wave_tasks = result.get("tasks", [])
            wave_num = result.get("wave", 0)
            logger.info(
                "gsd: project %s — dispatching wave %d (%d tasks)",
                project.name, wave_num, len(wave_tasks),
            )
            for t in wave_tasks:
                tasks.append(Task(
                    id=f"{project.name}:{t['id']}",
                    type=t.get("type", "general"),
                    payload=json.dumps(t),
                    metadata={
                        "source": "gsd",
                        "project": project.name,
                        "wave": wave_num,
                        "assignee": t.get("assignee", ""),
                        "approval": t.get("approval", ""),
                        "gsd_task": t,
                    },
                    status=TaskStatus.PENDING,
                ))

        elif action == "needs_approval":
            approval_tasks = result.get("tasks", [])
            logger.info(
                "gsd: project %s — %d task(s) awaiting Aaron's approval",
                project.name, len(approval_tasks),
            )
            for t in approval_tasks:
                tasks.append(Task(
                    id=f"{project.name}:{t['id']}",
                    type="approval",
                    payload=json.dumps(t),
                    metadata={
                        "source": "gsd",
                        "project": project.name,
                        "approval": "aaron",
                        "gsd_task": t,
                    },
                    status=TaskStatus.PENDING_REVIEW,
                ))

        elif action == "advance_lifecycle":
            next_lifecycle = result.get("next_lifecycle", "VERIFY")
            logger.info(
                "gsd: project %s — all waves complete, advancing to %s",
                project.name, next_lifecycle,
            )

        elif action == "idle":
            logger.debug("gsd: project %s — idle, nothing to dispatch", project.name)

        return tasks

    def _run_gsd_script(
        self,
        command: str,
        args: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Run the GSD bridge script and return parsed JSON output.

        The bridge script (daemon/gsd_bridge.js) is a thin Node.js wrapper
        that imports gsd-lawyerinc and exposes its functions as CLI commands
        with JSON I/O.
        """
        bridge_path = Path(__file__).parent.parent / "gsd_bridge.mjs"
        if not bridge_path.exists():
            return {"ok": False, "error": f"GSD bridge not found at {bridge_path}"}

        cmd = ["node", str(bridge_path), command]
        input_data = json.dumps(args) if args else "{}"

        try:
            proc = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.projects_dir),
                env={
                    **os.environ,
                    "GSD_PROJECTS_DIR": str(self.projects_dir),
                    "GSD_PACKAGE_DIR": str(self.package_dir),
                },
            )

            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                logger.warning("gsd bridge error: %s", stderr[:500])
                return {"ok": False, "error": stderr[:500]}

            output = proc.stdout.strip()
            if not output:
                return {"ok": False, "error": "empty output from bridge"}

            return json.loads(output)

        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"GSD bridge timed out ({timeout}s)"}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Invalid JSON from bridge: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
