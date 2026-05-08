import json
import sys
from types import SimpleNamespace

import tools.conversational_memory_tool as memory_tool
from tools.conversational_memory_tool import (
    CONVERSATIONAL_MEMORY_PROPOSAL_REVIEW_SCHEMA,
    CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA,
    check_conversational_memory_proposal_review_requirements,
    check_conversational_memory_sleep_review_requirements,
    conversational_memory_proposal_review,
    conversational_memory_sleep_review,
)


def test_sleep_review_schema_exposes_planning_controls():
    props = CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA["parameters"]["properties"]

    assert CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA["name"] == "conversational_memory_sleep_review"
    assert "proposal_mode" in props
    assert "include_proposals" in props
    assert "minimum_trace_summaries" in props
    assert "sleep" in CONVERSATIONAL_MEMORY_SLEEP_REVIEW_SCHEMA["description"].lower()


def test_proposal_review_schema_exposes_review_actions():
    props = CONVERSATIONAL_MEMORY_PROPOSAL_REVIEW_SCHEMA["parameters"]["properties"]

    assert CONVERSATIONAL_MEMORY_PROPOSAL_REVIEW_SCHEMA["name"] == "conversational_memory_proposal_review"
    assert props["action"]["enum"] == ["list", "approve", "reject"]
    assert "proposal_id" in props
    assert "proposal_type" in props
    assert "reviewer" in props


def test_sleep_review_requirements_check_env(monkeypatch):
    monkeypatch.delenv("HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND", raising=False)
    assert check_conversational_memory_sleep_review_requirements() is False

    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND", "python sleep.py")
    assert check_conversational_memory_sleep_review_requirements() is True


def test_proposal_review_requirements_check_env(monkeypatch):
    for name in (
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND",
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND",
    ):
        monkeypatch.delenv(name, raising=False)
    assert check_conversational_memory_proposal_review_requirements() is False

    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND", "python list.py")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND", "python approve.py")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND", "python reject.py")
    assert check_conversational_memory_proposal_review_requirements() is True


def test_sleep_review_calls_configured_command(tmp_path, monkeypatch):
    script = tmp_path / "sleep.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {\n"
        "  'include_proposals': True,\n"
        "  'minimum_trace_summaries': 2,\n"
        "  'proposal_mode': 'hybrid',\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'reviewedAt': '2026-05-08T10:00:00.000Z',\n"
        "  'updatedSummaryIds': ['summary_1'],\n"
        "  'updatedBoxIds': [],\n"
        "  'proposedBoxIds': ['box_smith_pip'],\n"
        "  'proposalIds': ['proposal_box_smith_pip'],\n"
        "  'proposedTraceIds': ['trace_smith_pip'],\n"
        "  'noopReason': None,\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_sleep_review(
        proposal_mode="hybrid",
        include_proposals=True,
        minimum_trace_summaries=2,
    ))

    assert result["success"] is True
    assert result["reviewed_at"] == "2026-05-08T10:00:00.000Z"
    assert result["updated_summary_ids"] == ["summary_1"]
    assert result["proposed_box_ids"] == ["box_smith_pip"]
    assert result["proposal_ids"] == ["proposal_box_smith_pip"]
    assert result["proposed_trace_ids"] == ["trace_smith_pip"]


def test_sleep_review_uses_sleep_timeout_env(monkeypatch):
    captured = {}

    def fake_run(*_args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(stdout=json.dumps({
            "ok": True,
            "reviewedAt": "2026-05-08T10:00:00.000Z",
            "updatedSummaryIds": [],
            "updatedBoxIds": [],
            "proposedBoxIds": [],
            "proposalIds": [],
            "proposedTraceIds": [],
            "noopReason": "No summaries or boxes needed sleep review changes.",
        }))

    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_SLEEP_COMMAND", "python sleep.py")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_SLEEP_TIMEOUT", "42")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_RESUME_TIMEOUT", "1")
    monkeypatch.setattr(memory_tool.subprocess, "run", fake_run)

    result = json.loads(conversational_memory_sleep_review())

    assert result["success"] is True
    assert captured["timeout"] == 42.0


