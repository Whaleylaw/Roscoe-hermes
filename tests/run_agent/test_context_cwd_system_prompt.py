from run_agent import AIAgent


def test_context_cwd_loads_case_agents_md(tmp_path, monkeypatch):
    case_dir = tmp_path / "cases" / "aleesha-williams"
    case_dir.mkdir(parents=True)
    (case_dir / "AGENTS.md").write_text(
        "# Aleesha Williams\n\nDo not ask which case when this cwd is active.",
        encoding="utf-8",
    )

    other = tmp_path / "profile-workspace"
    other.mkdir()
    (other / "AGENTS.md").write_text("# Wrong workspace", encoding="utf-8")
    monkeypatch.setenv("TERMINAL_CWD", str(other))

    # Bypass __init__ so this is a prompt-building unit test, not a provider
    # credential test. These are the fields _build_system_prompt reads.
    agent = AIAgent.__new__(AIAgent)
    agent.load_soul_identity = False
    agent.skip_context_files = False
    agent.valid_tool_names = []
    agent._tool_use_enforcement = False
    agent.model = "test-model"
    agent._memory_store = None
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_manager = None
    agent._context_cwd = str(case_dir)
    agent.pass_session_id = False
    agent.session_id = None
    agent.provider = "custom:test"
    agent.platform = None

    prompt = agent._build_system_prompt()
    assert "Aleesha Williams" in prompt
    assert "Do not ask which case" in prompt
    assert "Wrong workspace" not in prompt
