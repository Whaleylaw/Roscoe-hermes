# Hermes Agent v0.8.1-session-funnel-observability

Release date: 2026-04-15

## Summary
This patch finalizes the Unified Session Funnel tranche and adds explicit observability readiness reporting for Langfuse + OpenTelemetry.

## Included in this patch

1) Session Funnel finalization
- Gateway routing now consistently resolves through `resolve_session_key(...)`.
- `single-agent-main` funnel strategy remains feature-flagged via `gateway.session_funnel.enabled`.
- Regression coverage expanded for cross-channel/session-key convergence and origin metadata retention.

2) Observability startup self-check
- Gateway startup now logs a deterministic Langfuse state line:
  - enabled/disabled
  - reason when disabled
  - OTEL readiness + missing OTEL env vars
- File: `gateway/run.py`
- Readiness source: `agent/langfuse_tracing.py:get_langfuse_readiness()`

3) Verification script (Hermes + OpenClaw)
- New script: `scripts/verify_observability_readiness.py`
- Reports JSON status for:
  - Hermes Langfuse env readiness
  - Hermes OTEL env readiness
  - OpenClaw `~/.openclaw/openclaw.json` diagnostics/otel presence
- Never outputs secret values.

## Validation commands

Run tests:
- `python3.11 -m pytest -o addopts='' tests/test_langfuse_tracing.py tests/gateway/test_session.py tests/gateway/test_session_model_reset.py tests/gateway/test_resume_command.py -q`

Run readiness verifier:
- `python3 scripts/verify_observability_readiness.py`

## Rollout checklist

- [ ] Set Langfuse credentials in runtime env:
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - optional: `LANGFUSE_BASE_URL`
- [ ] Set OTEL env vars for collector target:
  - `OTEL_EXPORTER_OTLP_ENDPOINT`
  - `OTEL_EXPORTER_OTLP_HEADERS`
  - `OTEL_EXPORTER_OTLP_PROTOCOL`
  - `OTEL_SERVICE_NAME`
- [ ] (Optional but recommended) ensure OpenClaw has `diagnostics.otel.enabled=true` or equivalent env-driven OTEL wiring.
- [ ] Restart gateway and confirm startup logs show observability status line.
