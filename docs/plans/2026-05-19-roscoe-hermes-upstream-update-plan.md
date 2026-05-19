# Roscoe Hermes Upstream Update Plan

Date: 2026-05-19
Repo: `/Users/aaronwhaley/Github/Roscoe-hermes`
Target: update Roscoe Hermes from upstream NousResearch Hermes while preserving Roscoe-local work and verifying `/goal` / `/subgoal` behavior.

## Source-of-truth state at plan creation

- Current branch: `main`
- Local HEAD: `1f9681e7d Emit memory boundaries before native compression`
- Remotes:
  - `upstream`: `https://github.com/NousResearch/hermes-agent.git`
  - `origin`: `https://github.com/Whaleylaw/Roscoe-hermes.git`
  - `forgejo`: `ssh://git@localhost-forgejo/aaron/Roscoe-hermes.git`
- Divergence after fetch:
  - `HEAD...upstream/main`: `139` local-only commits, `1644` upstream-only commits
  - `HEAD...origin/main`: `18` local-only commits, `0` upstream-only commits
  - `HEAD...forgejo/main`: `0` / `0`
- Dirty local work to preserve:
  - Modified: `agent/anthropic_adapter.py`, `cli.py`, `hermes_cli/commands.py`, `toolsets.py`
  - Untracked: `docs/peer-agent-comms-mvp.md`, `peer_comms/`, `tests/test_peer_comms_interactive_cli.py`, `tests/tools/test_peer_comms_tool.py`, `tools/peer_comms_tool.py`
- Current Roscoe goal support:
  - `/goal` exists in `hermes_cli/commands.py`.
  - `hermes_cli/goals.py` exists.
  - `/subgoal` is absent from current `HEAD` registry.

## Completion criteria

Roscoe is considered updated only when all of the following are true:

1. Roscoe-local commits and currently dirty peer-comms/Anthropic changes are preserved on a named branch or commit.
2. An integration branch merges or rebases onto current `upstream/main` without unresolved conflicts.
3. `/goal` and `/subgoal` are both registered in the running source.
4. Goal-specific tests pass, including upstream `/subgoal` tests if present.
5. Roscoe-local peer-comms tests pass if the peer-comms work is retained.
6. Gateway command registry/help tests pass.
7. A broader Hermes test gate passes or any remaining failures are documented as pre-existing/non-scope with evidence.
8. Updated branch is pushed to `forgejo` and `origin` as appropriate.
9. Running gateways are restarted only after code gates pass.
10. Runtime verification confirms `/goal status`, `/goal pause`, `/goal resume`, `/goal clear`, and `/subgoal` are available in the installed `hermes` binary.

## Execution ledger

### R0 — Baseline and safety

- [x] R0.1 Fetch all remotes and record current divergence.
- [x] R0.2 Record dirty file inventory.
- [ ] R0.3 Create safety refs from current Roscoe state.
- [ ] R0.4 Preserve dirty work in a dedicated WIP branch/commit or stash with untracked files.

Gate: `git status --short --branch` and `git log --oneline -3` prove the preserved state.

### R1 — Integration branch

- [ ] R1.1 Create `integration/upstream-main-2026-05-19` from clean Roscoe main.
- [ ] R1.2 Merge `upstream/main`.
- [ ] R1.3 Resolve conflicts without dropping Roscoe-local features.
- [ ] R1.4 Reapply/reconcile preserved dirty peer-comms/Anthropic changes.

Gate: `git status --short --branch` shows no unresolved files.

### R2 — Goal/subgoal verification

- [ ] R2.1 Verify `CommandDef("goal" ...)` and `CommandDef("subgoal" ...)` exist.
- [ ] R2.2 Run `python -m pytest tests/hermes_cli/test_goals.py -q -o 'addopts='`.
- [ ] R2.3 Run targeted gateway/command registry tests covering slash command availability.

Gate: terminal output shows passing tests.

### R3 — Roscoe-local feature verification

- [ ] R3.1 Run peer-comms tests if retained.
- [ ] R3.2 Run tests for files touched by merge conflict resolution.
- [ ] R3.3 Run broader Hermes test gate.

Gate: passing output or documented failure triage.

### R4 — Push and runtime rollout

- [ ] R4.1 Commit integration result.
- [ ] R4.2 Push integration branch to ForgeJo and/or GitHub fork.
- [ ] R4.3 Restart affected Hermes gateways after tests pass.
- [ ] R4.4 Verify the active `hermes` binary exposes current `/goal` and `/subgoal` behavior.

Gate: `git ls-remote` matches local commit and runtime smoke succeeds.

## Non-goals and safety rules

- Do not run `git pull` directly on dirty `main`.
- Do not discard Roscoe-local commits or peer-comms work without explicit evidence they are obsolete.
- Do not restart live gateways until tests pass.
- Do not expose credentials or profile secrets in commits or reports.
- Treat `/goal` docs as the expected target behavior, but verify against running source and tests before reporting support.
