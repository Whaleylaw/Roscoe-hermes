#!/usr/bin/env python3
"""Verify Langfuse/OTel observability readiness for Hermes + OpenClaw.

Outputs JSON and never prints secret values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

LANGFUSE_REQUIRED = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]
LANGFUSE_OPTIONAL = ["LANGFUSE_BASE_URL"]
OTEL_RECOMMENDED = [
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SERVICE_NAME",
]


def _present(keys: List[str]) -> List[str]:
    return [k for k in keys if os.environ.get(k)]


def _missing(keys: List[str]) -> List[str]:
    return [k for k in keys if not os.environ.get(k)]


def _read_openclaw_config() -> Dict[str, Any]:
    path = Path.home() / ".openclaw" / "openclaw.json"
    result: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "diagnostics_present": False,
        "otel_present": False,
        "otel_enabled": None,
        "service_name": None,
        "error": None,
    }
    if not path.exists():
        return result

    try:
        data = json.loads(path.read_text())
        diagnostics = data.get("diagnostics") if isinstance(data, dict) else None
        otel = diagnostics.get("otel") if isinstance(diagnostics, dict) else None

        result["diagnostics_present"] = isinstance(diagnostics, dict)
        result["otel_present"] = isinstance(otel, dict)
        if isinstance(otel, dict):
            result["otel_enabled"] = otel.get("enabled")
            result["service_name"] = otel.get("serviceName")
    except Exception as exc:  # pragma: no cover - defensive
        result["error"] = str(exc)

    return result


def main() -> None:
    lf_missing = _missing(LANGFUSE_REQUIRED)
    otel_missing = _missing(OTEL_RECOMMENDED)

    output = {
        "hermes": {
            "langfuse": {
                "enabled": len(lf_missing) == 0,
                "present_required": _present(LANGFUSE_REQUIRED),
                "missing_required": lf_missing,
                "present_optional": _present(LANGFUSE_OPTIONAL),
            },
            "otel": {
                "ready": len(otel_missing) == 0,
                "present": _present(OTEL_RECOMMENDED),
                "missing": otel_missing,
            },
        },
        "openclaw": _read_openclaw_config(),
        "summary": {
            "status": "ready" if (len(lf_missing) == 0 and len(otel_missing) == 0) else "action_required",
            "next_actions": [],
        },
    }

    next_actions = output["summary"]["next_actions"]
    if lf_missing:
        next_actions.append(f"Set missing Langfuse env vars: {', '.join(lf_missing)}")
    if otel_missing:
        next_actions.append(f"Set missing OTel env vars: {', '.join(otel_missing)}")

    oc = output["openclaw"]
    if oc["exists"] and not oc["otel_present"]:
        next_actions.append("Add diagnostics.otel block to ~/.openclaw/openclaw.json (or rely fully on OTEL env vars).")
    if oc["exists"] and oc["otel_present"] and oc["otel_enabled"] is False:
        next_actions.append("Set diagnostics.otel.enabled=true in ~/.openclaw/openclaw.json.")
    if not oc["exists"]:
        next_actions.append("Create ~/.openclaw/openclaw.json and configure diagnostics/OTel settings.")

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
