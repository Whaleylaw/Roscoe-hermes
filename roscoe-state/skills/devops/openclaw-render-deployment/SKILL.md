---
name: openclaw-render-deployment
description: Deploy OpenClaw fork (Roscoebot) on Render with baked-in config, correct schema, and Codex OAuth setup.
tags: [openclaw, render, deployment, docker, oauth]
triggers:
  - deploying openclaw on render
  - roscoebot render issues
  - openclaw config errors
  - codex oauth setup
---

# OpenClaw (Roscoebot) Render Deployment

## Key Facts
- Repo: Whaleylaw/Roscoebot (fork of openclaw/openclaw)
- Render port: 10000 (hardcoded in openclaw.json)
- Config path: /home/node/.openclaw/openclaw.json
- Persistent volume at /data

## Critical Pitfalls

### 1. Render dockerCommand Override
Render may have a `dockerCommand` override that skips Dockerfile CMD/ENTRYPOINT. 
**Solution**: Bake config into Docker image via `RUN` step, not entrypoint:
```dockerfile
RUN mkdir -p /home/node/.openclaw && \
    cp deployment/agents/openclaw.json /home/node/.openclaw/openclaw.json && \
    chown node:node /home/node/.openclaw/openclaw.json
ENV OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json
```

### 2. Config Schema Changes (Upstream)
Old schema (broken):
```json
{ "gateway": { "token": "xxx" } }
```
New schema (correct):
```json
{ "gateway": { "auth": { "mode": "token", "token": "xxx" } } }
```

### 3. Control UI on Non-Loopback
Non-localhost deployments MUST set:
```json
{ "gateway": { "controlUi": { "enabled": false } } }
```
Otherwise: `Error: non-loopback Control UI requires gateway.controlUi.allowedOrigins`

### 4. Port Binding
openclaw.json must have:
```json
{ "gateway": { "port": 10000 } }
```
Render healthcheck path: `/`, port: `10000`

## OpenAI Codex OAuth (One-Time Setup)
1. Render Dashboard → Roscoebot service → Shell tab
2. Run: `openclaw models auth login openai-codex`
3. Copy printed URL → open in browser → sign in with OpenAI account
4. Browser redirects to localhost URL (will fail to load) → copy FULL redirect URL
5. Paste redirect URL back into Render shell
6. Token saved to persistent volume

## Agents (7 Legal Specialists)
All use `openai-codex/gpt-5.4`:
- lead-triage, intake-setup, treatment, demand, negotiation, lien-specialist, litigator

## Langfuse Tracing (OTel)
Render env vars:
- OTEL_EXPORTER_OTLP_ENDPOINT: https://us.cloud.langfuse.com/api/public/otel
- OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
- OTEL_EXPORTER_OTLP_HEADERS: Authorization=Basic <base64 of pk:sk>
