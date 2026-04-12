---
name: openclaw-agent-configuration
description: Complete reference for configuring agents in OpenClaw (Roscoebot fork) - workspace files, config schema, tool policies, skills, identity, bindings, and gateway discovery. Use when creating, modifying, or debugging OpenClaw agent configurations.
version: 1
tags: [openclaw, agents, configuration, roscoebot, legal-agents]
triggers:
  - Creating new OpenClaw agents
  - Configuring agent workspaces, tools, skills, or identity
  - Setting up multi-agent routing/bindings
  - Debugging agent configuration issues
  - Deploying agents on Render
---

# OpenClaw Agent Configuration

## Architecture Overview

OpenClaw uses a **single JSON5 config file** (`~/.openclaw/openclaw.json`, override via `OPENCLAW_CONFIG_PATH`) that the gateway reads at startup. Agents are declarative entries in the config - not standalone processes. The gateway manages all agents from this one config.

## 1. Config File Location & Format

- Path: `~/.openclaw/openclaw.json` (JSON5 format)
- Override: `OPENCLAW_CONFIG_PATH` env var
- On Render: `/etc/secrets/openclaw.json`
- Source types: `src/config/types.openclaw.ts` (OpenClawConfig), `src/config/types.agents.ts` (AgentConfig)

## 2. Agent Entry Schema (agents.list[])

Each agent in `agents.list[]` supports these fields:

```json5
{
  id: "agent-id",           // Required. Lowercase identifier.
  default: true,            // Optional. Marks as default agent.
  name: "Display Name",     // Optional. Human-friendly name.
  workspace: "~/path",      // Optional. Path to workspace dir. Default: ~/.openclaw/workspace-<id>
  agentDir: "~/path",       // Optional. State dir. Default: ~/.openclaw/agents/<id>/agent
  model: "provider/model",  // Optional. String or { primary: "...", fallbacks: ["..."] }
  thinkingDefault: "off",   // Optional. off|minimal|low|medium|high|xhigh|adaptive
  reasoningDefault: "off",  // Optional. on|off|stream
  fastModeDefault: false,   // Optional. Boolean.
  skills: ["skill-a"],      // Optional. Allowlist (omit = all skills, empty [] = none)
  memorySearch: {},          // Optional. Vector memory search config.
  humanDelay: {},            // Optional. { mode, minMs, maxMs }
  heartbeat: {},             // Optional. Per-agent heartbeat overrides.
  identity: {               // Optional. Agent identity for display.
    name: "Roscoe",
    theme: "legal assistant",
    emoji: "⚖️",
    avatar: "avatars/roscoe.png",  // workspace-relative, URL, or data URI
  },
  groupChat: {              // Optional. Group chat behavior.
    mentionPatterns: ["@roscoe"],
  },
  subagents: {              // Optional. Sub-agent spawn control.
    allowAgents: ["other-agent"],
    model: "provider/model",
  },
  sandbox: {                // Optional. Sandbox isolation.
    mode: "off",            // off|non-main|all
    scope: "agent",         // session|agent|shared
    workspaceAccess: "rw",  // none|ro|rw
    docker: {},             // Docker-specific settings
  },
  tools: {                  // Optional. Tool access policy.
    profile: "full",        // minimal|coding|messaging|full
    allow: ["read", "write", "exec"],
    alsoAllow: ["web_search"],  // Additive (merged into allow/profile)
    deny: ["browser", "canvas"],
    byProvider: {},         // Per-model overrides
    exec: {                 // Shell execution policy
      security: "allowlist",  // deny|allowlist|full
      safeBins: ["git", "node"],
    },
    fs: { workspaceOnly: false },
  },
  runtime: {                // Optional. Agent runtime type.
    type: "embedded",       // embedded|acp
  },
  params: {},               // Optional. Provider-specific params.
}
```

## 3. Workspace Files (Identity Templates)

Templates at `docs/reference/templates/`. Seeded into new workspaces automatically.

| File | Purpose | Loaded When |
|------|---------|-------------|
| SOUL.md | Persona, tone, boundaries. **This is the system prompt identity.** | Every session |
| AGENTS.md | Operating instructions, memory rules, session startup, red lines | Every session |
| IDENTITY.md | Structured: Name, Creature, Vibe, Emoji, Avatar, Capabilities | Bootstrap |
| USER.md | Who the user is | Every session |
| TOOLS.md | Tool usage notes (does NOT control availability) | Every session |
| HEARTBEAT.md | Periodic run checklist | Heartbeat runs |
| BOOTSTRAP.md | One-time first-run ritual. Deleted after. | First run only |
| MEMORY.md | Curated long-term memory | Main session only |

