# Slack Integration — Roscoe-hermes Fork Notes

Local configuration and fork-level patches for running Slack on all five
Hermes profiles (Roscoe, Brainstorm, Coder, Paralegal, Storysmith), plus
the per-case channel wiring that makes Paralegal's 100+ case channels
deterministically scope each turn to its own case folder.

This doc is the canonical reference when returning to this setup. It
covers architecture, file locations, operational recipes, and the shape of
the code patch so upstream Hermes merges can be re-applied.

---

## One bot per profile

Profiles are fully isolated `HERMES_HOME` directories, each with its own
gateway process, config, and `.env`. There is **no cross-profile routing
layer** — inbound Slack events can't be dispatched to a different
profile's gateway. Each profile therefore needs its own Slack app.

| Profile    | Slack app  | Home channel   | Channel ID     |
|------------|------------|----------------|----------------|
| default    | Roscoe     | `#roscoe1`     | `C0AL14Z684E`  |
| brainstorm | Brainstorm | `#brian`       | `C0ANF3U68HM`  |
| coder      | Coder      | `#codie`       | `C0AL14UP878`  |
| paralegal  | Paralegal  | `#perry`       | `C0AKWQHKPPV`  |
| storysmith | Storysmith | `#stewie`      | `C0AR1DBGE4T`  |

All five use Socket Mode (no public HTTP endpoint needed).

### Manifests

Pre-built Slack app manifests live at
`~/.hermes/slack_manifests/<profile>.yaml`. Create each app via
**api.slack.com/apps → Create New App → From a manifest** and paste the
YAML. Scopes included:

- **Messaging:** `app_mentions:read`, `chat:write`, `im:*`,
  `channels:history`, `channels:read`, `channels:join`, `groups:history`,
  `groups:read`, `mpim:history`, `mpim:read`
- **Assistant UX:** `assistant:write`
- **Attachments:** `files:read`, `files:write`
- **UX:** `reactions:write`, `users:read`

`channels:join` is required for the bulk bot-invite script below. If you
edit a live app to add scopes, click **Reinstall to Workspace** after
saving (token stays the same).

### Tokens

Each profile's `.env`:

```
SLACK_BOT_TOKEN=xoxb-...      # OAuth & Permissions
SLACK_APP_TOKEN=xapp-...      # Basic Information → App-Level Tokens (connections:write)
SLACK_HOME_CHANNEL=<channel id>
SLACK_HOME_CHANNEL_NAME=<name without #>
SLACK_ALLOWED_USERS=U09UA9EEECX   # Aaron's Slack user ID — only caller permitted
```

Raw token dumps (including client/signing secrets) are kept at
`~/.hermes/agents/*/[A-Z]*SLACK_TOKEN*.txt` with mode 600. These are
covered by the global gitignore (`~/.gitignore_global`, registered via
`git config --global core.excludesfile`) with patterns `*_SLACK_TOKEN*.txt`
/ `*slack_tokens.txt`.

### Per-channel behavior (all profiles)

`config.yaml` (profile-level) under `platforms.slack`:

```yaml
platforms:
  slack:
    require_mention: true
    free_response_channels:
      - <home channel id>   # bot replies without @-mention in its own channel
    channel_prompts:
      <channel id>: |
        Ephemeral system prompt injected for every message from this channel.
```

---

## Session model

- **Unified timeline** is on by default (`gateway.unified_timeline.enabled`).
  All inbound messages for a profile merge into one cross-channel
  conversation: the home Slack channel, DMs, Telegram, OpenWebUI, and
  anything else on that profile share one agent memory.
- **Isolated sessions** opt out via `SessionSource.session_isolated`. The
  turn reads only its per-session transcript and its rows do not append
  to the profile timeline. Slack sets the flag whenever a channel has a
  `channel_cwd` override — so Paralegal's case channels each keep their
  own conversation, while `#perry` + DMs stay in the unified view.
- The agent can still inspect isolated sessions on demand (tools can
  read the per-session transcript files / SQLite rows directly from the
  unified session).

Feature commit: `157fcae6`. Files touched: `gateway/session.py`,
`gateway/platforms/slack.py`, `gateway/run.py`.

