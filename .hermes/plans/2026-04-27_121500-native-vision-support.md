# Native Vision Support for Hermes Agent

**Date:** 2026-04-27
**Status:** Proposed
**Author:** Hermes (for Aaron Whaley)

---

## Goal

Make vision a first-class capability in Hermes so that vision-capable models
receive images, documents, and screenshots as native multimodal content parts
(`image_url` blocks) instead of the current text-description pipeline. Fall
back to the existing auxiliary-vision-describe approach only when the main
model lacks vision support.

---

## Current State (The Problem)

Today, every image that enters Hermes — whether from Telegram, CLI, or tool
results — goes through a **describe-then-text** pipeline:

```
User sends image on Telegram
  → gateway/platforms/telegram.py downloads & caches locally
  → gateway/run.py _enrich_message_with_vision()
    → tools/vision_tools.py vision_analyze_tool()
      → Separate auxiliary LLM call (not the main model)
      → Returns text description
    → Text is prepended: "[The user sent an image~ Here's what I can see: ...]"
  → run_agent.py run_conversation(user_message=<string>)
  → Main model only sees text — never the actual image
```

**Problems with this approach:**
1. **Double inference cost** — auxiliary vision model + main model reading description
2. **Information loss** — text descriptions miss visual nuance, spatial layout, fine details
3. **Latency** — two serial LLM calls before the agent can even start working
4. **Redundancy** — most modern models (GPT-4o, Claude 4, Gemini 2.5, etc.) are vision-native
5. **Tool results stripped** — browser_vision screenshots go through the same text-conversion even though the main model could examine them directly

**What already works (unused plumbing):**
- `agent/models_dev.py` has `ModelInfo.supports_vision()` and `ModelCapabilities.supports_vision`
- `agent/anthropic_adapter.py` has `_convert_content_to_anthropic()` for image_url → source blocks
- `agent/codex_responses_adapter.py` has `_chat_content_to_responses_parts()` for image_url → input_image
- `agent/gemini_native_adapter.py` has `_extract_multimodal_parts()` for inline_data
- Standard chat_completions passes `image_url` content parts natively

The downstream transports **can** handle multimodal content. The gateway and run_conversation just never send it.

---

## Proposed Approach

**Strategy: "Vision-first with graceful degradation"**

Check at the gateway level whether the main model supports vision. If yes,
pass images as native `image_url` content parts. If no, fall back to the
existing text-description pipeline. A config knob allows explicit override.

### Key Principle

The `run_conversation()` interface must accept multimodal content — not just strings.
This is the single most important change. Everything else flows from it.

---

## Step-by-Step Plan

### Step 1: Config — Add `vision.native` Setting

**File:** `hermes_cli/config.py` (DEFAULT_CONFIG, ~line 556)

Add a new top-level key under `auxiliary.vision`:

```yaml
auxiliary:
  vision:
    native: "auto"       # "auto" | true | false
    # auto = check models_dev supports_vision() at runtime
    # true = always send images natively (assumes model can handle it)
    # false = always describe-then-text (current behavior)
    provider: "auto"     # (existing — for auxiliary fallback)
    model: ""            # (existing — for auxiliary fallback)
    ...
```

**Why here:** Keeps all vision config together. The auxiliary.vision section
already configures the fallback vision provider — adding `native` alongside
it makes the relationship clear: "try native first, fall back to auxiliary."

**Bridge to env var:** Add `HERMES_VISION_NATIVE` env var bridge in cli.py
alongside the existing AUXILIARY_VISION_* bridges (~line 594).

### Step 2: Runtime Vision Capability Check

**File:** `gateway/run.py` (new helper function)

Add a function that resolves whether the current agent session should use
native vision:

```python
def _should_use_native_vision(config, provider: str, model: str) -> bool:
    """Check if the main model should receive images natively."""
    native_setting = config.get("auxiliary", {}).get("vision", {}).get("native", "auto")
    
    if native_setting is True or str(native_setting).lower() == "true":
        return True
    if native_setting is False or str(native_setting).lower() == "false":
        return False
    
    # "auto" — check model capabilities
    from agent.models_dev import get_model_capabilities
    caps = get_model_capabilities(provider, model)
    if caps and caps.supports_vision:
        return True
    return False
```