### IDENTITY.md Format (parsed by `src/agents/identity-file.ts`)

```markdown
# IDENTITY.md - Who Am I?
- **Name:** Roscoe
- **Creature:** AI paralegal
- **Vibe:** Precise, thorough, empathetic
- **Emoji:** ⚖️
- **Avatar:** avatars/roscoe.png
- **Capabilities:** legal-research, document-drafting, case-analysis
```

Capabilities are comma-separated strings. Placeholder values (like "pick something you like") are automatically ignored.

### SOUL.md Format (free-form markdown)

```markdown
# SOUL.md - Who You Are

## Core Truths
You are Roscoe, a specialized legal paralegal AI for personal injury cases...

## Boundaries
- Never give legal advice directly to clients
- Always route sensitive decisions through the attorney

## Vibe
Precise, empathetic, thorough. Speak like a senior paralegal.
```

## 4. Directory Structure

```
~/.openclaw/
  openclaw.json                          # Global config (JSON5)
  workspace/                             # Default agent workspace
  workspace-<agentId>/                   # Per-agent workspaces
    SOUL.md, AGENTS.md, IDENTITY.md...   # Workspace files
    skills/                              # Per-workspace skills (highest precedence)
    memory/YYYY-MM-DD.md                 # Daily memory logs
  agents/<agentId>/
    agent/                               # Agent state (auth-profiles.json)
    sessions/                            # Chat history + routing state
  skills/                                # Shared/managed skills
  sandboxes/                             # Sandbox workspaces (if enabled)
```

## 5. Tool Registration & Policies

Core tools are built-in (read, write, edit, exec, grep, find, ls, web_search, etc.). Plugin tools come from `extensions/*/`.

### Tool Profiles
- `minimal` - Restricted set
- `coding` - Development-focused
- `messaging` - Communication-focused  
- `full` - Everything available

### Policy Resolution Order
1. Per-agent `tools.profile` sets baseline
2. `tools.allow` restricts to explicit list
3. `tools.alsoAllow` adds to allow/profile list
4. `tools.deny` removes specific tools
5. `tools.byProvider` overrides per model
6. Owner-only tools (cron, gateway, nodes) filtered for non-owner senders

## 6. Skills Assignment

- **Per-agent allowlist**: `agents.list[].skills: ["skill-a", "skill-b"]`
  - Omit = all skills available
  - Empty array `[]` = no skills
- **Workspace skills**: `workspace/skills/` (highest precedence, overrides managed/bundled)
- **Shared skills**: `~/.openclaw/skills/` (managed/installed)
- **Extra dirs**: `skills.load.extraDirs: ["/path/to/more/skills"]`
- **Per-skill config**: `skills.entries.<name>.{ enabled, apiKey, env, config }`
- **Bundled allowlist**: `skills.allowBundled: ["skill-x"]` (only affects bundled skills)

## 7. Routing Bindings

Bindings route inbound messages to agents:

```json5
{
  bindings: [
    { agentId: "triage", match: { channel: "telegram", accountId: "triage-bot" } },
    { agentId: "intake", match: { channel: "telegram", peer: { kind: "group", id: "-1001234567890" } } },
    { agentId: "demand", match: { channel: "discord", accountId: "demand-bot" } },
  ],
}
```

### Routing Priority (most-specific wins)
1. `peer` match (exact DM/group/channel id)
2. `parentPeer` match (thread inheritance)
3. `guildId + roles` (Discord role routing)
4. `guildId` (Discord)
5. `teamId` (Slack)
6. `accountId` match
7. Channel-wide (`accountId: "*"`)
8. Fallback to default agent

## 8. Gateway Discovery

- Gateway reads `agents.list[]` from config at startup
- Default agent: first with `default: true`, else first in list, else `"main"`
- Sessions keyed as `agent:<agentId>:<mainKey>`
- Auth profiles are per-agent at `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`
- Agent IDs are normalized to lowercase

## 9. Environment Variables

