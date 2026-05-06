# Roscoe Unified CLI Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Ship an installable `roscoe` CLI that exposes a single command surface for built-in Hermes tools, Python callables, MCP tools/servers, and CLI-Anything harnesses.

**Architecture:** Build a Roscoe command bus with a strict `ToolSpec`/`ToolResult` contract and pluggable adapters. Reuse Hermes internals (`tools.registry`, `model_tools.handle_function_call`, `tools/mcp_tool.py`) instead of reimplementing execution logic. Treat CLI-Anything as an external catalog/provider adapter, not the core runtime.

**Tech Stack:** Python 3.11+, argparse (existing style), Pydantic (already dependency), Hermes tool registry, MCP integration, optional CLI-Anything bridge.

---

## Product requirements (from user intent)

1. Install once (`pipx install ...`) and run `roscoe ...` anywhere.
2. If unfamiliar, `roscoe help` gives complete command navigation.
3. Discoverability: list/search/inspect commands for all tools regardless of backend.
4. Unified invocation path: one `run` command, same JSON envelope for output/errors.
5. Backends include:
   - Hermes built-in tools
   - Python function adapters
   - MCP tools/servers
   - CLI-Anything harnesses
   - (Phase 2) Agent-task/A2A style tools
6. Keep LLM context clean by letting operators/agents run tools through CLI directly.

---

## Command surface (target UX)

```bash
roscoe help
roscoe tools list [--backend builtin|python|mcp|cli-anything|all] [--json]
roscoe tools search <query> [--json]
roscoe tools inspect <tool-name>
roscoe run <tool-name> --input '{"k":"v"}'
roscoe run <tool-name> --file payload.json
roscoe mcp servers list
roscoe mcp refresh
roscoe catalog sync
roscoe doctor
```

### Output contract (all backends)

```json
{
  "ok": true,
  "tool": "browser_snapshot",
  "backend": "builtin",
  "duration_ms": 123,
  "result": {"...": "..."},
  "error": null,
  "trace_id": "run_..."
}
```

Errors keep the same shape with `ok=false`, structured `error` object, and non-zero exit code.

---

## Repo changes (phased)

## Phase 1 — MVP command bus (builtin + MCP + Python)

### Task 1: Create Roscoe CLI package scaffold

**Objective:** Add an isolated package for new `roscoe` command without breaking `hermes`.

**Files:**
- Create: `roscoe_cli/__init__.py`
- Create: `roscoe_cli/main.py`
- Create: `roscoe_cli/commands.py`
- Modify: `pyproject.toml`

**Implementation notes:**
- Add script entrypoint:
  - `roscoe = "roscoe_cli.main:main"`
- Keep argparse style aligned with `hermes_cli/main.py`.
- `roscoe help` must work without provider credentials.

**Verification:**
```bash
python -m roscoe_cli.main --help
roscoe --help
```
Expected: usage and subcommands render cleanly.

---

### Task 2: Define universal contracts

**Objective:** Standardize tool metadata and execution envelope.

**Files:**
- Create: `roscoe_cli/contracts.py`

**Implementation notes:**
- Add pydantic/dataclass models:
  - `ToolSpec(name, backend, description, input_schema, tags, safety)`
  - `ToolRunRequest(tool, input, timeout, dry_run)`
  - `ToolRunResult(ok, tool, backend, duration_ms, result, error, trace_id)`
  - `ToolError(code, message, details)`
- Include versioned schema field (e.g., `contract_version="1"`).

**Verification:**
- Unit tests can instantiate and serialize all contracts.

---

### Task 3: Build adapter interface + registry

**Objective:** Enable multiple backend providers behind one dispatcher.

**Files:**
- Create: `roscoe_cli/adapters/base.py`
- Create: `roscoe_cli/adapters/registry.py`

**Implementation notes:**
- Define `ToolAdapter` protocol:
  - `list_tools() -> list[ToolSpec]`
  - `inspect_tool(name) -> ToolSpec | None`
  - `run(name, payload) -> ToolRunResult`
- Implement adapter registration and priority/collision policy.
- Collision rule: fully qualified IDs (`backend:name`) always available; short name allowed only if unique.

**Verification:**
- Unit tests for collision behavior and lookup order.

---

### Task 4: Built-in Hermes adapter

**Objective:** Expose existing Hermes tools without duplicating logic.

**Files:**
- Create: `roscoe_cli/adapters/hermes_builtin.py`

**Implementation notes:**
- Import from existing modules:
  - `tools.registry.registry` for metadata
  - `tools.registry.discover_builtin_tools()` for loading
  - `model_tools.handle_function_call()` for execution
- Map Hermes tool schema to `ToolSpec`.
- Parse JSON string result from `handle_function_call` safely.

**Verification:**
```bash
roscoe tools list --backend builtin
roscoe run read_file --input '{"path":"README.md","limit":5}'
```
Expected: successful envelope with parsed result.

---

### Task 5: MCP adapter (generic)

**Objective:** Treat MCP tools as first-class Roscoe tools.

**Files:**
- Create: `roscoe_cli/adapters/mcp.py`
- Modify (if needed): `tools/mcp_tool.py` (only minimal extraction seams)

**Implementation notes:**
- Reuse Hermes MCP tool registration/refresh behavior.
- Adapter discovers toolsets prefixed `mcp-` from tool registry.
- Preserve server identity in tool metadata (`tags=["mcp", "server:<id>"]`).

**Verification:**
```bash
roscoe mcp servers list
roscoe mcp refresh
roscoe tools list --backend mcp
```
Expected: MCP tools visible and invocable via `roscoe run`.

---

### Task 6: Python callable adapter

