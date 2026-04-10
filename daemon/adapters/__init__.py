"""Service adapters for upstream integrations.

Each adapter implements a minimal client interface to one external service.
Adapters that don't exist yet expose a clean abstract base so the supervisor
can reference them without import errors.
"""
