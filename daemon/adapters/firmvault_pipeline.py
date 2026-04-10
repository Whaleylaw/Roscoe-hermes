"""FirmVault Case Pipeline adapter — Lane 1 of the Lawyer Inc architecture.

Runs the FirmVault deterministic engine on each daemon tick:
  1. Syncs the FirmVault repo (git pull)
  2. Runs engine.assess_portfolio() to find available work across all cases
  3. Runs mc_bridge push to create MC tasks for unsatisfied landmarks
  4. Runs mc_bridge pull to update state.yaml from MC completed tasks
  5. Detects phase transitions and logs them

This adapter does NOT use GSD. The FirmVault case pipeline runs directly
through Mission Control → OpenClaw agents → FirmVault commits.

Environment variables:
  FIRMVAULT_DIR     — path to FirmVault repo clone (default: /opt/data/firmvault)
  MC_URL            — Mission Control backend URL
  MC_TOKEN          — Mission Control LOCAL_AUTH_TOKEN
  MC_BOARD_ID       — Default board UUID for case tasks
  FIRMVAULT_REPO    — Git remote URL for FirmVault (for pull/push)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from daemon.adapters.base import HealthCheckable, HealthStatus

logger = logging.getLogger("daemon.firmvault")


@dataclass
class PortfolioSnapshot:
    """Summary of engine assessment for logging."""
    total_cases: int = 0
    total_available_work: int = 0
    total_in_flight: int = 0
    transitions_ready: int = 0
    errors: list = field(default_factory=list)


class FirmVaultAdapter(HealthCheckable):
    """Drives the FirmVault case pipeline on each daemon tick.

    Unlike other adapters that implement TaskSource, this adapter
    manages its own complete loop: engine → mc_bridge → state updates.
    It doesn't feed tasks into the daemon's generic poll/delegate cycle
    because the FirmVault→MC→OpenClaw pipeline is self-contained.
    """

    def __init__(self) -> None:
        self.vault_dir = Path(
            os.environ.get("FIRMVAULT_DIR", "/opt/data/firmvault")
        )
        self.runtime_dir = self.vault_dir / "skills.tools.workflows" / "runtime"
        self.mc_url = os.environ.get("MC_URL", "")
        self.mc_token = os.environ.get("MC_TOKEN", "")
        self.mc_board_id = os.environ.get("MC_BOARD_ID", "")
        self.repo_url = os.environ.get(
            "FIRMVAULT_REPO",
            "https://github.com/Whaleylaw/FirmVault.git"
        )

    @property
    def configured(self) -> bool:
        """True if FirmVault repo and MC credentials are available."""
        return (
            self.vault_dir.exists()
            and (self.runtime_dir / "engine.py").exists()
            and bool(self.mc_url)
            and bool(self.mc_token)
        )

    # ── HealthCheckable ────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        if not self.vault_dir.exists():
            return HealthStatus(
                service_name="firmvault",
                healthy=False,
                latency_ms=0,
                error="FirmVault repo not cloned",
            )

        if not (self.runtime_dir / "engine.py").exists():
            return HealthStatus(
                service_name="firmvault",
                healthy=False,
                latency_ms=0,
                error="FirmVault runtime not found at expected path",
            )

        if not self.mc_url or not self.mc_token:
            return HealthStatus(
                service_name="firmvault",
                healthy=False,
                latency_ms=0,
                error="MC_URL or MC_TOKEN not configured",
            )

        return HealthStatus(
            service_name="firmvault",
            healthy=True,
            latency_ms=0,
            error=None,
        )

    # ── Main tick ──────────────────────────────────────────────────────

    async def tick(self) -> None:
        """Run one full Lane 1 cycle.

        Called from the supervisor on each heartbeat. This is the complete
        FirmVault → MC → state update pipeline.
        """
        if not self.configured:
            logger.debug("firmvault: not configured, skipping tick")
            return

        # Step 1: Git pull to get latest vault state
        self._git_sync()

        # Step 2: Run engine to assess portfolio
        snapshot = self._run_engine()
        if snapshot is None:
            return

        logger.info(
            "firmvault: portfolio — %d cases, %d available work, %d in-flight, %d transitions ready",
            snapshot.total_cases,
            snapshot.total_available_work,
            snapshot.total_in_flight,
            snapshot.transitions_ready,
        )

        if snapshot.errors:
            for err in snapshot.errors[:5]:
                logger.warning("firmvault: engine error — %s", err)

        # Step 3: Push available work to Mission Control
        if snapshot.total_available_work > 0:
            self._mc_bridge_push()

        # Step 4: Pull completed tasks from MC and update state.yaml
        self._mc_bridge_pull()

        # Step 5: Git commit + push any state changes
        self._git_commit_and_push()

    # ── Internal helpers ───────────────────────────────────────────────

    def _git_sync(self) -> None:
        """Pull latest FirmVault changes."""
        if not (self.vault_dir / ".git").exists():
            logger.info("firmvault: cloning repo to %s", self.vault_dir)
            self._run_shell(
                f"git clone {self.repo_url} {self.vault_dir}",
                cwd="/opt/data",
            )
        else:
            self._run_shell("git pull --ff-only origin main", cwd=str(self.vault_dir))

    def _git_commit_and_push(self) -> None:
        """Commit and push any state.yaml changes made by mc_bridge pull."""
        result = self._run_shell(
            "git diff --quiet -- '*/state.yaml'",
            cwd=str(self.vault_dir),
        )
        if result.get("exit_code") != 0:
            # There are changes
            self._run_shell(
                'git add "*/state.yaml" && '
                'git -c user.name="Roscoe (Hermes)" '
                '-c user.email="hermes@roscoe.bot" '
                'commit -m "[daemon] state.yaml updates from MC sync"',
                cwd=str(self.vault_dir),
            )
            self._run_shell(
                "git push origin HEAD",
                cwd=str(self.vault_dir),
            )
            logger.info("firmvault: pushed state.yaml updates")

    def _run_engine(self) -> Optional[PortfolioSnapshot]:
        """Run the FirmVault engine to assess all cases."""
        script = f"""
