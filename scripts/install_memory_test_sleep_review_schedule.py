"""Install a launchd schedule for the isolated memory-test sleep review."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


LABEL = "com.roscoe.memory-test-sleep-review"
DEFAULT_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "memory-test"
DEFAULT_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = REPO_ROOT / "scripts" / "run_memory_test_sleep_review.py"
DEFAULT_LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/opt/anaconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def build_launchd_plist(
    *,
    profile_home: Path = DEFAULT_PROFILE_HOME,
    python_executable: str = sys.executable,
    hour: int = 2,
    minute: int = 30,
) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    _validate_memory_test_profile_path(profile_home)
    logs_dir = profile_home / "logs"

    return {
        "Label": LABEL,
        "ProgramArguments": [
            python_executable,
            str(WRAPPER_PATH),
            "--profile-home",
            str(profile_home),
        ],
        "StartCalendarInterval": {
            "Hour": hour,
            "Minute": minute,
        },
        "StandardOutPath": str(logs_dir / "memory-test-sleep-review.stdout.log"),
        "StandardErrorPath": str(logs_dir / "memory-test-sleep-review.stderr.log"),
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": {
            "PATH": DEFAULT_LAUNCHD_PATH,
        },
        "RunAtLoad": False,
    }


def install_launchd_schedule(
    *,
    profile_home: Path = DEFAULT_PROFILE_HOME,
    plist_path: Path = DEFAULT_PLIST_PATH,
    python_executable: str = sys.executable,
    hour: int = 2,
    minute: int = 30,
    load: bool = True,
) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    plist_path = plist_path.expanduser().resolve()
    plist = build_launchd_plist(
        profile_home=profile_home,
        python_executable=python_executable,
        hour=hour,
        minute=minute,
    )
    profile_home.joinpath("logs").mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=False)

    loaded = False
    if load:
        _load_launchd_plist(plist_path)
        loaded = True

    return {
        "success": True,
        "label": LABEL,
        "profile_home": str(profile_home),
        "plist_path": str(plist_path),
        "loaded": loaded,
        "hour": hour,
        "minute": minute,
    }


def _validate_memory_test_profile_path(profile_home: Path) -> None:
    if profile_home.name != "memory-test":
        raise ValueError(f"Refusing to schedule non-test profile: {profile_home}")


def _load_launchd_plist(plist_path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True, text=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-home", type=Path, default=DEFAULT_PROFILE_HOME)
    parser.add_argument("--plist-path", type=Path, default=DEFAULT_PLIST_PATH)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--hour", type=int, default=2)
    parser.add_argument("--minute", type=int, default=30)
    parser.add_argument("--no-load", action="store_true")
    return parser.parse_args()


def main() -> None:
    import json

    args = _parse_args()
    result = install_launchd_schedule(
        profile_home=args.profile_home,
        plist_path=args.plist_path,
        python_executable=args.python,
        hour=args.hour,
        minute=args.minute,
        load=not args.no_load,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