This function is called once per session/turn, not per-image, so the models_dev
lookup cost is negligible.

### Step 3: Gateway Preprocessing — Conditional Native Vision

**File:** `gateway/run.py`

**3a. Modify `_prepare_inbound_message_text()` (~line 4024)**

Currently returns `Optional[str]`. Change return type to `Optional[Union[str, List[dict]]]`.

When `_should_use_native_vision()` is True and `event.media_urls` has images:
- Build a multimodal content list instead of calling `_enrich_message_with_vision()`
- Each image becomes an `image_url` content part with a `data:` URL or file path
- The user's text becomes a `text` content part

```python
if image_paths and _should_use_native_vision(self.config, provider, model):
    content_parts = []
    for path in image_paths:
        # Convert local file to base64 data URL
        data_url = _file_to_data_url(path)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": data_url, "detail": "auto"}
        })
    if message_text.strip():
        content_parts.append({"type": "text", "text": message_text})
    message_text = content_parts  # Now a list, not a string
else:
    # Existing text-description fallback
    if image_paths:
        message_text = await self._enrich_message_with_vision(message_text, image_paths)
```

**3b. Add `_file_to_data_url()` helper**

```python
import base64, mimetypes

def _file_to_data_url(file_path: str, max_size_mb: int = 20) -> str:
    """Convert local file to base64 data URL for vision content parts."""
    mime, _ = mimetypes.guess_type(file_path)
    if not mime:
        mime = "image/jpeg"
    with open(file_path, "rb") as f:
        data = f.read()
    # Auto-resize if too large (reuse logic from vision_tools.py)
    if len(data) > max_size_mb * 1024 * 1024:
        from tools.vision_tools import _resize_image
        data = _resize_image(data, target_mb=5)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"
```

**3c. Threading provider/model through to preprocessing**

The `_prepare_inbound_message_text()` function currently doesn't know the
provider or model. It's called before the agent is instantiated. We need to
thread the session's configured provider/model through.

Options:
- Read from the gateway config (the primary provider/model configured)
- Read from the session entry's last-used model if available
- Pass explicitly from the caller

**Recommended:** Read from `self.config` (the gateway-level config). The
provider and model are known at config load time. For per-session model
overrides, the session_entry may have a `model` field.

### Step 4: `run_conversation()` — Accept Multimodal Content

**File:** `run_agent.py` (~line 8865)

**4a. Widen the type signature:**

```python
def run_conversation(
    self,
    user_message: Union[str, List[Dict[str, Any]]],  # str or content parts
    system_message: str = None,
    conversation_history: List[Dict[str, Any]] = None,
    task_id: str = None,
    stream_callback: Optional[callable] = None,
    persist_user_message: Optional[str] = None,
) -> Dict[str, Any]:
```

**4b. Handle multimodal user_message in message construction:**

Where the user message is added to the messages list, handle both formats:

```python
if isinstance(user_message, list):
    # Multimodal content parts — use OpenAI content array format
    messages.append({"role": "user", "content": user_message})
else:
    # Plain string — current behavior
    messages.append({"role": "user", "content": user_message})
```

**4c. Adjust sanitization guards:**

The `_sanitize_surrogates()` and `sanitize_context()` calls (~line 8910-8922)
currently assume `user_message` is a string. Guard with `isinstance` check:

```python
if isinstance(user_message, str):
    user_message = _sanitize_surrogates(user_message)
    user_message = sanitize_context(user_message)
elif isinstance(user_message, list):
    # Sanitize only the text parts
    for part in user_message:
        if isinstance(part, dict) and part.get("type") == "text":
            part["text"] = _sanitize_surrogates(part["text"])
            part["text"] = sanitize_context(part["text"])
```

**4d. persist_user_message for transcript:**

When user_message is multimodal, we still need a plain-text version for
session transcripts/history display. Extract text parts for persistence:

