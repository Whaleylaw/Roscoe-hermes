"""Langfuse tracing integration for Hermes.

Auto-instruments OpenAI and Anthropic clients when LANGFUSE_SECRET_KEY is set.
Provides trace context for conversations and tool calls.

Usage:
    from agent.langfuse_tracing import wrap_openai_client, wrap_anthropic_client, get_langfuse

    # Wrap clients at creation time
    client = wrap_openai_client(OpenAI(**kwargs))
    anthropic_client = wrap_anthropic_client(Anthropic(**kwargs))
"""

import logging
import os
from typing import Dict, Any

from gateway.session_context import get_session_env

logger = logging.getLogger(__name__)

LANGFUSE_REQUIRED_ENV = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
LANGFUSE_OPTIONAL_ENV = ("LANGFUSE_BASE_URL",)
OTEL_RECOMMENDED_ENV = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SERVICE_NAME",
)

_langfuse_instance = None
_langfuse_available = None


def get_langfuse_readiness() -> Dict[str, Any]:
    """Return Langfuse/OTel readiness details without exposing secret values."""
    present_required = [k for k in LANGFUSE_REQUIRED_ENV if os.environ.get(k)]
    missing_required = [k for k in LANGFUSE_REQUIRED_ENV if not os.environ.get(k)]
    present_optional = [k for k in LANGFUSE_OPTIONAL_ENV if os.environ.get(k)]
    present_otel = [k for k in OTEL_RECOMMENDED_ENV if os.environ.get(k)]
    missing_otel = [k for k in OTEL_RECOMMENDED_ENV if not os.environ.get(k)]

    enabled = len(missing_required) == 0

    if enabled:
        reason = "configured"
    elif missing_required == ["LANGFUSE_PUBLIC_KEY"]:
        reason = "missing_langfuse_public_key"
    elif missing_required == ["LANGFUSE_SECRET_KEY"]:
        reason = "missing_langfuse_secret_key"
    else:
        reason = "missing_langfuse_credentials"

    return {
        "enabled": enabled,
        "reason": reason,
        "langfuse": {
            "present_required": present_required,
            "missing_required": missing_required,
            "present_optional": present_optional,
        },
        "otel": {
            "present": present_otel,
            "missing": missing_otel,
            "ready": len(missing_otel) == 0,
        },
    }


def is_langfuse_enabled() -> bool:
    """Check if Langfuse credentials are configured."""
    global _langfuse_available
    if _langfuse_available is not None:
        return _langfuse_available
    _langfuse_available = get_langfuse_readiness()["enabled"]
    return _langfuse_available


def get_langfuse():
    """Get or create the global Langfuse instance."""
    global _langfuse_instance
    if _langfuse_instance is not None:
        return _langfuse_instance
    if not is_langfuse_enabled():
        return None
    try:
        from langfuse import Langfuse
        _langfuse_instance = Langfuse()
        logger.info("Langfuse tracing initialized (host=%s)", os.environ.get("LANGFUSE_BASE_URL", "default"))
        return _langfuse_instance
    except Exception as e:
        logger.warning("Failed to initialize Langfuse: %s", e)
        _langfuse_available = False
        return None


def wrap_openai_client(client):
    """Wrap an OpenAI client with Langfuse tracing.

    Returns the wrapped client, or the original if Langfuse is unavailable.
    """
    if not is_langfuse_enabled():
        return client
    try:
        from langfuse.openai import openai as langfuse_openai
        # langfuse.openai patches the module; but for explicit wrapping
        # we use the observe decorator approach via the Langfuse instance
        lf = get_langfuse()
        if lf is None:
            return client
        # The langfuse openai integration works by patching the openai module.
        # Once imported, all OpenAI client calls are auto-traced.
        # We just need to ensure langfuse.openai is imported.
        logger.debug("OpenAI client wrapped with Langfuse tracing")
        return client
    except Exception as e:
        logger.warning("Failed to wrap OpenAI client with Langfuse: %s", e)
        return client


def wrap_anthropic_client(client):
    """Wrap an Anthropic client with Langfuse tracing.

    Returns the wrapped client, or the original if Langfuse is unavailable.
    """
    if not is_langfuse_enabled():
        return client
    try:
        from langfuse.anthropic import AnthropicInstrumentor
        AnthropicInstrumentor().instrument()
        logger.debug("Anthropic client instrumented with Langfuse tracing")
        return client
    except ImportError:
        # langfuse.anthropic may not exist in older versions
        logger.debug("Langfuse Anthropic instrumentation not available")
        return client
    except Exception as e:
        logger.warning("Failed to wrap Anthropic client with Langfuse: %s", e)
        return client


