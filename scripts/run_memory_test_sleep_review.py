"""Run conversational-memory sleep review for the isolated memory-test profile."""

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


DEFAULT_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "memory-test"
EXPECTED_PROFILE_NAME = "memory-test"
DEFAULT_LOG_FILENAME = "memory-test-sleep-review.jsonl"
DEFAULT_STATUS_FILENAME = "memory-test-sleep-review-status.json"


def run_memory_test_sleep_review(
    *,
    profile_home: Path = DEFAULT_PROFILE_HOME,
    reviewed_at: Optional[str] = None,
    proposal_mode: str = "deterministic",
    minimum_summaries_per_box: Optional[int] = None,
    minimum_trace_summaries: Optional[int] = 2,
    include_payload: bool = False,
    limit: int = 20,
    ran_at: Optional[str] = None,
) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    _validate_memory_test_profile(profile_home)
    env = _load_profile_env(profile_home)
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
        "profile_home": str(profile_home),
        "memory_db": env.get("HERMES_CONVERSATIONAL_MEMORY_DB"),
        "sleep_review": sleep_review,
        "proposals": proposals,
    }


def write_sleep_review_run_record(
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


def read_sleep_review_status(*, profile_home: Path = DEFAULT_PROFILE_HOME) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    _validate_memory_test_profile(profile_home)
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


def _validate_memory_test_profile(profile_home: Path) -> None:
    if profile_home.name != EXPECTED_PROFILE_NAME:
        raise ValueError(
            f"Refusing to run memory-test sleep review for non-test profile: {profile_home}"
        )
    if not (profile_home / ".env").is_file():
        raise FileNotFoundError(f"Missing profile env file: {profile_home / '.env'}")


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
    keys = set(env) | {
        "HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND",
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
    }
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(env)
    return previous


def _restore_env(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> None:
    args = _parse_args()
    if args.status:
        print(json.dumps(read_sleep_review_status(profile_home=args.profile_home), indent=2, sort_keys=True))
        return

    profile_home = args.profile_home.expanduser().resolve()
    result = run_memory_test_sleep_review(
        profile_home=profile_home,
        reviewed_at=args.reviewed_at,
        proposal_mode=args.proposal_mode,
        minimum_summaries_per_box=args.minimum_summaries_per_box,
        minimum_trace_summaries=args.minimum_trace_summaries,
        include_payload=args.include_payload,
        limit=args.limit,
    )
    if not args.no_log:
        write_sleep_review_run_record(
            result,
            log_file=args.log_jsonl or default_log_file(profile_home),
            status_file=args.status_json or default_status_file(profile_home),
        )
    print(json.dumps(result, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-home", type=Path, default=DEFAULT_PROFILE_HOME)
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
