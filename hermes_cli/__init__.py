"""
Hermes CLI - Unified command-line interface for Hermes Agent.

Provides subcommands for:
- hermes chat          - Interactive chat (same as ./hermes)
- hermes gateway       - Run gateway in foreground
- hermes gateway start - Start gateway service
- hermes gateway stop  - Stop gateway service
- hermes setup         - Interactive setup wizard
- hermes status        - Show status of all components
- hermes cron          - Manage cron jobs
"""

# Optional Langfuse tracing — must be initialized BEFORE any other Hermes
# module imports `openai`, otherwise captured class references (e.g.
# `from openai import OpenAI` at module level in agent/auxiliary_client.py)
# will point at the un-wrapped classes and tracing won't see those calls.
# Running this at package-import time guarantees the monkey-patch lands
# before any other hermes_cli submodule is loaded.
try:
    from hermes_cli import langfuse_tracing as _langfuse_tracing
    _langfuse_tracing.init()
except Exception:
    # Never let tracing failure break Hermes startup.
    pass

__version__ = "0.8.0"
__release_date__ = "2026.4.8"
