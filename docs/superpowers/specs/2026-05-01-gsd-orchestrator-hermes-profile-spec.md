# GSD-Style Orchestrator on Hermes + Mission Control Recipes

Date: 2026-05-01  
Owner: Aaron Whaley / Coder agent

## Goal
Create a new Hermes profile that behaves like a GSD orchestrator, but dispatches specialist work through Mission Control recipe agents instead of embedding a large custom runtime in Hermes.

## Architecture

1. **Hermes profile (`gsd-orchestrator`)**
   - Handles user interaction, channel routing, context shaping, and policy guardrails.
   - Decides task class and target recipe.
   - Submits/updates Mission Control tasks with recipe metadata.

2. **Mission Control recipes (specialists)**
   - Each recipe defines toolset, model, timeout, concurrency, and persona (`SOUL.md`).
   - Executes bounded tasks only.

3. **Workflow routing layer**
   - Maps normalized task classes to recipe slugs.
   - Allows easy swapping of specialist behavior without Hermes code changes.

## Hermes Profile Scaffold (new)

Create profile directory:
- `~/.hermes/profiles/gsd-orchestrator/`

Required files:
- `config.yaml`
- `.env`
- `SOUL.md`
- optional: `AGENTS.md`

### `config.yaml` starter
```yaml
default_model: gpt-5.3-codex
default_provider: openai-codex

group_sessions_per_user: false
thread_sessions_per_user: false

gateway:
  unified_timeline:
    enabled: true

platforms:
  slack:
    enabled: true
    require_mention: false
  telegram:
    enabled: true
```

### `.env` starter (per-profile)
```bash
LANGFUSE_BASE_URL="http://localhost:3002"
LANGFUSE_PUBLIC_KEY="<profile-public-key>"
LANGFUSE_SECRET_KEY="<profile-secret-key>"
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:3002/api/public/otel/v1/traces"
OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64(pub:sec)>"
OTEL_SERVICE_NAME="hermes-gsd-orchestrator"
```

### `SOUL.md` core responsibilities
- Normalize inbound requests to a `task_class` + `intent` + `scope`.
- Select recipe from routing table.
- Enforce approvals for destructive or external actions.
- Require concise completion packets from recipes (result, evidence, next action).

## Dispatch Contract (Hermes -> Mission Control)

Hermes submits recipe work with this normalized payload:

```json
{
  "task_class": "code_review",
  "recipe_slug": "gsd-reviewer",
  "title": "Review PR #123 for regressions",
  "context": "...",
  "priority": "high",
  "artifacts": ["/abs/path/file.py", "https://..."],
  "source": {
    "platform": "slack",
    "chat_id": "C123",
    "thread_id": "17123456.123",
    "session_key": "agent:main:slack:group:C123"
  },
  "constraints": {
    "max_runtime_minutes": 30,
    "allow_external_side_effects": false
  }
}
```

## Recipe Schema Convention (team standard)

Keep Mission Control recipe format, with required conventions:

- Required recipe fields: `slug`, `name`, `description`, `tools`, `model.primary`, `model.provider`.
- Required companion file: `SOUL.md` (persona + rules for that specialist).
- Optional: `references/`, `templates/`, `scripts/`.
- Every recipe must define:
  - **Inputs expected**
  - **Output contract**
  - **Stop conditions**
  - **Escalation conditions**

## Initial Routing Table (v1)

- `code_review` -> `gsd-reviewer`
- `implementation` -> `gsd-coder`
- `debug_incident` -> `gsd-debugger`
- `research` -> `gsd-researcher`
- `ops_triage` -> `gsd-ops-triage`
- `legal_intake_ops` -> `gsd-paralegal-intake`
- `doc_drafting` -> `gsd-doc-drafter`

Fallback:
- unknown class -> `gsd-generalist`

## Rollout Plan

1. Create profile scaffold + env + Langfuse keys.
2. Add 3 starter recipes (`gsd-coder`, `gsd-reviewer`, `gsd-ops-triage`).
3. Add routing table file in Mission Control workflows.
4. Run dry-run dispatch tests from Slack + Telegram.
5. Add remaining recipes and tighten guardrails.

## Acceptance Criteria

- Hermes profile can classify and dispatch to a recipe with no manual model/tool edits.
- Recipe execution returns output packets that Hermes can post directly.
- Langfuse traces include orchestrator session metadata and recipe run identifiers.
- No Hermes core changes required for adding a new specialist behavior.
