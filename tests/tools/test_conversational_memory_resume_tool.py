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
    assert "trace_id" in props
    assert "box_id" in props
    assert "max_turn_ranges" in props
    assert "include_child_boxes" in props
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


def test_conversational_memory_resume_tolerates_model_filled_empty_optional_fields(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "resume_defaults.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'summary_id': 'summary_smith_pip'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'turnCount': 1,\n"
        "  'sourceSummaryIds': ['summary_smith_pip'],\n"
        "  'contextBlock': '<memory-resume>Smith PIP</memory-resume>',\n"
        "  'turns': []\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_resume(
        summary_id="summary_smith_pip",
        trace_id="",
        box_id="",
        injection_packet={},
        max_turn_ranges=1,
        include_child_boxes=False,
    ))

    assert result["success"] is True
    assert result["turn_count"] == 1
    assert result["source_summary_ids"] == ["summary_smith_pip"]


def test_conversational_memory_resume_calls_configured_command_with_trace_id(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "resume_trace.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'trace_id': 'trace_smith_pip_provider_bills'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'turnCount': 3,\n"
        "  'sourceTraceIds': ['trace_smith_pip_provider_bills'],\n"
        "  'sourceBoxIds': ['box_smith_pip'],\n"
        "  'contextBlock': '<memory-resume>Provider bills</memory-resume>',\n"
        "  'turns': [{'role': 'assistant', 'content': 'Provider bills'}]\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_resume(
        trace_id="trace_smith_pip_provider_bills",
    ))

    assert result["success"] is True
    assert result["turn_count"] == 3
    assert result["source_trace_ids"] == ["trace_smith_pip_provider_bills"]
    assert result["source_box_ids"] == ["box_smith_pip"]
    assert result["context_block"] == "<memory-resume>Provider bills</memory-resume>"


def test_conversational_memory_resume_calls_configured_command_with_box_options(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "resume_box.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {\n"
        "  'box_id': 'box_smith_pip',\n"
        "  'include_child_boxes': True,\n"
        "  'max_turn_ranges': 2,\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'turnCount': 5,\n"
        "  'sourceSummaryIds': ['summary_smith_pip'],\n"
        "  'sourceBoxIds': ['box_smith_pip'],\n"
        "  'sourceTurnRanges': [{'start': 10, 'end': 15}],\n"
        "  'contextBlock': '<memory-resume>Smith PIP box</memory-resume>',\n"
        "  'turns': []\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_resume(
        box_id="box_smith_pip",
        include_child_boxes=True,
        max_turn_ranges=2,
    ))

    assert result["success"] is True
    assert result["turn_count"] == 5
    assert result["source_summary_ids"] == ["summary_smith_pip"]
    assert result["source_box_ids"] == ["box_smith_pip"]
    assert result["source_turn_ranges"] == [{"start": 10, "end": 15}]


def test_conversational_memory_resume_requires_exactly_one_resume_source(monkeypatch):
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "python unused.py")

    missing = json.loads(conversational_memory_resume())
    both = json.loads(conversational_memory_resume(
        summary_id="summary_1",
        trace_id="trace_1",
        injection_packet={"id": "inject_1"},
    ))

    assert missing["success"] is False
    assert "summary_id, trace_id, box_id, or injection_packet" in missing["error"]
    assert both["success"] is False
    assert "exactly one" in both["error"]


def test_conversational_memory_resume_requires_box_id_for_box_options(monkeypatch):
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_COMMAND", "python unused.py")

    result = json.loads(conversational_memory_resume(
        summary_id="summary_1",
        include_child_boxes=True,
    ))

    assert result["success"] is False
    assert "box_id" in result["error"]