def init_langfuse_tracing():
    """Initialize Langfuse tracing globally.

    Call once at startup. Auto-patches OpenAI and Anthropic SDKs.
    """
    if not is_langfuse_enabled():
        logger.debug("Langfuse tracing disabled (no credentials)")
        return False

    try:
        # Import langfuse.openai to auto-patch the openai module
        from langfuse.openai import openai as _  # noqa: F401
        logger.info("Langfuse OpenAI auto-instrumentation active")
    except Exception as e:
        logger.warning("Langfuse OpenAI instrumentation failed: %s", e)

    try:
        from langfuse.anthropic import AnthropicInstrumentor
        AnthropicInstrumentor().instrument()
        logger.info("Langfuse Anthropic auto-instrumentation active")
    except ImportError:
        logger.debug("Langfuse Anthropic instrumentation not available (older SDK)")
    except Exception as e:
        logger.warning("Langfuse Anthropic instrumentation failed: %s", e)

    # Ensure Langfuse instance is created (for flush on shutdown)
    get_langfuse()
    return True


def flush_langfuse():
    """Flush pending Langfuse events. Call on shutdown."""
    if _langfuse_instance is not None:
        try:
            _langfuse_instance.flush()
        except Exception as e:
            logger.warning("Langfuse flush failed: %s", e)


def set_current_trace_io(*, input: Any = None, output: Any = None) -> None:
    """Attach trace-level input/output to the current Langfuse trace.

    This is best-effort and fail-open. It helps when provider-level auto-
    instrumentation emits spans but omits final assistant text in the legacy
    trace-level output field used by some Langfuse views.
    """
    if not is_langfuse_enabled():
        return
    try:
        lf = get_langfuse()
        if lf is None:
            return
        # Avoid noisy "No active span in current context" warnings when called
        # outside an instrumented model span.
        if not getattr(lf, "get_current_trace_id", lambda: None)():
            return
        lf.set_current_trace_io(input=input, output=output)
    except Exception as e:
        logger.debug("Langfuse set_current_trace_io failed: %s", e)


def set_current_generation_output(output: Any) -> None:
    """Attach assistant output to the current generation/span when available.

    Some Langfuse UIs primarily display generation-level output. On certain
    streaming/instrumented paths the provider span may exist but not include
    final text unless it is updated explicitly.
    """
    if not is_langfuse_enabled():
        return
    try:
        lf = get_langfuse()
        if lf is None:
            return
        lf.update_current_generation(output=output)
    except Exception as e:
        logger.debug("Langfuse update_current_generation failed: %s", e)


def set_current_trace_session_context() -> None:
    """Attach gateway session metadata to the active Langfuse span/trace.

    Langfuse Python SDK v4 exposes ``update_current_span`` and trace I/O helpers,
    but not a generic ``update_current_trace(session_id=...)`` mutator. We
    therefore attach session context as span metadata (queryable in Langfuse)
    and mirror text I/O via ``set_current_trace_io`` elsewhere.

    Best-effort and fail-open.
    """
    if not is_langfuse_enabled():
        return

    session_key = (get_session_env("HERMES_SESSION_KEY", "") or "").strip()
    if not session_key:
        return

    platform = (get_session_env("HERMES_SESSION_PLATFORM", "") or "").strip()
    chat_id = (get_session_env("HERMES_SESSION_CHAT_ID", "") or "").strip()
    thread_id = (get_session_env("HERMES_SESSION_THREAD_ID", "") or "").strip()
    user_id = (get_session_env("HERMES_SESSION_USER_ID", "") or "").strip()

    metadata = {
        "hermes_session_key": session_key,
        "platform": platform,
        "chat_id": chat_id,
        "thread_id": thread_id,
        "channel_cwd": (os.getenv("HERMES_CHANNEL_CWD", "") or "").strip(),
        "session_isolated": (os.getenv("HERMES_SESSION_ISOLATED", "") or "").strip().lower() in ("1", "true", "yes"),
    }
    if user_id:
        metadata["user_id"] = user_id

    try:
        lf = get_langfuse()
        if lf is None:
            return
        if not getattr(lf, "get_current_trace_id", lambda: None)():
            return
        lf.update_current_span(metadata=metadata)
    except Exception as e:
        logger.debug("Langfuse update_current_span(session metadata) failed: %s", e)


def shutdown_langfuse():
    """Shutdown Langfuse cleanly. Call on process exit."""
    global _langfuse_instance
    if _langfuse_instance is not None:
        try:
            _langfuse_instance.shutdown()
        except Exception as e:
            logger.warning("Langfuse shutdown failed: %s", e)
        _langfuse_instance = None
