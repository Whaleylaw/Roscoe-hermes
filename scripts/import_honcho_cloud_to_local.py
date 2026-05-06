#!/usr/bin/env python3
"""Import Honcho Cloud workspace messages into local Honcho.

Default is dry-run. Use --execute to write to local Honcho.
Secrets are read from ~/.hermes/.env or environment and never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from honcho import Honcho


DEFAULT_WORKSPACE = "lawyer-incorporated"
DEFAULT_LOCAL_URL = "http://localhost:8000"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def page_items(page_obj: Any) -> list[Any]:
    items = getattr(page_obj, "items", None)
    if items is not None:
        return list(items)
    return list(page_obj)


def page_total(page_obj: Any) -> int | None:
    total = getattr(page_obj, "total", None)
    return int(total) if total is not None else None


def page_count(page_obj: Any) -> int:
    pages = getattr(page_obj, "pages", None)
    if pages is not None:
        return int(pages)
    return 1


def iter_sessions(client: Honcho, page_size: int = 100):
    page_no = 1
    while True:
        page = client.sessions(page=page_no, size=page_size)
        items = page_items(page)
        if not items:
            break
        for item in items:
            yield item
        if page_no >= page_count(page):
            break
        page_no += 1


def iter_messages(session, page_size: int = 100):
    page_no = 1
    while True:
        page = session.messages(page=page_no, size=page_size)
        items = page_items(page)
        if not items:
            break
        for item in items:
            yield item
        if page_no >= page_count(page):
            break
        page_no += 1


def obj_name(obj: Any) -> str:
    return getattr(obj, "name", None) or getattr(obj, "id", None) or str(obj)


def obj_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return dict(getattr(obj, "__dict__", {}))


def existing_imported_ids(local_session) -> set[str]:
    ids: set[str] = set()
    for msg in iter_messages(local_session, page_size=100):
        data = obj_dict(msg)
        metadata = data.get("metadata") or {}
        source_id = metadata.get("source_honcho_message_id")
        if source_id:
            ids.add(str(source_id))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--local-url", default=DEFAULT_LOCAL_URL)
    parser.add_argument("--execute", action="store_true", help="actually write to local Honcho")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.05, help="sleep between write batches")
    args = parser.parse_args()

    load_env_file(Path.home() / ".hermes" / ".env")
    cloud_key = os.environ.get("HONCHO_API_KEY")
    if not cloud_key:
        print("ERROR: HONCHO_API_KEY not found in env or ~/.hermes/.env", file=sys.stderr)
        return 2

    cloud = Honcho(api_key=cloud_key, environment="production", workspace_id=args.workspace)
    local = Honcho(api_key="local", base_url=args.local_url, workspace_id=args.workspace)

    total_sessions = 0
    total_cloud_messages = 0
    total_to_import = 0
    total_skipped = 0
    total_written = 0

    print(f"mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"workspace: {args.workspace}")
    print(f"local: {args.local_url}")

    for cloud_session_obj in iter_sessions(cloud):
        session_name = obj_name(cloud_session_obj)
        total_sessions += 1
        cloud_session = cloud.session(session_name)
        local_session = local.session(session_name)

        # Preserve session metadata/configuration when possible.
        if args.execute:
            try:
                metadata = cloud_session.get_metadata()
                if metadata:
                    local_session.set_metadata(metadata)
            except Exception:
                pass
            try:
                local_session.set_configuration(cloud_session.get_configuration())
            except Exception:
                pass

        imported_ids = existing_imported_ids(local_session)
        batch = []
        session_cloud_count = 0
        session_to_import = 0
        session_skipped = 0
        session_written = 0

        for msg in iter_messages(cloud_session):
            data = obj_dict(msg)
            source_id = str(data.get("id") or "")
            session_cloud_count += 1
            total_cloud_messages += 1
            if source_id and source_id in imported_ids:
                session_skipped += 1
                total_skipped += 1
                continue

            metadata = dict(data.get("metadata") or {})
            metadata.update(
                {
                    "imported_from": "honcho-cloud",
                    "source_honcho_workspace": args.workspace,
                    "source_honcho_session": session_name,
                    "source_honcho_message_id": source_id,
                }
            )
            message = {
                "content": data.get("content") or "",
                "peer_id": data.get("peer_id") or data.get("peer_name") or "unknown",
                "metadata": metadata,
                "created_at": data.get("created_at"),
            }
            session_to_import += 1
            total_to_import += 1

            if args.execute:
                batch.append(message)
                if len(batch) >= args.batch_size:
                    local_session.add_messages(batch)
                    session_written += len(batch)
                    total_written += len(batch)
                    batch.clear()
                    if args.sleep:
                        time.sleep(args.sleep)

        if args.execute and batch:
            local_session.add_messages(batch)
            session_written += len(batch)
            total_written += len(batch)

        print(
            f"session={session_name} cloud={session_cloud_count} "
            f"to_import={session_to_import} skipped_existing={session_skipped} written={session_written}"
        )

    print("summary:")
    print(f"  sessions_seen: {total_sessions}")
    print(f"  cloud_messages_seen: {total_cloud_messages}")
    print(f"  to_import: {total_to_import}")
    print(f"  skipped_existing: {total_skipped}")
    print(f"  written: {total_written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
