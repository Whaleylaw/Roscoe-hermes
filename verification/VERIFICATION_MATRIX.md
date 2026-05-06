# Roscoe Verification Matrix

Updated: 2026-04-18 03:55:53 UTC

## Scope
Deterministic conversion verification for Roscoe Platform (project RSC), covering:
- UI sanity (`tests/sanity`)
- Workspace UI sanity (`ws-tests/sanity`)
- API smoke (`ws-tests/api-tests`)

## Execution Order
1. Infra preflight
2. Data/fixture preflight
3. Smoke Lane 1 (UI)
4. Smoke Lane 2 (workspace UI)
5. Smoke Lane 3 (API)
6. Failure triage
7. Fix batches
8. Full matrix re-run
9. Verification readout

## Deterministic Lane Matrix
| Lane | Command | Pass/Fail Threshold | Artifacts | Owner |
|---|---|---|---|---|
| infra_preflight | `python scripts/verify_preflight.py` | Pass: exit code 0 and all required services/dependencies healthy. Fail: any missing dependency, unhealthy service, or required port conflict. | `verification/artifacts/infra_preflight.log` | Hermes |
| data_fixture_preflight | `python scripts/verify_data_fixtures.py` | Pass: exit code 0 and all required fixtures/datasets present and readable. Fail: missing/corrupt fixture, schema mismatch, or unreadable test dataset. | `verification/artifacts/data_fixture_preflight.log` | Hermes |
| smoke_lane_ui | `cd tests/sanity && pnpm test` | Pass: exit code 0 with no failing tests. Fail: any test failure or runner crash. | `verification/artifacts/smoke_lane_ui.log` | Hermes |
| smoke_lane_workspace | `cd ws-tests/sanity && pnpm test` | Pass: exit code 0 with no failing tests. Fail: any test failure or runner crash. | `verification/artifacts/smoke_lane_workspace.log` | Hermes |
| smoke_lane_api | `cd ws-tests/api-tests && pnpm test` | Pass: exit code 0 with no failing tests. Fail: any test failure, timeout, or runner crash. | `verification/artifacts/smoke_lane_api.log` | Hermes |
| full_smoke_matrix | `./scripts/run_full_smoke_matrix.sh` | Pass: all three smoke lanes pass in one run. Fail: any lane fail or infra/data precondition failure. | `verification/artifacts/full_smoke_matrix.log` and per-lane logs | Hermes |

## Acceptance Gates
A verification wave is **go** only if all are true:
1. Infra preflight passed.
2. Data/fixture preflight passed.
3. UI, workspace UI, and API smoke lanes passed.
4. Any discovered failures were triaged and either fixed or explicitly documented with owner decision required.
5. Full smoke matrix re-run passed after fixes.
6. Verification readout generated with clear go/no-go recommendation.

## Sign-off Criteria
- **Go**: all acceptance gates pass; no unresolved critical/high regression in scope.
- **No-go**: any acceptance gate fails, or unresolved critical/high issue remains.
- **Owner decision required**: if residual risk is business/legal/customer-impacting, set task to `awaiting_owner` with concise decision request.

## Worker Guardrails
- Process exactly one Mission Control task per cron run.
- Preserve task fields on every PUT update.
- Record concise evidence in `resolution`, `error_message`, and `outcome`.
- Do not execute external/client-facing actions; escalate via `awaiting_owner`.
