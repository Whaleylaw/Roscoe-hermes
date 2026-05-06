"""Gmail-to-Honcho ingestion helpers.

This module is intentionally side-effect free unless an ingestor method is
called with a Honcho client factory. It is meant to sit behind the existing
paralegal Gmail heartbeat: the heartbeat decides whether an email is case,
ops, or junk; this module only maps accepted emails into isolated Honcho
workspaces/sessions with dedupe metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.utils import getaddresses, parsedate_to_datetime
import re
from typing import Any, Callable, Iterable

DEFAULT_OPS_WORKSPACE = "lawyer-incorporated-ops-email"
HONCHO_MAX_MESSAGE_CONTENT_CHARS = 25_000
TRUNCATION_NOTICE = "\n\n[Honcho email ingest truncated this message at 25,000 characters. Original full email remains in Gmail/FirmVault.]"


@dataclass(frozen=True)
class EmailMessage:
    """Normalized Gmail message payload for Honcho ingestion."""

    gmail_message_id: str
    gmail_thread_id: str
    from_header: str
    to_headers: list[str]
    subject: str
    date: str
    body: str
    labels: list[str] = field(default_factory=list)
    firmvault_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    workspace_id: str
    session_id: str
    seen: int
    written: int
    skipped_existing: int


ClientFactory = Callable[[str], Any]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unknown"


def _peer_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unknown"


def case_workspace_id(case_slug_or_name: str) -> str:
    """Return the isolated Honcho workspace ID for a case."""

    return f"case-{_slugify(case_slug_or_name)}"


def ops_workspace_id() -> str:
    """Return the dedicated non-case operational email workspace ID."""

    return DEFAULT_OPS_WORKSPACE


def session_id_for_thread(gmail_thread_id: str) -> str:
    """Return the Honcho session ID for a Gmail thread."""

    return f"gmail-thread-{_slugify(gmail_thread_id)}"


def normalize_email_date(value: str) -> str | None:
    """Convert Gmail/RFC2822 date strings to Honcho/Pydantic-friendly ISO datetimes."""

    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError, AttributeError):
        return value


def normalize_email_peer_id(header_or_email: str) -> str:
    """Create a Honcho-safe peer ID from an email header or display name."""

    parsed = getaddresses([header_or_email or ""])
    email = ""
    display = header_or_email or "unknown"
    if parsed:
        parsed_display, parsed_email = parsed[0]
        if "@" in (parsed_email or ""):
            email = parsed_email
            display = parsed_email
        else:
            display = parsed_display or header_or_email or "unknown"

    source = email or display
    if email:
        source = source.replace("@", "_at_").replace(".", "_")
    return f"email-{_peer_slug(source)}"


def _page_items(page_obj: Any) -> list[Any]:
    items = getattr(page_obj, "items", None)
    if items is not None:
        return list(items)
    if page_obj is None:
        return []
    return list(page_obj)


def _page_count(page_obj: Any) -> int:
    pages = getattr(page_obj, "pages", None)
    if pages is None:
        return 1
    try:
        return int(pages)
    except (TypeError, ValueError):
        return 1


def _obj_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return dict(getattr(obj, "__dict__", {}))


def _iter_session_messages(session: Any, page_size: int = 100) -> Iterable[Any]:
    page_no = 1
    while True:
        page = session.messages(page=page_no, size=page_size)
        items = _page_items(page)
        if not items:
            break
        yield from items
        if page_no >= _page_count(page):
            break
        page_no += 1


class HonchoEmailIngestor:
    """Write accepted Gmail messages into local Honcho workspaces."""

    def __init__(self, client_factory: ClientFactory | None = None):
        self._client_factory = client_factory or self._default_client_factory

    @staticmethod
    def _default_client_factory(workspace_id: str) -> Any:
        from honcho import Honcho

        return Honcho(api_key="local", base_url="http://localhost:8000", workspace_id=workspace_id)

    def ingest_case_thread(self, case_slug: str, messages: list[EmailMessage]) -> IngestResult:
        return self._ingest_thread(
            workspace_id=case_workspace_id(case_slug),
            scope="case",
            messages=messages,
            case_slug=_slugify(case_slug),
        )

    def ingest_ops_thread(self, messages: list[EmailMessage]) -> IngestResult:
        return self._ingest_thread(
            workspace_id=ops_workspace_id(),
            scope="ops",
            messages=messages,
            case_slug=None,
        )

    def _ingest_thread(
        self,
        *,
        workspace_id: str,
        scope: str,
        messages: list[EmailMessage],
        case_slug: str | None,
    ) -> IngestResult:
        if not messages:
            return IngestResult(workspace_id=workspace_id, session_id="", seen=0, written=0, skipped_existing=0)

        thread_id = messages[0].gmail_thread_id
        session_id = session_id_for_thread(thread_id)
        client = self._client_factory(workspace_id)
        session = client.session(session_id)
        existing = self._existing_gmail_message_ids(session)

        batch: list[dict[str, Any]] = []
        skipped = 0
        for message in messages:
            if message.gmail_message_id in existing:
                skipped += 1
                continue
            batch.append(self._to_honcho_message(message, scope=scope, case_slug=case_slug))

        if batch:
            session.add_messages(batch)

        return IngestResult(
            workspace_id=workspace_id,
            session_id=session_id,
            seen=len(messages),
            written=len(batch),
            skipped_existing=skipped,
        )

    def _existing_gmail_message_ids(self, session: Any) -> set[str]:
        ids: set[str] = set()
        for item in _iter_session_messages(session):
            data = _obj_dict(item)
            metadata = data.get("metadata") or {}
            gmail_id = metadata.get("gmail_message_id")
            if gmail_id:
                ids.add(str(gmail_id))
        return ids

    @staticmethod
    def _to_honcho_message(message: EmailMessage, *, scope: str, case_slug: str | None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source": "gmail",
            "scope": scope,
            "gmail_message_id": message.gmail_message_id,
            "gmail_thread_id": message.gmail_thread_id,
            "subject": message.subject,
            "from": message.from_header,
            "to": list(message.to_headers),
            "labels": list(message.labels),
        }
        if case_slug:
            metadata["case_slug"] = case_slug
        if message.firmvault_path:
            metadata["firmvault_path"] = message.firmvault_path
        metadata.update(message.metadata)
        content = message.body or ""
        if len(content) > HONCHO_MAX_MESSAGE_CONTENT_CHARS:
            metadata["content_truncated"] = True
            metadata["original_content_length"] = len(content)
            keep = HONCHO_MAX_MESSAGE_CONTENT_CHARS - len(TRUNCATION_NOTICE)
            content = content[:max(0, keep)] + TRUNCATION_NOTICE

        return {
            "content": content,
            "peer_id": normalize_email_peer_id(message.from_header),
            "created_at": normalize_email_date(message.date),
            "metadata": metadata,
        }
