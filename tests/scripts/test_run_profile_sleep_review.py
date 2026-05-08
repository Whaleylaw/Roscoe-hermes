import json
import os
import subprocess
import sys

import pytest

from scripts.run_profile_sleep_review import (
    read_profile_sleep_review_status,
    run_profile_sleep_review,
    validate_profile_sleep_review_target,
    write_profile_sleep_review_run_record,
)


def _write_profile_env(profile_home, *, sleep_script, list_script, memory_db=None):
    memory_db = memory_db or profile_home / "memory.sqlite"
    profile_home.mkdir(parents=True, exist_ok=True)
    (profile_home / ".env").write_text(
        "\n".join([
            f"HERMES_CONVERSATIONAL_MEMORY_DB={memory_db}",
            f"HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND={sys.executable} {sleep_script}",
            f"HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND={sys.executable} {list_script}",
        ]),
        encoding="utf-8",
    )


def _write_fake_commands(tmp_path):
    sleep_script = tmp_path / "sleep.py"
    list_script = tmp_path / "list.py"
    sleep_script.write_text(
        "import json, os, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert os.environ['HERMES_CONVERSATIONAL_MEMORY_DB'].endswith('/roscoe/memory.sqlite')\n"
        "assert request == {\n"
        "  'include_proposals': True,\n"
        "  'minimum_trace_summaries': 2,\n"
        "  'proposal_mode': 'deterministic',\n"
        "  'reviewed_at': '2026-05-08T12:00:00.000Z',\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'reviewedAt': '2026-05-08T12:00:00.000Z',\n"
        "  'updatedSummaryIds': ['summary_1'],\n"
        "  'updatedBoxIds': [],\n"
        "  'proposedBoxIds': [],\n"
        "  'proposalIds': ['proposal_trace_1'],\n"
        "  'proposedTraceIds': ['trace_1'],\n"
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
        "    'id': 'proposal_trace_1',\n"
        "    'proposalType': 'trace',\n"
        "    'state': 'proposed',\n"
        "    'title': 'Trace One',\n"
        "    'rationale': 'Recurring issue',\n"
        "    'confidence': 0.9,\n"
        "    'createdAt': '2026-05-08T12:00:00.000Z',\n"
        "    'reviewedAt': '2026-05-08T12:00:00.000Z',\n"
        "    'sourceSummaryIds': ['summary_1'],\n"
        "    'targetBoxIds': [],\n"
        "    'targetTraceIds': ['trace_1']\n"
        "  }]\n"
        "}))\n",
        encoding="utf-8",
    )
    return sleep_script, list_script


def test_run_profile_sleep_review_requires_allowlisted_profile(tmp_path):
    profile_home = tmp_path / "profiles" / "roscoe"
    sleep_script, list_script = _write_fake_commands(tmp_path)
    _write_profile_env(profile_home, sleep_script=sleep_script, list_script=list_script)

    with pytest.raises(ValueError, match="not allowlisted"):
        run_profile_sleep_review(profile_name="roscoe", allowed_profiles=set(), profile_home=profile_home)


def test_run_profile_sleep_review_refuses_memory_test_profile(tmp_path):
    profile_home = tmp_path / "profiles" / "memory-test"
    sleep_script, list_script = _write_fake_commands(tmp_path)
    _write_profile_env(profile_home, sleep_script=sleep_script, list_script=list_script)

    with pytest.raises(ValueError, match="memory-test"):
        run_profile_sleep_review(profile_name="memory-test", allowed_profiles={"memory-test"}, profile_home=profile_home)


def test_run_profile_sleep_review_refuses_db_outside_profile(tmp_path):
    profile_home = tmp_path / "profiles" / "roscoe"
    sleep_script, list_script = _write_fake_commands(tmp_path)
    _write_profile_env(
        profile_home,
        sleep_script=sleep_script,
        list_script=list_script,
        memory_db=tmp_path / "outside.sqlite",
    )

    with pytest.raises(ValueError, match="Memory DB must live under profile home"):
        validate_profile_sleep_review_target(
            profile_name="roscoe",
            profile_home=profile_home,
            allowed_profiles={"roscoe"},
        )


def test_run_profile_sleep_review_requires_memory_env_keys(tmp_path):
    profile_home = tmp_path / "profiles" / "roscoe"
    profile_home.mkdir(parents=True, exist_ok=True)
    (profile_home / ".env").write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required memory env keys"):
        validate_profile_sleep_review_target(
            profile_name="roscoe",
            profile_home=profile_home,
            allowed_profiles={"roscoe"},
        )


def test_run_profile_sleep_review_uses_profile_env_and_restores_previous_env(tmp_path, monkeypatch):
    profile_home = tmp_path / "profiles" / "roscoe"
    sleep_script, list_script = _write_fake_commands(tmp_path)
    _write_profile_env(profile_home, sleep_script=sleep_script, list_script=list_script)
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_DB", "/previous.sqlite")

    result = run_profile_sleep_review(
        profile_name="roscoe",
        allowed_profiles={"roscoe"},
        profile_home=profile_home,
        reviewed_at="2026-05-08T12:00:00.000Z",
        ran_at="2026-05-08T12:01:00.000Z",
    )

    assert result["success"] is True
    assert result["mode"] == "dry-run-list-only"
    assert result["profile_name"] == "roscoe"
    assert result["ran_at"] == "2026-05-08T12:01:00.000Z"
    assert result["sleep_review"]["proposal_ids"] == ["proposal_trace_1"]
    assert result["proposals"]["proposals"][0]["target_trace_ids"] == ["trace_1"]
    assert os.environ["HERMES_CONVERSATIONAL_MEMORY_DB"] == "/previous.sqlite"


def test_profile_sleep_review_record_writes_jsonl_and_status(tmp_path):
    result = {"success": True, "profile_name": "roscoe", "proposals": {"count": 0}}
    log_file = tmp_path / "profile" / "logs" / "sleep.jsonl"
    status_file = tmp_path / "profile" / "logs" / "sleep-status.json"

    write_profile_sleep_review_run_record(result, log_file=log_file, status_file=status_file)

    assert json.loads(log_file.read_text(encoding="utf-8")) == result
    assert json.loads(status_file.read_text(encoding="utf-8")) == result


def test_read_profile_sleep_review_status_reports_missing_status(tmp_path):
    profile_home = tmp_path / "profiles" / "roscoe"
    profile_home.mkdir(parents=True)

    result = read_profile_sleep_review_status(profile_home=profile_home)

    assert result["success"] is False
    assert result["error"] == "No sleep-review status has been written yet."


def test_run_profile_sleep_review_cli_outputs_json(tmp_path):
    profiles_root = tmp_path / "profiles"
    profile_home = profiles_root / "roscoe"
    sleep_script, list_script = _write_fake_commands(tmp_path)
    _write_profile_env(profile_home, sleep_script=sleep_script, list_script=list_script)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_profile_sleep_review.py",
            "--profiles-root",
            str(profiles_root),
            "--profile",
            "roscoe",
            "--allow-profile",
            "roscoe",
            "--reviewed-at",
            "2026-05-08T12:00:00.000Z",
            "--no-log",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["success"] is True
    assert payload["profile_home"] == str(profile_home.resolve())
    assert payload["proposals"]["count"] == 1
