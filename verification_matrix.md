# Deterministic Verification Matrix

| Area | Check | Status | Evidence |
|---|---|---|---|
| Infra | Service health endpoints reachable | pending | Run Infra Preflight |
| Dependencies | Required runtimes/tools available | pending | Run Infra Preflight |
| Data/Fixtures | Required fixtures present and readable | pending | Run Data/Fixture Preflight |
| Smoke Lane | Core smoke command exits 0 | pending | Run Smoke Lane |
| Full Matrix | All smoke lanes pass | pending | Run re-run full smoke matrix |
| Readout | Go/No-Go generated | pending | Run Verification Readout |
