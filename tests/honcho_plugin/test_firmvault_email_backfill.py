from __future__ import annotations

from plugins.memory.honcho.firmvault_email_backfill import backfill_firmvault_emails, parse_activity_log_email


class RecordingIngestor:
    def __init__(self):
        self.calls = []

    def ingest_case_thread(self, case_slug, messages):
        self.calls.append((case_slug, messages))
        return type(
            "Result",
            (), {"workspace_id": f"case-{case_slug}", "session_id": "session", "seen": len(messages), "written": len(messages), "skipped_existing": 0},
        )()


def test_parse_activity_log_email_extracts_frontmatter_and_body(tmp_path):
    path = tmp_path / "2026-04-28-1441-email-test.md"
    path.write_text(
        """---
type: email
message_id: 19dd4898e35521ee
thread_id: 19a78fc97b554e2b
from: Natema S Wolfe <NATEMA_S_WOLFE@progressive.com>
to: \"AGWHALEY@WHALEYLAWFIRM.COM\" <AGWHALEY@whaleylawfirm.com>
date: Tue, 28 Apr 2026 14:41:09 +0000
subject: RE: PROGRESSIVE CLAIM: 25-934695754
---

# Email: RE: PROGRESSIVE CLAIM: 25-934695754

## Metadata
- Gmail message ID: 19dd4898e35521ee
- Gmail thread ID: 19a78fc97b554e2b

## Full email body

Hello, I wanted to touch base.
"""
    )

    email = parse_activity_log_email(path)

    assert email is not None
    assert email.gmail_message_id == "19dd4898e35521ee"
    assert email.gmail_thread_id == "19a78fc97b554e2b"
    assert email.from_header == "Natema S Wolfe <NATEMA_S_WOLFE@progressive.com>"
    assert email.to_headers == ['"AGWHALEY@WHALEYLAWFIRM.COM" <AGWHALEY@whaleylawfirm.com>']
    assert email.subject == "RE: PROGRESSIVE CLAIM: 25-934695754"
    assert email.body == "Hello, I wanted to touch base."
    assert email.firmvault_path == str(path)


def test_parse_activity_log_email_ignores_non_email_logs(tmp_path):
    path = tmp_path / "filevine.md"
    path.write_text("""---
type: filevine_activity_import
gmail_message_id: abc
---

not an email
""")

    assert parse_activity_log_email(path) is None


def _write_email(path, message_id, thread_id):
    path.write_text(
        f"""---
type: email
message_id: {message_id}
thread_id: {thread_id}
from: Sender <sender@example.com>
to: Aaron <agwhaley@whaleylawfirm.com>
date: Tue, 28 Apr 2026 14:41:09 +0000
subject: Test
---

## Full email body

Body {message_id}
"""
    )


def test_backfill_execute_groups_by_case_and_thread(tmp_path):
    cases = tmp_path / "cases"
    case_a = cases / "michael-crader" / "Activity Log"
    case_b = cases / "timothy-ruhl" / "Activity Log"
    case_a.mkdir(parents=True)
    case_b.mkdir(parents=True)
    _write_email(case_a / "one.md", "m1", "t1")
    _write_email(case_a / "two.md", "m2", "t1")
    _write_email(case_b / "three.md", "m3", "t2")

    ingestor = RecordingIngestor()
    results = backfill_firmvault_emails(cases, ingestor=ingestor, execute=True)

    assert len(results) == 2
    assert [(case, [m.gmail_message_id for m in messages]) for case, messages in ingestor.calls] == [
        ("michael-crader", ["m1", "m2"]),
        ("timothy-ruhl", ["m3"]),
    ]