**Objective:** Allow direct registration of arbitrary Python functions.

**Files:**
- Create: `roscoe_cli/adapters/python_callable.py`
- Create: `roscoe_cli/python_registry.py`

**Implementation notes:**
- Config file (YAML) maps tool names to `module:function` and JSON schema.
- Resolve/call safely with explicit import errors and argument validation.
- Add optional virtualenv boundary support in later phase (not required for MVP).

**Verification:**
- Add fixture callable in tests and run through `roscoe run`.

---

### Task 7: Dispatcher + CLI commands

**Objective:** Wire list/search/inspect/run command flow.

**Files:**
- Create: `roscoe_cli/dispatcher.py`
- Modify: `roscoe_cli/commands.py`

**Implementation notes:**
- Commands:
  - `tools list`
  - `tools search`
  - `tools inspect`
  - `run`
- `tools search` should match name, description, backend tags.
- `--json` flag for machine-readable output.

**Verification:**
```bash
roscoe tools search browser
roscoe tools inspect read_file
roscoe run read_file --file /tmp/payload.json
```

---

### Task 8: Tests for MVP

**Objective:** Lock core behavior before plugin expansion.

**Files:**
- Create: `tests/roscoe_cli/test_contracts.py`
- Create: `tests/roscoe_cli/test_dispatcher.py`
- Create: `tests/roscoe_cli/test_builtin_adapter.py`
- Create: `tests/roscoe_cli/test_name_collision.py`

**Implementation notes:**
- Focus on deterministic tests with mocked adapters.
- Include malformed JSON and unknown-tool failures.

**Verification:**
```bash
python -m pytest tests/roscoe_cli -q
```

---

## Phase 2 — CLI-Anything bridge + installability polish

### Task 9: CLI-Anything adapter

**Objective:** Use CLI-Anything as catalog/provider source.

**Files:**
- Create: `roscoe_cli/adapters/cli_anything.py`
- Create: `roscoe_cli/integrations/cli_anything_client.py`

**Implementation notes:**
- Discover installed harnesses from CLI-Anything registry.
- Represent each harness as `backend="cli-anything"` tool.
- Execute harness entrypoint and wrap stdout/stderr in `ToolRunResult`.
- Do **not** delegate core routing policy to CLI-Anything.

**Verification:**
```bash
roscoe tools list --backend cli-anything
roscoe run cli-anything:<harness-name> --input '{...}'
```

---

### Task 10: Catalog sync and local indexing

**Objective:** Improve discoverability at scale.

**Files:**
- Create: `roscoe_cli/catalog.py`
- Modify: `roscoe_cli/commands.py`

**Implementation notes:**
- `roscoe catalog sync` builds local cache (`~/.hermes/roscoe/catalog.json`).
- Search uses cache for fast fuzzy lookup.
- Keep offline-friendly behavior.

**Verification:**
```bash
roscoe catalog sync
roscoe tools search pdf
```

---

### Task 11: Packaging + docs

**Objective:** Make install/run behavior reliable for any agent host.

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `docs/user-guide/features/roscoe-cli.md`

**Implementation notes:**
- Add install snippets:
  - `pipx install .`
  - `pipx install git+https://github.com/...`
- Document `help`, search, and `run` JSON envelope.

**Verification:**
```bash
pipx install -e .
roscoe help
roscoe doctor
```

---

## Phase 3 — Policy, safety, and remote-agent workflows

### Task 12: Policy engine and approvals

**Objective:** Add backend-agnostic safety controls.

**Files:**
- Create: `roscoe_cli/policy.py`
- Create: `roscoe_cli/config.py`

**Implementation notes:**
- Safety scopes: `read`, `write`, `exec`, `network`.
- Optional `--require-approval` mode for destructive tools.
- Integrate with existing Hermes approval semantics where possible.

---

### Task 13: Traceability

**Objective:** Make runs debuggable across all adapters.

**Files:**
- Create: `roscoe_cli/tracing.py`
- Modify: adapters to emit common trace metadata

**Implementation notes:**
- Per-run trace ID and structured logs.
- `roscoe trace <id>` for retrieval.

---

### Task 14: Agent-task adapter (A2A/delegation)

**Objective:** Expose agent-level tasks as tools.

**Files:**
- Create: `roscoe_cli/adapters/agent_task.py`

**Implementation notes:**
- Wrap async task send/get under synchronous CLI result handling.
- Keep explicit timeout and status polling behavior.

---

## Design decisions and guardrails

1. **Core runtime remains Roscoe-owned.** CLI-Anything is one adapter only.
2. **No silent name collisions.** Must surface conflicts and require FQNs.
3. **Stable contract first.** New backends cannot bypass `ToolRunResult`.
4. **Help-first UX.** All commands provide examples and JSON mode.
5. **Backward compatibility.** Existing `hermes` workflows remain unchanged.

---

## Suggested rollout timeline

- **Week 1:** Phase 1 tasks 1–4 (scaffold, contracts, adapter registry, builtin)
- **Week 2:** Phase 1 tasks 5–8 (MCP, python adapter, dispatcher, tests)
- **Week 3:** Phase 2 tasks 9–11 (CLI-Anything bridge, catalog, docs/packaging)
- **Week 4+:** Phase 3 hardening (policy, tracing, agent-task)

---

## Definition of done (MVP)

MVP is done when all pass:

1. `pipx install ...` yields working `roscoe` command.
2. `roscoe help` and `roscoe tools search` work without setup surprises.
3. Can run one built-in tool, one MCP tool, and one Python callable via `roscoe run`.
4. Every run returns consistent JSON envelope with trace ID and proper exit codes.
5. Unit tests for dispatcher + adapters pass in CI.
