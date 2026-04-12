---
name: fork-rebase-sync
description: Rebase a GitHub fork onto upstream main, preserving custom commits. Handles large divergence (1000s of commits behind).
tags: [git, rebase, fork, sync, upstream]
triggers:
  - sync fork to upstream
  - rebase fork
  - commits behind main
  - fork out of date
---

# Fork Rebase Sync

## When to Use
- Fork is N commits behind upstream and M commits ahead
- Need to update without losing custom work
- Large divergence (hundreds/thousands of commits behind)

## Steps

### 1. Clone and Add Upstream
```bash
git clone git@github.com:USER/FORK.git
cd FORK
git remote add upstream https://github.com/ORIGINAL_ORG/ORIGINAL_REPO.git
git fetch upstream
```

### 2. Assess Divergence
```bash
git log --oneline main..upstream/main | wc -l  # commits behind
git log --oneline upstream/main..main | wc -l  # commits ahead (custom)
git log --oneline upstream/main..main  # review custom commits
```

### 3. Rebase Custom Commits onto Upstream
```bash
git rebase upstream/main
```

### 4. Resolve Conflicts
- For each conflict, check if upstream changed the same area
- Usually: accept upstream changes, then re-apply your customization on top
- `git rebase --continue` after each resolution

### 5. Verify
```bash
git log --oneline upstream/main..HEAD | wc -l  # should equal original ahead count
git log --oneline HEAD..upstream/main | wc -l  # should be 0
```

### 6. Force Push
```bash
git push --force-with-lease origin main
```

## Nuclear Option (Large Divergence)
If rebase has too many conflicts (e.g., 8000+ commits behind with incompatible changes):
1. Hard reset to upstream: `git reset --hard upstream/main`
2. Cherry-pick essential custom commits: `git cherry-pick <hash1> <hash2> ...`
3. Force push

## Pitfalls
- Always `git log` custom commits BEFORE rebasing to know what to preserve
- If cherry-picking after nuclear reset, apply in chronological order
- Package.json/lock conflicts: usually take upstream, re-add your additions
- Force push required — coordinate with any collaborators

## Aaron's Forks (April 2026 status)
- Roscoe-hermes (NousResearch/hermes-agent): 16 ahead
- Roscoebot (openclaw/openclaw): ~8 ahead  
- paperclip-dashboard (paperclipai/paperclip): 22 ahead
