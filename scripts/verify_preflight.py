#!/usr/bin/env python3
"""
Roscoe Infra Preflight — checks required runtimes, tools, and ports.
Exit 0 = all pass. Exit 1 = one or more checks failed.
"""
import subprocess
import sys
import shutil
import platform

REQUIRED_COMMANDS = [
    ("python3", "--version"),
    ("node", "--version"),
    ("npm", "--version"),
    ("pnpm", "--version"),
    ("git", "--version"),
    ("docker", "--version"),
]

REQUIRED_PORTS_BLOCKED = []  # No required ports for this project at present

failures = []

print("# Infra Preflight")
print()

# 1. Check required CLI tools
for cmd, flag in REQUIRED_COMMANDS:
    if not shutil.which(cmd):
        print(f"[FAIL] {cmd}: not found in PATH")
        failures.append(f"{cmd} missing")
        continue
    try:
        result = subprocess.run([cmd, flag], capture_output=True, text=True, timeout=10)
        version = (result.stdout or result.stderr).strip().splitlines()[0]
        print(f"[PASS] {cmd}: {version}")
    except Exception as e:
        print(f"[FAIL] {cmd}: {e}")
        failures.append(f"{cmd} error: {e}")

# 2. Check port conflicts (macOS: lsof; Linux: ss or lsof fallback)
print()
print("## Port check")
is_macos = platform.system() == "Darwin"
if is_macos:
    # macOS: use lsof -i -P -n
    try:
        result = subprocess.run(
            ["lsof", "-i", "-P", "-n"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.splitlines() if "LISTEN" in l]
        print(f"[PASS] lsof: {len(lines)} listening ports found (macOS)")
    except Exception as e:
        print(f"[WARN] port check skipped: {e}")
else:
    # Linux: try ss first, fall back to lsof
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"[PASS] ss: port list retrieved")
        else:
            raise RuntimeError("ss returned non-zero")
    except Exception:
        try:
            result = subprocess.run(["lsof", "-i", "-P", "-n"], capture_output=True, text=True, timeout=10)
            lines = [l for l in result.stdout.splitlines() if "LISTEN" in l]
            print(f"[PASS] lsof fallback: {len(lines)} listening ports found")
        except Exception as e:
            print(f"[WARN] port check skipped: {e}")

print()
if failures:
    print(f"RESULT: FAIL — {len(failures)} blocker(s): {', '.join(failures)}")
    sys.exit(1)
else:
    print("RESULT: PASS — all infra checks passed")
    sys.exit(0)
