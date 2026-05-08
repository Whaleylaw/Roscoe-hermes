import json
import os
import subprocess
import sys

import pytest

from scripts.run_memory_test_sleep_review import (
    read_sleep_review_status,
    run_memory_test_sleep_review,
    write_sleep_review_run_record,
)


def test_run_memory_test_sleep_review_uses_profile_env(tmp_path, monkeypatch):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    sleep_script = tmp_path / "sleep.py"
    list_script = tmp_path / "list.py"
    memory_db = profile_home / "memory.sqlite"

    sleep_script.write_text(
        "import json, os, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert os.environ['HERMES_CONVERSATIONAL_MEMORY_DB'].endswith('/memory-test/memory.sqlite')\n"
        "assert request == {\n"
        "  'include_proposals': True,\n"
        "  'minimum_trace_summaries': 2,\n"
        "  'proposal_mode': 'deterministic',\n"
        "  'reviewed_at': '2026-05-08T06:00:00.000Z',\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'reviewedAt': '2026-05-08T06:00:00.000Z',\n"
        "  'updatedSummaryIds': [],\n"
        "  'updatedBoxIds': [],\n"
        "  'proposedBoxIds': [],\n"
        "  'proposalIds': ['proposal_trace_trace_smith_pip_provider_bill'],\n"
        "  'proposedTraceIds': ['trace_smith_pip_provider_bill'],\n"
        "  'noopReason': None,\n"
        "}))\n",
        encoding="utf-8",
    )
    list_script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'include_payload': False, 'limit': 20, 'state': 'proposed'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'count': 1,\n"
        "  'proposals': [{\n"
        "    'id': 'proposal_trace_trace_smith_pip_provider_bill',\n"
        "    'proposalType': 'trace',\n"
        "    'state': 'proposed',\n"
        "    'title': 'Smith PIP Provider Bill',\n"
        "    'rationale': 'Recurring issue',\n"
        "    'confidence': 0.9,\n"
        "    'createdAt': '2026-05-08T06:00:00.000Z',\n"
        "    'reviewedAt': '2026-05-08T06:00:00.000Z',\n"
        "    'sourceSummaryIds': ['summary_1'],\n"
        "    'targetBoxIds': [],\n"
        "    'targetTraceIds': ['trace_smith_pip_provider_bill']\n"
        "  }]\n"
        "}))\n",
        encoding="utf-8",
    )
    (profile_home / ".env").write_text(
        "\n".join([
            f"HERMES_CONVERSATIONAL_MEMORY_DB={memory_db}",
            f"HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND={sys.executable} {sleep_script}",
            f"HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND={sys.executable} {list_script}",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_DB", "/should/not/be/used.sqlite")

    result = run_memory_test_sleep_review(
        profile_home=profile_home,
        reviewed_at="2026-05-08T06:00:00.000Z",
        ran_at="2026-05-08T06:01:00.000Z",
    )

    assert result["success"] is True
    assert result["ran_at"] == "2026-05-08T06:01:00.000Z"
    assert result["profile_home"] == str(profile_home)
    assert result["memory_db"] == str(memory_db)
    assert result["sleep_review"]["proposed_trace_ids"] == ["trace_smith_pip_provider_bill"]
    assert result["proposals"]["proposals"][0]["target_trace_ids"] == ["trace_smith_pip_provider_bill"]
    assert os.environ["HERMES_CONVERSATIONAL_MEMORY_DB"] == "/should/not/be/used.sqlite"


def test_sleep_review_run_record_writes_jsonl_and_status(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    (profile_home / ".env").write_text("", encoding="utf-8")
    result = {
        "success": True,
        "ran_at": "2026-05-08T06:01:00.000Z",
        "profile_home": str(profile_home),
        "proposals": {"count": 0},
    }
    log_file = profile_home / "logs" / "sleep.jsonl"
    status_file = profile_home / "logs" / "sleep-status.json"

    write_sleep_review_run_record(result, log_file=log_file, status_file=status_file)

    assert json.loads(log_file.read_text(encoding="utf-8")) == result
    assert json.loads(status_file.read_text(encoding="utf-8")) == result


def test_read_sleep_review_status_reports_missing_status(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    (profile_home / ".env").write_text("", encoding="utf-8")

    result = read_sleep_review_status(profile_home=profile_home)

    assert result["success"] is False
    assert result["error"] == "No sleep-review status has been written yet."


def test_run_memory_test_sleep_review_refuses_non_test_profile(tmp_path):
    profile_home = tmp_path / "default"
    profile_home.mkdir()
    (profile_home / ".env").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="non-test profile"):
        run_memory_test_sleep_review(profile_home=profile_home)


def test_run_memory_test_sleep_review_cli_outputs_json(tmp_path):
    profile_home = tmp_path / "memory-test"
    profile_home.mkdir()
    sleep_script = tmp_path / "sleep.py"
    list_script = tmp_path / "list.py"

    sleep_script.write_text(
        "import json\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'reviewedAt': '2026-05-08T06:00:00.000Z',\n"
        "  'updatedSummaryIds': [],\n"
        "  'updatedBoxIds': [],\n"
        "  'proposedBoxIds': [],\n"
        "  'proposalIds': [],\n"
        "  'proposedTraceIds': [],\n"
        "  'noopReason': 'No changes'\n"
        "}))\n",
        encoding="utf-8",
    )
    list_script.write_text(
        "import json\n"
        "print(json.dumps({'ok': True, 'count': 0, 'proposals': []}))\n",
        encoding="utf-8",
    )
    (profile_home / ".env").write_text(
        "\n".join([
            f"HERMES_CONVERSATIONAL_MEMORY_DB={profile_home / 'memory.sqlite'}",
            f"HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND={sys.executable} {sleep_script}",
            f"HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND={sys.executable} {list_script}",
        ]),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_memory_test_sleep_review.py",
            "--profile-home",
            str(profile_home),
            "--no-log",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["success"] is True
    assert payload["profile_home"] == str(profile_home.resolve())
    assert payload["proposals"]["count"] == 0
