# Delegate Session-Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `delegate_task` route a child agent's transcript into a *named* gateway session (typically a Slack case channel) instead of into a child session under its parent — so case work kicked off from Perry/Telegram/the web app lands in `#abby-sitgraves`'s session record.

**Architecture:** Add an optional `session_target` parameter to `delegate_task`. A new resolver maps a target spec (e.g. `slack:#abby-sitgraves`, `slack:C0AH0V6G2Q1`, or `case:abby-sitgraves`) to three values: an existing gateway `session_id`, an absolute case-folder `cwd`, and the underlying `(platform, chat_id)`. When a child is built with `session_target`, we (a) seed the child's `session_id` with the resolved value (SessionDB's `INSERT OR IGNORE` makes `create_session` a no-op for existing rows, so the child appends rather than overwrites), (b) set `parent_session_id` to the parent so the audit chain still shows Perry initiated the work, (c) run the child inside a `turn_cwd_var` context manager so file/terminal tools and `AGENTS.md` resolve under the case folder, and (d) write a one-line "inbound mirror" into the target session before the child starts so `#abby-sitgraves`'s transcript shows the request that triggered the work.

**Tech Stack:** Python 3, existing `gateway/mirror.py`, `gateway/channel_directory.py`, `agent/turn_context.py`, `tools/delegate_tool.py`, `hermes_state.SessionDB` (SQLite + JSONL), pytest.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `gateway/cross_session.py` | Create | Resolver: `resolve_session_target(spec, profile=None) -> SessionTarget` (session_id, cwd, platform, chat_id, channel_name). Uses `mirror._find_session_id` + Paralegal's `case_channels.yaml`. |
| `gateway/mirror.py` | Modify | Promote `_find_session_id` to a public helper (`find_session_id`) so the resolver can reuse it; add `mirror_inbound_to_session(session_id, request_text, source_label)` for the "request that triggered this work" entry. |
| `tools/delegate_tool.py` | Modify | Add `session_target` to `DELEGATE_SCHEMA`; resolve at the top of `delegate_task`; thread the resolved target through `_build_child_agent`; wrap each child's run in `turn_cwd_var.set(target.cwd)`. |
| `tests/gateway/test_cross_session_resolver.py` | Create | Unit tests for the resolver: slack channel ID, slack `#name`, case slug, missing target, cross-profile rejection. |
| `tests/tools/test_delegate_session_target.py` | Create | Unit tests asserting `_build_child_agent` honors `session_target` (seeds session_id, sets cwd, preserves parent linkage). |
| `docs/slack-integration.md` | Modify | Add a "Cross-session delegation" section under the Paralegal heading. |

---

## Task 1: Promote `find_session_id` and add inbound-mirror helper

**Files:**
- Modify: `gateway/mirror.py`
- Test: `tests/gateway/test_mirror.py` (extend if exists, otherwise create)

- [ ] **Step 1: Check whether `tests/gateway/test_mirror.py` exists**

Run: `ls tests/gateway/test_mirror.py 2>/dev/null && echo EXISTS || echo MISSING`

If MISSING, create it with the imports below. If EXISTS, append the new test cases.

- [ ] **Step 2: Write failing tests for the public name and the new helper**

Add (or create) `tests/gateway/test_mirror.py`:

```python
"""Tests for gateway/mirror.py — public API and inbound mirror helper."""

import json
from unittest.mock import patch

from gateway.mirror import (
    find_session_id,
    mirror_inbound_to_session,
)


def _write_sessions_index(tmp_path, entries):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "sessions.json").write_text(json.dumps(entries))
    return sessions_dir


class TestFindSessionId:
    def test_matches_chat_id(self, tmp_path):
        _write_sessions_index(tmp_path, {
            "k": {
                "session_id": "sess-abby",
                "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
                "updated_at": "2026-04-25T00:00:00",
            },
        })
        with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
            assert find_session_id("slack", "C0AH0V6G2Q1") == "sess-abby"

    def test_returns_none_when_missing(self, tmp_path):
        _write_sessions_index(tmp_path, {})
        with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
            assert find_session_id("slack", "C-nope") is None


class TestMirrorInboundToSession:
    def test_writes_user_role_to_jsonl(self, tmp_path):
        sessions_dir = _write_sessions_index(tmp_path, {})
        with patch("gateway.mirror._SESSIONS_DIR", sessions_dir), \
             patch("gateway.mirror._append_to_sqlite") as fake_sql:
            ok = mirror_inbound_to_session(
                session_id="sess-abby",
                request_text="Draft a complaint for the Smith case.",
                source_label="perry-delegate",
            )
        assert ok is True
        line = (sessions_dir / "sess-abby.jsonl").read_text().splitlines()[0]
        record = json.loads(line)
        assert record["role"] == "user"
        assert record["mirror"] is True
        assert record["mirror_source"] == "perry-delegate"
        assert "Smith" in record["content"]
        fake_sql.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_mirror.py -x -q -o addopts=""`
