# Unified Timeline

Release date: 2026-04-21

## Summary

Each agent profile now has a single message timeline spanning every
channel: Telegram, Discord, Open WebUI (via the OpenAI-compatible API
server), iMessage, Slack, and any future adapters. A conversation
started on one channel continues seamlessly on another.

## What changed

- New `unified_timeline` table in the per-profile SQLite state DB,
  with FTS5 search and an append-only, monotonic sequence per profile.
- New `UnifiedTimeline` service (`gateway/unified_timeline.py`) that
  wraps writes and exposes `record_inbound` / `record_outbound`.
- `GatewayRunner._handle_message_with_agent` records every
  runner-backed platform's inbound and outbound messages to the
  timeline. One code path covers Telegram, Discord, Slack, iMessage,
  Matrix, WhatsApp, Feishu, WeCom, and future runner-backed adapters.
- OpenAI-compatible API server (`gateway/platforms/api_server.py`)
  records through the timeline on both `/v1/chat/completions` and
  `/v1/responses`, including the streaming variants.
  `X-Hermes-Session-Id` is now advisory — the agent's memory comes
  from the profile's unified timeline, not from any client-supplied
  session id.
- `SessionStore.load_transcript` routes through the timeline when
  `unified_timeline.enabled` is true, so every caller of that method
  (including agents assembling context) gets cross-channel continuity
  without per-caller wiring.
- New `gateway.unified_timeline.enabled` config (default true).
- `gateway.session_funnel` is deprecated. Enabled `session_funnel`
  config is transparently mapped to `unified_timeline.enabled = true`
  with a log warning.

## Migration

On first gateway start, existing per-channel transcripts are migrated
into the unified timeline. A flag file
(`$HERMES_HOME/.unified_timeline_migrated`) prevents re-walking.
Rerun manually at any time: `python3 scripts/migrate_to_unified_timeline.py`.

## Validation

```
.venv/bin/python -m pytest -o addopts='' \
  tests/test_hermes_state_unified_timeline.py \
  tests/gateway/test_unified_timeline.py \
  tests/gateway/test_unified_timeline_telegram.py \
  tests/gateway/test_unified_timeline_startup.py \
  tests/gateway/test_cross_channel_continuity.py \
  tests/scripts/test_migrate_to_unified_timeline.py \
  tests/gateway/test_api_server.py \
  tests/gateway/test_config.py \
  tests/gateway/test_session.py \
  -q
```
