# Orchestrator Daemon

## What this is

The orchestrator daemon is a background loop that runs inside the Hermes
Railway service.  It turns Hermes from a chat-only Telegram bot into the
brain of the Lawyer Incorporated paralegal stack — the single point of
coordination that decides what work needs doing, assigns it to the right
OpenClaw agent, watches for results, and makes sure a human reviews
everything before it goes anywhere.

It runs as a thread alongside the Hermes gateway.  The gateway keeps
handling Telegram messages normally.  The daemon runs next to it,
independently, on a configurable heartbeat timer.

## Why it exists

The paralegal stack has three layers:

1. **Hermes** (this service, Railway) — the orchestrator.  One instance.
   Knows the big picture.  Talks to you on Telegram.  Decides what needs
   doing and who should do it.

2. **OpenClaw agents** (Render) — the workers.  Many instances, each
   potentially specialized (document review, research, drafting, etc.).
   They have their own heartbeat and lifecycle managed by the OpenClaw
   gateway.  They do the actual paralegal work.

3. **Mission Control / FirmVault** (not yet built) — the task queue and
   document store.  Mission Control holds the queue of tasks that need
   orchestrating and the approval pipeline for completed work.  FirmVault
   holds documents and evidence.

Without the daemon, Hermes only responds when you message it.  With the
daemon, Hermes proactively checks for work, assigns it out, collects
results, and routes them for your review — all in the background, whether
or not you're actively chatting with it.

## How it fits together

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

The direction of control flows **from Hermes outward**:

- Hermes asks Mission Control: "Any tasks I need to handle?"
- Hermes asks OpenClaw: "Which agents are free?"
- Hermes tells OpenClaw: "Give this task to Agent 2."
- Hermes asks OpenClaw: "Any results back yet?"
- Hermes tells Mission Control: "Here's the result — put it in the review queue."

OpenClaw agents never call Hermes.  They only talk to the OpenClaw gateway,
which manages their own heartbeat and lifecycle independently.

## What happens on each tick

Every `DAEMON_HEARTBEAT_SECONDS` (default 60), the daemon runs one cycle:

**1. Health check**

Pings the OpenClaw gateway (and Mission Control / FirmVault if configured).
If OpenClaw is unreachable, the tick stops early — there's no point trying
to delegate work if the agents can't be reached.

**2. Poll for tasks**

Asks Mission Control for tasks that need orchestrating.  These are tasks
that have been created (by you, by a scheduled job, by another system) but
haven't been assigned to an agent yet.

Right now Mission Control doesn't exist, so this returns an empty list and
the daemon logs "no tasks available" and moves on.

**3. Delegate to agents**

For each task found, the daemon asks OpenClaw for available (idle) agents,
picks one that matches the task type, and sends the assignment.  The agent
starts working.

Right now the agent listing and delegation endpoints don't exist on
OpenClaw, so this is a no-op.

**4. Collect results**

Asks OpenClaw for any completed work from agents.  If an agent finished a
task since the last tick, its result shows up here.

**5. Route to approval**

This is the critical safety step.  Every result is tagged `pending_review`
and submitted to the approval pipeline.  In testing mode
(`DAEMON_APPROVAL_ONLY=true`, the default), **nothing is ever auto-accepted**.
A human must explicitly approve each piece of work before it goes anywhere.

If Mission Control isn't configured yet, the result is logged locally at
WARNING level so it's impossible to miss in the Railway deploy logs.

## How it starts and stops

The daemon uses the Hermes gateway's hook system.  When the gateway boots,
it emits a `gateway:startup` event.  A built-in hook
(`gateway/builtin_hooks/worker_daemon.py`) catches this event and, if
`DAEMON_ENABLED=true`, spawns a background thread running the supervisor
loop.

- **Startup**: gateway boots → hook fires → daemon thread starts → waits
  `DAEMON_INITIAL_DELAY_SECONDS` (default 10) for the gateway to finish
  booting → begins ticking.
- **Shutdown**: you press Ctrl+C (or Railway stops the container) → SIGINT
  arrives → gateway calls `runner.stop()` → the daemon thread is a daemon
  thread, so Python kills it automatically when the main thread exits.
  The daemon also checks a `threading.Event` between ticks, so it can stop
  mid-sleep without waiting for the full heartbeat interval.
- **Duplicate prevention**: a module-level `threading.Lock` ensures only one
  daemon instance runs per process.  A second call to `start()` is rejected.

The daemon creates its own asyncio event loop (the gateway owns the main
one).  Errors in the daemon never crash the gateway — they're caught,
logged, and the next tick proceeds normally.

## Safety guarantees

This system is designed for a legal context where mistakes have real
consequences.  The safety model is:

1. **Off by default.**  `DAEMON_ENABLED` defaults to `false`.  You must
   explicitly turn it on.

2. **Approval-only by default.**  `DAEMON_APPROVAL_ONLY` defaults to `true`.
   Every result from every agent is forced into `pending_review` status
   regardless of what the agent or the queue says.  There is no code path
   that auto-accepts work when this flag is true.

3. **Errors don't propagate.**  If the OpenClaw gateway goes down, the
   daemon logs a warning and sleeps until the next tick.  If Mission
   Control returns garbage, the daemon catches the exception and moves on.
   The Hermes gateway (and your Telegram bot) keeps running regardless.

