---
name: roscoe-stack-deployment
description: >
  Lawyer Incorporated paralegal stack deployment and operations. Five repos,
  two lanes. Use for daemon debugging, cross-service wiring, and deployments.
  Load lawyer-inc-architecture first for the full system map.
version: 7.0.0
tags: [lawyer-inc, roscoe, hermes, openclaw, gsd, daemon, orchestrator, railway, render, firmvault, mission-control]
---

# Roscoe Stack — Deployment & Operations

## Trigger
Load this skill when:
- Debugging the daemon or cross-service communication
- Deploying or redeploying any part of the stack
- Fixing Railway rebuild wipes or Render 502s
- Wiring env vars or credentials between services

**For the full architecture map, load `lawyer-inc-architecture` first.**

## Two-Lane Architecture (CRITICAL)

Aaron's key design decision: two parallel control planes.

**Lane 1: FirmVault → MC → OpenClaw** (case work)
- FirmVault engine.py reads PHASE_DAG.yaml + state.yaml per case
- mc_bridge.py pushes available work to Mission Control as tasks
- MC dispatches to OpenClaw agents via WebSocket RPC
- Agents load SKILL.md, execute, commit results to FirmVault
- mc_bridge.py pulls completed tasks, updates state.yaml
- Deterministic, autonomous. GSD is NOT involved.

**Lane 2: Aaron → Hermes → GSD → agents** (ad-hoc projects)
- For projects outside the PI case lifecycle
- GSD 7-stage lifecycle (IDEA→SHIP) with wave dispatch
- Routes to OpenClaw or Hermes directly (Paperclip disabled)

## Five Repos

| Repo | Service | Platform | Purpose |
|---|---|---|---|
| Whaleylaw/Roscoe-hermes | Roscoe-hermes | Railway | Orchestrator + Telegram |
| Whaleylaw/Roscoebot | roscoebot-gateway | Render | 7 worker agents |
| Whaleylaw/gsd-lawyerinc | (library) | Hermes volume | Ad-hoc project mgmt |
| Whaleylaw/Roscoe-mission-control | mission-control | Render | Dashboard + task queue |
| Whaleylaw/FirmVault | (git repo) | GitHub / Hermes volume | Case vault + engine |

## Daemon Tick (supervisor.py)

```python
async def _tick(self):
    # Lane 1: FirmVault case pipeline
    if self._firmvault.configured:
        await self._firmvault.tick()
        # git pull → engine assess → mc_bridge push → mc_bridge pull → git push

    # Lane 2: GSD + OpenClaw orchestration
    statuses = await check_all(self._health_targets)
    tasks = await poll_for_tasks(self._task_sources)  # GSD adapter
    # ... dispatch, collect, route
```

## Deployment Specifics

### Hermes (Railway)
- Project: illustrious-enthusiasm, region: us-east4
- Volume: /opt/data (persists across rebuilds)
- Entrypoint: docker/entrypoint.sh — creates symlinks, clones FirmVault + GSD
- DAEMON_ENABLED=true, DAEMON_HEARTBEAT_SECONDS=60, DAEMON_APPROVAL_ONLY=true
- FirmVault cloned to /opt/data/firmvault, GSD to /opt/data/gsd-lawyerinc

