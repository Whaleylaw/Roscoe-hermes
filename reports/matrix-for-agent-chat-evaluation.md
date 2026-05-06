# Matrix as Agent Chat for Hermes / FirmVault

Date: 2026-04-28

## Bottom line

Matrix is worth piloting as a Slack replacement for agent/case chat, but I would not cut Slack over immediately.

The fit is good because Matrix gives us self-hosted rooms, private ownership of message history, open clients, E2EE support, and Hermes already has a Matrix gateway adapter. The main risk is operational complexity: Synapse/Element needs real server administration, room/permission discipline, encryption key handling, backups, mobile push decisions, and some Hermes Matrix adapter work to match the Slack case-channel behavior we now rely on.

Recommendation: run Matrix as a **parallel pilot** for 2–3 active/internal test cases. Keep Slack live until Matrix proves it can handle:

- case-room routing,
- case cwd / `AGENTS.md` context,
- case Honcho workspace scoping,
- file/audio/image delivery,
- mobile notifications,
- E2EE recovery,
- cron/job delivery,
- room invite/permission workflows.

## Why this is attractive for Lawyer Incorporated

### 1. Self-hosted case collaboration

Slack is convenient, but it is another external SaaS workspace holding case communications. Matrix can be hosted under our own domain, with room history and media on our infrastructure.

Potential Matrix identity model:

```text
@aaron:lawyerincorporated.com
@hermes:lawyerincorporated.com
@paralegal:lawyerincorporated.com
@intake:lawyerincorporated.com
@matchmaker:lawyerincorporated.com
```

Case rooms:

```text
#case-michael-crader:lawyerincorporated.com
#case-abby-sitgraves:lawyerincorporated.com
#ops:lawyerincorporated.com
#intake:lawyerincorporated.com
#agent-alerts:lawyerincorporated.com
```

### 2. Better privacy posture than Slack

Matrix can be private and self-hosted. Synapse stores messages/media locally. You can disable public registration and either disable federation or strictly control it.

For legal/case work, I would start with:

```text
closed registration
private rooms only
no public room directory
federation disabled or tightly limited at first
manual account creation
backups encrypted
```

### 3. Hermes already supports Matrix

Hermes has a Matrix gateway adapter at:

```text
/Users/aaronwhaley/Github/Roscoe-hermes/gateway/platforms/matrix.py
```

Hermes Matrix support includes:

- DMs
- rooms
- Matrix threads
- optional E2EE
- file/media delivery
- access-token or password login
- allowed-user controls
- home room for cron/notifications
- mention gating / free-response rooms

Relevant env/config knobs from the adapter and docs:

```env
MATRIX_HOMESERVER=https://matrix.example.com
MATRIX_ACCESS_TOKEN=[REDACTED]
MATRIX_USER_ID=@hermes:example.com
MATRIX_PASSWORD=[REDACTED]
MATRIX_ENCRYPTION=true
MATRIX_DEVICE_ID=hermes-main
MATRIX_ALLOWED_USERS=@aaron:example.com
MATRIX_HOME_ROOM=!roomid:example.com
MATRIX_REACTIONS=true
MATRIX_REQUIRE_MENTION=true
MATRIX_FREE_RESPONSE_ROOMS=!roomid:example.com,!room2:example.com
MATRIX_AUTO_THREAD=true
MATRIX_RECOVERY_KEY=[REDACTED]
MATRIX_DM_MENTION_THREADS=false
```

Config file also supports:

```yaml
matrix:
  require_mention: true
  free_response_rooms:
    - "!roomid:example.com"
  auto_thread: true
  dm_mention_threads: false
```

### 4. Matrix rooms map naturally to FirmVault cases

Slack case-channel model:

```text
Slack channel ID → case cwd → AGENTS.md → Honcho workspace case-<slug>
```

Matrix can use the same model:

```text
Matrix room ID → case cwd → AGENTS.md → Honcho workspace case-<slug>
```

But this is the first code gap I noticed: Slack currently resolves `channel_cwd` before constructing the `MessageEvent`. Matrix currently builds `MessageEvent` without resolving `channel_cwd` or `channel_prompt`.

So to make Matrix first-class for FirmVault, we should add Matrix room-to-cwd support mirroring Slack:

```text
room_to_cwd:
  "!abc123:lawyerincorporated.com": "/Users/aaronwhaley/.hermes/agents/paralegal/workspace/FirmVault/cases/michael-crader"

room_to_slug:
  "!abc123:lawyerincorporated.com": "michael-crader"
```