## Paralegal: per-case channel wiring

Paralegal's workflow has a dedicated Slack channel for every active case.
Channel name matches the case folder slug (e.g. `#abby-sitgraves` ↔
`~/.hermes/agents/paralegal/workspace/FirmVault/cases/abby-sitgraves/`).

### Requirements

1. Session isolation per channel → **free** from Hermes (session key
   includes `chat_id`).
2. Per-channel working directory → **required a fork-level patch**; see
   below.
3. Auto-load the case's `AGENTS.md` on first message → follows from (2):
   `build_context_files_prompt` reads from cwd.
4. Terminal/file tools scoped to the case folder → follows from (2).

### Code patches

Two related commits power the Paralegal setup. Re-apply both if an
upstream merge drops any of the files listed.

**`157fcae6` — per-source isolation from unified timeline**

- `gateway/session.py`: `SessionSource.session_isolated` field + opt-out
  in `load_agent_context`.
- `gateway/run.py`: skip `record_inbound`/`record_outbound` when isolated.
- `gateway/platforms/slack.py`: mark source isolated when `channel_cwd`
  is set.

**`2c6ad99a` — per-channel cwd override**

`feat(slack): per-channel cwd override for case-scoped sessions`.
Eight files; ~140 added lines. **If an upstream merge drops any of these,
re-apply them:**

| File | Purpose |
|------|---------|
| `agent/turn_context.py` (new) | `ContextVar` `turn_cwd_var` — asyncio/thread-safe per-turn cwd. |
| `tools/terminal_tool.py` | Prefers `get_turn_cwd()` over `TERMINAL_CWD` env var. |
| `tools/file_tools.py` | Same for path resolution. |
| `run_agent.py` | Same for `build_context_files_prompt` so the right `AGENTS.md` loads. |
| `gateway/platforms/base.py` | Adds `MessageEvent.channel_cwd` field + `resolve_channel_cwd()` helper (mirrors `channel_prompt`). |
| `gateway/platforms/slack.py` | Resolves `channel_cwd` on every inbound message and attaches to the event. |
| `gateway/config.py` | Accepts `channel_cwds` (inline dict) and `channel_cwds_file` (external YAML with `channel_to_cwd` top-level key) under `platforms.slack`. Also fixes a bug where settings under `platforms.<name>` were ignored (only top-level `<name>:` was read). |
| `gateway/run.py` | Plumbs `channel_cwd` through `_run_agent`; sets the `ContextVar` around `agent.run_conversation`. |

Why ContextVar and not an env-var swap: concurrent turns across different
channels in the same gateway would race the process-wide `TERMINAL_CWD`.
ContextVars are copied into the executor via `copy_context().run(...)`,
which the gateway already uses (`_run_in_executor_with_context`).

### Mapping file

`~/.hermes/profiles/paralegal/case_channels.yaml` — bidirectional map:

```yaml
_meta:
  description: "Bidirectional case ↔ Slack channel mapping for the Paralegal profile."
  cases_root: /Users/aaronwhaley/.hermes/agents/paralegal/workspace/FirmVault/cases
slug_to_channel:        # {case-slug: channel_id}
channel_to_slug:        # {channel_id: case-slug}  (primary cases only, no aliases)
channel_to_cwd:         # {channel_id: absolute-path-to-case-folder}  (consumed by the gateway)
```

Referenced from `~/.hermes/profiles/paralegal/config.yaml`:

```yaml
platforms:
  slack:
    channel_cwds_file: ~/.hermes/profiles/paralegal/case_channels.yaml
```

### Regeneration script

`~/.hermes/profiles/paralegal/regen_case_channels.py`

- Lists case folders under `cases_root` (skips `_*` templates and `.*`
  hidden dirs).
- Calls Slack `conversations.list` with the Paralegal bot token (`xoxb`)
  to fetch all channels the bot can see.
- Matches by exact name. Writes the YAML.
- Applies `ALIASES` (module-level dict) for cases that intentionally share
  another case's channel (e.g. sub-matters). Aliases populate only
  `slug_to_channel`, never `channel_to_cwd` (so the primary case's folder
  stays the active cwd for that channel).

