"""Run conversational-memory sleep review for the isolated memory-test profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def run_memory_test_sleep_review(
    *,
    profile_home: Path = DEFAULT_PROFILE_HOME,
    reviewed_at: Optional[str] = None,
    proposal_mode: str = "deterministic",
    minimum_summaries_per_box: Optional[int] = None,
    minimum_trace_summaries: Optional[int] = 2,
    include_payload: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    profile_home = profile_home.expanduser().resolve()
    _validate_memory_test_profile(profile_home)
    env = _load_profile_env(profile_home)
    previous_env = _apply_env(env)

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
        "profile_home": str(profile_home),
        "memory_db": env.get("HERMES_CONVERSATIONAL_MEMORY_DB"),
        "sleep_review": sleep_review,
        "proposals": proposals,
    }


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


def main() -> None:
    args = _parse_args()
    result = run_memory_test_sleep_review(
        profile_home=args.profile_home,
        reviewed_at=args.reviewed_at,
        proposal_mode=args.proposal_mode,
        minimum_summaries_per_box=args.minimum_summaries_per_box,
        minimum_trace_summaries=args.minimum_trace_summaries,
        include_payload=args.include_payload,
        limit=args.limit,
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
    return parser.parse_args()


if __name__ == "__main__":
    main()