```python
if persist_user_message is None and isinstance(user_message, list):
    persist_user_message = " ".join(
        p.get("text", "") for p in user_message
        if isinstance(p, dict) and p.get("type") == "text"
    ).strip() or "[Image(s) attached]"
```

### Step 5: Fix Anthropic Content Preprocessing

**File:** `run_agent.py` (~line 6949)

`_preprocess_anthropic_content()` currently strips ALL image_url parts from
messages for Anthropic models. This is wrong — Claude supports vision natively.

**Change:** Only strip image_url parts when the model does NOT support vision.

```python
def _preprocess_anthropic_content(self, content: Any, role: str) -> Any:
    if not self._content_has_image_parts(content):
        return content
    
    # If the main model supports vision, let image parts through —
    # the Anthropic adapter will convert them to source blocks.
    if self._main_model_supports_vision:
        return content
    
    # Otherwise, fall back to describe-then-text (current behavior)
    ...
```

Add `_main_model_supports_vision` as a cached property on AIAgent, resolved
once at init from `get_model_capabilities()`.

Similarly, update `_prepare_anthropic_messages_for_api()` (~line 7011) which
calls the preprocessing — skip image stripping when vision is supported.

### Step 6: Tool Results With Native Images (Optional Enhancement)

**File:** `model_tools.py` + `tools/browser_tool.py` + `tools/vision_tools.py`

Currently, `handle_function_call()` returns `str`. Tool result messages are
always `{"role": "tool", "content": <string>}`.

**Phase 1 (skip for now):** Keep tool results as strings. The agent can still
use `vision_analyze` or `browser_vision` tools manually, and the auxiliary
vision pipeline handles those internally.

**Phase 2 (future):** Allow tool results to return multimodal content parts.
When `browser_vision` takes a screenshot and the main model supports vision,
include the screenshot as an image_url content part in the tool result. This
requires:
- `handle_function_call()` returning `Union[str, List[dict]]`
- Tool result message construction handling content arrays
- Provider-specific handling (Anthropic tool results support images differently)

**Recommendation:** Phase 1 for this plan. Phase 2 is a separate follow-up.
The biggest win is user-submitted images going native. Tool result images are
a nice-to-have that can be added incrementally.

### Step 7: Gateway Call Site — Thread Multimodal Message Through

**File:** `gateway/run.py` (~line 10346)

The call `agent.run_conversation(message, ...)` currently passes a string.
After Step 3, `message` may be a `list` (multimodal content parts). This
should "just work" since run_conversation now accepts both types.

Verify the `persist_user_message` parameter is set correctly so the session
transcript stores a clean text version even when the message is multimodal.

### Step 8: Document-Specific Vision (PDF, etc.)

**File:** `gateway/run.py` (~line 4085+)

Some models support native PDF input (Gemini, Claude). The `ModelInfo`
dataclass already has `supports_pdf()`. For document uploads:

```python
if mime_type == "application/pdf" and model_supports_pdf:
    # Send PDF as a document content part
    content_parts.append({
        "type": "file",   # or provider-specific format
        "file_data": {"url": data_url, "mime_type": "application/pdf"}
    })
```