import sys, json
sys.path.insert(0, '{self.runtime_dir}')
from engine import PhaseDag, Engine

dag_path = '{self.vault_dir}/skills.tools.workflows/workflows/PHASE_DAG.yaml'
dag = PhaseDag(dag_path)
engine = Engine(dag)
summary = engine.assess_portfolio('{self.vault_dir}')

result = {{
    'total_cases': len(summary.assessments),
    'total_available_work': summary.total_available_work,
    'total_in_flight': summary.total_in_flight,
    'transitions_ready': len(summary.transitions_ready),
    'errors': summary.errors[:10],
    'available_by_case': {{
        a.case_slug: len(a.available_work)
        for a in summary.assessments
        if a.available_work
    }},
    'transitions': [
        {{'case': t.case_slug, 'from': t.from_phase, 'to': t.to_phase, 'reason': t.reason}}
        for t in summary.transitions_ready
    ],
}}
print(json.dumps(result))
"""
        result = self._run_python(script)
        if result is None:
            return None

        snap = PortfolioSnapshot(
            total_cases=result.get("total_cases", 0),
            total_available_work=result.get("total_available_work", 0),
            total_in_flight=result.get("total_in_flight", 0),
            transitions_ready=result.get("transitions_ready", 0),
            errors=result.get("errors", []),
        )

        # Log available work by case
        for case_slug, count in result.get("available_by_case", {}).items():
            logger.info("firmvault: %s — %d tasks available", case_slug, count)

        # Log phase transitions
        for trans in result.get("transitions", []):
            logger.warning(
                "firmvault: PHASE TRANSITION READY — %s: %s → %s (%s)",
                trans["case"], trans["from"], trans["to"], trans["reason"],
            )

        return snap

    def _mc_bridge_push(self) -> None:
        """Push available work to Mission Control."""
        bridge_path = self.runtime_dir / "mc_bridge.py"
        if not bridge_path.exists():
            logger.warning("firmvault: mc_bridge.py not found")
            return

        args = f"push {self.vault_dir}"
        if self.mc_board_id:
            args += f" --board-id {self.mc_board_id}"

        result = self._run_shell(
            f"python3 {bridge_path} {args}",
            cwd=str(self.vault_dir),
            env_extra={
                "MC_URL": self.mc_url,
                "MC_TOKEN": self.mc_token,
                "MC_BOARD_ID": self.mc_board_id,
            },
        )
        if result.get("exit_code") == 0:
            logger.info("firmvault: mc_bridge push complete")
        else:
            logger.warning("firmvault: mc_bridge push error — %s", result.get("stderr", "")[:500])

    def _mc_bridge_pull(self) -> None:
        """Pull completed tasks from MC and update state.yaml."""
        bridge_path = self.runtime_dir / "mc_bridge.py"
        if not bridge_path.exists():
            return

        args = f"pull {self.vault_dir}"
        if self.mc_board_id:
            args += f" --board-id {self.mc_board_id}"

        result = self._run_shell(
            f"python3 {bridge_path} {args}",
            cwd=str(self.vault_dir),
            env_extra={
                "MC_URL": self.mc_url,
                "MC_TOKEN": self.mc_token,
                "MC_BOARD_ID": self.mc_board_id,
            },
        )
        if result.get("exit_code") == 0:
            logger.info("firmvault: mc_bridge pull complete")
        else:
            logger.warning("firmvault: mc_bridge pull error — %s", result.get("stderr", "")[:500])

    def _run_python(self, script: str) -> Optional[dict]:
        """Run a Python script and return parsed JSON output."""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.vault_dir),
            )
            if proc.returncode != 0:
                logger.warning("firmvault: python script error — %s", proc.stderr[:500])
                return None
            output = proc.stdout.strip()
            if not output:
                return None
            return json.loads(output)
        except subprocess.TimeoutExpired:
            logger.warning("firmvault: python script timed out")
            return None
        except json.JSONDecodeError as exc:
            logger.warning("firmvault: invalid JSON from script — %s", exc)
            return None
        except Exception as exc:
            logger.warning("firmvault: script error — %s", exc)
            return None

    def _run_shell(
        self,
        cmd: str,
        cwd: Optional[str] = None,
        env_extra: Optional[dict] = None,
    ) -> dict:
        """Run a shell command and return result dict."""
        env = {**os.environ}
        if env_extra:
            env.update(env_extra)

        # Inject GitHub token for git operations
        github_token = os.environ.get("GITHUB_TOKEN", "")
        if github_token and "github.com" in self.repo_url:
            # Set credential helper for this git operation
            env["GIT_ASKPASS"] = "true"
            env["GIT_TERMINAL_PROMPT"] = "0"

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=cwd or str(self.vault_dir),
                env=env,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "timeout"}
        except Exception as exc:
            return {"exit_code": -1, "stdout": "", "stderr": str(exc)}
