# Conversational Memory Dogfood Profile

Use an isolated profile before wiring standalone conversational memory into a day-to-day Roscoe profile.

Create or recreate the local-only profile:

```bash
OPENROUTER_API_KEY="$(grep '^OPENROUTER_API_KEY=' /Users/aaronwhaley/.hermes/.env | head -1 | cut -d= -f2-)" \
python scripts/setup_memory_test_profile.py --force
```

Profile home:

```bash
/Users/aaronwhaley/.hermes/profiles/memory-test
```

The setup script intentionally does not copy Slack, Telegram, API server, or other production platform tokens. It writes only the conversational-memory command environment and an optional OpenRouter key.

Seed and verify the memory database:

```bash
set -a
source /Users/aaronwhaley/.hermes/profiles/memory-test/.env
set +a
npm --prefix /Users/aaronwhaley/Github/conversational-memory-system run hermes:smoke -- --db "$HERMES_CONVERSATIONAL_MEMORY_DB"
```

Run Roscoe memory tests against the isolated profile:

```bash
HERMES_HOME=/Users/aaronwhaley/.hermes/profiles/memory-test \
python -m pytest -o addopts='' \
  tests/tools/test_conversational_memory_search_tool.py \
  tests/tools/test_conversational_memory_resume_tool.py \
  tests/tools/test_conversational_memory_proposal_tools.py \
  tests/gateway/test_conversational_memory_context.py \
  tests/gateway/test_conversational_memory_live_loop.py
```

Run a foreground search check:

```bash
set -a
source /Users/aaronwhaley/.hermes/profiles/memory-test/.env
set +a
HERMES_HOME=/Users/aaronwhaley/.hermes/profiles/memory-test \
python -m hermes_cli.main -z \
  "Use the conversational_memory_search tool to search for Smith PIP demand timing in standalone memory, then answer in one sentence with whether you found memory and what source summary id was returned." \
  --toolsets memory --yolo
```
