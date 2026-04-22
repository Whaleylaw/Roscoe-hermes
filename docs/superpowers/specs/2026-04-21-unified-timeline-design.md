# Unified Timeline — Design Spec

**Status:** Draft
**Date:** 2026-04-21
**Scope:** Cross-channel session continuity per agent profile

---

## Problem

An agent profile in Hermes can be reached from many channels — Telegram,
Open WebUI (via the OpenAI-compatible API server), Discord, iMessage, and
others. Today, each channel writes to its own per-channel session, so a
conversation started in Telegram is invisible when the user switches to
Open WebUI. The agent has no shared memory across channels and behaves
like a stranger on each surface.

An earlier attempt — `session_funnel` with strategy `single-agent-main`
(see `gateway/session.py:529`) — collapsed all traffic to a single
global session key `agent:main:main`. Two problems:

1. The OpenAI-compatible API server (`gateway/platforms/api_server.py`)
   never routes through `resolve_session_key`; it trusts a
   client-supplied `X-Hermes-Session-Id` header. So Open WebUI traffic
   bypasses the funnel entirely.
2. The funnel's single global key predates profiles. Each profile is now
   its own isolated agent with its own `HERMES_HOME`, and the funnel
   key should be scoped to the profile, not global.

## Goal

One unified message timeline per agent profile. Every inbound message
from any channel, and every outbound message the agent sends on any
channel, appends to the same timeline. The agent's context on every
turn is loaded from this timeline — so the agent has continuous memory
regardless of where the current message arrived.

Future chat paths (new platform adapters) plug into this system by
default, with no ambient/archive complexity today.

## Non-goals (for this revision)

- Group-chat "ambient" tiering. The design reserves a `salience`
  column for future use, but today every message is treated as primary.
  When group chats become a real use case, tiering can be added without
  a schema migration.
- Cross-profile routing. Each profile is one running gateway process;
  profiles do not share state or route between each other.
- Replacing the `sessions` table. Per-channel session entries still
  exist for routing metadata (origin, delivery, reset policy, token
  counters, resume state). They stop owning the message transcript.

## Mental model

An agent profile is a virtual user with its own accounts on every
connected platform. Just as a person has one continuous memory of
everyone they've talked to regardless of which app was open, the agent
has one continuous timeline spanning all of its channels.

## Architecture overview

```
Inbound message (Telegram / Open WebUI / Discord / …)
      │
      ▼
Platform adapter
  - Builds SessionSource (unchanged)
  - Calls UnifiedTimeline.record_inbound()
      │
      ▼
UnifiedTimeline layer
  - Appends a row to unified_timeline (profile-scoped, monotonic seq)
  - Updates per-channel sessions entry (routing metadata only)
  - Returns a turn handle
      │
      ▼
Agent turn
  - Context assembled from profile's unified_timeline
    (last N messages, ordered by seq)
  - SessionSource still injected into system prompt so the agent
    knows which channel the current message arrived on
      │
      ▼
Agent response
  - UnifiedTimeline.record_outbound() appends an outbound row
  - Delivery goes to origin platform via existing routing
```

The `session_funnel` feature is absorbed. Its config stays parseable
for one release with a deprecation warning, silently mapped to the new
system.

## Data model

All tables live in the existing SQLite session database (`SessionDB`).

### `unified_timeline`

```
profile_id        TEXT
seq               INTEGER    -- monotonic per profile
ts                DATETIME
direction         TEXT       -- "inbound" | "outbound"
platform          TEXT       -- "telegram", "openai_api", "discord", …
source_chat_id    TEXT       -- origin chat id
source_thread_id  TEXT       -- nullable
author            TEXT       -- user_name or "agent"
content           TEXT
message_id        TEXT       -- platform-native id, nullable
salience          TEXT       -- default "primary"; reserved for future tiering
PRIMARY KEY (profile_id, seq)
```

Plus:

- An FTS5 virtual index over `content` for search.
- A secondary index on `(profile_id, platform, source_chat_id, source_thread_id, message_id, ts)` to make migration idempotency checks and per-channel archive browsing cheap.

Properties:

- Every inbound and outbound message across every channel lands here,
  for the profile that received / sent it.
- `seq` is strictly monotonic per `profile_id`, assigned at write
  time under the profile lock.
- `salience` always has a value. Today it is always `"primary"`; the
  column exists so group-chat ambient tiering can be added later
  without a migration.

### `sessions` (existing, unchanged schema)

Continues to track per-channel `session_key` → `session_id` mapping,
origin metadata, display name, token counters, reset policy, and
resume/suspend state. Stops being the source of truth for message
transcripts.

## Ingest path

`UnifiedTimeline` is a new thin service in `gateway/` that wraps
writes. Platform adapters call two methods:

- `record_inbound(source: SessionSource, content: str, ts, message_id) -> TurnHandle`
- `record_outbound(turn: TurnHandle, content: str, ts) -> None`

`record_inbound` does:

1. Resolve the active profile from gateway config.
2. Acquire the profile lock (replaces the current per-session lock
   from `process_registry`).