def test_proposal_review_lists_pending_proposals(tmp_path, monkeypatch):
    script = tmp_path / "list.py"
    script.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'include_payload': False, 'limit': 5, 'proposal_type': 'trace', 'state': 'proposed'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'count': 1,\n"
        "  'proposals': [{\n"
        "    'id': 'proposal_trace_smith_pip',\n"
        "    'proposalType': 'trace',\n"
        "    'state': 'proposed',\n"
        "    'title': 'Smith PIP provider bills',\n"
        "    'rationale': 'Recurring issue',\n"
        "    'confidence': 0.82,\n"
        "    'createdAt': '2026-05-08T10:00:00.000Z',\n"
        "    'reviewedAt': '2026-05-08T10:00:00.000Z',\n"
        "    'sourceSummaryIds': ['summary_1'],\n"
        "    'targetBoxIds': ['box_smith_pip'],\n"
        "    'targetTraceIds': ['trace_smith_pip']\n"
        "  }]\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND",
        f"{sys.executable} {script}",
    )

    result = json.loads(conversational_memory_proposal_review(
        action="list",
        state="proposed",
        proposal_type="trace",
        limit=5,
        include_payload=False,
    ))

    assert result["success"] is True
    assert result["count"] == 1
    assert result["proposals"][0]["proposal_type"] == "trace"
    assert result["proposals"][0]["source_summary_ids"] == ["summary_1"]
    assert result["proposals"][0]["target_trace_ids"] == ["trace_smith_pip"]


def test_proposal_review_approves_and_rejects_with_decision_metadata(tmp_path, monkeypatch):
    approve = tmp_path / "approve.py"
    approve.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {\n"
        "  'note': 'Looks right',\n"
        "  'proposal_id': 'proposal_box_smith_pip',\n"
        "  'reviewer': 'Roscoe',\n"
        "}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'proposalId': 'proposal_box_smith_pip',\n"
        "  'proposalType': 'box',\n"
        "  'approvedAt': '2026-05-08T10:00:00.000Z',\n"
        "  'createdBoxIds': ['box_smith_pip'],\n"
        "  'updatedBoxIds': [],\n"
        "  'createdTraceIds': [],\n"
        "  'updatedProposalIds': ['proposal_box_smith_pip']\n"
        "}))\n"
    )
    reject = tmp_path / "reject.py"
    reject.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request == {'proposal_id': 'proposal_trace_old'}\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'proposalId': 'proposal_trace_old',\n"
        "  'proposalType': 'trace',\n"
        "  'rejectedAt': '2026-05-08T10:00:00.000Z',\n"
        "  'updatedProposalIds': ['proposal_trace_old']\n"
        "}))\n"
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND",
        f"{sys.executable} {approve}",
    )
    monkeypatch.setenv(
        "HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_REJECT_COMMAND",
        f"{sys.executable} {reject}",
    )

    approved = json.loads(conversational_memory_proposal_review(
        action="approve",
        proposal_id="proposal_box_smith_pip",
        reviewer="Roscoe",
        note="Looks right",
    ))
    rejected = json.loads(conversational_memory_proposal_review(
        action="reject",
        proposal_id="proposal_trace_old",
    ))

    assert approved["success"] is True
    assert approved["proposal_id"] == "proposal_box_smith_pip"
    assert approved["proposal_type"] == "box"
    assert approved["created_box_ids"] == ["box_smith_pip"]
    assert rejected["success"] is True
    assert rejected["proposal_id"] == "proposal_trace_old"
    assert rejected["rejected_at"] == "2026-05-08T10:00:00.000Z"


def test_proposal_review_validates_action_requirements(monkeypatch):
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_LIST_COMMAND", "python unused.py")
    monkeypatch.setenv("HERMES_CONVERSATIONAL_MEMORY_PROPOSALS_APPROVE_COMMAND", "python unused.py")

    missing = json.loads(conversational_memory_proposal_review(action="approve"))
    unknown = json.loads(conversational_memory_proposal_review(action="archive"))

    assert missing["success"] is False
    assert "proposal_id" in missing["error"]
    assert unknown["success"] is False
    assert "Unknown proposal review action" in unknown["error"]
