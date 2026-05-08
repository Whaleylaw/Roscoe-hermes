from pathlib import Path

from scripts.setup_memory_test_profile import create_memory_test_profile


def test_create_memory_test_profile_writes_isolated_memory_config(tmp_path):
    profile_home = tmp_path / "memory-test"
    cms_root = tmp_path / "conversational-memory-system"
    cms_root.mkdir()

    create_memory_test_profile(
        profile_home=profile_home,
        cms_root=cms_root,
        openrouter_api_key="sk-or-test",
    )

    assert (profile_home / "config.yaml").exists()
    assert (profile_home / ".env").exists()
    assert (profile_home / "SOUL.md").exists()
    assert (profile_home / "workspace" / "memory-case-alpha" / "AGENTS.md").exists()
    assert (profile_home / "memories" / "MEMORY.md").exists()
    assert (profile_home / "README.md").exists()

    env_text = (profile_home / ".env").read_text(encoding="utf-8")
    assert "HERMES_CONVERSATIONAL_MEMORY_DB=" in env_text
    assert f"npm --silent --prefix {cms_root}" in env_text
    assert "OPENROUTER_API_KEY=sk-or-test" in env_text
    assert "SLACK_BOT_TOKEN" not in env_text
    assert "TELEGRAM_BOT_TOKEN" not in env_text
    assert "API_SERVER_KEY" not in env_text

    config_text = (profile_home / "config.yaml").read_text(encoding="utf-8")
    assert "provider: openrouter" in config_text
    assert f"cwd: {profile_home / 'workspace'}" in config_text


def test_create_memory_test_profile_can_omit_openrouter_key(tmp_path):
    profile_home = tmp_path / "memory-test"
    cms_root = tmp_path / "cms"
    cms_root.mkdir()

    create_memory_test_profile(profile_home=profile_home, cms_root=cms_root)

    env_text = (profile_home / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY" not in env_text


def test_create_memory_test_profile_refuses_existing_profile_without_force(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    cms_root = tmp_path / "cms"
    cms_root.mkdir()

    try:
        create_memory_test_profile(profile_home=profile_home, cms_root=cms_root)
    except FileExistsError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")
