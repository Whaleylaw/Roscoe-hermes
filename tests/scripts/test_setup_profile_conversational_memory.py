from pathlib import Path

import pytest
import yaml

from scripts.setup_profile_conversational_memory import (
    configure_profile_conversational_memory,
)


def _write_profile(profile_home: Path) -> None:
    profile_home.mkdir(parents=True)
    (profile_home / ".env").write_text("OPENROUTER_API_KEY=sk-test\n", encoding="utf-8")
    (profile_home / "config.yaml").write_text(
        "\n".join([
            "toolsets:",
            "- hermes-cli",
            "platform_toolsets:",
            "  api_server:",
            "  - web",
        ]) + "\n",
        encoding="utf-8",
    )


def test_configure_profile_conversational_memory_appends_marked_env_block(tmp_path):
    profile_home = tmp_path / "profiles" / "coder"
    cms_root = tmp_path / "conversational-memory-system"
    cms_root.mkdir()
    _write_profile(profile_home)

    result = configure_profile_conversational_memory(
        profile_name="coder",
        profile_home=profile_home,
        cms_root=cms_root,
    )

    env_text = (profile_home / ".env").read_text(encoding="utf-8")
    memory_db = profile_home / "conversational-memory.sqlite"
    assert result["env_updated"] is True
    assert result["memory_db"] == str(memory_db.resolve())
    assert "OPENROUTER_API_KEY=sk-test" in env_text
    assert "# BEGIN ROSCOE CONVERSATIONAL MEMORY" in env_text
    assert f"HERMES_CONVERSATIONAL_MEMORY_DB={memory_db.resolve()}" in env_text
    assert f"npm --silent --prefix {cms_root.resolve()} run hermes:ingest" in env_text
    assert "HERMES_CONVERSATIONAL_MEMORY_INJECT_ENABLED=1" in env_text


def test_configure_profile_conversational_memory_updates_existing_marked_block(tmp_path):
    profile_home = tmp_path / "profiles" / "coder"
    first_cms_root = tmp_path / "cms-a"
    second_cms_root = tmp_path / "cms-b"
    first_cms_root.mkdir()
    second_cms_root.mkdir()
    _write_profile(profile_home)

    configure_profile_conversational_memory(
        profile_name="coder",
        profile_home=profile_home,
        cms_root=first_cms_root,
    )
    result = configure_profile_conversational_memory(
        profile_name="coder",
        profile_home=profile_home,
        cms_root=second_cms_root,
    )

    env_text = (profile_home / ".env").read_text(encoding="utf-8")
    assert result["env_updated"] is True
    assert str(first_cms_root.resolve()) not in env_text
    assert str(second_cms_root.resolve()) in env_text
    assert env_text.count("# BEGIN ROSCOE CONVERSATIONAL MEMORY") == 1


def test_configure_profile_conversational_memory_refuses_unmarked_memory_keys(tmp_path):
    profile_home = tmp_path / "profiles" / "coder"
    cms_root = tmp_path / "cms"
    cms_root.mkdir()
    _write_profile(profile_home)
    (profile_home / ".env").write_text(
        "HERMES_CONVERSATIONAL_MEMORY_DB=/tmp/other.sqlite\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unmanaged conversational-memory keys"):
        configure_profile_conversational_memory(
            profile_name="coder",
            profile_home=profile_home,
            cms_root=cms_root,
        )


def test_configure_profile_conversational_memory_refuses_memory_test(tmp_path):
    profile_home = tmp_path / "profiles" / "memory-test"
    cms_root = tmp_path / "cms"
    cms_root.mkdir()
    _write_profile(profile_home)

    with pytest.raises(ValueError, match="memory-test"):
        configure_profile_conversational_memory(
            profile_name="memory-test",
            profile_home=profile_home,
            cms_root=cms_root,
        )


def test_configure_profile_conversational_memory_can_update_config_toolsets(tmp_path):
    profile_home = tmp_path / "profiles" / "coder"
    cms_root = tmp_path / "cms"
    cms_root.mkdir()
    _write_profile(profile_home)

    result = configure_profile_conversational_memory(
        profile_name="coder",
        profile_home=profile_home,
        cms_root=cms_root,
        update_config=True,
    )

    config = yaml.safe_load((profile_home / "config.yaml").read_text(encoding="utf-8"))
    assert result["config_updated"] is True
    assert "memory" in config["toolsets"]
    assert "memory" in config["platform_toolsets"]["api_server"]

