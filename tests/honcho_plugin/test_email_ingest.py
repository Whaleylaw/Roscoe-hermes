from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from plugins.memory.honcho.email_ingest import (
    EmailMessage,
    HonchoEmailIngestor,
    _iter_session_messages,
    case_workspace_id,
    normalize_email_date,
    normalize_email_peer_id,
    ops_workspace_id,
    session_id_for_thread,
)


class FakeSession:
    def __init__(self, existing_messages=None):
        self._messages = list(existing_messages or [])
        self.added_batches = []

    def messages(self, page=1, size=100):
        return type("Page", (), {"items": self._messages, "pages": 1})()

    def add_messages(self, batch):
        self.added_batches.append(list(batch))
        self._messages.extend(batch)


class FakeHoncho:
    def __init__(self):
        self.sessions_by_name = {}

    def session(self, name):
        self.sessions_by_name.setdefault(name, FakeSession())
        return self.sessions_by_name[name]


class FakeFactory:
    def __init__(self):
        self.clients = {}

    def __call__(self, workspace_id):
        self.clients.setdefault(workspace_id, FakeHoncho())
        return self.clients[workspace_id]


def test_case_workspace_id_is_isolated_and_slug_safe():
    assert case_workspace_id("Michael Crader") == "case-michael-crader"
    assert case_workspace_id(" Estate of Betty Prince!! ") == "case-estate-of-betty-prince"


def test_ops_workspace_id_is_separate_from_case_workspaces():
    assert ops_workspace_id() == "lawyer-incorporated-ops-email"


def test_normalize_email_peer_id_keeps_domains_but_removes_invalid_chars():
    assert normalize_email_peer_id("Justin Lawyer <justin@whaleylawfirm.com>") == "email-justin_at_whaleylawfirm_com"
    assert normalize_email_peer_id("No Email Sender") == "email-no-email-sender"


def test_session_id_for_thread_uses_gmail_thread_id():
    assert session_id_for_thread("19dd486e0751a352") == "gmail-thread-19dd486e0751a352"


def test_normalize_email_date_converts_rfc2822_to_iso():
    assert normalize_email_date("Tue, 28 Apr 2026 14:39:22 +0000") == "2026-04-28T14:39:22+00:00"


def test_ingests_case_email_to_case_workspace_with_metadata_and_dedupes():
    factory = FakeFactory()
    existing = {"content": "old", "peer_id": "email-old", "metadata": {"gmail_message_id": "m-1"}}
    factory.clients["case-michael-crader"] = FakeHoncho()
    factory.clients["case-michael-crader"].sessions_by_name["gmail-thread-t-1"] = FakeSession([existing])

    ingestor = HonchoEmailIngestor(client_factory=factory)
    duplicate = EmailMessage(
        gmail_message_id="m-1",
        gmail_thread_id="t-1",
        from_header="Justin <justin@whaleylawfirm.com>",
        to_headers=["Aaron <agwhaley@whaleylawfirm.com>"],
        subject="Crader lien update",
        date="Tue, 28 Apr 2026 14:38:22 +0000",
        body="Duplicate body",
    )
    fresh = EmailMessage(
        gmail_message_id="m-2",
        gmail_thread_id="t-1",
        from_header="Justin <justin@whaleylawfirm.com>",
        to_headers=["Aaron <agwhaley@whaleylawfirm.com>"],
        subject="Crader lien update",
        date="Tue, 28 Apr 2026 14:39:22 +0000",
        body="VA lien is under review.",
        labels=["INBOX"],
        firmvault_path="/FirmVault/cases/michael-crader/Activity Log/email.md",
    )

    result = ingestor.ingest_case_thread("michael-crader", [duplicate, fresh])

    assert result.workspace_id == "case-michael-crader"
    assert result.session_id == "gmail-thread-t-1"
    assert result.written == 1
    assert result.skipped_existing == 1
    batch = factory.clients["case-michael-crader"].sessions_by_name["gmail-thread-t-1"].added_batches[0]
    assert batch == [
        {
            "content": "VA lien is under review.",
            "peer_id": "email-justin_at_whaleylawfirm_com",
            "created_at": "2026-04-28T14:39:22+00:00",
            "metadata": {
                "source": "gmail",
                "scope": "case",
                "case_slug": "michael-crader",
                "gmail_message_id": "m-2",
                "gmail_thread_id": "t-1",
                "subject": "Crader lien update",
                "from": "Justin <justin@whaleylawfirm.com>",
                "to": ["Aaron <agwhaley@whaleylawfirm.com>"],
                "labels": ["INBOX"],
                "firmvault_path": "/FirmVault/cases/michael-crader/Activity Log/email.md",
            },
        }
    ]


