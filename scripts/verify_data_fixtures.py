#!/usr/bin/env python3
"""
Roscoe Data/Fixture Preflight — checks required fixtures and datasets.
Exit 0 = all present and readable. Exit 1 = gaps found.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Canonical fixture paths to check
FIXTURE_PATHS = [
    "tests/fixtures",
    "fixtures",
    "data",
    "test-data",
]

# Required individual fixture files (add as known)
REQUIRED_FILES = []

print("# Data/Fixture Preflight")
print(f"Repo root: {REPO_ROOT}")
print()

gaps = []
found = []

for path in FIXTURE_PATHS:
    full = REPO_ROOT / path
    if full.exists():
        contents = list(full.iterdir()) if full.is_dir() else []
        print(f"[PASS] {path}: exists ({len(contents)} items)")
        found.append(str(path))
    else:
        print(f"[INFO] {path}: absent (not required for current scope)")

for req_file in REQUIRED_FILES:
    full = REPO_ROOT / req_file
    if full.exists():
        try:
            full.read_text()
            print(f"[PASS] {req_file}: readable")
        except Exception as e:
            print(f"[FAIL] {req_file}: unreadable — {e}")
            gaps.append(f"{req_file} unreadable: {e}")
    else:
        print(f"[FAIL] {req_file}: MISSING")
        gaps.append(f"{req_file} missing")

# Note: No required fixtures in Roscoe-hermes (Python agent) — fixture dirs are optional.
# Core test suite uses inline fixtures via conftest.py.
print()
print("## Conftest check")
conftest = REPO_ROOT / "tests" / "conftest.py"
if conftest.exists():
    print(f"[PASS] tests/conftest.py: exists")
else:
    print(f"[FAIL] tests/conftest.py: MISSING")
    gaps.append("tests/conftest.py missing")

print()
if gaps:
    print(f"RESULT: FAIL — {len(gaps)} gap(s): {', '.join(gaps)}")
    sys.exit(1)
else:
    if found:
        print(f"RESULT: PASS — fixture dirs present: {', '.join(found)}; conftest healthy")
    else:
        print("RESULT: PASS — no required fixture dirs (inline conftest pattern in use); conftest healthy")
    sys.exit(0)