**Recommendation:** Defer PDF-native support to a follow-up. Focus on images
first. PDF handling varies significantly across providers (Anthropic uses
document type, Gemini uses inline_data, OpenAI doesn't support it).

---

## Files That Change

| File | Change | Risk |
|------|--------|------|
| `hermes_cli/config.py` | Add `native` key under `auxiliary.vision` | Low — additive config |
| `cli.py` | Bridge `HERMES_VISION_NATIVE` env var | Low — pattern already exists |
| `gateway/run.py` | `_should_use_native_vision()`, modify `_prepare_inbound_message_text()`, add `_file_to_data_url()` | **Medium** — core preprocessing path |
| `run_agent.py` | Widen `run_conversation()` signature, guard sanitization, fix `_preprocess_anthropic_content()`, add `_main_model_supports_vision` | **High** — core agent loop |
| `agent/models_dev.py` | No changes needed — `supports_vision()` already exists | None |
| `agent/anthropic_adapter.py` | No changes needed — already handles image_url → source blocks | None |
| `agent/codex_responses_adapter.py` | No changes needed — already handles image_url → input_image | None |

---

## Tests / Validation

### Unit Tests (new)

1. **`test_should_use_native_vision_auto`** — verify auto-detection via models_dev
2. **`test_should_use_native_vision_forced`** — verify true/false overrides
3. **`test_prepare_inbound_multimodal`** — verify image_paths → content parts when native=true
4. **`test_prepare_inbound_fallback`** — verify text-description when native=false
5. **`test_run_conversation_multimodal_message`** — verify content list flows through
6. **`test_anthropic_preserves_images_when_vision_capable`** — verify _preprocess_anthropic_content passes images through
7. **`test_anthropic_strips_images_when_not_vision_capable`** — verify existing behavior preserved
8. **`test_file_to_data_url`** — verify base64 encoding, MIME detection, resize
9. **`test_multimodal_persist_user_message`** — verify transcript gets text version

### Integration Test

- Send an image to the Telegram bot with native vision enabled
- Verify the model receives `image_url` content parts (check via langfuse trace or debug log)
- Verify the response references visual details not capturable by text description

### Regression Tests

- Existing vision tool tests still pass
- Models without vision still get text-description fallback
- Anthropic models without vision still get text fallback
- Session history/transcript still stores clean text

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|-----------|
| **Base64 bloat** — images as data URLs are ~1.33x the file size in tokens | Use `detail: "auto"` (or `detail: "low"` for thumbnails) to let the API decide resolution. Most providers downsample server-side. |
| **Token cost** — vision tokens may be more expensive per-image than a text description | Net savings: one LLM call instead of two. Text descriptions are typically 200-500 tokens; a medium image is ~1000 tokens. But you skip the entire auxiliary call. |
| **Provider inconsistency** — image_url format varies (OpenAI vs Anthropic vs Gemini) | Existing adapters already handle conversion. No new adapter work needed. |
| **Large image batches** — user sends 10 photos, all become base64 | Cap at reasonable number (e.g. 5 native images, rest described). Or use `detail: "low"` for batch. |
| **Regression in non-vision models** — accidentally sending image parts to text-only model | The `auto` mode checks models_dev. Plus the `false` override exists as escape hatch. |
| **run_conversation signature change** — could break callers | It's Union[str, list] — existing str callers unaffected. Only gateway/run.py passes multimodal. |

---

## Open Questions

1. **Should `detail` level be configurable?** OpenAI supports `detail: "low" | "high" | "auto"`. Could add to auxiliary.vision config. Default `auto` is sensible.

2. **Image count cap?** Should we limit how many images get sent natively in one message? 5? 10? Or leave it unlimited and let the provider reject if too many?

3. **Tool result images (Phase 2)?** When browser_vision takes a screenshot, should we also send that natively? This is a separate change since tool results have different message structure constraints per provider.

4. **URL vs base64?** For images already hosted (URLs), we could pass the URL directly instead of downloading + base64 encoding. But local cached files need base64. Could optimize later.

---

## Implementation Order

1. Config change (Step 1) — 15 min
2. `_should_use_native_vision()` + `_file_to_data_url()` (Step 2-3b) — 30 min
3. `_prepare_inbound_message_text()` modification (Step 3a, 3c) — 45 min
4. `run_conversation()` signature widening (Step 4) — 30 min
5. Anthropic fix (Step 5) — 20 min
6. Tests (Step 9) — 45 min
7. Integration test on Telegram — 15 min

**Total estimated: ~3.5 hours of implementation**

---

## Non-Goals (Explicitly Deferred)

- Native PDF/document vision (provider-specific, needs separate plan)
- Tool result multimodal content (Phase 2)
- Audio/video native input (different modality, different plan)
- Per-provider image format optimization (URL vs base64 vs file upload)
- Image caching/dedup across turns (nice-to-have, not blocking)