4. **Single writer.**  `railway.toml` enforces `numReplicas = 1`, and
   the module-level lock prevents duplicate loops within a process.
   There is no distributed lock for multi-replica scenarios — this is
   documented as a known limitation, not papered over.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `DAEMON_ENABLED` | `false` | Master on/off switch. |
| `DAEMON_HEARTBEAT_SECONDS` | `60` | Time between ticks. Lower = more responsive, higher = less load. |
| `DAEMON_INITIAL_DELAY_SECONDS` | `10` | Pause before the first tick so the gateway can finish booting. |
| `DAEMON_APPROVAL_ONLY` | `true` | Forces all results to pending_review. Leave true during testing. |
| `OPENCLAW_GATEWAY_URL` | `https://openclaw-gateway-dfdi.onrender.com` | Where to reach the OpenClaw gateway. |
| `MISSION_CONTROL_URL` | *(empty)* | Where to reach Mission Control. Adapter disabled when empty. |
| `FIRMVAULT_URL` | *(empty)* | Where to reach FirmVault. Adapter disabled when empty. |
| `DAEMON_WORKER_ID` | *(auto-generated)* | Unique identity for this Hermes instance. Used to tag results. |
| `DAEMON_LOG_LEVEL` | `INFO` | Controls verbosity of daemon-specific logs. |
| `DAEMON_HEALTH_TIMEOUT_SECONDS` | `10` | HTTP timeout for health probes. |

## Enabling it on Railway

Add these to your Railway service's **Variables** tab (alongside the
existing `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, etc.):

```
DAEMON_ENABLED=true
DAEMON_HEARTBEAT_SECONDS=60
DAEMON_APPROVAL_ONLY=true
OPENCLAW_GATEWAY_URL=https://openclaw-gateway-dfdi.onrender.com
```

Railway redeploys automatically.  In the **Deploy Logs** you'll see:

```
worker daemon hook: starting supervisor (worker_id=a3f8c1b2)
orchestrator started — worker_id=a3f8c1b2 heartbeat=60s approval_only=True
orchestrator: initial delay 10s before first tick
heartbeat tick=1 orchestrator=a3f8c1b2
health: openclaw OK (245ms)
poll: no tasks available from any source
heartbeat tick=2 orchestrator=a3f8c1b2
health: openclaw OK (198ms)
poll: no tasks available from any source
...
```

This is normal — there are no tasks because Mission Control doesn't exist
yet.  The daemon is alive, healthy, and ready.  Once you wire up the task
queue, it'll start delegating.

## Running locally

```bash
export DAEMON_ENABLED=true
export DAEMON_HEARTBEAT_SECONDS=10   # faster for local dev
export DAEMON_APPROVAL_ONLY=true
hermes gateway run
```

Watch the console for lines prefixed with `daemon.` loggers.  Ctrl+C stops
both the gateway and the daemon.

## What's built vs. what's stubbed

| Component | Status | Notes |
|---|---|---|
| Daemon lifecycle (start, stop, heartbeat, duplicate prevention) | **Done** | Fully working |
| Health check (OpenClaw gateway) | **Done** | Probes /health, /api/health, / |
| Health check (Mission Control, FirmVault) | **Interface only** | Returns "not configured" until URLs are set |
| Task polling from Mission Control | **Interface only** | Returns empty list; needs Mission Control API |
| Agent listing from OpenClaw | **Interface only** | Returns empty list; needs OpenClaw endpoint |
| Task delegation to OpenClaw agents | **Interface only** | No-op; needs OpenClaw endpoint |
| Result collection from OpenClaw agents | **Interface only** | Returns empty list; needs OpenClaw endpoint |
| Approval routing (local fallback) | **Done** | Logs results at WARNING level |
| Approval routing (Mission Control) | **Interface only** | Needs Mission Control API |
| FirmVault document read/write | **Interface only** | Needs FirmVault API |
| Config from env vars | **Done** | All vars listed above |
| Logging | **Done** | Every state transition logged |
| Graceful shutdown | **Done** | Responds to SIGINT/SIGTERM within one tick |
| Duplicate prevention (same process) | **Done** | Module-level threading.Lock |
| Duplicate prevention (multiple replicas) | **Not implemented** | Documented limitation |
| Tests | **Done** | 27 tests covering config, lifecycle, polling, routing |

Every stub has a `# TODO:` comment in the source showing the expected API
call shape (HTTP method, path, request body).  When you're ready to wire up
a real endpoint, find the TODO and replace the stub body — the interface
stays the same.

## Module structure

```
daemon/
├── __init__.py              Package init
├── config.py                Env var parsing → frozen DaemonConfig dataclass
├── supervisor.py            Main loop, threading, start/stop helpers
├── health.py                Health-check aggregator (probes all services)
├── poller.py                Poll → delegate → collect → route pipeline
├── approval.py              LocalApprovalRouter (fallback: logs to WARNING)
└── adapters/
    ├── base.py              Abstract types: Task, TaskResult, TaskStatus,
    │                        TaskSource, ApprovalRouter, HealthCheckable
    ├── openclaw.py          OpenClaw gateway client (health + delegation stubs)
    ├── mission_control.py   Mission Control client (all stubs)
    └── firmvault.py         FirmVault client (all stubs)

gateway/builtin_hooks/
└── worker_daemon.py         gateway:startup hook that conditionally spawns daemon

tests/daemon/
├── test_config.py           12 tests: env parsing, defaults, safety flags
├── test_supervisor.py       6 tests: start/stop, ticks, duplicate rejection
└── test_poller.py           9 tests: polling, routing, approval-only enforcement
```