3. In a single SQLite transaction:
   - Append a row to `unified_timeline` with the next `seq`.
   - Update the per-channel `sessions` entry (origin, display name,
     reset tracking — unchanged behavior).
4. Return an opaque `TurnHandle` the agent loop uses when it replies.

`record_outbound` appends one `direction="outbound"` row, scoped to the
same profile, with `platform` and `source_chat_id` copied from the
turn's origin so the message is clearly tied to where the agent sent
it.

## Context assembly

Today, context is loaded from a per-channel session. The change:
replace that read with a query against `unified_timeline` filtered by
`profile_id` and `salience="primary"`, ordered by `seq DESC`, limited
to the context window.

The inbound message's `SessionSource` is still injected into the system
prompt so the agent knows which channel the current turn is on — it
has continuous memory but situational awareness of where it is right
now.

This one-line read-source swap is the critical behavior change that
makes Telegram and Open WebUI converge.

## Concurrency

The existing `process_registry` per-session lock is repurposed as a
per-profile lock over the unified timeline. Simultaneous inbound
messages from multiple channels serialize cleanly: the second message
waits for the first turn to complete, then runs with the first turn's
outbound row already in context. No new lock infrastructure.

## Extensibility

A new platform adapter needs to:

1. Build a `SessionSource` (already required).
2. Call `UnifiedTimeline.record_inbound()` / `record_outbound()`.

No new table, no new config block, no migration. The adapter is
unaware of unification — it reports messages and the timeline layer
handles scoping.

The `api_server.py` change specifically: `X-Hermes-Session-Id` becomes
advisory (used for client-side response correlation only). Agent
memory is sourced from the profile's unified timeline, not the header.
This closes the Open WebUI bypass that caused the original bug.

## Config

- New top-level gateway config: `unified_timeline: { enabled: true }`.
  Default on.
- `session_funnel` stays parseable for one release, logs a deprecation
  warning on load, behaves identically to `unified_timeline.enabled = true`.
- No per-platform config changes.

## Profile scoping

Profiles are resolved once at gateway startup from `HERMES_HOME`.
Every write and read scopes to that profile's `profile_id`. Two
profiles run in two gateway processes with two separate
`unified_timeline` logs, isolated by `profile_id`. No cross-profile
routing is introduced.

## Migration

`migrate_to_unified_timeline` script:

1. Walk existing `SessionDB` transcripts in `(ts, session_key)` order.
2. For each message, write a `unified_timeline` row scoped to the
   current profile.
3. Idempotent: skip if a row with the same `(profile_id, platform,
   chat_id, thread_id, message_id, ts, direction, content)` exists.
4. Record completion in a `$HERMES_HOME/.unified_timeline_migrated`
   flag file so the gateway does not re-walk on every startup.
5. Safe to rerun manually at any time.

`sessions.json` is left alone. Existing per-channel session routing
continues to work throughout migration.

## Error handling

- Writes to `unified_timeline` happen in the same transaction as the
  existing per-channel session write. Failure rolls back both; no
  partial state.
- FTS5 indexing failures log and continue — search is a convenience,
  not correctness.
- Profile lock contention uses the existing `process_registry` wait
  path. No new retry logic.
- Unknown `salience` values default to `"primary"` on read — future
  tiering stays backwards-compatible.
- No new fallback paths or silent degradation. Errors surface through
  `SessionDB`'s existing paths.

## Testing

Unit:

- `UnifiedTimeline.record_inbound()` writes a single row with the
  correct fields and monotonic `seq`.
- `UnifiedTimeline.record_outbound()` writes a single row tied to the
  same profile and origin.
- Profile scoping does not leak: writes under profile A are invisible
  to reads under profile B.

Integration:

- Message into Telegram, reply via Open WebUI → second turn's context
  contains the first turn. Same test with the platforms swapped.
  This is the primary regression test for the original bug.
- Interleaved inbound from three platforms → timeline ordering matches
  ingest ordering.
- `session_funnel: { enabled: true }` in legacy config still works via
  the deprecation shim.

Migration:

- Fixture DB with pre-existing per-channel sessions → run migrator →
  unified rows match source. Rerun migrator → no duplicates.

## Documentation

- `gateway/platforms/ADDING_A_PLATFORM.md`: new canonical section on
  how adapters plug into `UnifiedTimeline`, with an explicit before/after
  code diff showing `X-Hermes-Session-Id` is no longer authoritative
  and `UnifiedTimeline.record_inbound` is.
- New user-facing page at `docs/user-guide/features/unified-timeline.md`
  (or the repo's equivalent docs location) explaining the mental model:
  "your agent has one memory across all channels."
- Deprecation note in the gateway config reference for `session_funnel`.
- Release notes entry describing the migration and behavior change.

## Open questions

None identified at design time. Group-chat ambient tiering is
explicitly deferred; the `salience` column reserves space for it.

## Rollout

1. Ship the schema + `UnifiedTimeline` service behind
   `unified_timeline.enabled = true` default.
2. Migration script runs once on first boot; flag file prevents
   re-walk.
3. `session_funnel` deprecation warning for one release, then removed.
4. Documentation updates ship with the feature.