Expected: FAIL — `ImportError: cannot import name 'find_session_id'` and `mirror_inbound_to_session`.

- [ ] **Step 4: Implement the changes in `gateway/mirror.py`**

Replace the existing `_find_session_id` definition with a public alias and add the inbound-mirror helper. Keep the underscore name as a backward-compatible alias.

```python
# In gateway/mirror.py, replace `def _find_session_id(...)` with:

def find_session_id(platform: str, chat_id: str, thread_id: Optional[str] = None) -> Optional[str]:
    """
    Find the active session_id for a platform + chat_id pair.

    Scans sessions.json entries and matches where origin.chat_id == chat_id
    on the right platform.  DM session keys don't embed the chat_id
    (e.g. "agent:main:telegram:dm"), so we check the origin dict.
    """
    if not _SESSIONS_INDEX.exists():
        return None

    try:
        with open(_SESSIONS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    platform_lower = platform.lower()
    best_match = None
    best_updated = ""

    for _key, entry in data.items():
        origin = entry.get("origin") or {}
        entry_platform = (origin.get("platform") or entry.get("platform", "")).lower()

        if entry_platform != platform_lower:
            continue

        origin_chat_id = str(origin.get("chat_id", ""))
        if origin_chat_id == str(chat_id):
            origin_thread_id = origin.get("thread_id")
            if thread_id is not None and str(origin_thread_id or "") != str(thread_id):
                continue
            updated = entry.get("updated_at", "")
            if updated > best_updated:
                best_updated = updated
                best_match = entry.get("session_id")

    return best_match


# Backward-compatible alias — older imports still work.
_find_session_id = find_session_id


def mirror_inbound_to_session(
    session_id: str,
    request_text: str,
    source_label: str = "delegate",
) -> bool:
    """Append a user-role mirror entry recording why a delegate was started.

    Used when a delegate kicked off in one channel (e.g. #perry) is doing
    work on behalf of another channel (e.g. #abby-sitgraves).  The receiving
    case session gets a "user (via Perry) asked: ..." breadcrumb so its
    transcript explains where the upcoming work came from.
    """
    try:
        mirror_msg = {
            "role": "user",
            "content": request_text,
            "timestamp": datetime.now().isoformat(),
            "mirror": True,
            "mirror_source": source_label,
        }
        _append_to_jsonl(session_id, mirror_msg)
        _append_to_sqlite(session_id, mirror_msg)
        return True
    except Exception as e:
        logger.debug("mirror_inbound_to_session failed for %s: %s", session_id, e)
        return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_mirror.py -x -q -o addopts=""`
Expected: PASS for both new tests.

- [ ] **Step 6: Commit**

```bash
git add gateway/mirror.py tests/gateway/test_mirror.py
git commit -m "feat(mirror): public find_session_id + inbound mirror helper

Promote _find_session_id and add mirror_inbound_to_session so the
delegate session_target flow can route case-work into the right gateway
session.  Underscore alias kept for backward compat."
```

---

## Task 2: Cross-session resolver

**Files:**
- Create: `gateway/cross_session.py`
- Test: `tests/gateway/test_cross_session_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `tests/gateway/test_cross_session_resolver.py`:

```python
"""Tests for gateway/cross_session.py — session_target resolution."""

import json
from unittest.mock import patch

import pytest
import yaml

from gateway.cross_session import (
    SessionTarget,
    resolve_session_target,
    SessionTargetError,
)


