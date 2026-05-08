import json
import sys

from tools.conversational_memory_tool import (
    CONVERSATIONAL_MEMORY_SEARCH_SCHEMA,
    check_conversational_memory_search_requirements,
    conversational_memory_search,
)


def test_conversational_memory_search_schema_exposes_query_controls():
    props = CONVERSATIONAL_MEMORY_SEARCH_SCHEMA["parameters"]["properties"]

    assert CONVERSATIONAL_MEMORY_SEARCH_SCHEMA["name"] == "conversational_memory_search"
    assert "query" in props
    assert "profile_id" in props
    assert "session_id" in props
    assert "max_memory_tokens" in props
    assert "search" in CONVERSATIONAL_MEMORY_SEARCH_SCHEMA["description"].lower()


def test_conversational_memory_search_requirements_check_env(monkeypatch):
    monkeypatch.delenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND", raising=False)
    assert check_conversational_memory_search_requirements() is False

    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND", "python inject.py")
    assert check_conversational_memory_search_requirements() is True


def test_conversational_memory_search_calls_configured_inject_command(tmp_path, monkeypatch):
    script = tmp_path / "inject.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {\n"
        "  'max_memory_tokens': 80,\n"
        "  'profile_id': 'default',\n"
        "  'query': 'Smith PIP provider bills',\n"
        "  'session_id': 'profile:default',\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'contextBlock': '<memory-context>Smith PIP</memory-context>',\n"
        "  'packet': {\n"
        "    'id': 'inject_1',\n"
        "    'currentTopicSummary': 'Smith PIP provider bills',\n"
        "    'selectedMemory': 'Smith PIP provider bill review',\n"
        "    'sourceSummaryIds': ['summary_smith_pip'],\n"
        "    'sourceTraceIds': ['trace_smith_pip_provider_bills'],\n"
        "    'sourceBoxIds': ['box_smith_pip'],\n"
        "    'sourceTurnRanges': [{'threadId': 'profile:default', 'startSequence': 10, 'endSequence': 12}],\n"
        "    'relevanceReason': 'Top trace match',\n"
        "    'confidence': 0.82,\n"
        "    'disclosureText': 'Searched memory for Smith PIP provider bills.'\n"
        "  }\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_search(
        query="Smith PIP provider bills",
        profile_id="default",
        session_id="profile:default",
        max_memory_tokens=80,
    ))

    assert result["success"] is True
    assert result["found"] is True
    assert result["context_block"] == "<memory-context>Smith PIP</memory-context>"
    assert result["packet"]["id"] == "inject_1"
    assert result["source_summary_ids"] == ["summary_smith_pip"]
    assert result["source_trace_ids"] == ["trace_smith_pip_provider_bills"]
    assert result["source_box_ids"] == ["box_smith_pip"]
    assert result["source_turn_ranges"] == [
        {"threadId": "profile:default", "startSequence": 10, "endSequence": 12}
    ]


def test_conversational_memory_search_returns_found_false_when_no_packet(tmp_path, monkeypatch):
    script = tmp_path / "inject_empty.py"
    script.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({'ok': True, 'packet': None, 'contextBlock': None}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_search(query="unrelated"))

    assert result == {
        "success": True,
        "found": False,
        "packet": None,
        "context_block": None,
        "source_summary_ids": [],
        "source_trace_ids": [],
        "source_box_ids": [],
        "source_turn_ranges": [],
    }


def test_conversational_memory_search_requires_query(monkeypatch):
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_INJECT_COMMAND", "python unused.py")

    result = json.loads(conversational_memory_search(query=""))

    assert result["success"] is False
    assert "query" in result["error"]