def test_ingests_ops_email_to_ops_workspace():
    factory = FakeFactory()
    ingestor = HonchoEmailIngestor(client_factory=factory)
    email = EmailMessage(
        gmail_message_id="ops-1",
        gmail_thread_id="thread-ops",
        from_header="OpenRouter <support@openrouter.ai>",
        to_headers=["Aaron <agwhaley@whaleylawfirm.com>"],
        subject="Auto top-up failed",
        date="Tue, 28 Apr 2026 14:39:22 +0000",
        body="Payment method failed.",
    )

    result = ingestor.ingest_ops_thread([email])

    assert result.workspace_id == "lawyer-incorporated-ops-email"
    assert result.session_id == "gmail-thread-thread-ops"
    assert result.written == 1
    batch = factory.clients["lawyer-incorporated-ops-email"].sessions_by_name["gmail-thread-thread-ops"].added_batches[0]
    assert batch[0]["metadata"]["scope"] == "ops"
    assert "case_slug" not in batch[0]["metadata"]


def test_ingested_email_content_is_truncated_to_honcho_limit_with_metadata_flag():
    ingestor = HonchoEmailIngestor(client_factory=FakeFactory())
    email = EmailMessage(
        gmail_message_id="long-1",
        gmail_thread_id="thread-long",
        from_header="Filevine <noreply@filevine.com>",
        to_headers=["Aaron <agwhaley@whaleylawfirm.com>"],
        subject="Long activity report",
        date="Tue, 28 Apr 2026 14:39:22 +0000",
        body="x" * 26050,
    )

    result = ingestor.ingest_case_thread("abby-sitgraves", [email])

    assert result.written == 1
    batch = ingestor._client_factory.clients["case-abby-sitgraves"].sessions_by_name["gmail-thread-thread-long"].added_batches[0]
    assert len(batch[0]["content"]) <= 25000
    assert batch[0]["metadata"]["content_truncated"] is True
    assert batch[0]["metadata"]["original_content_length"] == 26050


class LegacyPagedSession:
    def __init__(self):
        self.calls = []

    def messages(self, *, page, size):
        self.calls.append((page, size))
        if page == 1:
            return SimpleNamespace(items=["first"], pages=2)
        if page == 2:
            return SimpleNamespace(items=["second"], pages=2)
        return SimpleNamespace(items=[], pages=2)


class CurrentSdkSession:
    def __init__(self):
        self.calls = 0

    def messages(self, *args, **kwargs):
        self.calls += 1
        if kwargs:
            raise TypeError("Unexpected keyword argument 'page'")
        return SimpleNamespace(items=["only"], pages=1)


class BrokenSecondPageSession:
    def __init__(self):
        self.calls = []

    def messages(self, *, page, size):
        self.calls.append((page, size))
        if page == 1:
            return SimpleNamespace(items=["first"], pages=2)
        raise TypeError("Unexpected keyword argument 'page'")


def test_iter_session_messages_supports_legacy_paged_honcho_sdk():
    session = LegacyPagedSession()

    assert list(_iter_session_messages(session, page_size=50)) == ["first", "second"]
    assert session.calls == [(1, 50), (2, 50)]


def test_iter_session_messages_falls_back_for_current_honcho_sdk_signature():
    session = CurrentSdkSession()

    assert list(_iter_session_messages(session, page_size=50)) == ["only"]
    assert session.calls == 2


def test_iter_session_messages_does_not_fallback_after_first_page():
    session = BrokenSecondPageSession()

    with pytest.raises(TypeError, match="Unexpected keyword argument"):
        list(_iter_session_messages(session, page_size=50))