Or reuse the existing config key name `channel_cwds` because internally Matrix room IDs can be treated as channel IDs.

Then Matrix messages get the same passive case context:

```text
Matrix case room
  → channel_cwd / room_cwd
  → case AGENTS.md
  → FirmVault cwd
  → Honcho workspace case-<slug>
```

## Practical architecture

### Recommended stack

For a serious self-hosted Matrix pilot:

```text
Synapse homeserver
PostgreSQL database
Element Web / Element Desktop / Element mobile clients
Reverse proxy with TLS — Caddy, Traefik, or Nginx
Backups for Postgres + media store + signing keys
Optional: Synapse Admin UI
Optional later: bridges, SSO, push gateway, monitoring
```

I would avoid hand-rolling too much. Best deployment options:

1. **matrix-docker-ansible-deploy** — best community automation; big but mature.
2. **Element Server Suite Community** — official-ish path from Element, likely cleaner but may be heavier/Kubernetes-oriented.
3. **Simple Docker Compose Synapse + Postgres + Caddy** — best for a local/private pilot, less feature-rich.

For us, I’d start with simple Docker Compose if this is LAN/Tailscale/private. If it becomes production case chat, move to matrix-docker-ansible-deploy or a hardened Compose setup with monitoring/backups.

## Suggested pilot layout

### Homeserver

Use a subdomain:

```text
matrix.lawyerincorporated.com
```

But decide identity domain carefully. Matrix server names are effectively permanent. If you want clean user IDs:

```text
@aaron:lawyerincorporated.com
```

while hosting on:

```text
https://matrix.lawyerincorporated.com
```

then set up Matrix delegation / `.well-known` correctly from day one.

For a pilot, simpler but less pretty:

```text
@aaron:matrix.lawyerincorporated.com
@hermes:matrix.lawyerincorporated.com
```

### Accounts

Create dedicated bot users:

```text
@hermes:...
@paralegal:...
@intake:...
@matchmaker:...
```

Do not run Hermes as Aaron unless it is only a personal assistant. For case work, bot identity should be explicit.

### Rooms

Start small:

```text
#ops
#agent-alerts
#case-michael-crader
#case-abby-sitgraves
#case-test-sandbox
```

Room policy:

- case rooms private/invite-only
- encrypted if we can tolerate E2EE operational friction
- no federation during pilot
- bot invited only to rooms it should access
- room ID mapped to FirmVault case slug/cwd

### Hermes profile layout

Keep role isolation:

```text
~/.hermes/profiles/paralegal/.env
~/.hermes/profiles/paralegal/config.yaml
```

Add Matrix credentials to the paralegal profile, not global, if the paralegal bot should be the one participating in case rooms.

Example env shape — values redacted:

```env
MATRIX_HOMESERVER=https://matrix.lawyerincorporated.com
MATRIX_USER_ID=@paralegal:lawyerincorporated.com
MATRIX_ACCESS_TOKEN=[REDACTED]
MATRIX_ALLOWED_USERS=@aaron:lawyerincorporated.com
MATRIX_HOME_ROOM=!opsroom:lawyerincorporated.com
MATRIX_REQUIRE_MENTION=true
MATRIX_AUTO_THREAD=true
MATRIX_REACTIONS=true
MATRIX_ENCRYPTION=false
```

For E2EE pilot:

```env
MATRIX_ENCRYPTION=true
MATRIX_DEVICE_ID=paralegal-hermes-main
MATRIX_RECOVERY_KEY=[REDACTED]
```

## Use cases worth testing

### 1. Case-room paralegal assistant

Aaron posts in a case room:

```text
@paralegal summarize latest medical records and tell me what's still missing
```

Expected passive behavior:

```text
Matrix room ID → case cwd → AGENTS.md → case Honcho workspace → FirmVault files
```

### 2. Case email alerts

Paralegal heartbeat finds case email:

```text
case email → FirmVault → case Honcho workspace → Matrix case room alert
```

This would replace Slack case alerts.

### 3. Ops email / billing alerts

Non-case but important item:

```text
OpenRouter billing issue → #ops or #agent-alerts
```

### 4. Multi-agent room workflow

Room participants:

```text
Aaron
@paralegal
@matchmaker
@intake
@hermes-ceo
```

Each bot can have its own profile/tool permissions. That’s more transparent than hidden delegation because you can see which agent said what.

### 5. External collaboration later

Matrix federation means you *could* invite outside attorneys/partners later without forcing them into Slack. I would not start there. Legal/case privacy first.

### 6. Voice/file/media testing

