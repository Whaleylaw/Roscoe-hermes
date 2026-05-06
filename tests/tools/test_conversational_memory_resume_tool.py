import json
import sys

from tools.conversational_memory_tool import (
    CONVERSATIONAL_MEMORY_RESUME_SCHEMA,
    check_conversational_memory_resume_requirements,
    conversational_memory_resume,
)


def test_conversational_memory_resume_schema_exposes_summary_and_injection_modes():
    props = CONVERSATIONAL_MEMORY_RESUME_SCHEMA["parameters"]["properties"]

    assert "summary_id" in props
    assert "injection_packet" in props
    assert CONVERSATIONAL_MEMORY_RESUME_SCHEMA["name"] == "conversational_memory_resume"
    assert "verbatim" in CONVERSATIONAL_MEMORY_RESUME_SCHEMA["description"].lower()


def test_resume_requirements_check_env(monkeypatch):
    monkeypatch.delenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", raising=False)
    assert check_conversational_memory_resume_requirements() is False

    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "python tool.py")
    assert check_conversational_memory_resume_requirements() is True


def test_conversational_memory_resume_calls_configured_command_with_summary_id(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "resume.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'summary_id': 'summary_smith_pip'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'turnCount': 2,\n"
        "  'contextBlock': '<memory-resume>Smith PIP</memory-resume>',\n"
        "  'turns': [{'role': 'user', 'content': 'Smith PIP'}]\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_resume(summary_id="summary_smith_pip"))

    assert result["success"] is True
    assert result["turn_count"] == 2
    assert result["context_block"] == "<memory-resume>Smith PIP</memory-resume>"
    assert result["turns"] == [{"role": "user", "content": "Smith PIP"}]


def test_conversational_memory_resume_requires_exactly_one_resume_source(monkeypatch):
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "python unused.py")

    missing = json.loads(conversational_memory_resume())
    both = json.loads(conversational_memory_resume(
        summary_id="summary_1",
        injection_packet={"id": "inject_1"},
    ))

    assert missing["success"] is False
    assert "summary_id or injection_packet" in missing["error"]
    assert both["success"] is False
    assert "not both" in both["error"]
