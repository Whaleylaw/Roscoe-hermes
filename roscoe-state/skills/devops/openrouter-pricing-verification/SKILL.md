---
name: openrouter-pricing-verification
description: >
  Verify and update LLM model pricing from the OpenRouter API. Use when
  building or updating pricing tables, estimating costs, or answering
  questions about model availability/pricing. Never trust web search,
  subagent research, or LLM memory for pricing — always query live.
tags: [openrouter, pricing, models, llm, costs]
triggers:
  - updating model pricing table
  - user asks about model costs
  - building cost estimation features
  - "what does X model cost"
  - verifying model availability
---

# OpenRouter Pricing Verification

## Why This Skill Exists

LLM model pricing is volatile and provider-specific. Web search returns stale
data (often 6-12 months old). Subagent research compounds the error. LLM
memory hallucinates models and prices. The ONLY reliable source is a live
API query to the provider actually being used.

Aaron uses **OpenRouter** as his unified LLM provider. All pricing must come
from there, not from OpenAI/Anthropic/Google directly (OpenRouter markup may
differ from direct API pricing).

## Steps

### 1. Query the OpenRouter models API

```bash
curl -s 'https://openrouter.ai/api/v1/models' | python3 -c "
import sys, json
data = json.loads(sys.stdin.read(), strict=False)
for m in data.get('data', []):
    mid = m['id']
    inp = float(m.get('pricing', {}).get('prompt', 0)) * 1_000_000
    out = float(m.get('pricing', {}).get('completion', 0)) * 1_000_000
    ctx = m.get('context_length', '?')
    print(f'{mid}|in=\${inp:.4f}|out=\${out:.4f}|ctx={ctx}')
"
```

NOTE: Must use `strict=False` on json.loads because the API response contains
control characters that break Python's default strict JSON parser.

### 2. Filter for specific models

Pipe through grep or add filtering inside the Python:
```bash
# Filter for specific providers/models
... | grep -E 'openai/gpt-5|anthropic/claude|google/gemini'
```

Or use execute_code with hermes_tools for programmatic filtering.

### 3. Format for the GSD costs.js pricing table

The pricing table lives at `/opt/data/gsd-lawyerinc/src/costs.js` in the
`MODEL_PRICING` constant. Format:

```javascript
// https://openrouter.ai/{model_id}  — ${input}/${output}, {context} ctx
'provider/model-name':  { input: X.XX,  output: Y.YY  },
'short-alias':          { input: X.XX,  output: Y.YY  },
```

Each entry MUST have:
- A comment with the verifiable OpenRouter URL
- The price in USD per 1M tokens
- Both the full provider/model ID and a short alias

### 4. Cite sources

Every price must be traceable to `https://openrouter.ai/{model_id}`.
Include the retrieval date in the JSDoc block above the table.

## Pitfalls

1. **Never trust web search for pricing.** It returns cached/stale results,
   often from a different year or provider.
2. **Never trust subagent research.** Subagents compound the staleness
   problem and may mix direct-API and OpenRouter prices.
3. **Never trust LLM memory for model names.** Models get released, renamed,
   and deprecated constantly. The live API is the source of truth.
4. **OpenRouter prices ≠ direct provider prices.** OpenRouter may add markup
   or have different pricing tiers. Always use OpenRouter prices since that's
   the provider in use.
5. **Only include current-generation models.** Aaron aggressively prunes old
   models. As of 2026-04: OpenAI = only gpt-5.4 family + gpt-5.3-codex
   (cut everything 5.2 and below, all 4.x, all reasoning models).
   Anthropic = only 4.6 family + haiku-4.5 (cut all older Claude).
   Google = only 3.1 family (cut all 3.0/2.x). When in doubt, ask which
   generation to include — don't include everything the API returns.
6. **The API response has control characters.** Use `json.loads(data, strict=False)`
   or the `json_parse()` helper in execute_code to avoid JSONDecodeError.
7. **Preview vs GA models.** Check if models are still in "preview" — note
   this in the pricing table comment if so (e.g., Gemini 3.1 models).

## Verification

After updating the pricing table:
```bash
cd /opt/data/gsd-lawyerinc && node src/test-s02.js
```
The S02 test suite validates cost estimation against the pricing table.
