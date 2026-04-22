# Inter-Agent Tools — Design

**Date:** 2026-04-22
**Repo:** Roscoe-hermes
**Related:** `a2a-bridge` (unchanged by this feature)

## Summary

Add a new `inter_agent` toolset to Roscoe-hermes that lets one Hermes profile discover and talk to other Hermes profiles over the existing A2A bridge. This implements the "Roscoe asks Paralegal" use case the user has been wanting without modifying `a2a-bridge`.

## Background

- Each Hermes profile (`default`/Roscoe, `paralegal`, `coder`, `storysmith`, `brainstorm`) is an independent agent with its own config and model.
- The `a2a-bridge` repo (`/Users/aaronwhaley/Github/a2a-bridge`) already exposes each profile at `127.0.0.1:1880{0..4}` as an A2A JSON-RPC endpoint: `tasks/send`, `tasks/get`, `tasks/cancel`, `tasks/sendSubscribe`.
- Hermes's existing `delegate_task` tool spawns **in-process subagents** that inherit the parent's model/credentials. It cannot route to a different profile — that's an unrelated mechanism.
- Nothing in Hermes currently calls the bridge. This spec closes that gap.

## Goals

1. Profile A can list available peer profiles.
2. Profile A can send a synchronous Q&A message to profile B and receive the reply.
3. Profile A can dispatch a longer task to profile B without blocking, then poll for completion.
4. No changes required in `a2a-bridge`.
5. Subagents spawned via `delegate_task` cannot use these tools (depth-limit integrity).

## Non-Goals

