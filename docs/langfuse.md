# Langfuse Tracing

Optional observability integration.  When enabled, every LLM call Hermes
makes — whether directly to Anthropic/OpenAI, through OpenRouter, to any
OpenAI-compatible endpoint — is automatically traced to Langfuse with full
prompt, response, token counts, latency, and cost.

## What gets traced

All OpenAI-SDK calls made by Hermes are wrapped automatically:

- The main agent loop (every turn, every tool call)
- Auxiliary-model calls (trajectory compression, summarization, etc.)
- Cron job executions
- Subagent delegations

Hermes uses the OpenAI SDK for all OpenAI-compatible providers (OpenRouter,
OpenAI direct, z.ai, Kimi, MiniMax, Nous Portal), so one integration covers
all of them.  Direct Anthropic SDK calls go through a separate
`AnthropicAuxiliaryClient` and are **not** currently traced — see "What's
not traced" below.

## How it's wired in

Hermes uses Langfuse's drop-in OpenAI wrapper.  At the very top of the
`hermes_cli` package init, before any other Hermes module imports `openai`,
the tracing module checks for `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`
and if both are set:

1. Imports `langfuse.openai` (which exposes traced subclasses of
   `openai.OpenAI` / `openai.AsyncOpenAI`).
2. Monkey-patches the attributes on the `openai` module so any subsequent
   `from openai import OpenAI` picks up the traced version.

Because this happens at package import time, all downstream Hermes modules
(`agent/auxiliary_client.py`, `hermes_cli/models.py`, etc.) see the traced
classes automatically.  **Zero changes to core LLM-client code were needed.**

The integration is best-effort and silent on failure:

- No env vars set → nothing happens, Hermes runs normally.
- Env vars set but `langfuse` package not installed → warning logged, Hermes
  runs normally.
- Langfuse package installed and init succeeds → every LLM call is traced.

## Enabling it on Railway

### 1. Make sure the package is installed

`langfuse` is included in the `[all]` extra in `pyproject.toml` (under the
`observability` sub-extra).  The `Dockerfile.railway` installs `.[all]`, so
your Railway image already contains it — no Dockerfile changes needed as
long as you're on the latest build.

### 2. Create a Langfuse project

- Go to https://cloud.langfuse.com (or your self-hosted instance).
- Create a project.
- Open **Settings → API Keys → Create new API keys**.
- Copy the **Public Key** (`pk-lf-...`) and **Secret Key** (`sk-lf-...`).

### 3. Add the env vars on Railway

Service → **Variables** → **Raw Editor**, append:

```
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

If you're self-hosting Langfuse, set `LANGFUSE_HOST` to your instance URL
(e.g. `https://langfuse.mycompany.com`).  Otherwise you can omit it — the
default is `https://cloud.langfuse.com`.

Save.  Railway will redeploy automatically (no full rebuild, ~30 seconds).

### 4. Verify

Check the **Deploy Logs** for:

```
Langfuse tracing enabled — host=https://cloud.langfuse.com
```

If you see that line, tracing is on.  Send your Hermes bot a message on
Telegram, wait a few seconds, then open your Langfuse project dashboard —
the trace will show up under **Traces** with the full prompt, response,
model, token counts, and latency.

## Running locally

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
export LANGFUSE_SECRET_KEY=sk-lf-xxxx
export LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
hermes gateway run
```

Same log line as above confirms tracing is on.

## Environment variables

| Variable | Required | Default | What it does |
|---|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | yes | — | Langfuse project public key (`pk-lf-...`) |
| `LANGFUSE_SECRET_KEY` | yes | — | Langfuse project secret key (`sk-lf-...`) |
| `LANGFUSE_HOST` | no | `https://cloud.langfuse.com` | Langfuse API base URL.  Override for self-hosted instances. |

## What's not traced

A few edge cases aren't covered by the OpenAI-SDK monkey-patch and would
need additional instrumentation:

- **Direct Anthropic SDK calls.**  When Hermes uses Anthropic as an
  auxiliary provider (not via OpenRouter), it uses the `anthropic` package
  directly.  These calls are not traced by the OpenAI patch.  Adding
  Langfuse's `@observe` decorator to `AnthropicAuxiliaryClient.complete()`
  would fix this — TODO.
- **Codex (OpenAI Codex CLI backend).**  Uses a custom client class that
  wraps `codex` binary calls.  Not traced.  Rarely used.
- **Daytona / Modal terminal backends.**  Remote code execution in
  Daytona/Modal sandboxes makes its own LLM calls inside the sandbox.
  Those calls run in a separate Python process and won't appear in the
  Hermes service's Langfuse traces.  They would need their own Langfuse
  env vars inside the sandbox.

For a Telegram-gateway deployment using OpenRouter (the typical Railway
setup), **everything you care about is traced**.

## Privacy / data handling

Langfuse's OpenAI wrapper sends:

- The full prompt (system + user + assistant messages)
- The full model response
- Model name, token counts, latency
- Any tool-call arguments and results

**If your Hermes instance handles sensitive legal or personal data, make
sure your Langfuse deployment is compliant with your data-handling
requirements.**  Self-hosting Langfuse is the safer option for sensitive
workloads — Langfuse Cloud is US-hosted.

You can also opt to disable tracing for specific calls using Langfuse's
SDK-level controls (e.g., `@observe(capture_input=False)`), but this
requires touching the Hermes call sites and isn't wired up by default.

## Disabling

To turn off tracing, remove the env vars from Railway and redeploy:

```
# remove these from Variables:
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_HOST
```

The monkey-patch only runs when both keys are present, so unsetting either
one disables tracing entirely.  No code changes needed.
