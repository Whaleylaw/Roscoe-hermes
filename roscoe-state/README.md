# Roscoe Agent State

Snapshot of Hermes agent runtime data from the Railway deployment (`/opt/data/`).

## Contents

| Directory | Description | Size |
|-----------|-------------|------|
| `memories/` | MEMORY.md + USER.md — persistent agent memory across sessions | 12K |
| `sessions/` | 132 session logs (`.json` metadata + `.jsonl` transcripts) | 58M |
| `skills/` | All loaded skills — stock + custom (lawyer-inc, openclaw, firmvault) | 896K |
| `plugins/` | Semantic skills plugin config | 52K |
| `honcho/` | Honcho memory backend config | 8K |
| `cron/` | Scheduled job outputs | 8K |
| `logs/` | Agent runtime logs | 1.1M |
| `platforms/` | Platform (Telegram) session state | 20K |
| `hooks/` | Event hooks | 4K |

## Key Custom Skills

These are Lawyer Inc-specific skills created during operations:

- `devops/roscoe-stack-deployment` — Full stack deployment guide
- `devops/openclaw-render-deployment` — OpenClaw on Render
- `devops/openclaw-agent-configuration` — Agent config reference
- `devops/railway-persistence-fix` — Railway volume persistence fix
- `devops/hermes-semantic-skills-plugin` — Semantic skills plugin
- `domain/lawyer-inc-architecture` — Complete architecture map
- `domain/law-firm-wiki-compiler` — Wiki compilation from case logs
- `domain/architecture-decision-records` — ADR practice (cherry-picked from Stirps)

## Snapshot Date

April 12, 2026
