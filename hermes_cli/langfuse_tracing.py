"""Optional Langfuse tracing integration.

When ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set in the
environment, this module monkey-patches the ``openai`` package so every LLM
call Hermes makes through the OpenAI SDK (including OpenRouter, which speaks
the OpenAI protocol) is automatically traced to Langfuse.

The ``init()`` function is called from ``hermes_cli/__init__.py`` so the
patch is in place BEFORE any other Hermes module imports ``openai``.  That
ordering matters: ``from openai import OpenAI`` captures the class reference
at import time, so the patch must land on the ``openai`` module attributes
before ``agent/auxiliary_client.py`` (and any other client instantiator) is
ever loaded.

This is a best-effort, no-op-on-failure integration:

* If the ``langfuse`` package isn't installed → silently skip.
* If the required env vars are missing → silently skip.
* If patching raises unexpectedly → log a warning and continue.

Hermes's normal operation is never affected by Langfuse being unavailable.
"""

from __future__ import annotations

import logging
import os

_logger = logging.getLogger("hermes.langfuse")

# Track initialization state so repeated calls are no-ops.
_initialized = False


def is_configured() -> bool:
    """Return True if the minimum Langfuse env vars are set."""
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


def init() -> bool:
    """Initialize Langfuse tracing if configured.

    Returns True if tracing was successfully enabled, False otherwise.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return True

    if not is_configured():
        # Not configured — stay silent at DEBUG level so we don't pollute
        # logs for users who aren't using Langfuse.
        _logger.debug(
            "Langfuse not configured (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)"
        )
        return False

    try:
        # langfuse.openai exposes OpenAI / AsyncOpenAI subclasses that
        # automatically emit Langfuse generation events for each call.
        # Replacing the attributes on the openai module means any later
        # `from openai import OpenAI` picks up the wrapped version.
        import langfuse.openai as _lf_openai
        import openai

        openai.OpenAI = _lf_openai.OpenAI
        openai.AsyncOpenAI = _lf_openai.AsyncOpenAI

        _initialized = True
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        _logger.info("Langfuse tracing enabled — host=%s", host)
        return True

    except ImportError:
        _logger.warning(
            "LANGFUSE_PUBLIC_KEY is set but the `langfuse` package is not "
            "installed — tracing disabled.  Install with: "
            "pip install 'hermes-agent[observability]'"
        )
        return False

    except Exception as exc:
        _logger.warning("Failed to initialize Langfuse tracing: %s", exc)
        return False