Hermes Matrix adapter supports media events and send_message media delivery. Test:

- PDFs
- images
- voicemail/audio
- generated PDFs
- long markdown reports
- encrypted media if E2EE enabled

## Benefits vs Slack

| Area | Matrix advantage |
|---|---|
| Ownership | Self-hosted messages/media/database |
| Privacy | Can run private, no Slack SaaS retention exposure |
| Open protocol | Not locked into Slack APIs/client UX |
| Federation | Optional external interop later |
| Identity | Own domain user IDs |
| Agents | Bot accounts can be normal Matrix users |
| E2EE | Available, including encrypted rooms |
| Cost | No Slack per-seat SaaS cost |
| Automation | Hermes already has a gateway adapter |

## Problems / risks

### 1. Matrix is operationally heavier than Slack

Slack is boring SaaS. Matrix is infrastructure. You inherit:

- database backups,
- upgrades,
- TLS,
- reverse proxy,
- media store growth,
- signing keys,
- account recovery,
- push notifications,
- abuse controls if federated,
- client quirks.

### 2. Domain choice is sticky

Matrix server name / identity domain is not something to casually change later. Decide whether you want:

```text
@user:lawyerincorporated.com
```

or:

```text
@user:matrix.lawyerincorporated.com
```

before production use.

### 3. E2EE is both good and annoying

For legal privacy, E2EE sounds ideal. But bots + E2EE means:

- crypto store must persist,
- recovery key matters,
- device verification/cross-signing can break,
- if `crypto.db` is lost, bot may lose ability to read old encrypted room messages,
- backups become more sensitive.

For pilot, I’d start unencrypted but private/Tailscale/firewalled, then test E2EE deliberately before case production.

### 4. Mobile push may not be as smooth

Element mobile works, but push can be different from Slack. If self-hosting privately, push notification plumbing can matter. Element X vs Element Classic also differs in features and reliability.

### 5. Hermes Matrix adapter needs FirmVault parity work

Right now, Matrix does not appear to resolve `channel_cwd`/case cwd in the same way Slack does. It likely works as generic chat, but not yet as a passive case-context replacement unless we patch it.

Needed Hermes work:

- add Matrix room ID → cwd resolution to adapter,
- pass `channel_prompt` and `channel_cwd` in Matrix `MessageEvent`,
- support room-to-case map file equivalent to Slack `case_channels.yaml`,
- update case Slack routing skill into a generic `case-chat-routing` skill that supports Slack and Matrix,
- verify `send_message(target="matrix:!roomid:server")`,
- update paralegal heartbeat delivery target from Slack channel to Matrix room when configured,
- ensure Matrix room ID drives Honcho `case-<slug>` workspace.

### 6. Search/admin UX may be worse than Slack

Slack’s search/admin UX is polished. Matrix/Element is usable but rougher. For legal operations, rough edges matter if humans actually live in it all day.

### 7. Federation can become a liability

Federation is a strength, but for case work it is also risk. If enabled, you need policies for room visibility, invited users, remote homeservers, retention, and moderation.

Start closed.

## Implementation plan

### Phase 0 — Decide pilot scope

Decision points:

```text
Domain: lawyerincorporated.com vs matrix.lawyerincorporated.com identity
Hosting: local Mac mini / VM / VPS / Tailscale
Federation: off for pilot
Encryption: off for first smoke test, then E2EE test room
Agents: one @paralegal bot first
Cases: 1 sandbox + 1 real low-risk/internal case
```

### Phase 1 — Stand up Matrix

Minimum viable stack:

```text
Synapse + Postgres + Caddy/Traefik + Element Web
```

Lock it down:

```text
disable public registration
manual user creation
private rooms
backups
firewall/Tailscale or TLS-only public endpoint
```

### Phase 2 — Connect Hermes

Install dependencies if missing:

```bash
pip install 'mautrix[encryption]'
```

Configure paralegal profile env:

```env
MATRIX_HOMESERVER=https://matrix.example.com
MATRIX_USER_ID=@paralegal:example.com
MATRIX_ACCESS_TOKEN=[REDACTED]
MATRIX_ALLOWED_USERS=@aaron:example.com
MATRIX_HOME_ROOM=!opsroom:example.com
MATRIX_REQUIRE_MENTION=true
MATRIX_AUTO_THREAD=true
```

Restart gateway:

```bash
hermes gateway restart --profile paralegal
```

or equivalent profile-specific service command.

### Phase 3 — Patch Matrix case context

Mirror Slack behavior in `gateway/platforms/matrix.py`:

