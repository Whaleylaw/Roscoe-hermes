# Deterministic Verification Matrix

| Lane | Command | Purpose | Pass Criteria |
|---|---|---|---|
| infra_preflight | `./scripts/verification/infra_preflight.sh` | Validate runtime deps/env/ports | Exit 0 and no critical missing deps |
| data_fixture_preflight | `./scripts/verification/data_fixture_preflight.sh` | Validate fixtures/data readiness | Exit 0 and required fixtures present |
| smoke_api | `./scripts/verification/run_smoke_lane.sh api` | API smoke | All API smoke tests pass |
| smoke_ui | `./scripts/verification/run_smoke_lane.sh ui` | UI smoke | All UI smoke tests pass |
| smoke_worker | `./scripts/verification/run_smoke_lane.sh worker` | Worker smoke | Worker smoke passes with no fatal errors |
