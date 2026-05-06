"""Historical Gmail case-thread backfill into local Honcho.

The stock Honcho Gmail guide imports broad mailbox threads. This module adapts
that pattern for Lawyer Incorporated's safer architecture: one Honcho workspace
per FirmVault case, emails only, no attachments/PDFs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

import yaml

from plugins.memory.honcho.email_ingest import EmailMessage, HonchoEmailIngestor, IngestResult

DEFAULT_GMAIL_HELPER = (
    Path.home()
    / "Github/Roscoe-hermes/skills/productivity/google-workspace/scripts/google_api.py"
)


@dataclass(frozen=True)
class CaseIdentity:
    slug: str
    client_name: str
    aliases: list[str] = field(default_factory=list)


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _quote_gmail_term(value: str) -> str:
    escaped = str(value).replace('"', r'\"')
    return f'"{escaped}"'


def build_case_gmail_query(case: CaseIdentity) -> str:
    """Build a conservative Gmail query for one case identity."""

    slug_words = case.slug.replace("-", " ")
    # Keep both display-cased client names and slug-derived lowercase names.
    # Gmail search is usually case-insensitive, but keeping both terms makes the
    # query auditable and preserves the case identity source that matched.
    terms = []
    seen: set[str] = set()
    for term in [case.client_name, slug_words, *case.aliases]:
        cleaned = " ".join(str(term or "").split()).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return " OR ".join(_quote_gmail_term(term) for term in terms)


def iter_firmvault_case_identities(cases_root: Path) -> Iterable[CaseIdentity]:
    """Yield case identities from FirmVault case folders.

    Uses AGENTS.md YAML frontmatter when available, then state.yaml, then the
    slug-derived display name as a fallback. Avoids reading substantive case docs.
    """

    for case_dir in sorted(cases_root.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("_") or case_dir.name.startswith("."):
            continue
        slug = case_dir.name
        client_name = ""
        aliases: list[str] = []

        agents = case_dir / "AGENTS.md"
        if agents.exists():
            text = agents.read_text(errors="replace")
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    try:
                        data = yaml.safe_load(parts[1]) or {}
                        if isinstance(data, dict):
                            client_name = str(data.get("client_name") or "")
                            legacy_id = data.get("legacy_id")
                            if legacy_id:
                                aliases.append(str(legacy_id))
                    except yaml.YAMLError:
                        pass

        state = case_dir / "state.yaml"
        if state.exists():
            try:
                data = yaml.safe_load(state.read_text(errors="replace")) or {}
                if isinstance(data, dict):
                    client_name = client_name or str(data.get("client_name") or data.get("name") or "")
                    legacy_id = data.get("legacy_id")
                    if legacy_id:
                        aliases.append(str(legacy_id))
            except yaml.YAMLError:
                pass

        if not client_name:
            client_name = slug.replace("-", " ").title()
        yield CaseIdentity(slug=slug, client_name=client_name, aliases=_dedupe_keep_order(aliases))


def _run_gmail_helper(helper: Path, *args: str) -> Any:
    cmd = ["/opt/anaconda3/bin/python3", str(helper), "gmail", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"gmail helper failed: {cmd}")
    stdout = result.stdout.strip()
    if not stdout or stdout == "No messages found.":
        return []
    return json.loads(stdout)


def gmail_search_case_messages(case: CaseIdentity, *, helper: Path = DEFAULT_GMAIL_HELPER, max_results: int = 50) -> list[dict[str, Any]]:
    query = build_case_gmail_query(case)
    results = _run_gmail_helper(helper, "search", query, "--max", str(max_results))
    return results if isinstance(results, list) else []


def gmail_get_message(message_id: str, *, helper: Path = DEFAULT_GMAIL_HELPER) -> dict[str, Any]:
    result = _run_gmail_helper(helper, "get", message_id)
    return result if isinstance(result, dict) else {}


def gmail_get_thread(thread_id: str, *, helper: Path = DEFAULT_GMAIL_HELPER) -> list[dict[str, Any]]:
    result = _run_gmail_helper(helper, "thread-get", thread_id)
    if isinstance(result, dict) and isinstance(result.get("messages"), list):
        return result["messages"]
    return []


def normalize_gmail_message(raw: dict[str, Any], *, case_slug: str, firmvault_path: str | None = None) -> EmailMessage:
    to_value = raw.get("to") or raw.get("To") or ""
    to_headers = to_value if isinstance(to_value, list) else [str(to_value)] if to_value else []
    labels = raw.get("labels") or raw.get("labelIds") or []
    return EmailMessage(
        gmail_message_id=str(raw.get("id") or raw.get("message_id") or raw.get("gmail_message_id") or ""),
        gmail_thread_id=str(raw.get("threadId") or raw.get("thread_id") or raw.get("gmail_thread_id") or ""),
        from_header=str(raw.get("from") or raw.get("From") or "unknown"),
        to_headers=[str(v) for v in to_headers],
        subject=str(raw.get("subject") or raw.get("Subject") or ""),
        date=str(raw.get("date") or raw.get("Date") or ""),
        body=str(raw.get("body") or raw.get("snippet") or ""),
        labels=[str(v) for v in labels],
        firmvault_path=firmvault_path,
        metadata={"case_slug": case_slug, "source_import": "gmail_case_backfill"},
    )


def group_thread_messages_by_case(threads_by_case: dict[str, list[list[dict[str, Any]]]]) -> dict[tuple[str, str], list[EmailMessage]]:
    grouped: dict[tuple[str, str], list[EmailMessage]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for case_slug, threads in threads_by_case.items():
        for thread in threads:
            for raw in thread:
                email = normalize_gmail_message(raw, case_slug=case_slug)
                if not email.gmail_message_id or not email.gmail_thread_id:
                    continue
                key = (case_slug, email.gmail_message_id)
                if key in seen:
                    continue
                seen.add(key)
                grouped[(case_slug, email.gmail_thread_id)].append(email)
    return dict(grouped)


def select_case_identities(
    cases: Iterable[CaseIdentity],
    *,
    case_slugs: Iterable[str] | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> list[CaseIdentity]:
    """Return a deterministic subset of case identities for bounded backfills."""

    selected = list(cases)
    if case_slugs:
        wanted = {slug.strip() for slug in case_slugs if slug and slug.strip()}
        selected = [case for case in selected if case.slug in wanted]
    if offset:
        selected = selected[offset:]
    if limit is not None:
        selected = selected[:limit]
    return selected


def collect_case_gmail_threads(
    cases: Iterable[CaseIdentity],
    *,
    helper: Path = DEFAULT_GMAIL_HELPER,
    max_results_per_case: int = 50,
) -> dict[tuple[str, str], list[EmailMessage]]:
    """Search Gmail for each case and return grouped full-message threads."""

    grouped: dict[tuple[str, str], list[EmailMessage]] = {}
    for case in cases:
        grouped.update(collect_one_case_gmail_threads(case, helper=helper, max_results_per_case=max_results_per_case))
    return grouped


def collect_one_case_gmail_threads(
    case: CaseIdentity,
    *,
    helper: Path = DEFAULT_GMAIL_HELPER,
    max_results_per_case: int = 50,
) -> dict[tuple[str, str], list[EmailMessage]]:
    """Search Gmail for one case and return grouped full-message threads."""

    raw_threads_by_case: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    fetched_threads: dict[str, list[dict[str, Any]]] = {}
    search_results = gmail_search_case_messages(case, helper=helper, max_results=max_results_per_case)
    thread_ids = _dedupe_keep_order(str(hit.get("threadId") or "") for hit in search_results)
    for thread_id in thread_ids:
        if not thread_id:
            continue
        if thread_id not in fetched_threads:
            try:
                fetched_threads[thread_id] = gmail_get_thread(thread_id, helper=helper)
            except RuntimeError:
                fetched_threads[thread_id] = []
                continue
        if fetched_threads[thread_id]:
            raw_threads_by_case[case.slug].append(fetched_threads[thread_id])
    return group_thread_messages_by_case(raw_threads_by_case)


def backfill_gmail_case_threads(
    cases_root: Path,
    *,
    ingestor: HonchoEmailIngestor | None = None,
    helper: Path = DEFAULT_GMAIL_HELPER,
    max_results_per_case: int = 50,
    execute: bool = False,
    case_slugs: Iterable[str] | None = None,
    limit_cases: int | None = None,
    offset_cases: int = 0,
) -> list[IngestResult]:
    """Backfill existing case-related Gmail messages into per-case Honcho workspaces.

    Processes one case at a time so long historical imports make incremental
    progress and can be resumed safely through Honcho's gmail_message_id dedupe.
    """

    cases = select_case_identities(
        iter_firmvault_case_identities(cases_root),
        case_slugs=case_slugs,
        offset=offset_cases,
        limit=limit_cases,
    )
    writer = ingestor or HonchoEmailIngestor()
    results: list[IngestResult] = []
    for case in cases:
        grouped = collect_one_case_gmail_threads(case, helper=helper, max_results_per_case=max_results_per_case)
        for (case_slug, thread_id), messages in sorted(grouped.items()):
            if execute:
                results.append(writer.ingest_case_thread(case_slug, messages))
            else:
                from plugins.memory.honcho.email_ingest import case_workspace_id, session_id_for_thread

                results.append(
                    IngestResult(
                        workspace_id=case_workspace_id(case_slug),
                        session_id=session_id_for_thread(thread_id),
                        seen=len(messages),
                        written=0,
                        skipped_existing=0,
                    )
                )
    return results
