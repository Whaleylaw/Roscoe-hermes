---
sidebar_position: 20
title: "Use Gstack with Hermes"
description: "Install, verify, and remove a local gstack integration for Hermes"
---

# Use Gstack with Hermes

This guide covers the local-machine integration between Hermes and a checked-out `gstack` repo.

Use this path when:

- `gstack` already exists on your machine (point `$GSTACK_DIR` at it, default `~/Github/gstack-main`)
- you want Hermes to load the generated local `gstack-*` skills from `~/.hermes/skills`
- you want a deterministic install, verify, and uninstall flow

If you only want to browse or import community skills from GitHub, use the normal Skills Hub flow instead:

```bash
hermes skills browse --source github
hermes skills install openai/skills/k8s
```

That is a different workflow from the local gstack integration in this guide.

## Local paths

- Hermes repo: `path/to/hermes-agent`
- gstack repo: `$GSTACK_DIR`
- installed Hermes skills: `~/.hermes/skills`

## One-command helper

Hermes includes a small wrapper script for the local integration:

```bash
cd path/to/hermes-agent
scripts/gstack-hermes.sh install
scripts/gstack-hermes.sh verify
```

The helper:

- resolves `bun` from `PATH` or `~/.bun/bin/bun`
- resolves `hermes` from `PATH`, `./.venv/bin/hermes`, or the repo-local `./hermes`
- runs the gstack Hermes host setup
- exits non-zero if the expected generated files, installed skills, or runtime symlinks are missing

## Manual install

Run from the Hermes repo or any shell that can reach both repos:

```bash
export PATH="$HOME/.bun/bin:$PATH"
source path/to/hermes-agent/.venv/bin/activate
cd $GSTACK_DIR
bun run gen:skill-docs --host hermes
./setup --host hermes --quiet
```

Expected result:

- generated skills under `$GSTACK_DIR/.hermes/skills/gstack-*`
- installed links under `~/.hermes/skills/gstack-*`
- runtime root at `~/.hermes/skills/gstack`

## Verify

Helper:

```bash
cd path/to/hermes-agent
scripts/gstack-hermes.sh verify
```

Manual checks:

```bash
test -f $GSTACK_DIR/.hermes/skills/gstack-browse/SKILL.md
test -f $GSTACK_DIR/.hermes/skills/gstack-review/SKILL.md
test -f $GSTACK_DIR/.hermes/skills/gstack-qa-only/SKILL.md

test -f ~/.hermes/skills/gstack-browse/SKILL.md
test -f ~/.hermes/skills/gstack-review/SKILL.md
test -f ~/.hermes/skills/gstack-qa-only/SKILL.md

test -L ~/.hermes/skills/gstack/bin
test -L ~/.hermes/skills/gstack/browse/dist
test -L ~/.hermes/skills/gstack/browse/bin
```

## Uninstall

Helper:

```bash
cd path/to/hermes-agent
scripts/gstack-hermes.sh uninstall
```

Manual:

```bash
cd $GSTACK_DIR
bin/gstack-uninstall --force --keep-state
find ~/.hermes/skills -maxdepth 1 -name 'gstack*'
```

After a successful uninstall, the `find` command should print nothing.

## Skills Hub vs local gstack

There are two different ways gstack can show up in Hermes:

1. Local install:
   Uses `$GSTACK_DIR` plus `./setup --host hermes --quiet`.
   This generates host-specific local skills and links them into `~/.hermes/skills`.
2. Remote GitHub import:
   Uses the default Skills Hub GitHub tap for [`garrytan/gstack`](https://github.com/garrytan/gstack).
   This is for browsing or importing upstream repository content through `hermes skills ...`.

If you want the local machine integration described in the handoff, use the local install path, not `hermes skills install garrytan/gstack/...`.

## Troubleshooting

### `bun: command not found`

The helper checks both `PATH` and `~/.bun/bin/bun`. If Bun is installed but not exported in your shell, run:

```bash
export PATH="$HOME/.bun/bin:$PATH"
```

### `hermes: command not found`

In this checkout, Hermes is available from `.venv`, not `venv`:

```bash
source path/to/hermes-agent/.venv/bin/activate
```

The helper also falls back to `path/to/hermes-agent/.venv/bin/hermes`.

### Non-git gstack checkout

This machine's `gstack-main` directory is not a Git checkout. The current gstack build logic already uses a non-fatal `git rev-parse ... || true` fallback for version stamping, so Hermes host generation still works.

### Broken symlinks under `~/.hermes/skills`

If `scripts/gstack-hermes.sh verify` reports broken runtime links:

1. Run `scripts/gstack-hermes.sh uninstall`
2. Re-run `scripts/gstack-hermes.sh install`
3. Re-run `scripts/gstack-hermes.sh verify`
