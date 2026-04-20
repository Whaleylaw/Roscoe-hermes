#!/usr/bin/env python3
"""Ingest OpenClaw memory archive into Hermes Honcho.

One-shot migration run on 2026-04-16: uploads dated day-summaries, design docs,
and litigation reports from the retired OpenClaw main/coder/paralegal agents
into the configured Hermes Honcho workspace under the user peer. Also refreshes
the canonical MEMORY.md / USER.md / SOUL.md so the peer representation picks up
the post-merge content.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from plugins.memory.honcho.client import (  # noqa: E402
    HonchoClientConfig,
    get_honcho_client,
    reset_honcho_client,
)
from plugins.memory.honcho.session import HonchoSessionManager  # noqa: E402

AGENT_DESCRIPTIONS = {
    "main": (
        "day-summaries, decisions, and operational notes from Roscoe (the main "
        "agent) — covers setup, fork migration, infrastructure, and cross-agent "
        "coordination"
    ),
    "coder": (
        "coding and technical design notes from the Coder agent — covers "
        "Roscoe/Hermes architecture, workflow design, and integration plans"
    ),
    "paralegal": (
        "legal work notes from the Paralegal agent — covers case management, "
        "litigation, client/attorney relationships, and firm operations"
    ),
}


def wrap(content: str, agent: str, original_file: str) -> str:
    description = AGENT_DESCRIPTIONS[agent]
    return (
        "<prior_openclaw_memory>\n"
        "<context>\n"
        f"This memory file was written by the OpenClaw '{agent}' agent before "
        "OpenClaw was retired on 2026-04-16. It contains "
        f"{description}. Treat as foundational historical context — events "
        "that happened and facts that may still apply.\n"
        f"Original file: {original_file}\n"
        "</context>\n"
        "\n"
        f"{content}\n"
        "</prior_openclaw_memory>\n"
    )


def main() -> int:
    home = Path.home()
    archive = home / ".hermes" / "memories" / "openclaw-archive"
    memories_dir = home / ".hermes" / "memories"
    soul_path = home / ".hermes" / "SOUL.md"

    if not archive.exists():
        print(f"Archive not found: {archive}")
        return 1

    reset_honcho_client()
    hcfg = HonchoClientConfig.from_global_config()
    client = get_honcho_client(hcfg)
    mgr = HonchoSessionManager(honcho=client, config=hcfg)
    session_key = hcfg.resolve_session_name()
    print(f"Honcho session key: {session_key}")
    session = mgr.get_or_create(session_key)
    honcho_session = mgr._sessions_cache.get(session.honcho_session_id)
    if honcho_session is None:
        print("Could not resolve Honcho session — aborting.")
        return 2
    user_peer = mgr._get_or_create_peer(session.user_peer_id)
    assistant_peer = mgr._get_or_create_peer(session.assistant_peer_id)

    uploaded = 0
    failed = 0
    for agent in ("main", "coder", "paralegal"):
        agent_dir = archive / agent
        if not agent_dir.exists():
            print(f"[skip] {agent_dir} not found")
            continue
        for f in sorted(agent_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8").strip()
                if not content:
                    print(f"[skip] {agent}/{f.name} (empty)")
                    continue
                wrapped = wrap(content, agent, f.name)
                upload_name = f"openclaw-{agent}-{f.stem}.md"
                honcho_session.upload_file(
                    file=(upload_name, wrapped.encode("utf-8"), "text/plain"),
                    peer=user_peer,
                    metadata={
                        "source": "openclaw-archive",
                        "agent": agent,
                        "original_file": f.name,
                    },
                )
                print(f"[ok]   {agent}/{f.name}")
                uploaded += 1
            except Exception as e:
                print(f"[fail] {agent}/{f.name}: {e}")
                failed += 1

    print()
    print("Re-uploading canonical MEMORY.md / USER.md...")
    if mgr.migrate_memory_files(session_key, str(memories_dir)):
        print("[ok]   canonical user memory uploaded")
    else:
        print("[skip] no canonical user memory uploaded")

    print()
    print("Re-uploading SOUL.md to assistant peer...")
    if soul_path.exists():
        try:
            soul_content = soul_path.read_text(encoding="utf-8").strip()
            wrapped_soul = (
                "<prior_memory_file>\n"
                "<context>\n"
                "Post-OpenClaw-merge SOUL.md (2026-04-16). Defines Hermes' "
                "identity as CEO of Lawyer Incorporated + The Hand, with "
                "paralegal/coding/brainstorm mode-switching absorbed from the "
                "retired Roscoe agent family.\n"
                "</context>\n"
                "\n"
                f"{soul_content}\n"
                "</prior_memory_file>\n"
            )
            honcho_session.upload_file(
                file=("agent_soul.md", wrapped_soul.encode("utf-8"), "text/plain"),
                peer=assistant_peer,
                metadata={
                    "source": "local_memory",
                    "original_file": "SOUL.md",
                    "target_peer": "ai",
                    "post_openclaw_merge": "true",
                },
            )
            print("[ok]   SOUL.md uploaded to assistant peer")
        except Exception as e:
            print(f"[fail] SOUL.md upload: {e}")
    else:
        print("[skip] SOUL.md not found")

    print()
    print(f"Archive files uploaded: {uploaded}")
    if failed:
        print(f"Failures: {failed}")
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
