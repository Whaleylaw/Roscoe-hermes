from __future__ import annotations

from pathlib import Path

from plugins.memory.honcho.gmail_case_backfill import (
    CaseIdentity,
    backfill_gmail_case_threads,
    build_case_gmail_query,
    group_thread_messages_by_case,
    normalize_gmail_message,
    select_case_identities,
)


def test_build_case_gmail_query_quotes_client_name_and_slug_parts():
    case = CaseIdentity(slug="michael-crader", client_name="Michael Crader", aliases=["VA lien"])

    query = build_case_gmail_query(case)

    assert '"Michael Crader"' in query
    assert '"michael crader"' in query
    assert '"VA lien"' in query
    assert " OR " in query


def test_normalize_gmail_message_uses_text_body_and_metadata():
    raw = {
        "id": "msg-1",
        "threadId": "thread-1",
        "from": "Justin <justin@whaleylawfirm.com>",
        "to": "Aaron <agwhaley@whaleylawfirm.com>",
        "subject": "Crader update",
        "date": "Tue, 28 Apr 2026 14:39:22 +0000",
        "labels": ["INBOX"],
        "body": "Lien update body",
    }

    email = normalize_gmail_message(raw, case_slug="michael-crader")

    assert email.gmail_message_id == "msg-1"
    assert email.gmail_thread_id == "thread-1"
    assert email.body == "Lien update body"
    assert email.metadata["case_slug"] == "michael-crader"


def test_group_thread_messages_by_case_dedupes_same_message_per_case():
    case = CaseIdentity(slug="michael-crader", client_name="Michael Crader")
    threads_by_case = {
        case.slug: [
            [
                {"id": "msg-1", "threadId": "thread-1", "from": "A", "to": "B", "subject": "S", "date": "D", "body": "one"},
                {"id": "msg-1", "threadId": "thread-1", "from": "A", "to": "B", "subject": "S", "date": "D", "body": "dupe"},
                {"id": "msg-2", "threadId": "thread-1", "from": "A", "to": "B", "subject": "S", "date": "D", "body": "two"},
            ]
        ]
    }

    grouped = group_thread_messages_by_case(threads_by_case)

    assert list(grouped) == [("michael-crader", "thread-1")]
    messages = grouped[("michael-crader", "thread-1")]
    assert [m.gmail_message_id for m in messages] == ["msg-1", "msg-2"]
    assert messages[0].body == "one"


def test_select_case_identities_supports_slug_filter_offset_and_limit():
    cases = [
        CaseIdentity(slug="abby-sitgraves", client_name="Abby Sitgraves"),
        CaseIdentity(slug="michael-crader", client_name="Michael Crader"),
        CaseIdentity(slug="timothy-ruhl", client_name="Timothy Ruhl"),
    ]

    assert [c.slug for c in select_case_identities(cases, case_slugs=["timothy-ruhl", "missing"])] == ["timothy-ruhl"]
    assert [c.slug for c in select_case_identities(cases, offset=1, limit=1)] == ["michael-crader"]


def test_backfill_gmail_case_threads_streams_and_writes_per_case(monkeypatch, tmp_path: Path):
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    for slug, client in [("abby-sitgraves", "Abby Sitgraves"), ("michael-crader", "Michael Crader")]:
        case_dir = cases_root / slug
        case_dir.mkdir()
        (case_dir / "state.yaml").write_text(f"case_slug: {slug}\nclient_name: {client}\n")

    searches = []
    writes = []

    def fake_search(case, *, helper, max_results):
        searches.append(case.slug)
        return [{"threadId": f"thread-{case.slug}"}]

    def fake_thread(thread_id, *, helper):
        slug = thread_id.removeprefix("thread-")
        return [{"id": f"msg-{slug}", "threadId": thread_id, "from": "A", "to": "B", "subject": slug, "date": "D", "body": slug}]

    class FakeIngestor:
        def ingest_case_thread(self, case_slug, messages):
            writes.append((case_slug, [m.gmail_message_id for m in messages]))
            from plugins.memory.honcho.email_ingest import IngestResult
            return IngestResult(workspace_id=f"case-{case_slug}", session_id=f"gmail-thread-thread-{case_slug}", seen=len(messages), written=len(messages), skipped_existing=0)

    monkeypatch.setattr("plugins.memory.honcho.gmail_case_backfill.gmail_search_case_messages", fake_search)
    monkeypatch.setattr("plugins.memory.honcho.gmail_case_backfill.gmail_get_thread", fake_thread)

    results = backfill_gmail_case_threads(cases_root, ingestor=FakeIngestor(), execute=True, limit_cases=1, offset_cases=1)

    assert searches == ["michael-crader"]
    assert writes == [("michael-crader", ["msg-michael-crader"])]
    assert [r.workspace_id for r in results] == ["case-michael-crader"]


def test_backfill_skips_thread_fetch_errors_and_continues(monkeypatch, tmp_path: Path):
    cases_root = tmp_path / "cases"
    case_dir = cases_root / "michael-crader"
    case_dir.mkdir(parents=True)
    (case_dir / "state.yaml").write_text("case_slug: michael-crader\nclient_name: Michael Crader\n")

    def fake_search(case, *, helper, max_results):
        return [{"threadId": "bad-thread"}, {"threadId": "good-thread"}]

    def fake_thread(thread_id, *, helper):
        if thread_id == "bad-thread":
            raise RuntimeError("gmail timeout")
        return [{"id": "msg-good", "threadId": thread_id, "from": "A", "to": "B", "subject": "S", "date": "D", "body": "ok"}]

    class FakeIngestor:
        def ingest_case_thread(self, case_slug, messages):
            from plugins.memory.honcho.email_ingest import IngestResult
            return IngestResult(workspace_id=f"case-{case_slug}", session_id="gmail-thread-good-thread", seen=len(messages), written=len(messages), skipped_existing=0)

    monkeypatch.setattr("plugins.memory.honcho.gmail_case_backfill.gmail_search_case_messages", fake_search)
    monkeypatch.setattr("plugins.memory.honcho.gmail_case_backfill.gmail_get_thread", fake_thread)

    results = backfill_gmail_case_threads(cases_root, ingestor=FakeIngestor(), execute=True)

    assert len(results) == 1
    assert results[0].session_id == "gmail-thread-good-thread"
