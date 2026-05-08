"""Run guarded conversational-memory sleep review for an explicitly allowlisted profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.conversational_memory_tool import (
    conversational_memory_proposal_review,
    conversational_memory_sleep_review,
)


DEFAULT_PROFILES_ROOT = Path.home() / ".hermes" / "profiles"
DEFAULT_LOG_FILENAME = "conversational-memory-sleep-review.jsonl"
DEFAULT_STATUS_FILENAME = "conversational-memory-sleep-review-status.json"
REQUIRED_ENV_KEYS = (
    "HERMES_CONVERSATIONAL_MEMORY_DB",
    "HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND",
    "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
)


def run_profile_sleep_review(
    *,
    profile_name: str,
    allowed_profiles: set[str],
    profile_home: Optional[Path] = None,
    profiles_root: Path = DEFAULT_PROFILES_ROOT,
    reviewed_at: Optional[str] = None,
    proposal_mode: str = "deterministic",
    minimum_summaries_per_box: Optional[int] = None,
    minimum_trace_summaries: Optional[int] = 2,
    include_payload: bool = False,
    limit: int = 20,
    ran_at: Optional[str] = None,
) -> Dict[str, Any]:
    profile_home = _resolve_profile_home(
        profile_name=profile_name,
        profile_home=profile_home,
        profiles_root=profiles_root,
    )
    env = validate_profile_sleep_review_target(
        profile_name=profile_name,
        profile_home=profile_home,
        allowed_profiles=allowed_profiles,
    )
    previous_env = _apply_env(env)
    ran_at = ran_at or _now_iso()

    try:
        sleep_review = json.loads(conversational_memory_sleep_review(
            reviewed_at=reviewed_at,
            proposal_mode=proposal_mode,
            include_proposals=True,
            minimum_summaries_per_box=minimum_summaries_per_box,
            minimum_trace_summaries=minimum_trace_summaries,
        ))
        proposals = json.loads(conversational_memory_proposal_review(
            action="list",
            state="proposed",
            limit=limit,
            include_payload=include_payload,
        ))
    finally:
        _restore_env(previous_env)

    return {
        "success": bool(sleep_review.get("success")) and bool(proposals.get("success")),
        "ran_at": ran_at,
        "profile_name": profile_name,
        "profile_home": str(profile_home),
        "memory_db": env["HERMES_CONVERSATIONAL_MEMORY_DB"],
        "mode": "dry-run-list-only",
        "sleep_review": sleep_review,
        "proposals": proposals,
    }


def validate_profile_sleep_review_target(
    *,
    profile_name: str,
    profile_home: Path,
    allowed_profiles: set[str],
) -> Dict[str, str]:
    profile_home = profile_home.expanduser().resolve()
    if profile_name == "memory-test" or profile_home.name == "memory-test":
        raise ValueError("Use run_memory_test_sleep_review.py for the isolated memory-test profile.")
    if profile_name not in allowed_profiles:
        raise ValueError(f"Profile {profile_name!r} is not allowlisted for sleep review.")
    env_file = profile_home / ".env"
    if not env_file.is_file():
        raise FileNotFoundError(f"Missing profile env file: {env_file}")

    env = _load_profile_env(profile_home)
    missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key)]
    if missing:
        raise ValueError(f"Profile {profile_name!r} is missing required memory env keys: {', '.join(missing)}")

    memory_db = Path(env["HERMES_CONVERSATIONAL_MEMORY_DB"]).expanduser().resolve()
    if not _is_relative_to(memory_db, profile_home):
        raise ValueError(f"Memory DB must live under profile home {profile_home}: {memory_db}")
    if "memory-test" in memory_db.parts:
        raise ValueError(f"Real profile memory DB must not point at memory-test: {memory_db}")

    return env


def write_profile_sleep_review_run_record(
    result: Dict[str, Any],
    *,
    log_file: Path,
    status_file: Path,
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, sort_keys=True))
        handle.write("\n")
    status_file.write_text(f"{json.dumps(result, indent=2, sort_keys=True)}\n", encoding="utf-8")


def read_profile_sleep_review_status(*, profile_home: Path) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    status_file = default_status_file(profile_home)
    if not status_file.is_file():
        return {
            "success": False,
            "profile_home": str(profile_home),
            "status_file": str(status_file),
            "error": "No sleep-review status has been written yet.",
        }
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    payload["status_file"] = str(status_file)
    return payload


def default_log_file(profile_home: Path) -> Path:
    return profile_home / "logs" / DEFAULT_LOG_FILENAME


def default_status_file(profile_home: Path) -> Path:
    return profile_home / "logs" / DEFAULT_STATUS_FILENAME


def _resolve_profile_home(
    *,
    profile_name: str,
    profile_home: Optional[Path],
    profiles_root: Path,
) -> Path:
    if profile_home is not None:
        return profile_home.expanduser().resolve()
    return (profiles_root.expanduser().resolve() / profile_name).resolve()


def _load_profile_env(profile_home: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}

    for raw_line in (profile_home / ".env").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = _unquote_env_value(value.strip())

    return env


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _apply_env(env: Dict[str, str]) -> Dict[str, Optional[str]]:
    keys = set(env) | set(REQUIRED_ENV_KEYS)
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(env)
    return previous


def _restore_env(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> None:
    args = _parse_args()
    profile_home = _resolve_profile_home(
        profile_name=args.profile,
        profile_home=args.profile_home,
        profiles_root=args.profiles_root,
    )
    if args.status:
        print(json.dumps(read_profile_sleep_review_status(profile_home=profile_home), indent=2, sort_keys=True))
        return

    result = run_profile_sleep_review(
        profile_name=args.profile,
        allowed_profiles=set(args.allow_profile),
        profile_home=profile_home,
        reviewed_at=args.reviewed_at,
        proposal_mode=args.proposal_mode,
        minimum_summaries_per_box=args.minimum_summaries_per_box,
        minimum_trace_summaries=args.minimum_trace_summaries,
        include_payload=args.include_payload,
        limit=args.limit,
    )
    if not args.no_log:
        write_profile_sleep_review_run_record(
            result,
            log_file=args.log_jsonl or default_log_file(profile_home),
            status_file=args.status_json or default_status_file(profile_home),
        )
    print(json.dumps(result, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Profile name to review. Must also be passed via --allow-profile.")
    parser.add_argument("--allow-profile", action="append", default=[], help="Explicitly allow a profile name. Repeatable.")
    parser.add_argument("--profile-home", type=Path)
    parser.add_argument("--profiles-root", type=Path, default=DEFAULT_PROFILES_ROOT)
    parser.add_argument("--reviewed-at")
    parser.add_argument(
        "--proposal-mode",
        choices=("deterministic", "openrouter", "hybrid"),
        default="deterministic",
    )
    parser.add_argument("--minimum-summaries-per-box", type=int)
    parser.add_argument("--minimum-trace-summaries", type=int, default=2)
    parser.add_argument("--include-payload", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--log-jsonl", type=Path)
    parser.add_argument("--status-json", type=Path)
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--status", action="store_true", help="Print the last sleep-review status JSON and exit.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
