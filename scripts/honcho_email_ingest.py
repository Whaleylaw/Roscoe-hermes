#!/usr/bin/env python3
"""CLI for local Honcho email-memory ingestion.

This intentionally does not route/triage email. Existing paralegal Gmail logic
classifies and saves email; this CLI only writes accepted email text into the
proper local Honcho workspace.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.honcho.email_ingest import EmailMessage, HonchoEmailIngestor
from plugins.memory.honcho.firmvault_email_backfill import backfill_firmvault_emails
from plugins.memory.honcho.gmail_case_backfill import backfill_gmail_case_threads


def _email_from_json(data: dict) -> EmailMessage:
    to_value = data.get("to_headers") or data.get("to") or []
    if isinstance(to_value, str):
        to_headers = [to_value]
    else:
        to_headers = [str(v) for v in to_value]
    labels = data.get("labels") or []
    return EmailMessage(
        gmail_message_id=str(data["gmail_message_id"]),
        gmail_thread_id=str(data["gmail_thread_id"]),
        from_header=str(data.get("from_header") or data.get("from") or "unknown"),
        to_headers=to_headers,
        subject=str(data.get("subject") or ""),
        date=str(data.get("date") or ""),
        body=str(data.get("body") or ""),
        labels=[str(v) for v in labels],
        firmvault_path=data.get("firmvault_path"),
        metadata=dict(data.get("metadata") or {}),
    )


def _print_summary(results) -> None:
    print(json.dumps({
        "threads": len(results),
        "seen": sum(r.seen for r in results),
        "written": sum(r.written for r in results),
        "skipped_existing": sum(r.skipped_existing for r in results),
        "workspaces": sorted({r.workspace_id for r in results}),
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("ingest-case-email", help="Write one accepted case email JSON payload to Honcho")
    one.add_argument("--case-slug", required=True)
    one.add_argument("--json-file", type=Path, help="Payload file; stdin if omitted")

    ops = sub.add_parser("ingest-ops-email", help="Write one curated non-case operational email JSON payload to the ops Honcho workspace")
    ops.add_argument("--json-file", type=Path, help="Payload file; stdin if omitted")

    firm = sub.add_parser("firmvault-backfill", help="Backfill accepted FirmVault Activity Log emails")
    firm.add_argument("--cases-root", type=Path, default=Path.home()/".hermes/agents/paralegal/workspace/FirmVault/cases")
    firm.add_argument("--execute", action="store_true")

    gmail = sub.add_parser("gmail-case-backfill", help="Backfill existing case Gmail messages into per-case Honcho workspaces")
    gmail.add_argument("--cases-root", type=Path, default=Path.home()/".hermes/agents/paralegal/workspace/FirmVault/cases")
    gmail.add_argument("--max-results-per-case", type=int, default=25)
    gmail.add_argument("--case-slug", action="append", dest="case_slugs", help="Limit to one case slug; repeatable")
    gmail.add_argument("--limit-cases", type=int, help="Limit number of cases processed in this run")
    gmail.add_argument("--offset-cases", type=int, default=0, help="Skip N sorted case folders before processing")
    gmail.add_argument("--execute", action="store_true")

    args = parser.parse_args()
    ingestor = HonchoEmailIngestor()

    if args.command == "ingest-case-email":
        text = args.json_file.read_text() if args.json_file else sys.stdin.read()
        email = _email_from_json(json.loads(text))
        result = ingestor.ingest_case_thread(args.case_slug, [email])
        _print_summary([result])
        return 0

    if args.command == "ingest-ops-email":
        text = args.json_file.read_text() if args.json_file else sys.stdin.read()
        email = _email_from_json(json.loads(text))
        result = ingestor.ingest_ops_thread([email])
        _print_summary([result])
        return 0

    if args.command == "firmvault-backfill":
        _print_summary(backfill_firmvault_emails(args.cases_root, ingestor=ingestor, execute=args.execute))
        return 0

    if args.command == "gmail-case-backfill":
        _print_summary(backfill_gmail_case_threads(
            args.cases_root,
            ingestor=ingestor,
            max_results_per_case=args.max_results_per_case,
            execute=args.execute,
            case_slugs=args.case_slugs,
            limit_cases=args.limit_cases,
            offset_cases=args.offset_cases,
        ))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
