# Cloud deployment — Railway (Telegram gateway + OpenRouter)

This guide walks you through taking a working local Hermes install and
running it as an always-on Telegram gateway on [Railway](https://railway.app),
using OpenRouter as the LLM provider. Once deployed, you can chat with your
agent from Telegram 24/7 without keeping your laptop online.

## What you end up with

- A single Railway service running `hermes gateway run` from
  `Dockerfile.railway` (a Railway-specific copy of the main Dockerfile with
  the `VOLUME` instruction removed — Railway rejects Dockerfiles that
  declare Docker VOLUMEs).
- A persistent volume at `/opt/data` holding your `.env`, `config.yaml`,
  sessions, memories, and skills — upgrades don't touch it.
- Long-polling Telegram connection (no public HTTP port, no webhook, no TLS).
- Auto-restart on crashes, auto-redeploy on git push.

## Prerequisites

Before you start, gather:

1. **Railway account** — sign in at https://railway.app.
2. **OpenRouter API key** — get one at https://openrouter.ai/keys.
3. **Telegram bot token** — message [@BotFather](https://t.me/BotFather),
   run `/newbot`, follow the prompts, copy the token.
4. **Your Telegram numeric user id** — message [@userinfobot](https://t.me/userinfobot)
   and it replies with your id. You'll use this as the allowlist.

## 1. Install the Railway CLI

The CLI lets you deploy from your laptop without copying anything through the
web UI.

```sh
# macOS / Linux
curl -fsSL https://railway.com/install.sh | sh

# or with Homebrew
brew install railway

# verify
railway --version
```

Authenticate:

```sh
railway login
```

A browser window opens; approve the login, then come back to the terminal.

## 2. Create the project and link this repo

From the root of your Hermes checkout:

```sh
cd /path/to/Roscoe-hermes
railway init           # creates a new Railway project
railway link           # if the project already exists, link to it instead
```

Pick a project name (e.g. `hermes-gateway`). Railway will pick up the
`railway.toml` at the repo root on the next deploy.

## 3. Add a persistent volume

Hermes stores everything (API keys, sessions, memories, skills, config) under
`/opt/data` inside the container. Without a volume, every redeploy wipes the
lot. Create one and mount it:

**Dashboard path:**
1. Open the service in the Railway dashboard.
2. Go to **Settings → Volumes → + New Volume**.
3. Mount path: `/opt/data`
4. Size: start with **2 GB** (sessions/skills grow over time; you can resize
   later).

**CLI path:**
```sh
railway volume add --mount-path /opt/data --size 2
```

## 4. Set environment variables

Hermes reads secrets from environment variables at startup. Set these on the
service (dashboard **Variables** tab or the commands below):

```sh
railway variables set OPENROUTER_API_KEY="sk-or-v1-..."
railway variables set TELEGRAM_BOT_TOKEN="1234567890:AA..."
railway variables set TELEGRAM_ALLOWED_USERS="123456789"   # your numeric id
```

Optional extras:

| Variable | Purpose |
|---|---|
| `TELEGRAM_HOME_CHANNEL` | Default chat id for cron jobs / proactive messages |
| `HERMES_MODEL` | Override the model used by cron jobs (e.g. `anthropic/claude-sonnet-4-5`) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Additional providers if you later switch away from OpenRouter |

> **Do not** commit real keys into `railway.toml` or any file in the repo.
> Railway injects variables from its Variables tab at runtime — that's the
> right place for secrets.

## 5. Deploy

```sh
railway up
```

Railway uploads the repo, builds the Dockerfile (takes a few minutes the first
time — Playwright + npm deps), then starts the service with
`gateway run`. The Dockerfile entrypoint bootstraps `/opt/data` on first run,
copying the default `config.yaml`, `.env.example`, and `SOUL.md` into the
volume.

Stream logs:

```sh
railway logs
```

You should see Hermes connect to Telegram and the gateway announce it's ready.
Send your bot a message — it should reply.

## 6. Ongoing operations

**Redeploy after pulling new code:**
```sh
git pull
railway up
```

Or enable Railway's GitHub integration to auto-deploy on push to your branch.

**Tail logs:**
```sh
railway logs --tail
```

**Open a shell inside the running container** (for `hermes model`, `hermes
config set`, editing `config.yaml`, etc.):
```sh
railway shell
# then inside the container:
hermes model                 # pick a different model
hermes config set ...        # tweak config
hermes doctor                # diagnose any issues
```

Because `/opt/data` is a volume, edits made via `hermes config set` persist
across redeploys.

**Rotate a secret:**
```sh
railway variables set OPENROUTER_API_KEY="sk-or-v1-NEW..."
railway redeploy
```

## 7. Scaling and cost notes

- One replica only. Hermes is single-writer against its data volume — never
  run two instances against the same volume. `numReplicas = 1` is enforced in
  `railway.toml`.
- Resource baseline: 1 vCPU / 1 GB RAM is enough for a Telegram gateway with
  no browser tools in use. If you enable Playwright/Chromium-backed tools
  heavily, bump memory to 2 GB.
- Railway bills by resource-seconds. A mostly-idle gateway typically fits
  under the Hobby plan.

## 8. Troubleshooting

**`hermes` exits immediately on first deploy**
Check logs. If you see complaints about missing `.env` or config, the volume
isn't mounted at `/opt/data` — fix the mount path and redeploy.

**Bot doesn't reply**
- Verify `TELEGRAM_BOT_TOKEN` is set on the service.
- Verify your numeric user id is in `TELEGRAM_ALLOWED_USERS`. Without an
  allowlist, Hermes denies all Telegram messages by default.
- Check `railway logs` for auth errors.

**"OpenRouter API key not configured"**
`OPENROUTER_API_KEY` isn't set on the service. Add it, then `railway redeploy`.

**Need to migrate local data to the cloud**
From your laptop, tar up `~/.hermes/` and copy it into the volume via
`railway shell`:
```sh
# on your laptop
tar czf hermes-data.tgz -C ~/.hermes .

# upload via railway shell (or use Railway's file upload UI)
railway run "cat > /tmp/hermes-data.tgz" < hermes-data.tgz
railway shell
  tar xzf /tmp/hermes-data.tgz -C /opt/data
  exit

railway redeploy
```

Be careful not to copy over `logs/` or stale PID files — start with
`sessions/`, `memories/`, `skills/`, `SOUL.md`, and `config.yaml`.

## 9. Optional: switch to webhook mode

Long polling works everywhere and requires no public port, so it's the
default. If you later want to switch to webhook mode (lower latency, no
outbound connection held open), expose an HTTP port on the Railway service
and set these variables:

```sh
railway variables set TELEGRAM_WEBHOOK_URL="https://<your-app>.up.railway.app/telegram"
railway variables set TELEGRAM_WEBHOOK_PORT="8443"
railway variables set TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)"
```

Polling mode is fine for almost every personal deployment — don't bother with
webhook mode unless you have a specific reason.
