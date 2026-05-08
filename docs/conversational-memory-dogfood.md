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

The setup script intentionally does not copy Slack, Telegram, or other production platform tokens. It writes only the conversational-memory command environment, a loopback API server config, and an optional OpenRouter key.

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

Run the gateway API server dogfood path:

```bash
set -a
source /Users/aaronwhaley/.hermes/profiles/memory-test/.env
set +a
HERMES_HOME=/Users/aaronwhaley/.hermes/profiles/memory-test \
python -m hermes_cli.main gateway run
```

In another shell, verify the OpenAI-compatible surface:

```bash
curl -sS http://127.0.0.1:8765/v1/models \
  -H 'Authorization: Bearer memory-test-local-key'
```

Then exercise the memory tool through the API server agent:

```bash
curl -sS http://127.0.0.1:8765/v1/chat/completions \
  -H 'Authorization: Bearer memory-test-local-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: memory-dogfood' \
  -H 'X-Hermes-Session-Key: memory-dogfood' \
  -H 'X-Hermes-Use-Unified-Timeline: true' \
  -d '{"model":"memory-test","messages":[{"role":"user","content":"Use conversational_memory_search to search for Smith PIP demand timing. Answer with the found status and source summary id."}],"stream":false}'
```
