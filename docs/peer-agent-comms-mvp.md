# Local Peer Agent Comms MVP

This document describes the first Hermes-native peer-to-peer communication slice.
It is intentionally local and simple: multiple Hermes processes on the same
machine share a SQLite mailbox and use tools to send, receive, and answer tasks.

## Goal

Avoid manually ferrying messages between two agents, for example:

- `builder` implements a feature.
- `tester` runs tests/reviews the patch.
- `builder` sends work directly to `tester` and awaits the answer.

## Storage

Default mailbox:

```text
~/.hermes/peer-comms/peer_comms.sqlite
```

The default is rooted at the Hermes root, not a single profile, so local profiles
can see each other. Override with either:

```bash
export HERMES_PEER_COMMS_DIR=/path/to/shared/peer-comms
export HERMES_PEER_COMMS_DB=/path/to/shared/peer_comms.sqlite
```

## Toolset

Toolset name:

```text
peer_comms
```

Tools:

- `peer_team_start` — start a temporary, session-scoped agent-team room and register its members.
- `peer_team_status` — inspect active/stopped/expired team rooms and their registered peers.
- `peer_team_launch` — one-call chat-start path: create a temporary team, spawn bounded runner processes for its agents, and optionally seed the first task.
- `peer_team_stop` — shut down a temporary team room, stop its inbound runners, and mark members offline.
- `peer_runner_start` — start a temporary inbound watcher for one team agent; queued peer messages are automatically claimed, dispatched to a one-shot command, and answered.
- `peer_runner_status` — inspect active/exited runner processes.
- `peer_runner_stop` — stop one or more temporary inbound runners without stopping the team room.
- `peer_register` — register/refresh the current agent card.
- `peer_list` — list available peer agents.
- `peer_send` — send a prompt/task to a peer.
- `peer_inbox` — read inbound tasks for this agent.
- `peer_claim` — mark an inbound task as in progress.
- `peer_reply` — complete/fail an inbound task with a response.
- `peer_get` — inspect a message by id.
- `peer_await` — wait for a message to complete/fail.
- `peer_offline` — mark the current agent offline.

## Temporary agent-team sessions

This is the workflow Aaron described: **not always-on A2A**, but an explicit team
session that is active only while a particular job is running.

Example: start a Coder + Paralegal room for a case task:

```text
peer_team_start(
  name="abby-chronology-team",
  project="abby-sitgraves",
  coordinator_id="coder",
  agents=[
    {"name": "coder", "agent_id": "coder", "role": "implementation / binder generation"},
    {"name": "paralegal", "agent_id": "paralegal", "role": "medical-record review and legal chronology QA"}
  ],
  ttl_seconds=14400
)
```

While the team is active, either agent can send to the other through the same
mailbox:

```text
peer_send(
  sender_id="coder",
  target="paralegal",
  project="abby-sitgraves",
  subject="Review grouped ED visit",
  prompt="Please review whether these 7/13-7/14 records should be one visit and return chronology wording."
)
```

When the work is done, shut the room down:

```text
peer_team_stop(team_id="team_...", reason="chronology review complete")
```

Stopping the team marks its registered members offline and stops any runners tied
to that team. If nobody stops it, the TTL expires and the room becomes inactive
automatically. This gives us a bounded agent-team session instead of a daemon
that accepts random messages forever.

## Chat-started team launch

For the UX Aaron wants from Telegram/API chat — “start a team with Coder and
Paralegal and give them this task” — use `peer_team_launch`. It composes
`peer_team_start` + `peer_runner_start` + optional `peer_send` in one tool call,
so the user does not need to open terminal windows.

```text
peer_team_launch(
  name="abby-chronology-team",
  project="abby-sitgraves",
  sender_id="user",
  initial_target="paralegal",
  initial_subject="Build visit-level chronology",
  initial_task="Review the Abby medical folder and produce a visit-level chronology package. Coordinate with coder for scripts/binder generation.",
  agents=[
    {
      "name": "Coder",
      "agent_id": "coder",
      "role": "implementation / binder generation",
      "profile": "coder",
      "cwd": "/Users/aaronwhaley/Github/Roscoe-hermes",
      "toolsets": "peer_comms,file,terminal"
    },
    {
      "name": "Paralegal",
      "agent_id": "paralegal",
      "role": "medical-record review and legal chronology QA",
      "profile": "paralegal",
      "cwd": "/Users/aaronwhaley/.hermes/agents/paralegal/workspace",
      "toolsets": "peer_comms,file,terminal"
    }
  ],
  ttl_seconds=14400
)
```

