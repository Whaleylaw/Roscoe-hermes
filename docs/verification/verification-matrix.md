# Roscoe Verification Matrix

Generated: 2026-04-18T02:38:36.427647Z
Task: Test Scope: Conversion verification matrix and acceptance gates

| Lane | Intent | Command | Pass Criteria |
|---|---|---|---|
| infra-preflight | runtime/dependency readiness | `python --version && node --version` | required runtimes present |
| fixtures-preflight | fixture/data readiness | `python -m pytest -q -k fixture --maxfail=1` | no critical fixture gaps |
| smoke-core | baseline smoke | `python -m pytest -q -k smoke --maxfail=1` | all smoke tests pass |
| readout | summarize go/no-go | n/a | deterministic report generated |

Deterministic policy: one-task-per-run, no external side effects without owner approval.