### Roscoebot (Render) — IMPORTANT: this is the canonical OpenClaw gateway
- Service name on Render: `roscoebot-gateway` (NOT `openclaw`)
- URL: https://openclaw-gateway-dfdi.onrender.com
- Repo: Whaleylaw/Roscoebot (Aaron's OpenClaw fork)
- **Render dockerCommand pitfall**: Render's `dockerCommand` field can cause exit code 127 even with valid commands. Multiple shell-based commands (`bash -c '...'`) consistently fail. Approaches tried and results:
  1. `bash -c 'bash seed-agents.sh && node openclaw.mjs ...'` → exit 127 
  2. `node /app/openclaw.mjs gateway --port 10000 --bind lan` → exit 127
  3. `node openclaw.mjs gateway --allow-unconfigured --bind lan --port 10000` → exit 1
  4. **Empty dockerCommand + env vars** → Dockerfile CMD takes over, use OPENCLAW_GATEWAY_PORT=10000 and OPENCLAW_GATEWAY_BIND=lan env vars
  - To clear dockerCommand via Render API: `PATCH /v1/services/{id}` with `{"serviceDetails":{"envSpecificDetails":{"dockerCommand":""}}}`
  - Gateway CLI reads OPENCLAW_GATEWAY_PORT from config/paths.ts and OPENCLAW_GATEWAY_BIND from gateway-cli/run.ts
  - If seed-agents.sh is needed, bake it into the Dockerfile as a RUN or ENTRYPOINT layer — do NOT rely on Render's dockerCommand field for multi-command sequences
- **Dockerfile HEALTHCHECK mismatch**: The Dockerfile has `HEALTHCHECK ... CMD ... fetch('http://127.0.0.1:18789/healthz')` hardcoded to port 18789. When running on port 10000, Docker marks the container unhealthy. Render uses its own healthCheckPath (`/health`) on the service port, but the Docker HEALTHCHECK may still interfere. Consider overriding the HEALTHCHECK in the Dockerfile to use `$OPENCLAW_GATEWAY_PORT` or disabling it.
- **Config: bake into Docker image at build time** (CRITICAL lesson from Apr 2026):
  - Render's `dockerCommand` override completely bypasses Dockerfile CMD — any entrypoint.sh or seed-agents.sh set via CMD will NOT run if dockerCommand is set on the Render service
  - Fix: Dockerfile `RUN cp deployment/agents/openclaw.json /home/node/.openclaw/openclaw.json` + `ENV OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json` — this bakes config into the image layer and sets the env var, both survive any CMD override
  - DO NOT rely on runtime scripts (entrypoint.sh, seed-agents.sh) for critical config — they may never execute
  - DO NOT use `/etc/secrets/` — not writable as `node` user on Render (Dockerfile runs `USER node`)
  - If OPENCLAW_CONFIG_PATH is set but the file has invalid/stale content, the gateway may crash with exit 1 even with `--allow-unconfigured` — remove the env var entirely to truly run unconfigured
- 7 agents configured via deployment/agents/openclaw.json
- seed-agents.sh runs on boot, preserves MEMORY.md
- Agents: lead-triage, intake-setup, treatment, demand, negotiation, lien-specialist, litigator
- **Models: OpenAI Codex OAuth** (switched Apr 2026): all agents use `openai-codex/gpt-5.4`
  - Native `openai-codex` provider plugin (extensions/openai/) — no API key, uses ChatGPT OAuth
  - Auth: ChatGPT browser sign-in. Remote/VPS flow: shows URL → open locally → sign in → paste redirect URL back
  - Tokens stored at `$OPENCLAW_STATE_DIR/agents/main/agent/auth-profiles.json`
  - Also reads Codex CLI tokens from `~/.codex/auth.json` (auth_mode: "chatgpt")
  - Token refresh is automatic via OAuth refresh_token
  - First boot: seed-agents.sh checks for openai-codex profile in auth-profiles.json; if missing, runs `openclaw models auth login --provider openai-codex --set-default` interactively
  - Set `SKIP_OAUTH_SETUP=1` to bypass auth flow in fully headless deploys (agents will fail until auth'd)
  - OPENROUTER_API_KEY no longer needed for agents (was previous provider)
- **OpenRouter fallback** (if Codex OAuth not desired):
  - Model slug format: `openrouter/anthropic/claude-sonnet-4-6`
  - Requires OPENROUTER_API_KEY env var on Render dashboard
- DO NOT confuse with any generic `openclaw-gateway-image` service — that should be suspended
- **Stale config pitfall**: seed-agents.sh was changed to ALWAYS overwrite openclaw.json (no more skip-if-exists). If reverted, stale config on persistent disk blocks model/agent changes.

### Mission Control (Render)
- URL: https://ops.lawyerincorporated.com
- Backend: Custom Next.js app (v2.0.1), SQLite-powered, self-hosted
- **NOT Planka** — completely custom app. No boards, no Planka API patterns.
- **API auth: `x-api-key` header** with the API_KEY env var from Render
  - This is the ONLY auth method that works for programmatic access
  - Bearer tokens, session cookies, X-Auth-Token all fail on API routes
- **API routes at `/api/` (NOT `/api/v1/`)**
  - GET/POST `/api/tasks` — list/create tasks
  - GET `/api/tasks/{id}` — single task
  - GET/POST `/api/agents` — list/create agents
  - GET/POST `/api/gateways` — list/create gateways
  - PUT `/api/tasks` — bulk update `{tasks: [{id, ...}]}` (triggers Aegis approval for status changes)
  - DELETE `/api/tasks/{id}` — delete
  - POST `/api/auth/login` `{username, password}` — web UI login (cookie-based, NOT needed for API)
- **No boards concept** — tasks are flat, assigned to a project automatically
- Task creation returns: `{task: {id, title, status, ticket_ref, project_name, ...}}`
- **Rate limit: ~20 req/min** — use 2s delay between creates, 10s pause every 20 tasks. Retry 429s with exponential backoff (2s, 4s, 8s). The initial get_existing_tasks fetch also burns rate limit — use limit=200 per page. A full 487-task push takes ~20 minutes with proper throttling.
- **Aegis approval**: PUT status changes return 403 "Aegis approval required". Daemon can CREATE and READ tasks but not change status. Status changes happen via MC UI or approved agent workflows.
- Auth env vars: API_KEY (x-api-key header), AUTH_SECRET (JWT signing, internal only)
- Admin account: admin / REDACTED_PASSWORD
- Gateway registration: POST `/api/gateways` with `{name, host, port, is_primary}`
- Agent registration: POST `/api/agents` with `{name, role, status}`
- `/api/nodes` does NOT accept POST — nodes register via gateway heartbeats

### FirmVault (GitHub + Hermes volume)
- 117 cases with state.yaml, 487 tasks ready, 2 transitions pending
- Engine at skills.tools.workflows/runtime/engine.py (deterministic, zero side effects)
- mc_bridge at skills.tools.workflows/runtime/mc_bridge.py (rewritten Apr 2026 for MC v2 API)
- **GitHub Actions workflows** (materializer, worker, landmark-detector):
  - All use Claude Code CLI with `--model openrouter/anthropic/claude-sonnet-4-6`
  - Auth: `OPENROUTER_API_KEY` repo secret (NOT ANTHROPIC_API_KEY — switched Apr 2026)
  - Worker also supports codex and gemini agents via workflow_dispatch input
  - Uses x-api-key auth, /api/tasks endpoint (no boards)
  - Throttled push with 429 retry and exponential backoff
  - Agent assignment by phase (PHASE_AGENT mapping)
  - Metadata-rich tasks enable clean pull-back without title parsing
- Env: FIRMVAULT_DIR, MC_URL, MC_API_KEY (NOT MC_TOKEN or MC_BOARD_ID — those are obsolete)

## Paperclip Separation (IMPORTANT)

Paperclip (agents.lawyerincorporated.com) is a SEPARATE agent platform for business roles
(COO, Marketing, Intake Specialist, Matchmaker, Follow-up). It is:
- Live but ACTIVELY DISABLED in all dispatch paths (as of Apr 2026)
- detectPlatform() in dispatcher.js has Paperclip routing commented out
- dispatchTask() switch/case for 'paperclip' commented out
- dispatchToPaperclip removed from index.js public exports
- To re-enable: set PAPERCLIP_ENABLED=true and uncomment in dispatcher.js
- NEVER involved in FirmVault case work — cases go through MC → OpenClaw only
- Possible future integration per Aaron, but actively unwired for now

Do NOT route FirmVault tasks to Paperclip. Do NOT re-enable Paperclip without Aaron's approval.

## Hermes → MC Wiring

- Hermes registered as agent #8 in MC (role: orchestrator)
- daemon/adapters/mission_control.py: real health check (GET /api/tasks?limit=1), heartbeat, task polling
- DaemonConfig.mission_control_url falls back: MISSION_CONTROL_URL → MC_URL
- Entrypoint sources /opt/data/.env so daemon gets MC_API_KEY, MC_URL etc.
- Supervisor sends MC heartbeat on every tick (before Lane 2)
- MC adapter reads MC_API_KEY from env (same key used by mc_bridge)

## Fork Sync Procedure

Both Roscoe repos are forks. Sync periodically to pick up upstream fixes.

**Roscoe-hermes** (fork of NousResearch/hermes-agent) — clean rebase:
```bash
git clone https://x-access-token:${GITHUB_TOKEN}@github.com/Whaleylaw/Roscoe-hermes.git
cd Roscoe-hermes
git remote add upstream https://github.com/NousResearch/hermes-agent.git
git fetch upstream main
git rebase upstream/main   # ~16 custom commits, typically conflict-free
git push --force-with-lease origin main
```

**Roscoebot** (fork of openclaw/openclaw) — nuclear sync + cherry-pick:
The fork diverges heavily because upstream is very active (~8000+ commits).
Do NOT attempt a full rebase — conflicts on nearly every commit.
```bash
git clone https://x-access-token:${GITHUB_TOKEN}@github.com/Whaleylaw/Roscoebot.git
cd Roscoebot
git remote add upstream https://github.com/openclaw/openclaw.git
git fetch upstream main
# Save deployment commit SHAs first:
git log --oneline upstream/main..main | grep -E "fix:|refactor:|feat: add 7"
git reset --hard upstream/main
git cherry-pick <bind-commit> <agents-commit> <openrouter-commit> <model-slug-commit>
# Then on top of upstream, add new commits for:
# - Codex OAuth model switch + first-boot auth in seed-agents.sh
# - controlUi.enabled: false (required for non-loopback LAN bind)
# - Langfuse OTel diagnostics in openclaw.json
# Dockerfile conflict (agents commit): upstream adds `COPY ... /app/qa ./qa`,
# your commit adds `COPY ... /app/deployment ./deployment` + ENV OPENCLAW_BUNDLED_PLUGINS_DIR.
# Resolution: keep BOTH lines (qa + deployment + env var).
# Skip projectsService fix commit — it patched PM feature code that no longer exists.
git push --force-with-lease origin main
```
Key: only cherry-pick deployment commits (gateway bind, agent config, model routing, Codex OAuth, controlUi disable, Langfuse OTel). Drop any feature code built against the old codebase.

**paperclip-dashboard** (fork of paperclipai/paperclip) — standard rebase:
```bash
git clone https://x-access-token:${GITHUB_TOKEN}@github.com/Whaleylaw/paperclip-dashboard.git
cd paperclip-dashboard
git remote add upstream https://github.com/paperclipai/paperclip.git
git fetch upstream master  # NOTE: default branch is 'master', not 'main'
git rebase upstream/master  # ~22 custom commits (bootstrap scripts + hermes adapter patch)
# Likely conflict: package.json pnpm.patchedDependencies — merge both upstream's
# overrides section AND your hermes-paperclip-adapter patch entry.
git push --force-with-lease origin master
```

**Setting GitHub repo secrets via API** (when `gh` CLI is unavailable):
```python
# Requires: pip install pynacl requests
import base64, requests
from nacl import encoding, public
headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
r = requests.get(f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/public-key", headers=headers)
pub_key = public.PublicKey(r.json()["key"].encode(), encoding.Base64Encoder())
encrypted = base64.b64encode(public.SealedBox(pub_key).encrypt(SECRET_VALUE.encode())).decode()
requests.put(f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/{SECRET_NAME}",
    headers=headers, json={"encrypted_value": encrypted, "key_id": r.json()["key_id"]})
```

## Langfuse Tracing (added Apr 2026)

Both services send traces to Langfuse at us.cloud.langfuse.com.

**Hermes (Railway):**
- agent/langfuse_tracing.py auto-patches OpenAI + Anthropic SDKs on gateway startup
- Configured via env vars in /opt/data/.env: LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL
- Uses `langfuse` Python SDK (langfuse.openai auto-instrument + langfuse.anthropic AnthropicInstrumentor)
- init_langfuse_tracing() called in gateway/run.py start_gateway() after logging setup
- Clean shutdown via atexit.register(shutdown_langfuse)

**Roscoebot (Render):**
- Uses OpenClaw's native OTel support (diagnostics.otel in openclaw.json)
- serviceName: "roscoebot-openclaw", traces: true
- Endpoint/auth configured via standard OTEL env vars on Render dashboard:
  - OTEL_EXPORTER_OTLP_ENDPOINT=https://us.cloud.langfuse.com/api/public/otel
  - OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(public_key:secret_key)>
- base64 auth string = `echo -n "pk-lf-...:sk-lf-..." | base64 -w0`

## Known Pitfalls

0. **OpenClaw config schema drift** — After syncing to upstream, config keys may move. Example (Apr 2026): `gateway.token` became `gateway.auth.token` + `gateway.auth.mode: "token"`. Old location rejected as "Unrecognized key". Always check `src/config/schema.base.generated.ts` for current schema after a fork sync. Search for the key name to find the new path.
1. **Railway rebuilds** wipe ~/.hermes — entrypoint.sh recreates symlink to /opt/data
2. **Roscoebot 502/exit failures** — debug checklist: (a) Config is baked into Docker image via `RUN cp` + `ENV` — verify the Dockerfile build log shows the copy step; (b) If Render dockerCommand is set, it BYPASSES Dockerfile CMD entirely — entrypoint.sh won't run. Clear via API: `PATCH /v1/services/{id}` with `{"serviceDetails":{"envSpecificDetails":{"dockerCommand":""}}}` or use env vars OPENCLAW_GATEWAY_PORT=10000 + OPENCLAW_GATEWAY_BIND=lan instead; (c) If exit 127: Render dockerCommand field is the problem, not the image; (d) If exit 1: config file exists but is stale/invalid, or controlUi not disabled — check for "non-loopback Control UI" error; (e) Dockerfile HEALTHCHECK port must match bind port (10000, not default 18789).
3. **MC auth is x-api-key ONLY** — MC is NOT Planka. Do NOT try Bearer tokens, session cookies, or /api/v1/ paths. Use `x-api-key: {API_KEY}` header on `/api/*` endpoints.
4. **MC rate limits are AGGRESSIVE (~20 req/min)** — 0.2s delay causes 429 storms. Use 2s+ delay between creates. Retry 429s with exponential backoff (2s, 4s, 8s). The initial get_existing_tasks fetch also burns rate limit — use limit=200 per page.
5. **MC Aegis approval** — PUT to update task status returns 403. Daemon creates tasks, humans/agents mark done.
6. **FirmVault is the vault** — agents commit to git, not a database. PHI uses {{placeholders}} only.
7. **GSD repos are private** — need GITHUB_TOKEN to clone.
8. **MC DELETE on gateways returns HTML** — the MC API only has DELETE for /api/tasks/{id}. Gateway and agent deletes must be done via the MC web UI.
9. **Stale config on Roscoebot** — Config is now baked into the Docker image at build time via `RUN cp` + `ENV OPENCLAW_CONFIG_PATH`. This is the ONLY reliable approach because Render's dockerCommand override can bypass CMD/ENTRYPOINT entirely. seed-agents.sh and entrypoint.sh exist but are NOT guaranteed to run. If config issues persist: (a) verify Dockerfile has the `RUN cp` line, (b) check no Render env var overrides OPENCLAW_CONFIG_PATH, (c) confirm the Dockerfile build log shows the copy step.
10. **Roscoebot fork sync (Apr 2026)** — The fork had 200 commits (Claude-built PM/kanban feature, phases 1-10) that were redundant with GSD + FirmVault + MC. Nuclear sync: `git reset --hard upstream/main`, then cherry-pick only deployment commits. The PM feature code (ProjectGatewayService, kanban views, queue manager, checkpoint sidecars) was abandoned — GSD handles project lifecycle, MC handles task queuing, FirmVault handles case state. Only 4 deployment commits survived: gateway bind, 7 agents, OpenRouter routing, model slug fix. The `projectsService` ReferenceError fix (commit 70c7a76f45) was dropped since it fixed PM code that no longer exists.
11. **Two lanes share agents** — an OpenClaw agent may serve both Lane 1 (MC task) and Lane 2 (GSD task) but control flows are independent.
12. **MC_BOARD_ID and MC_TOKEN are OBSOLETE** — removed from mc_bridge and daemon adapter. Use MC_API_KEY only.
13. **Roscoebot is the canonical service name** — do not refer to a generic "openclaw" service. The Render service is `roscoebot-gateway`, the repo is Whaleylaw/Roscoebot.
14. **OpenClaw Control UI crash on LAN bind** — New upstream (post Apr 2026 sync) requires `gateway.controlUi.allowedOrigins` for non-loopback binds, or set `gateway.controlUi.enabled: false`. Without this, gateway crashes with: `non-loopback Control UI requires gateway.controlUi.allowedOrigins`. Fix: disable controlUi in openclaw.json since agents are headless API workers.