The launched child agents run as bounded local runner processes tied to the team
id. They use the shared peer-comms hub even though each profile has its own
`HERMES_HOME`, so Coder and Paralegal see the same mailbox. Stop everything with:

```text
peer_team_stop(team_id="team_...", reason="work complete")
```

Use `await_initial_response=true` only when the caller should block until the
first target answers. For long legal/medical jobs, leave it false and check back
with `peer_team_status`, `peer_runner_status`, or `peer_get`/`peer_await` on the
initial message id.

## Temporary inbound runners

After a room exists, start a runner for any agent that should receive peer tasks
automatically. The runner is a normal local process, scoped to the team/project,
and should be stopped when the job finishes.

```text
peer_runner_start(
  team_id="team_...",
  agent_id="paralegal",
  project="abby-sitgraves",
  name="paralegal",
  role="medical-record review and legal chronology QA",
  command="python cli.py --quiet --toolsets peer_comms,file,terminal -q {prompt}",
  poll_seconds=1,
  command_timeout_seconds=1800
)
```

The command receives these placeholders:

- `{prompt}` — peer message body.
- `{msg_id}` — peer message id.
- `{subject}` — peer subject.
- `{sender_id}` — sending peer id.
- `{project}` — project namespace.

If `command` is omitted, the runner defaults to the current repo's Hermes CLI in
quiet one-shot mode:

```bash
python cli.py --quiet -q "{prompt}"
```

For testing or non-LLM workers, provide any command that prints the answer to
stdout. A non-zero exit code marks the peer response as `failed` and returns
stderr/stdout to the sender.

Check/stop runners directly:

```text
peer_runner_status(team_id="team_...")
peer_runner_stop(team_id="team_...", agent_id="paralegal")
```

## Live interactive peer-watch

For an already-open Hermes CLI session, use `/peer-watch` instead of a one-shot
runner. This subscribes the active chat loop to its peer inbox, claims incoming
messages, injects them as the next turn in that same conversation, then writes the
final assistant response back to the peer mailbox automatically.

```text
/peer-watch start --agent paralegal --project abby-sitgraves --team team_... --poll 1
```

Useful commands:

```text
/peer-watch status
/peer-watch stop
```

Notes:

- `/peer-watch` is CLI-only and opt-in. It starts no global daemon and stops when
  the CLI exits or `/peer-watch stop` is run.
- The watcher refreshes the local peer registration while active and marks that
  agent offline on stop.
- Incoming peer prompts are queued behind any already-pending local input. If the
  agent is busy, they wait for the next turn rather than interrupting the current
  turn.
- This is the preferred mode when you want the receiving agent to preserve and use
  its open-session context. `peer_runner_start` remains useful for headless or
  command-based one-shot workers.

## Example workflow

In the builder agent:

```text
peer_register(name="builder", agent_id="builder", project="roscoe-hermes", role="implementation")
peer_list(project="roscoe-hermes")
peer_send(
  sender_id="builder",
  target="tester",
  project="roscoe-hermes",
  subject="Run tests for peer-comms MVP",
  prompt="Please run the focused peer-comms tests and report exact failures."
)
peer_await(msg_id="peer_...", timeout_seconds=600)
```

In the tester agent:

```text
peer_register(name="tester", agent_id="tester", project="roscoe-hermes", role="testing/review")
peer_inbox(agent_id="tester", project="roscoe-hermes", mark_seen=true)
peer_claim(agent_id="tester", msg_id="peer_...")
# run the requested work
peer_reply(agent_id="tester", msg_id="peer_...", response="Tests passed: ...")
```

## Design notes

- This is **not always-on A2A**. `peer_team_start` creates a bounded team room;
  `peer_team_stop` shuts it down; TTL expiry is the fallback.
- Automatic inbound work is available only while an explicit `peer_runner_start`
  process or live `/peer-watch start` session is running for that agent. No
  dormant agent is woken up outside an active team runner/watch.
- Without a runner, the target can still use manual `peer_inbox` / `peer_claim` /
  `peer_reply`.
- Message ids are stable (`peer_<hex>`).
- Agents register with a TTL and become unavailable after expiry unless they
  refresh with `peer_register`.
- Messages have a TTL and are pruned after expiry.
- Project names are used as namespaces so generic names like `tester` can be
  reused across projects.
- Tool descriptions tell agents not to use `peer_send` to reply to inbound work;
  use `peer_reply` instead. This avoids ping-pong loops.

## Future enhancements

Potential next steps:

- Add CLI wrappers for team lifecycle, e.g. `hermes peer team start` / `stop`.
- Add a compact TUI indicator showing queued/completed peer messages.
- Add stricter per-team allowlists and max task budgets for runner commands.
