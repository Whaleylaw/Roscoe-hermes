---
name: hermes-semantic-skills-plugin
description: >
  Maintain and troubleshoot the semantic skills plugin for Hermes. Replaces the
  static 2228-token skill index with vector search (fastembed + numpy). Load this
  skill when the plugin needs debugging, threshold tuning, index rebuilding, or
  when adding new skills and verifying they surface correctly.
tags: [hermes, plugin, semantic-search, fastembed, skills, embeddings, optimization]
---

# Semantic Skills Plugin — Operations Guide

## What It Does

Replaces the static skill index in the system prompt (~2228 tokens, every turn)
with on-demand semantic vector search. Only relevant skills surface per turn.

- System prompt: 98 tokens (slim instruction)
- Per-turn context: 0-400 tokens (only matching skills)
- Savings: 88-96% per turn

## Architecture

```
User message → pre_llm_call hook → embed query (~15ms)
  → cosine similarity vs skill vectors (~0.02ms)
  → filter by threshold (0.55) → inject top N as context
```

## File Locations

- Plugin code: /opt/data/plugins/semantic-skills/__init__.py
- Plugin manifest: /opt/data/plugins/semantic-skills/plugin.yaml
- Vector index: /opt/data/semantic-skills/skill_vectors.npz
- Metadata: /opt/data/semantic-skills/skill_meta.json
- Cache manifest: /opt/data/semantic-skills/skill_manifest.json
- Prompt builder patch: agent/prompt_builder.py (checks HERMES_SEMANTIC_SKILLS_ACTIVE)
- Entrypoint: docker/entrypoint.sh (installs fastembed on boot)

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| SEMANTIC_SKILLS_ENABLED | true | Master toggle |
| SEMANTIC_SKILLS_THRESHOLD | 0.55 | Min cosine similarity to surface a skill |
| SEMANTIC_SKILLS_MAX_RESULTS | 8 | Max skills returned per turn |
| SEMANTIC_SKILLS_MODEL | BAAI/bge-small-en-v1.5 | Embedding model |
| HERMES_SEMANTIC_SKILLS_ACTIVE | (set by plugin) | Tells prompt_builder to use slim mode |

## Key Design Decisions

1. **fastembed over sentence-transformers**: ONNX-based, no PyTorch dependency.
   Install: ~80MB vs ~1.5GB. Docker image stays small for Railway.

2. **numpy over hnswlib/faiss/chromadb**: At 50-500 skills, brute-force cosine
   similarity takes 0.02ms. ANN indexing is overkill. Zero extra dependencies.

3. **Threshold 0.55**: Empirically tuned. At 0.45, "tell me a joke" matches
   random skills. At 0.60, "fix Railway persistence" only gets 1 hit. 0.55
   kills false positives while catching all real matches.

4. **pre_llm_call hook (not system prompt)**: Plugin context goes into the
   user message, preserving the system prompt cache prefix. This is by design
   in the Hermes plugin system.

5. **Lazy model loading**: The embedding model loads on first pre_llm_call
   (~1s), not at import time. Avoids slowing down boot.

6. **Manifest-based cache**: Index rebuilds automatically when skills are
   added/removed/modified (checks mtime+size per SKILL.md file).

## Troubleshooting

### Plugin not loading
```bash
# Check if plugin dir exists in the right place
ls ~/.hermes/plugins/semantic-skills/  # or /opt/data/plugins/semantic-skills/
# Check for plugin.yaml + __init__.py
# Verify fastembed is installed: python3 -c "import fastembed"
```

### Skills not surfacing
```python
# Test from execute_code:
import sys; sys.path.insert(0, '/opt/hermes')
from hermes_cli.plugins import PluginManager
m = PluginManager(); m.discover_and_load()
results = m.invoke_hook('pre_llm_call', session_id='test',
    user_message='your query here', conversation_history=[],
    is_first_turn=True, model='test', platform='test')
print(results)
```

### Force index rebuild
```bash
rm /opt/data/semantic-skills/skill_manifest.json
# Next pre_llm_call will rebuild
```

### Adjust threshold at runtime
```bash
export SEMANTIC_SKILLS_THRESHOLD=0.50  # lower = more results
```

### Disable without removing
```bash
export SEMANTIC_SKILLS_ENABLED=false
# Or: export HERMES_SEMANTIC_SKILLS_ACTIVE=false (restores full static index)
```

## Pitfalls

1. **First-turn latency**: Model download (~42MB) happens on first use.
   Pre-download in Dockerfile if cold starts matter.
2. **Stock skills cause false positives**: p5js, openhue, pytorch-fsdp etc.
   score 0.55-0.62 for unrelated queries due to generic description overlap.
   Fix: prune irrelevant stock skills. (Done: pruned from 81 to 37 skills —
   removed apple, gaming, mlops, creative, smart-home, red-teaming, social-media,
   and other irrelevant categories. Final count: 37 skills (was 81). Keep obsidian,
   github, devops, software-dev, mcp, media/youtube+gif, email, research/arxiv+blogwatcher,
   productivity/google+ocr+pdf. Now at 38 after wiki-compiler was added.)
3. **Embedding text format matters**: Skills are embedded as "name: description".
   Short/vague descriptions produce poor vectors. Keep descriptions specific.
4. **Plugin context is ephemeral**: Not saved to session DB. If you need to
   debug what skills were surfaced, check logs (logger.info outputs match count).
