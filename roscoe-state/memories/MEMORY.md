Entrypoint.sh symlinks ~/.hermes+~/.honcho to /opt/data, installs fastembed for semantic skills plugin.
§
GitHub repo: Whaleylaw/Roscoe-hermes — this is the Hermes fork deployed on Railway. GITHUB_TOKEN is now set in /opt/data/.env. The entrypoint.sh symlink fix has been pushed (commit 452e54db) so rebuilds should no longer wipe memory/sessions.
§
Railway project: illustrious-enthusiasm, service: Roscoe-hermes, region: us-east4. Volume: roscoe-hermes-volume at /opt/data. Agent name is Roscoe. Daemon heartbeat triggers builds.
§
Lawyer Inc stack: Hermes on Railway = orchestrator. OpenClaw on Render = 7 agents (lead-triage, intake-setup, treatment, demand, negotiation, lien-specialist, litigator). MC at ops.lawyerincorporated.com. FirmVault at github.com/Whaleylaw/FirmVault (case vault + workflows + skills). OpenClaw repo: Whaleylaw/Roscoebot. Agents configured via deployment/agents/openclaw.json with per-agent SOUL.md workspaces.
§
GSD v2 at /opt/data/gsd-lawyerinc. S01 (hierarchy+state+parser, 44 tests), S02 (agent-cards, contracts, costs, smart dispatch, 159 tests), S03 (lifecycle runner, checkpoint/recovery, mc-sync upgrade, 93 tests) all COMPLETE — 296 total tests. Cost pricing table sourced from OpenRouter API (live query), trimmed to current models only (GPT-5.x, Claude 4.6, Gemini 3.1). S04+ pending.
§
Mission Control (ops.lawyerincorporated.com) v2.0.1: Custom Next.js app, NOT Planka. API routes at /api/ (not /api/v1/). Auth: x-api-key header with API_KEY env var (REDACTED). Login: POST /api/auth/login with username/password returns cookie __Host-mc-session. Has agents, tasks endpoints. Admin: REDACTED. No boards concept — uses agents + tasks directly.
§
Roscoebot is the user's OpenClaw fork/canonical service; do not refer to a generic OpenClaw service when wiring gateway integration.
§
Semantic skills plugin at /opt/data/plugins/semantic-skills/ (fastembed, threshold=0.55). Law firm wiki (93 articles: 65 concepts + 28 connections) in FirmVault/wiki/. FirmVault: 1,170 cases, ~56K activity log files. Research at /opt/data/research/.