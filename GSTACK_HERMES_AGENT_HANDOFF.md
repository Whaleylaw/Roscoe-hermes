# G-Stack ↔ Roscoe-Hermes Integration Handoff (for Claude Code / Codex)

## Mission
Integrate **gstack** with the existing **Roscoe-Hermes** agent stack so Hermes can reliably use gstack-generated skills and tooling on this machine.

Target outcome: one deterministic setup/verify/uninstall flow with clear docs and no regressions to existing Hermes behavior.

---

## Local paths (authoritative)
- Hermes repo: `/Users/aaronwhaley/Github/Roscoe-hermes`
- gstack repo: `/Users/aaronwhaley/Github/gstack-main`

---

## Current known state
1. `gstack-main` already has a Hermes host adapter (`hosts/hermes.ts`) with path/tool rewrites and runtime-root settings.
2. `gstack-main/setup` includes Hermes install flow:
   - `--host hermes`
   - Hermes autodetect in `--host auto`
   - generates host docs via `bun run gen:skill-docs --host hermes`
   - installs/links to `~/.hermes/skills`
3. `gstack-main/bin/gstack-uninstall` includes Hermes cleanup (`~/.hermes/skills/gstack*`).
4. `gstack-main/package.json` build script has non-git-safe version stamping (`git rev-parse ... || true`).
5. Roscoe-Hermes already references gstack in `tools/skills_hub.py` tap list (`garrytan/gstack`).

Do not assume this is perfect — verify each claim in code before editing.

---

## Constraints
- Keep changes minimal, reversible, and testable.
- Preserve existing behavior for Claude/Codex/Kiro/Factory/OpenCode hosts.
- No broad refactors unrelated to this integration.
- If uncertain, prefer explicit checks over assumptions.

---

## Required deliverables

### A) Integration validation + gap fixes in `gstack-main`
1. Validate Hermes install flow end-to-end:
   - `./setup --host hermes --quiet`
   - confirm generated skills under `.hermes/skills/gstack-*`
   - confirm installed links under `~/.hermes/skills`
2. Validate uninstall:
   - `bin/gstack-uninstall --force --keep-state`
   - confirm `~/.hermes/skills/gstack*` removed
3. If any Hermes-specific breakage is found, patch it in `gstack-main`.
4. Keep any fix scoped and documented.

### B) Roscoe-Hermes integration wiring
Implement Hermes-side affordances so operators can use gstack with less manual work.

At minimum, add:
1. **Docs** in Roscoe-Hermes:
   - where gstack lives locally
   - install command
   - verify commands
   - uninstall command
   - troubleshooting (bun missing, non-git checkout, broken symlinks)
2. **Optional helper command/script** (recommended):
   - script in Roscoe-Hermes to run/install/verify gstack hermes host
   - should be idempotent and print pass/fail checks
3. Ensure Skills Hub guidance clearly tells users how to activate local gstack install vs remote skill import path.

### C) Verification artifacts
Produce a concise verification report including:
- commands run
- key stdout snippets
- file paths created/removed
- final status (PASS/FAIL)

---

## Suggested command plan
Run from `gstack-main` unless noted.

```bash
# sanity
bash -n setup
bash -n bin/gstack-uninstall

# generate + install
bun run gen:skill-docs --host hermes
./setup --host hermes --quiet

# verify install artifacts
ls -la ~/.hermes/skills | grep gstack || true
test -f ~/.hermes/skills/gstack-browse/SKILL.md
test -f ~/.hermes/skills/gstack-review/SKILL.md
test -f ~/.hermes/skills/gstack-qa-only/SKILL.md

# verify uninstall cleanup
bin/gstack-uninstall --force --keep-state
ls -la ~/.hermes/skills | grep gstack || true
```

Then, from `Roscoe-hermes`, run any docs/helper validation and include exact outputs.

---

## Acceptance criteria
- Hermes host install is one command and reproducible.
- Uninstall removes Hermes gstack artifacts cleanly.
- Roscoe-Hermes has clear operator docs for install/verify/remove.
- Any new helper script is idempotent and exits non-zero on failed checks.
- No regressions to non-Hermes host setup paths.

---

## Git hygiene
Use this commit structure if changes are non-trivial:
1. `feat(gstack): harden hermes setup/install verification`
2. `feat(hermes): add gstack integration docs/helper`
3. `test(chore): add integration verification notes`

Include a PR summary with:
- What changed
- Why it changed
- How to verify
- Known limitations

---

## What to return
Return:
1. A short summary of implemented changes.
2. Unified diff or commit list.
3. Exact verification log.
4. Any follow-up recommendations (max 5 bullets).
