# Orchestrator Daemon

Background supervisor for the Lawyer Incorporated / AI paralegal stack.
Hermes is the **orchestrator** — it runs a heartbeat loop alongside the
gateway, polls Mission Control for tasks, delegates work to OpenClaw agents,
collects their results, and routes everything through approval/review.

## Architecture

```
                     ┌──────────────────────────────────────────┐
                     │  Railway Service (Hermes = Orchestrator) │
                     │                                          │
                     │  ┌──────────────┐  ┌──────────────────┐  │
                     │  │ Hermes       │  │ Orchestrator     │  │
                     │  │ Gateway      │  │ Daemon (thread)  │  │
                     │  │ (Telegram,   │  │                  │  │
                     │  │  messaging)  │  │ health check     │  │
                     │  │              │  │ poll tasks       │  │
                     │  │              │  │ delegate → agents│  │
                     │  │              │  │ collect results  │  │
                     │  │              │  │ route → approval │  │
                     │  └──────────────┘  └────────┬─────────┘  │
                     │                             │            │
                     └─────────────────────────────┼────────────┘
                                                   │
                  ┌────────────────────────────────┼──────────────────┐
                  │                                │                  │
                  ▼                                ▼                  ▼
   ┌───────────────────────┐      ┌──────────────────┐  ┌──────────────────┐
   │  OpenClaw Gateway     │      │  Mission Control │  │  FirmVault       │
   │  (Render)             │      │  (TODO)          │  │  (TODO)          │
   │                       │      │  task queue +    │  │  document store  │
   │  ┌─────┐ ┌─────┐     │      │  approval queue  │  │                  │
   │  │Agent│ │Agent│ ... │      └──────────────────┘  └──────────────────┘
   │  │  1  │ │  2  │     │
   │  └─────┘ └─────┘     │
   │  (own heartbeat)      │
   └───────────────────────┘
```

**One Hermes orchestrator, many OpenClaw agents.**  Hermes delegates work
to OpenClaw agents via the gateway.  OpenClaw already has its own heartbeat
for agent liveness — Hermes doesn't heartbeat individual agents, it just
queries their status and dispatches work.

## How it starts

The daemon hooks into the gateway via a built-in `gateway:startup` hook
(`gateway/builtin_hooks/worker_daemon.py`).  When the gateway emits its
startup event, the hook checks `DAEMON_ENABLED`; if true, it spawns a
daemon thread running the supervisor loop.