Run after: creating a case folder, archiving a case, renaming a Slack
channel, or adding a sub-matter alias.

```bash
python3 ~/.hermes/profiles/paralegal/regen_case_channels.py
hermes -p paralegal gateway restart
```

Current aliases:

- `jerome-hedinger-premise → C0AGN32BL9Y` (#jerome-hedinger) — his two
  matters consolidated into one.

### Bulk-invite bot to case channels

`~/.hermes/profiles/paralegal/invite_bot_to_cases.py` uses the Paralegal
bot token + `conversations.join` to add the bot to every channel in
`channel_to_slug`. Run after creating new case channels:

```bash
python3 ~/.hermes/profiles/paralegal/invite_bot_to_cases.py
```

Requires `channels:join` scope (already in the manifest).

---

## Operational recipes

### Add a new case

1. Create the case folder under `workspace/FirmVault/cases/<first-last>/`
   with its `AGENTS.md`.
2. Create `#<first-last>` channel in Slack.
3. Regenerate: `python3 ~/.hermes/profiles/paralegal/regen_case_channels.py`
4. Invite bot: `python3 ~/.hermes/profiles/paralegal/invite_bot_to_cases.py`
5. Restart gateway: `hermes -p paralegal gateway restart`

### Alias one folder to another case's channel (sub-matter)

Edit `ALIASES` in `regen_case_channels.py`, add the slug → channel mapping,
regenerate, restart.

### Add a new profile

1. `hermes profile create <name>` (optionally `--clone`).
2. Copy `~/.hermes/slack_manifests/<template>.yaml`, tailor
   display/description/scopes, create Slack app from manifest.
3. Add tokens to `~/.hermes/profiles/<name>/.env`.
4. Add `platforms.slack` block to that profile's `config.yaml`.
5. `hermes -p <name> gateway install && hermes -p <name> gateway start`

### Rotate tokens

1. api.slack.com → the affected app → OAuth & Permissions (or Basic
   Information for app tokens) → Regenerate.
2. Update `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` in that profile's `.env`.
3. Restart that profile's gateway.

---

## System limits (macOS)

All five gateways running concurrently plus Docker saturated the default
launchd soft `maxfiles` limit (256), causing `errno 23 — Too many open
files in system` when the paralegal gateway loaded its 116-entry
`channel_cwds_file`.

Raised to `65536 unlimited` (session + persistent):

- Session: `sudo launchctl limit maxfiles 65536 unlimited`
- Persistent: `/Library/LaunchDaemons/limit.maxfiles.plist` (loaded
  at boot).

If you see the error again, check `launchctl limit maxfiles` — if it's
back to 256, the plist didn't load.

---

## Permission model recap

- `SLACK_ALLOWED_USERS=U09UA9EEECX` in every profile — only Aaron's
  Slack user ID can trigger the bots. Everyone else is silently ignored.
- Bots live in their home channel plus (for Paralegal) every case
  channel. They won't respond to un-mentioned messages outside their home
  / free-response channels (`require_mention: true` by default).
- DMs to any bot are accepted from allowed users only.

---

## File index

| Path | Purpose |
|------|---------|
| `~/.hermes/slack_manifests/*.yaml` | Reusable Slack app manifests per profile |
| `~/.hermes/slack_manifests/_shared.md` | Quick install cheatsheet |
| `~/.hermes/profiles/<name>/.env` | Per-profile Slack tokens + home channel |
| `~/.hermes/profiles/<name>/config.yaml` | Per-profile `platforms.slack` settings |
| `~/.hermes/profiles/paralegal/case_channels.yaml` | Case ↔ channel map (regenerable) |
| `~/.hermes/profiles/paralegal/regen_case_channels.py` | Regenerate the mapping |
| `~/.hermes/profiles/paralegal/invite_bot_to_cases.py` | Bulk bot invites |
| `~/.hermes/agents/*/*SLACK_TOKEN*.txt` | Raw token backups (mode 600, gitignored globally) |
| `/Library/LaunchDaemons/limit.maxfiles.plist` | Persistent launchd fd limit |