def _setup(tmp_path, sessions, case_channels=None):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "sessions.json").write_text(json.dumps(sessions))
    if case_channels is not None:
        (tmp_path / "case_channels.yaml").write_text(yaml.safe_dump(case_channels))


def test_resolves_slack_channel_id(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "slack:C0AH0V6G2Q1",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target == SessionTarget(
        session_id="sess-abby",
        cwd="/cases/abby-sitgraves",
        platform="slack",
        chat_id="C0AH0V6G2Q1",
        channel_name="abby-sitgraves",
    )


def test_resolves_case_slug(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "case:abby-sitgraves",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target.session_id == "sess-abby"
    assert target.cwd == "/cases/abby-sitgraves"


def test_resolves_slack_hash_name(tmp_path):
    _setup(tmp_path, {
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        },
    }, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        target = resolve_session_target(
            "slack:#abby-sitgraves",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
    assert target.session_id == "sess-abby"


def test_no_session_yet_raises(tmp_path):
    _setup(tmp_path, {}, case_channels={
        "slug_to_channel": {"abby-sitgraves": "C0AH0V6G2Q1"},
        "channel_to_cwd": {"C0AH0V6G2Q1": "/cases/abby-sitgraves"},
        "channel_to_slug": {"C0AH0V6G2Q1": "abby-sitgraves"},
    })
    with patch("gateway.mirror._SESSIONS_INDEX", tmp_path / "sessions" / "sessions.json"):
        with pytest.raises(SessionTargetError) as exc:
            resolve_session_target(
                "slack:C0AH0V6G2Q1",
                case_channels_path=tmp_path / "case_channels.yaml",
            )
    assert "no gateway session" in str(exc.value).lower()


def test_unknown_spec_raises(tmp_path):
    _setup(tmp_path, {})
    with pytest.raises(SessionTargetError):
        resolve_session_target(
            "telegram:42",
            case_channels_path=tmp_path / "case_channels.yaml",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_cross_session_resolver.py -x -q -o addopts=""`
Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Implement `gateway/cross_session.py`**

```python
"""Resolve a session_target spec to a concrete gateway session + case folder.

Used by tools/delegate_tool.py so a child agent spawned from #perry (or DM,
or Telegram) can write its transcript into a *different* gateway session —
typically the per-case Slack channel session that owns the work.

Spec forms accepted:
    slack:<channel_id>          e.g. slack:C0AH0V6G2Q1
    slack:#<channel_name>        e.g. slack:#abby-sitgraves
    case:<slug>                  e.g. case:abby-sitgraves   (Paralegal only)

The resolver returns a :class:`SessionTarget` with the existing gateway
session_id, the absolute case-folder cwd, and the underlying platform +
chat_id.  Callers hand the cwd to ``turn_cwd_var`` so file/terminal tools
scope to the case, and hand the session_id to the child AIAgent so its
``append_message`` calls land in the case session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from gateway.mirror import find_session_id
from hermes_cli.config import get_hermes_home

logger = logging.getLogger(__name__)


class SessionTargetError(ValueError):
    """Raised when a session_target spec cannot be resolved."""


@dataclass(frozen=True)
class SessionTarget:
    session_id: str
    cwd: Optional[str]
    platform: str
    chat_id: str
    channel_name: Optional[str]


def _default_case_channels_path() -> Path:
    return get_hermes_home() / "case_channels.yaml"


def _load_case_channels(path: Optional[Path]) -> dict:
    p = Path(path) if path else _default_case_channels_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("case_channels load failed (%s): %s", p, e)
        return {}
    return data if isinstance(data, dict) else {}


def resolve_session_target(
    spec: str,
    case_channels_path: Optional[Path] = None,
) -> SessionTarget:
    """Resolve a session_target spec to a SessionTarget.

    Raises SessionTargetError if the spec can't be parsed, the case isn't
    mapped, or no gateway session exists yet for the channel.
    """
    if not spec or ":" not in spec:
        raise SessionTargetError(
            f"session_target must be 'slack:<id|#name>' or 'case:<slug>', got {spec!r}"
        )

    kind, _, value = spec.partition(":")
    kind = kind.strip().lower()
    value = value.strip()

    case_map = _load_case_channels(case_channels_path)
    slug_to_channel = case_map.get("slug_to_channel") or {}
    channel_to_cwd = case_map.get("channel_to_cwd") or {}
    channel_to_slug = case_map.get("channel_to_slug") or {}

    if kind == "case":
        channel_id = slug_to_channel.get(value)
        if not channel_id:
            raise SessionTargetError(f"Unknown case slug: {value}")
        platform = "slack"
        chat_id = channel_id
        channel_name = value
    elif kind == "slack":
        if value.startswith("#"):
            name = value[1:]
            channel_id = slug_to_channel.get(name)
            if not channel_id:
                raise SessionTargetError(
                    f"Slack channel #{name} is not in case_channels.yaml"
                )
            channel_name = name
        else:
            channel_id = value
            channel_name = channel_to_slug.get(channel_id)
        platform = "slack"
        chat_id = channel_id
    else:
        raise SessionTargetError(
            f"Unsupported session_target kind {kind!r} (expected 'slack' or 'case')"
        )

    session_id = find_session_id(platform, chat_id)
    if not session_id:
        raise SessionTargetError(
            f"{platform}:{chat_id} has no gateway session yet — send any "
            "message in that channel first so the gateway records its origin."
        )

    cwd = channel_to_cwd.get(chat_id)
    return SessionTarget(
        session_id=session_id,
        cwd=cwd,
        platform=platform,
        chat_id=chat_id,
        channel_name=channel_name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_cross_session_resolver.py -x -q -o addopts=""`
Expected: PASS — all five tests.

- [ ] **Step 5: Commit**

```bash
git add gateway/cross_session.py tests/gateway/test_cross_session_resolver.py
git commit -m "feat(cross-session): resolver maps session_target to existing session+cwd"
```

---

## Task 3: `delegate_task` schema + plumbing

**Files:**
- Modify: `tools/delegate_tool.py`
- Test: `tests/tools/test_delegate_session_target.py`

- [ ] **Step 1: Write failing test for `_build_child_agent` honoring session_target**

Create `tests/tools/test_delegate_session_target.py`:

```python
"""Unit tests: _build_child_agent uses session_target to override session_id+cwd."""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from gateway.cross_session import SessionTarget


def _fake_parent_agent():
    return SimpleNamespace(
        session_id="sess-perry",
        _session_db=MagicMock(),
        platform="slack",
        max_tokens=4096,
        prefill_messages=None,
        tool_progress_callback=None,
        providers_allowed=None,
        providers_ignored=None,
        providers_order=None,
        provider_sort=None,
        cwd=None,
        terminal_cwd=None,
        _delegate_depth=0,
        _delegate_spinner=None,
        _print_fn=None,
        _active_children=[],
        _subdirectory_hints=None,
        _credential_pool=None,
    )


def test_build_child_uses_target_session_id_and_cwd(monkeypatch):
    """When session_target is provided, child.session_id == target.session_id."""
    from tools import delegate_tool

    target = SessionTarget(
        session_id="sess-abby",
        cwd="/cases/abby-sitgraves",
        platform="slack",
        chat_id="C0AH0V6G2Q1",
        channel_name="abby-sitgraves",
    )

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        # Attributes _build_child_agent assigns post-construction
        def __setattr__(self, k, v):
            captured[k] = v

    monkeypatch.setattr(delegate_tool, "AIAgent", FakeAgent)
    # Skip credential resolution and config noise — the test just checks
    # the session_id / parent_session_id wiring.
    monkeypatch.setattr(delegate_tool, "_resolve_delegation_credentials",
                        lambda *_a, **_kw: (None, None, None, None, None, None, None))
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {})

    parent = _fake_parent_agent()

    delegate_tool._build_child_agent(
        parent_agent=parent,
        task_index=0,
        goal="Draft complaint",
        context=None,
        toolsets=["file_ops"],
        role="leaf",
        max_iterations=5,
        creds=(None, None, None, None, None, None, None),
        cfg={},
        subagent_id="sub-1",
        parent_subagent_id=None,
        child_depth=1,
        session_target=target,
    )

    assert captured["session_id"] == "sess-abby"
    assert captured["parent_session_id"] == "sess-perry"
```

(NOTE: `_build_child_agent`'s real signature has more positional args — Step 3 below adds the `session_target` kwarg. Adjust the call above to match the new signature exactly when the implementation step is done.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tools/test_delegate_session_target.py -x -q -o addopts=""`
Expected: FAIL — `_build_child_agent` has no `session_target` parameter.

- [ ] **Step 3: Update `DELEGATE_SCHEMA` and `delegate_task` to accept session_target**

In `tools/delegate_tool.py`, find `DELEGATE_SCHEMA` (search: `"name": "delegate_task"`). Add a `session_target` property:

```python
"session_target": {
    "type": "string",
    "description": (
        "Optional. Route this delegate's transcript into an existing "
        "gateway session instead of a fresh child session. Format: "
        "'slack:<channel_id>', 'slack:#<channel_name>', or "
        "'case:<slug>'. The child's working directory and AGENTS.md "
        "are also scoped to the case folder when the target maps to "
        "one. Use this when work kicked off from #perry or a DM "
        "should be recorded under a specific case."
    ),
},
```

Add the same property to each task-shaped schema inside `DELEGATE_SCHEMA["parameters"]["properties"]["tasks"]["items"]["properties"]` so batch tasks can override it per-entry.

- [ ] **Step 4: Resolve `session_target` at the top of `delegate_task`**

In `delegate_task` (around line 1697), after the `top_role = _normalize_role(role)` line, add:

```python
# Resolve top-level session_target once.  Per-task overrides re-resolve.
top_session_target_spec = (
    kwargs.get("session_target") if isinstance(kwargs, dict) else None
)
```

Wait — `delegate_task` doesn't take `**kwargs`. Update its signature:

```python
def delegate_task(
    goal: Optional[str] = None,
    context: Optional[str] = None,
    toolsets: Optional[List[str]] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
    max_iterations: Optional[int] = None,
    acp_command: Optional[str] = None,
    acp_args: Optional[List[str]] = None,
    role: Optional[str] = None,
    session_target: Optional[str] = None,
    parent_agent=None,
) -> str:
```

Then wherever the top-level task is built (around line 1791), include the spec:

```python
elif goal and isinstance(goal, str) and goal.strip():
    task_list = [
        {
            "goal": goal,
            "context": context,
            "toolsets": toolsets,
            "role": top_role,
            "session_target": session_target,
        }
    ]
```

- [ ] **Step 5: Plumb resolved target into `_build_child_agent`**

Inside `delegate_task`'s task loop (where it calls `_build_child_agent`), resolve each task's `session_target`:

```python
from gateway.cross_session import resolve_session_target, SessionTargetError, SessionTarget

resolved_target: Optional[SessionTarget] = None
spec = t.get("session_target") or session_target
if spec:
    try:
        resolved_target = resolve_session_target(spec)
    except SessionTargetError as exc:
        results.append({
            "task_index": i,
            "goal": t.get("goal", ""),
            "error": f"session_target unresolved: {exc}",
        })
        continue
```

Pass it into `_build_child_agent(..., session_target=resolved_target)`.

- [ ] **Step 6: Update `_build_child_agent` to override session_id and parent_session_id**

In `_build_child_agent` (line 768), add `session_target: Optional[SessionTarget] = None` to the signature. Just before the `child = AIAgent(...)` block at line 955, compute the overrides:

```python
override_session_id = session_target.session_id if session_target else None
parent_session_id_for_child = (
    getattr(parent_agent, "session_id", None)
    if not session_target else getattr(parent_agent, "session_id", None)
)
# Note: parent_session_id is preserved — even when writing into the case
# session, we want the audit chain to still show Perry initiated it.
```

Then in the `AIAgent(...)` call:
- Replace `session_id=task_id` (if present — search for it) with `session_id=override_session_id or task_id`.
- Keep `parent_session_id=parent_session_id_for_child`.

If `_build_child_agent` doesn't currently pass `session_id` to AIAgent (the child auto-generates one), add the kwarg:

```python
session_id=override_session_id,
```

(AIAgent's `__init__` already handles `session_id=None` by auto-generating, so this is safe.)

- [ ] **Step 7: Wrap child execution in `turn_cwd_var` when target.cwd is set**

Find the executor that runs child agents (around line 1328 — `task_id=child_task_id`). The child's `agent.run_conversation` call must be wrapped in `turn_cwd_var.set(...)` so `_resolve_workspace_hint`, terminal_tool, file_tools, and AGENTS.md loader pick up the case folder.

Add at the top of the file:

```python
from agent.turn_context import turn_cwd_var
```

Before invoking `child.run_conversation(...)` inside `_run_single_child` (or whichever wrapper actually executes the child), capture and reset:

```python
_cwd_token = None
if session_target and session_target.cwd:
    _cwd_token = turn_cwd_var.set(session_target.cwd)
try:
    result = child.run_conversation(...)
finally:
    if _cwd_token is not None:
        turn_cwd_var.reset(_cwd_token)
```

Plumb `session_target` into `_run_single_child` (or equivalent) the same way `goal`/`subagent_id` are plumbed today.

- [ ] **Step 8: Mirror the inbound request into the target session**

Right before the child runs (after the cwd context is set, before `child.run_conversation`), record the breadcrumb:

```python
if session_target:
    from gateway.mirror import mirror_inbound_to_session
    mirror_inbound_to_session(
        session_id=session_target.session_id,
        request_text=f"(via {parent_agent.platform or 'parent session'}) {t['goal']}",
        source_label=f"delegate-from-{getattr(parent_agent, 'session_id', 'unknown')}",
    )
```

- [ ] **Step 9: Run the focused unit test to verify**

Run: `python -m pytest tests/tools/test_delegate_session_target.py -x -q -o addopts=""`
Expected: PASS.

- [ ] **Step 10: Run the broader delegate test suite to verify no regressions**

Run: `python -m pytest tests/tools/ -k delegate -x -q -o addopts=""`
Expected: PASS (or pre-existing failures only — note any).

- [ ] **Step 11: Commit**

```bash
git add tools/delegate_tool.py tests/tools/test_delegate_session_target.py
git commit -m "feat(delegate): session_target routes child transcript into target session

Child agents spawned with session_target='slack:#abby-sitgraves' now
write their messages into that case channel's gateway session, run with
the case-folder cwd, and leave a breadcrumb in the target session
explaining where the request came from. Parent linkage preserved."
```

---

## Task 4: End-to-end smoke test

**Files:**
- Test: `tests/integration/test_delegate_session_target_e2e.py` (create)

- [ ] **Step 1: Write an integration-style test that exercises the full path**

```python
"""End-to-end: delegate_task with session_target writes to the target session."""

import json
from unittest.mock import patch

import pytest


@pytest.mark.integration
def test_delegate_with_session_target_appends_to_existing_session(tmp_path, monkeypatch):
    """Stand up a minimal sessions.json + case_channels, run delegate_task with
    a session_target spec, and assert the target session's JSONL transcript
    received the inbound mirror plus at least one assistant entry."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "sessions.json").write_text(json.dumps({
        "k": {
            "session_id": "sess-abby",
            "origin": {"platform": "slack", "chat_id": "C0AH0V6G2Q1"},
            "updated_at": "2026-04-25T00:00:00",
        }
    }))
    (sessions_dir / "sess-abby.jsonl").write_text("")

    case_channels = tmp_path / "case_channels.yaml"
    case_channels.write_text(
        "channel_to_cwd:\n"
        "  C0AH0V6G2Q1: /tmp/cases/abby-sitgraves\n"
        "channel_to_slug:\n"
        "  C0AH0V6G2Q1: abby-sitgraves\n"
        "slug_to_channel:\n"
        "  abby-sitgraves: C0AH0V6G2Q1\n"
    )

    monkeypatch.setattr("gateway.mirror._SESSIONS_INDEX",
                        sessions_dir / "sessions.json")
    monkeypatch.setattr("gateway.mirror._SESSIONS_DIR", sessions_dir)

    # Stub the child agent so we don't make real API calls.
    from tools import delegate_tool

    class StubAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs.get("session_id")
            self.session_log_file = sessions_dir / f"{self.session_id}.jsonl"
            self._session_db = kwargs.get("session_db")

        def run_conversation(self, user_message, task_id=None):
            from gateway.mirror import _append_to_jsonl
            _append_to_jsonl(self.session_id, {
                "role": "assistant",
                "content": "Drafted complaint.",
            })
            return {"final_response": "Drafted complaint."}

    monkeypatch.setattr(delegate_tool, "AIAgent", StubAgent)

    parent = type("P", (), {
        "session_id": "sess-perry",
        "platform": "slack",
        "_session_db": None,
        "providers_allowed": None,
        "providers_ignored": None,
        "providers_order": None,
        "provider_sort": None,
        "max_tokens": 4096,
        "prefill_messages": None,
        "tool_progress_callback": None,
        "_active_children": [],
        "_delegate_depth": 0,
        "_delegate_spinner": None,
        "_print_fn": None,
        "cwd": None,
        "terminal_cwd": None,
    })()

    out = delegate_tool.delegate_task(
        goal="Draft a complaint.",
        toolsets=["file_ops"],
        session_target="case:abby-sitgraves",
        parent_agent=parent,
    )

    transcript = (sessions_dir / "sess-abby.jsonl").read_text().splitlines()
    roles = [json.loads(line)["role"] for line in transcript]
    assert "user" in roles      # inbound mirror
    assert "assistant" in roles # child output
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/integration/test_delegate_session_target_e2e.py -x -q -o addopts="-m integration"`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_delegate_session_target_e2e.py
git commit -m "test(delegate): e2e smoke test for session_target routing"
```

---

## Task 5: Documentation

**Files:**
- Modify: `docs/slack-integration.md`

- [ ] **Step 1: Add a "Cross-session delegation" subsection under the Paralegal heading**

Insert after the "Mapping file" subsection (around line 196 in `docs/slack-integration.md`):

````markdown
### Cross-session delegation

Perry can be asked from `#perry`, a DM, Telegram, or the web app to "go work
the Smith case and post an update to `#smith`". The straightforward path —
have Perry just call `send_message` — works, but the upstream tool calls
and reasoning end up in Perry's unified-timeline session, not in the case
session that owns the work.

`delegate_task` accepts a `session_target` argument that routes a child
agent's whole transcript into a *named* gateway session:

```
delegate_task(
    goal="Review the latest medical records and draft a demand letter.",
    toolsets=["file_ops", "messaging"],
    session_target="case:smith",   # or "slack:#smith" or "slack:C0…"
)
```

What that does:

- Resolves the existing gateway session_id for `#smith` (must have been
  messaged at least once so the gateway has recorded its origin).
- Sets the child's `cwd` to the case folder so AGENTS.md, terminal, and
  file tools are scoped to the case.
- Records a "(via slack) <goal>" breadcrumb in `#smith`'s transcript.
- Preserves `parent_session_id = <Perry's session>` so the audit chain
  still shows Perry initiated the work.

Spec forms:

- `slack:<channel_id>` — e.g. `slack:C0AH0V6G2Q1`
- `slack:#<channel_name>` — resolved via `case_channels.yaml`
- `case:<slug>` — Paralegal-only convenience form

If the target channel has never received a message (no gateway session
exists yet), the resolver raises `SessionTargetError`; send any message
in the channel first.
````

- [ ] **Step 2: Commit**

```bash
git add docs/slack-integration.md
git commit -m "docs(slack): document delegate session_target for cross-session work"
```

---

## Self-review checklist (run before declaring complete)

- [ ] All five tasks committed in order.
- [ ] `python -m pytest tests/gateway/test_mirror.py tests/gateway/test_cross_session_resolver.py tests/tools/test_delegate_session_target.py -x -q -o addopts=""` passes.
- [ ] `grep -n session_target tools/delegate_tool.py` shows: schema property, function signature, resolution at top of delegate_task, override in `_build_child_agent`, cwd ContextVar wrap around child run, and inbound-mirror call.
- [ ] `docs/slack-integration.md` has the "Cross-session delegation" subsection.
- [ ] Restart paralegal gateway and try one real call from `#perry`: ask Perry to delegate work into `#abby-sitgraves` with `session_target="case:abby-sitgraves"`, then read `~/.hermes/profiles/paralegal/sessions/<sess-abby>.jsonl` and confirm the breadcrumb + assistant output landed there.
