# Roscoe Verification Matrix

Generated: 2026-04-17T23:37:45.609030Z

| Lane | Purpose | Command | Expected |
|---|---|---|---|
| infra-preflight | Validate runtime prerequisites | python3 --version; node --version; npm --version | pass |
| data-fixture-preflight | Validate fixture/data availability | filesystem checks | required assets present |
| smoke-lane | Run lane from task command | task-defined command | pass |
