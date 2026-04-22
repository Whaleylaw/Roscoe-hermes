# Unified Timeline

Your agent has one memory across every channel you use to reach it.

When you start a conversation in Telegram and continue it in Open WebUI
(or Discord, iMessage, Slack, or any future platform), the agent picks
up where you left off. Each agent profile has its own timeline; running
multiple profiles keeps them independent.

## Mental model

Think of the agent as its own user: it has accounts on every connected
platform, and a single continuous memory of what was said, regardless
of which app you were using at the time. That's the unified timeline.

## What gets into the timeline

Today, every inbound message to the agent and every message the agent
sends lands in the timeline. Group chats are a future concern — when
the agent participates in busy multi-user chats, tiering will keep
unrelated traffic out of its primary context.

## Configuration

```yaml
gateway:
  unified_timeline:
    enabled: true   # default
```

`session_funnel` (the older, global-only version of this feature) is
deprecated. If present in your config, it is parsed and treated as a
request to enable `unified_timeline`, with a log warning.

## Migration

On first start after the unified-timeline rollout, the gateway walks
your existing per-channel transcripts once and copies them into the
timeline. A flag file (`$HERMES_HOME/.unified_timeline_migrated`)
prevents re-walking. To rerun manually:

```bash
python3 scripts/migrate_to_unified_timeline.py
```

The migration is idempotent — safe to rerun at any time.