- Persistent task storage across restarts (bridge already in-memory; we don't improve that here).
- Loop prevention beyond self-call rejection. Two-agent ping-pong is theoretically possible but capped by each profile's `max_turns` (60) and the bridge's 120 s HTTP timeout. If observed in practice, add hop-counter depth limiting later.
- Streaming responses (`tasks/sendSubscribe`). Out of scope for MVP.
- Context/history hand-off. Each peer message is a fresh user turn on the receiving side.
- Modifications to `agents.registry.json` at runtime.

## Design

### Architecture

```
 Hermes (roscoe profile)
   └─ inter_agent toolset
        ├─ list_agents         ─┐
        ├─ ask_agent           ─┼─> POST http://127.0.0.1:1880{N} (A2A bridge)
        ├─ dispatch_agent_task ─┤         │
        └─ check_agent_task    ─┘         └─> target Hermes profile (e.g. paralegal) :8643
```

All four tools are pure HTTP clients. No shared state in Hermes; the bridge's per-profile in-memory task store is the only authoritative source for task state.

### Components

| File | Change |
|---|---|
| `tools/inter_agent_tool.py` | **New.** All four tools, shared HTTP helper, registry loader, env-var-driven config. |
| `toolsets.py` | Register new `"inter_agent"` entry containing the four tool names. |
| `tools/delegate_tool.py` | Add `list_agents`, `ask_agent`, `dispatch_agent_task`, `check_agent_task` to `DELEGATE_BLOCKED_TOOLS`. |
| `tests/tools/test_inter_agent.py` | **New.** Unit tests (mocked HTTP) and an opt-in live integration block. |
| `tests/tools/test_delegate.py` | Add assertion that the four new tool names appear in `DELEGATE_BLOCKED_TOOLS`. |

### Config surface (env vars only)

| Var | Required | Default | Purpose |
|---|---|---|---|
| `A2A_REGISTRY_PATH` | yes | — | Path to `agents.registry.json`. Toolset `check_fn` returns false if unset or unreadable. |
| `HERMES_TOKEN` | yes | — | Bearer token shared with the bridge. Toolset disabled if unset. |
| `HERMES_A2A_SELF` | recommended | — | This profile's `id` (e.g. `"roscoe"`). Used to block self-calls and filter self from `list_agents`. If unset, tools run in degraded mode (warning logged; self-filter and self-call rejection disabled). |
| `INTER_AGENT_TIMEOUT` | no | `120` | Per-call HTTP timeout, seconds. |

No `~/.hermes/config.yaml` additions. Keeps the tool's boundary aligned with how the bridge itself is already configured.

### Tools

#### `list_agents()` — no args

1. Read `A2A_REGISTRY_PATH`; take entries with `source == "hermes"`.
2. Exclude the entry whose `id == HERMES_A2A_SELF` (if set).
3. Fan out `GET {a2a_url}/health` in parallel (`ThreadPoolExecutor`, 4 workers, 3 s timeout each). Unauth'd — the bridge treats `/health` as public.
4. Return JSON:
   ```json
   { "agents": [
       { "id": "paralegal", "name": "Paralegal",
         "description": "...",
         "a2a_url": "http://127.0.0.1:18801",
         "skills": [{"id":"case-support","name":"Case Support"}, ...],
         "online": true }
     ] }
   ```

#### `ask_agent(agent_id, goal, context=None, timeout=None)` — synchronous

1. Resolve `agent_id` against the registry; error if unknown, error if self.
2. Compose text: `goal` alone, or `goal + "\n\nCONTEXT:\n" + context` when context is provided.
3. `task_id = uuid4()`. POST `{a2a_url}/` with JSON-RPC `tasks/send`:
   ```json
   {"jsonrpc":"2.0","id":"<req_uuid>","method":"tasks/send",
    "params":{"id":"<task_id>","message":{"role":"user","parts":[{"type":"text","text":"<composed>"}]}}}
   ```
   Header: `Authorization: Bearer $HERMES_TOKEN`.
4. Block up to `timeout` (default `INTER_AGENT_TIMEOUT`).
5. Parse JSON-RPC response; return:
   ```json
   { "agent_id": "paralegal", "task_id": "<uuid>",
     "status": "completed", "reply": "<text>" }
   ```

#### `dispatch_agent_task(agent_id, goal, context=None)` — asynchronous

1. Same resolution + compose as `ask_agent`.
2. `task_id = uuid4()`. Spawn a daemon thread that POSTs the same JSON-RPC `tasks/send` (using `INTER_AGENT_TIMEOUT`) and logs any non-2xx / exception via `logger.warning`. No retry. No shared queue. No persistence.
3. Return immediately:
   ```json
   { "agent_id": "paralegal", "task_id": "<uuid>", "status": "dispatched" }
   ```
4. Because the bridge inserts the task in `"working"` state before calling Hermes (`hermes-server/server.py:211-214`), a subsequent `check_agent_task` sees real status — not 404 — even if the dispatch thread has not finished.

#### `check_agent_task(agent_id, task_id)`

1. POST `tasks/get` with `{"id": task_id}` to the agent's `a2a_url`, bearer-authed.
2. Parse `status.state`:
   - `"working"` → `{ "status": "working" }`
   - `"completed"` → `{ "status": "completed", "reply": artifacts[0].parts[0].text }`
   - `"failed"` / `"canceled"` → `{ "status": "<state>", "error": "<msg if present>" }`
3. Bridge returns JSON-RPC `-32001` ("task not found") → `{ "status": "unknown", "error": "task not found on bridge — may have been lost to bridge restart" }`.

### Data flow

```
list_agents:
  file read → parallel GET /health → merge → return

ask_agent:
  registry lookup → compose → POST tasks/send (blocking) → parse → return

dispatch_agent_task:
  registry lookup → compose → spawn daemon POST tasks/send → return {task_id,"dispatched"}

check_agent_task:
  POST tasks/get → parse status → return {status, reply?|error?}
```

### Error handling

All errors return structured JSON via `tool_error(...)`; no exceptions reach the LLM.

| Condition | Return |
|---|---|
| `agent_id == HERMES_A2A_SELF` | `{"error": "Cannot send to yourself (agent_id=<self>). Use delegate_task for in-process subagents."}` |
| `agent_id` not in registry | `{"error": "Unknown agent_id: '<x>'. Call list_agents to see available agents."}` |
| `HERMES_TOKEN` unset | `check_fn` returns false → toolset disabled at tool-registry load; logs `"inter_agent disabled: HERMES_TOKEN not set"`. |
| `A2A_REGISTRY_PATH` unset/unreadable | Same: `check_fn` disables toolset. |
| Bridge not reachable (connection refused / DNS / socket) | `{"status": "error", "error": "Bridge not reachable at <url>: <msg>"}`. `list_agents` reports `online: false` per-agent rather than a top-level error. |
| HTTP 401 | `{"status": "error", "error": "Auth rejected by bridge. Check HERMES_TOKEN matches bridge config."}` |
| HTTP timeout in `ask_agent` | `{"status": "timeout", "agent_id": "<x>", "task_id": "<uuid>", "hint": "Task may still complete on the bridge. Call check_agent_task with this task_id."}` |
| JSON-RPC error from bridge | Pass `code`/`message` through in a structured error object. |
| Malformed response | `{"status": "error", "error": "Bridge returned malformed response: <first 200 chars>"}` |
| `dispatch_agent_task` thread failure | Logged via `logger.warning`; `check_agent_task` will surface the bridge's terminal state. |

### Testing

**Unit tests** (`tests/tools/test_inter_agent.py`, mirroring `test_delegate.py`):

- Mock `urllib.request.urlopen` at module level.
- Happy paths for each tool (`list_agents`, `ask_agent`, `dispatch_agent_task`, `check_agent_task`).
- Error paths: self-call rejection, unknown agent, 401, timeout, malformed response.
- `check_fn` behavior: missing env vars → returns False.
- Self-filter: `list_agents` excludes the `HERMES_A2A_SELF` entry.
- Degraded mode: if `HERMES_A2A_SELF` unset, self-call protection is skipped (expected) and a warning is logged.

**Subagent block** (addition to `tests/tools/test_delegate.py`): set-membership assertion that all four tool names are present in `DELEGATE_BLOCKED_TOOLS`.

**Integration tests** (opt-in): gated on `INTER_AGENT_LIVE_TEST=1` and bridge reachability. For each registered peer, run `ask_agent` with a sentinel prompt and assert the reply contains the sentinel. Skipped by default.

### Interface summary (tool schemas)

```
list_agents() → {"agents": [...]}

ask_agent(agent_id: str, goal: str, context: str? = None, timeout: int? = None)
  → {"agent_id", "task_id", "status": "completed"|"timeout"|"error", "reply"?, "error"?, "hint"?}

dispatch_agent_task(agent_id: str, goal: str, context: str? = None)
  → {"agent_id", "task_id", "status": "dispatched"|"error", "error"?}

check_agent_task(agent_id: str, task_id: str)
  → {"agent_id", "task_id", "status": "working"|"completed"|"failed"|"canceled"|"unknown",
     "reply"?, "error"?}
```

All schemas registered via the existing `tools.registry.registry.register(...)` pattern, following `tools/delegate_tool.py` conventions.

## Rollout

1. Land the feature with `check_fn` gating — toolset is a no-op until env vars are set and registry is reachable.
2. Enable on the `roscoe` (default) profile first by adding `inter_agent` to its enabled toolsets. Validate with live integration tests.
3. Enable on remaining profiles incrementally (`paralegal`, `coder`, `storysmith`, `brainstorm`) after behavior is confirmed.
4. Document usage in `docs/user-guide/`.

## Open questions (deferred)

- Hop-counter depth limiting: add if we observe ping-pong in practice.
- Streaming via `tasks/sendSubscribe`: worth adding once an LLM use case demands partial responses.
- Surface delivery receipts / audit log: tie into Hermes's existing memory/session layer if/when needed.