- import `resolve_channel_prompt`, `resolve_channel_cwd`
- call them with `room_id`
- set `source.session_isolated = True` when cwd is present
- include `channel_prompt` and `channel_cwd` on `MessageEvent`
- do this for both text and media messages

Config should support:

```yaml
matrix:
  channel_cwds:
    "!abc123:lawyerincorporated.com": "/.../FirmVault/cases/michael-crader"
```

or share the platform `extra.channel_cwds` convention.

### Phase 4 — Matrix case routing map

Create a generic map:

```yaml
slug_to_matrix_room:
  michael-crader: "!abc123:lawyerincorporated.com"

matrix_room_to_slug:
  "!abc123:lawyerincorporated.com": michael-crader

matrix_room_to_cwd:
  "!abc123:lawyerincorporated.com": "/.../FirmVault/cases/michael-crader"
```

Long term, stop calling this Slack routing. It becomes:

```text
case chat routing
```

with backends:

```text
Slack channel
Matrix room
Telegram topic maybe later
```

### Phase 5 — Test gates

Before replacing Slack, prove:

- Aaron can DM bot.
- Aaron can mention bot in Matrix case room.
- Bot gets correct `AGENTS.md` from case cwd.
- Bot gets correct Honcho workspace `case-<slug>`.
- Bot can post file/media.
- Paralegal heartbeat can post case email alert to Matrix room.
- Cron delivery to Matrix home room works.
- E2EE room works across restart.
- Losing/restarting gateway does not lose crypto identity.
- Mobile notifications are acceptable.

## Sources worth using

### Hermes Matrix docs

- Hermes Matrix integration docs  
  https://hermes-agent.nousresearch.com/docs/user-guide/messaging/matrix

Key takeaways:

- Hermes uses `mautrix`.
- Supports DMs, rooms, files/media, threads, and optional E2EE.
- Access token is preferred.
- `MATRIX_ALLOWED_USERS` controls who can interact.
- `MATRIX_REQUIRE_MENTION`, `MATRIX_FREE_RESPONSE_ROOMS`, and `MATRIX_AUTO_THREAD` control room behavior.
- E2EE needs persistent crypto store and recovery key handling.

### Synapse / Matrix hosting docs

- Synapse GitHub / official docs entry point  
  https://github.com/element-hq/synapse

- Matrix.org “Understanding Synapse Hosting”  
  https://matrix.org/docs/older/understanding-synapse-hosting/

Useful warning from Matrix docs: the server name/domain is effectively permanent, and production needs monitoring/backups/upgrades.

### Deployment automation

- matrix-docker-ansible-deploy  
  https://github.com/spantaleev/matrix-docker-ansible-deploy

This is probably the strongest community deployment option. It handles Synapse, Postgres, Traefik, Let’s Encrypt, Element Web, and optional ecosystem services.

### Practical tutorials

- UpCloud Synapse install guide  
  https://upcloud.com/global/resources/tutorials/install-matrix-synapse/

- Matrix + Element Docker/Compose style guides are common, but quality varies. Use them for concepts, not as production authority.

### YouTube starting points

- “How to install Matrix-docker-ansible”  
  https://www.youtube.com/watch?v=dtE-5obG8yE

- “Running Matrix Synapse Home Server in Docker on Ubuntu Server”  
  https://www.youtube.com/watch?v=ZUNJ84dMHxk

- Matrix Tutorials #1 — Understanding Synapse hosting with Docker  
  https://www.youtube.com/watch?v=JCsw1bbBjAM

Use YouTube for walkthrough familiarity. For production, trust official Synapse docs and matrix-docker-ansible-deploy docs over video configs.

## My recommendation

Do it, but as a controlled pilot.

Matrix is directionally aligned with your whole stack: self-hosted, private, case-isolated, agent-native, not SaaS-dependent. It could become a better long-term case chat substrate than Slack.

But the exact thing that matters for us — passive case context — is not fully wired in Matrix yet. Slack has the mature path today. Matrix needs a small but important patch to reach parity:

```text
Matrix room ID → case cwd → AGENTS.md → Honcho case workspace
```

That patch is straightforward because we already built the pattern for Slack and Honcho. The bigger work is infrastructure/operations, not Hermes code.

Recommended next action:

1. Spin up a private Matrix pilot.
2. Create one `@paralegal` bot account.
3. Patch Hermes Matrix adapter to support `channel_cwd` from room ID.
4. Mirror 2 test case rooms from Slack.
5. Run both systems in parallel for a week.
6. Decide whether Matrix is good enough to become the primary case-chat layer.