| Variable | Purpose |
|----------|---------|
| OPENCLAW_CONFIG_PATH | Config file path |
| OPENCLAW_STATE_DIR | State directory (~/.openclaw) |
| OPENCLAW_WORKSPACE_DIR | Default workspace override |
| OPENCLAW_GATEWAY_TOKEN | Auth token for gateway API |
| OPENCLAW_GATEWAY_PORT | Gateway listen port |
| OPENCLAW_PROFILE | Profile name (workspace-<profile>) |
| OPENCLAW_HOME | Home directory override |

## 10. Render Deployment

render.yaml gateway command:
```
node openclaw.mjs gateway --allow-unconfigured --port 10000 --bind lan
```

Key Render env vars:
- `OPENCLAW_STATE_DIR=/data/.openclaw`
- `OPENCLAW_WORKSPACE_DIR=/data/workspace`
- `OPENCLAW_CONFIG_PATH=/etc/secrets/openclaw.json`
- `OPENCLAW_GATEWAY_PORT=10000`

## 11. CLI Commands

```bash
openclaw agents list [--json] [--bindings]    # List configured agents
openclaw agents add <name> [--workspace <dir>] [--model <id>] [--bind <channel>]
openclaw agents delete <id> [--force]
openclaw agents bind --agent <id> --bind <channel[:accountId]>
openclaw agents unbind --agent <id> --bind <channel[:accountId]>
openclaw agents set-identity --agent <id> --name "X" --emoji "🦞"
openclaw agents set-identity --workspace <dir> --from-identity  # Read IDENTITY.md
openclaw agents bindings [--agent <id>] [--json]
openclaw agent --message "text" --agent <id>  # Run an agent turn
```

## 12. Model Providers & Auth

### OpenAI Codex (OAuth — no API key)
- Model slug: `openai-codex/gpt-5.4` (also `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`)
- Auth method: ChatGPT OAuth browser sign-in (not an API key)
- Provider plugin: `extensions/openai/openai-codex-provider.ts`
- Auth stored at: `$OPENCLAW_STATE_DIR/agents/main/agent/auth-profiles.json`
- Also reads Codex CLI tokens from `~/.codex/auth.json` automatically
- CLI login: `openclaw models auth login --provider openai-codex --set-default`
- Remote/VPS flow: Shows URL → open in local browser → sign in with ChatGPT → paste redirect URL back
- Token refresh is automatic (OAuth refresh_token flow)
- Auth profiles inherit from main agent to sub-agents automatically

### OpenRouter (API key)
- Model slug: `openrouter/<provider>/<model>` (e.g. `openrouter/anthropic/claude-sonnet-4-6`)
- Requires `OPENROUTER_API_KEY` env var

### First-Boot OAuth in seed-agents.sh
When deploying with OAuth models on a fresh volume:
1. seed-agents.sh checks `auth-profiles.json` for an `openai-codex` profile
2. If missing, runs `openclaw models auth login --provider openai-codex --set-default`
3. Set `SKIP_OAUTH_SETUP=1` env var to bypass in fully headless deploys
4. After first auth, tokens persist on volume across restarts

## Pitfalls

1. **Never reuse agentDir** across agents - causes auth/session collisions
2. **tools.allow on agents.list[] controls tool access**, not TOOLS.md (which is just guidance)
3. **skills[] is an allowlist** - omitting it gives all skills, setting `[]` gives none
4. **Workspace is default cwd, not a sandbox** - enable sandbox config for true isolation
5. **Auth profiles are per-agent** - not shared. Copy auth-profiles.json manually if needed.
6. **IDENTITY.md placeholder values** ("pick something you like") are auto-ignored by the parser
7. **Config is JSON5** - supports comments, trailing commas, unquoted keys
8. **Agent IDs are normalized to lowercase** throughout the system

## Source Files Reference

- Agent scope/resolution: `src/agents/agent-scope.ts`
- Agent config commands: `src/commands/agents.config.ts`
- CLI registration: `src/cli/program/register.agent.ts`
- Identity parsing: `src/agents/identity-file.ts`
- Identity resolution: `src/agents/identity.ts`
- Workspace bootstrap: `src/agents/workspace.ts`
- System prompt builder: `src/agents/system-prompt.ts`
- Tool policy: `src/agents/tool-policy.ts`
- Skills: `src/agents/skills.ts`, `src/agents/skills/workspace.ts`
- Config types: `src/config/types.agents.ts`, `src/config/types.openclaw.ts`
- Bindings: `src/config/bindings.ts`
- Routing: `src/routing/session-key.ts`