- The daemon thread creates its own asyncio event loop (separate from the
  gateway's main loop).
- It's a daemon thread, so it won't block gateway shutdown.
- A module-level lock prevents duplicate concurrent loops in the same process.
- The gateway continues to handle Telegram/Discord/Slack messages normally.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DAEMON_ENABLED` | `false` | Master toggle. Set `true` to start the daemon. |
| `DAEMON_HEARTBEAT_SECONDS` | `60` | Seconds between poll cycles. |
| `DAEMON_INITIAL_DELAY_SECONDS` | `10` | Delay before the first tick (lets the gateway boot). |
| `DAEMON_APPROVAL_ONLY` | `true` | **Safety flag.** When true, all results go to review and are NEVER auto-accepted. Leave `true` during testing. |
| `OPENCLAW_GATEWAY_URL` | `https://openclaw-gateway-dfdi.onrender.com` | OpenClaw backend URL. |
| `MISSION_CONTROL_URL` | (empty) | Mission Control URL. Adapter disabled when empty. |
| `FIRMVAULT_URL` | (empty) | FirmVault URL. Adapter disabled when empty. |
| `DAEMON_WORKER_ID` | (random 12-char UUID) | Unique worker identity. Auto-generated if not set. |
| `DAEMON_LOG_LEVEL` | `INFO` | Logging level for the `daemon.*` logger hierarchy. |
| `DAEMON_HEALTH_TIMEOUT_SECONDS` | `10` | HTTP timeout for health probes. |

## Railway deployment

Add the daemon variables to your Railway service's **Variables** tab alongside
the existing Hermes variables:

```
DAEMON_ENABLED=true
DAEMON_HEARTBEAT_SECONDS=60
DAEMON_APPROVAL_ONLY=true
OPENCLAW_GATEWAY_URL=https://openclaw-gateway-dfdi.onrender.com
```

Railway will redeploy automatically.  Check **Deploy Logs** for:

```
worker daemon hook: starting supervisor (worker_id=abc123)
supervisor started — worker_id=abc123 heartbeat=60s approval_only=True
heartbeat tick=1 worker=abc123
health: openclaw OK (245ms)
heartbeat: no work available — sleeping
```

## Running locally

```bash
# From the repo root, with your .env loaded:
export DAEMON_ENABLED=true
export DAEMON_HEARTBEAT_SECONDS=10   # faster for local testing
export DAEMON_APPROVAL_ONLY=true
hermes gateway run
```

The daemon starts alongside the gateway.  Check the console for `daemon.*`
log lines.  Press Ctrl+C to stop both.

## Testing mode (approval-only)

**During testing, `DAEMON_APPROVAL_ONLY=true` is enforced by default.**
This means:

1. Any result produced by task execution is tagged `pending_review`.
2. The result is submitted to the approval router (Mission Control if
   configured, otherwise a local logger that prints the result at WARNING
   level so it can't be missed).
3. **Nothing is ever auto-accepted.**  A human must review and approve
   each output before it propagates downstream.

To disable approval-only mode (production use only):

```
DAEMON_APPROVAL_ONLY=false
```

## Duplicate worker risk

`railway.toml` sets `numReplicas = 1`, which prevents Railway from running
two containers against the same volume.  Within a single process, the
supervisor uses a module-level `threading.Lock` to reject duplicate starts.

**If you scale to multiple Railway replicas (or multiple services polling
the same queue), there is a risk of duplicate task claiming.**  The current
implementation does NOT include a distributed lock.  To mitigate this:

- Implement optimistic locking in the queue API (claim returns false if
  already claimed by another worker).
- Or use an external distributed lock (Redis, Postgres advisory lock).
- Or use Mission Control as the single source of truth for task assignment
  (assign tasks to specific worker_ids before they poll).

This limitation is documented rather than papered over with a fake solution.

## Module structure

```
daemon/
├── __init__.py              Package docstring + DaemonConfig export
├── config.py                Env var parsing → DaemonConfig dataclass
├── supervisor.py            Main loop, lifecycle, start/stop helpers
├── health.py                Health-check aggregator
├── poller.py                Poll → claim → execute → route pipeline
├── approval.py              LocalApprovalRouter (fallback logger)
└── adapters/
    ├── __init__.py
    ├── base.py              Abstract interfaces: QueueAdapter, ApprovalRouter, etc.
    ├── openclaw.py          OpenClaw gateway client (health + queue stubs)
    ├── mission_control.py   Mission Control client (interface only, TODO)
    └── firmvault.py         FirmVault client (interface only, TODO)

gateway/builtin_hooks/
└── worker_daemon.py         gateway:startup hook that spawns the daemon

tests/daemon/
├── test_config.py           Config parsing tests
├── test_supervisor.py       Lifecycle, start/stop, tick count tests
└── test_poller.py           Poll, claim, execute, route tests
```

## TODO boundaries

The following integrations are defined as clean interfaces with stub
implementations.  Replace the stubs with real HTTP calls when the APIs
are available:

| Adapter | Status | What's needed |
|---|---|---|
| `OpenClawAdapter.health_check()` | **Working** | Probes /health, /api/health, / |
| `OpenClawAdapter.list_agents()` | **Stub** | Agent listing endpoint on OpenClaw |
| `OpenClawAdapter.delegate_task()` | **Stub** | Task assignment endpoint on OpenClaw |
| `OpenClawAdapter.collect_results()` | **Stub** | Result collection endpoint on OpenClaw |
| `MissionControlAdapter` (all methods) | **Stub** | Mission Control API definition |
| `FirmVaultAdapter` (all methods) | **Stub** | FirmVault API definition |

Each stub is marked with a `# TODO:` comment showing the expected API call
shape.  The daemon runs safely with stubs — it just no-ops on each tick
(health checks, finds no tasks, sleeps).
