#!/usr/bin/env python3
"""Wire standalone conversational memory into an existing non-test Hermes profile."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


DEFAULT_PROFILES_ROOT = Path.home() / ".hermes" / "profiles"
DEFAULT_CMS_ROOT = Path.home() / "Github" / "conversational-memory-system"
ENV_BLOCK_BEGIN = "# BEGIN ROSCOE CONVERSATIONAL MEMORY"
ENV_BLOCK_END = "# END ROSCOE CONVERSATIONAL MEMORY"
MEMORY_KEY_RE = re.compile(r"^\s*HERMES_CONVERSATIONAL_MEMORY_[A-Z0-9_]+\s*=", re.MULTILINE)


def configure_profile_conversational_memory(
    *,
    profile_name: str,
    profile_home: Optional[Path] = None,
    profiles_root: Path = DEFAULT_PROFILES_ROOT,
    cms_root: Path = DEFAULT_CMS_ROOT,
    memory_db: Optional[Path] = None,
    update_config: bool = False,
    force_unmanaged_env: bool = False,
) -> Dict[str, Any]:
    profile_home = _resolve_profile_home(
        profile_name=profile_name,
        profile_home=profile_home,
        profiles_root=profiles_root,
    )
    cms_root = cms_root.expanduser().resolve()
    memory_db = (memory_db or profile_home / "conversational-memory.sqlite").expanduser().resolve()

    _validate_target(profile_name=profile_name, profile_home=profile_home, cms_root=cms_root, memory_db=memory_db)

    env_file = profile_home / ".env"
    env_text = env_file.read_text(encoding="utf-8")
    env_block = _memory_env_block(cms_root=cms_root, memory_db=memory_db)
    updated_env = _upsert_env_block(env_text, env_block, force_unmanaged_env=force_unmanaged_env)
    env_updated = updated_env != env_text
    if env_updated:
        env_file.write_text(updated_env, encoding="utf-8")
        env_file.chmod(0o600)

    config_updated = False
    config_file = profile_home / "config.yaml"
    if update_config:
        config_updated = _ensure_config_memory_toolset(config_file)

    return {
        "success": True,
        "profile_name": profile_name,
        "profile_home": str(profile_home),
        "cms_root": str(cms_root),
        "memory_db": str(memory_db),
        "env_file": str(env_file),
        "env_updated": env_updated,
        "config_file": str(config_file) if config_file.exists() else None,
        "config_updated": config_updated,
    }


def _resolve_profile_home(*, profile_name: str, profile_home: Optional[Path], profiles_root: Path) -> Path:
    if profile_home is not None:
        return profile_home.expanduser().resolve()
    return (profiles_root.expanduser().resolve() / profile_name).resolve()


def _validate_target(*, profile_name: str, profile_home: Path, cms_root: Path, memory_db: Path) -> None:
    if profile_name == "memory-test" or profile_home.name == "memory-test":
        raise ValueError("Use setup_memory_test_profile.py for the isolated memory-test profile.")
    if not profile_home.is_dir():
        raise FileNotFoundError(f"Profile home does not exist: {profile_home}")
    if not (profile_home / ".env").is_file():
        raise FileNotFoundError(f"Profile env file does not exist: {profile_home / '.env'}")
    if not cms_root.is_dir():
        raise FileNotFoundError(f"CMS root does not exist: {cms_root}")
    if not _is_relative_to(memory_db, profile_home):
        raise ValueError(f"Memory DB must live under profile home {profile_home}: {memory_db}")


def _memory_env_block(*, cms_root: Path, memory_db: Path) -> str:
    command = f"npm --silent --prefix {cms_root}"
    lines = [
        ENV_BLOCK_BEGIN,
        f"HERMES_CONVERSATIONAL_MEMORY_DB={memory_db}",
        "HERMES_CONVERSATIONAL_MEMORY_ENABLED=1",
        f'HERMES_CONVERSATIONAL_MEMORY_COMMAND="{command} run hermes:ingest -- --db {memory_db}"',
        "HERMES_CONVERSATIONAL_MEMORY_TIMEOUT=10",
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED=1",
        f'HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND="{command} run hermes:inject -- --db {memory_db}"',
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_TIMEOUT=10",
        "HERMES_CONVERSATIONAL_MEMORY_MAX_TOKENS=120",
        f'HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND="{command} run hermes:resume -- --db {memory_db}"',
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_TIMEOUT=10",
        f'HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND="{command} run hermes:sleep -- --db {memory_db}"',
        "HERMES_CONVERSATIONAL_MEMORY_SLEEP_TIMEOUT=60",
        f'HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND="{command} run hermes:proposals:list -- --db {memory_db}"',
        f'HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND="{command} run hermes:proposals:approve -- --db {memory_db}"',
        f'HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND="{command} run hermes:proposals:reject -- --db {memory_db}"',
        ENV_BLOCK_END,
    ]
    return "\n".join(lines)


def _upsert_env_block(env_text: str, block: str, *, force_unmanaged_env: bool) -> str:
    if ENV_BLOCK_BEGIN in env_text or ENV_BLOCK_END in env_text:
        if ENV_BLOCK_BEGIN not in env_text or ENV_BLOCK_END not in env_text:
            raise ValueError("Found incomplete conversational-memory env marker block.")
        pattern = re.compile(
            rf"{re.escape(ENV_BLOCK_BEGIN)}.*?{re.escape(ENV_BLOCK_END)}",
            re.DOTALL,
        )
        return pattern.sub(block, env_text).rstrip() + "\n"

    if MEMORY_KEY_RE.search(env_text) and not force_unmanaged_env:
        raise ValueError("Profile .env contains unmanaged conversational-memory keys. Use --force-unmanaged-env to replace them.")

    cleaned = env_text.rstrip()
    if cleaned:
        return f"{cleaned}\n\n{block}\n"
    return f"{block}\n"


def _ensure_config_memory_toolset(config_file: Path) -> bool:
    if not config_file.is_file():
        raise FileNotFoundError(f"Profile config file does not exist: {config_file}")

    original = config_file.read_text(encoding="utf-8")
    config = yaml.safe_load(original) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Profile config must be a YAML mapping: {config_file}")

    changed = _append_unique(config, "toolsets", "memory")

    platform_toolsets = config.setdefault("platform_toolsets", {})
    if not isinstance(platform_toolsets, dict):
        raise ValueError("platform_toolsets must be a YAML mapping.")
    api_server_toolsets = platform_toolsets.setdefault("api_server", [])
    if not isinstance(api_server_toolsets, list):
        raise ValueError("platform_toolsets.api_server must be a YAML list.")
    if "memory" not in api_server_toolsets:
        api_server_toolsets.append("memory")
        changed = True

    if changed:
        config_file.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return changed


def _append_unique(config: Dict[str, Any], key: str, value: str) -> bool:
    items = config.setdefault(key, [])
    if not isinstance(items, list):
        raise ValueError(f"{key} must be a YAML list.")
    if value in items:
        return False
    items.append(value)
    return True


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def main() -> None:
    args = _parse_args()
    result = configure_profile_conversational_memory(
        profile_name=args.profile,
        profile_home=args.profile_home,
        profiles_root=args.profiles_root,
        cms_root=args.cms_root,
        memory_db=args.memory_db,
        update_config=args.update_config,
        force_unmanaged_env=args.force_unmanaged_env,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Existing non-test Hermes profile name.")
    parser.add_argument("--profile-home", type=Path)
    parser.add_argument("--profiles-root", type=Path, default=DEFAULT_PROFILES_ROOT)
    parser.add_argument("--cms-root", type=Path, default=DEFAULT_CMS_ROOT)
    parser.add_argument("--memory-db", type=Path)
    parser.add_argument("--update-config", action="store_true", help="Add the memory toolset to profile config.yaml.")
    parser.add_argument(
        "--force-unmanaged-env",
        action="store_true",
        help="Allow appending the managed block even if unmanaged HERMES_CONVERSATIONAL_MEMORY_* keys already exist.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
