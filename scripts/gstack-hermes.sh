#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_GSTACK_DIR="/Users/aaronwhaley/Github/gstack-main"
GSTACK_DIR="${GSTACK_DIR:-$DEFAULT_GSTACK_DIR}"
HERMES_SKILLS_DIR="${HOME}/.hermes/skills"

usage() {
  cat <<'EOF'
Usage: scripts/gstack-hermes.sh <install|verify|uninstall> [--gstack-dir PATH]

Commands:
  install     Generate Hermes skills in gstack and install/link them into ~/.hermes/skills
  verify      Check generated files, installed skills, and runtime symlinks
  uninstall   Remove gstack Hermes skills via gstack-uninstall --force --keep-state
EOF
}

log() {
  printf '%s\n' "$1"
}

pass() {
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  exit 1
}

resolve_bun() {
  if command -v bun >/dev/null 2>&1; then
    command -v bun
    return
  fi
  if [ -x "${HOME}/.bun/bin/bun" ]; then
    printf '%s\n' "${HOME}/.bun/bin/bun"
    return
  fi
  fail "bun not found; install Bun or add ~/.bun/bin to PATH"
}

resolve_hermes() {
  if command -v hermes >/dev/null 2>&1; then
    command -v hermes
    return
  fi
  if [ -x "${HERMES_REPO_ROOT}/.venv/bin/hermes" ]; then
    printf '%s\n' "${HERMES_REPO_ROOT}/.venv/bin/hermes"
    return
  fi
  if [ -x "${HERMES_REPO_ROOT}/hermes" ]; then
    printf '%s\n' "${HERMES_REPO_ROOT}/hermes"
    return
  fi
  fail "hermes not found; activate the Hermes environment or use the repo-local .venv"
}

ensure_paths() {
  [ -d "$GSTACK_DIR" ] || fail "gstack directory not found: $GSTACK_DIR"
  [ -x "$GSTACK_DIR/setup" ] || fail "gstack setup script not found: $GSTACK_DIR/setup"
  [ -x "$GSTACK_DIR/bin/gstack-uninstall" ] || fail "gstack uninstall script not found: $GSTACK_DIR/bin/gstack-uninstall"
}

check_generated_skill() {
  local skill="$1"
  [ -f "$GSTACK_DIR/.hermes/skills/${skill}/SKILL.md" ] || fail "generated skill missing: $GSTACK_DIR/.hermes/skills/${skill}/SKILL.md"
  pass "generated ${skill}"
}

check_installed_skill() {
  local skill="$1"
  [ -e "$HERMES_SKILLS_DIR/${skill}" ] || fail "installed skill missing: $HERMES_SKILLS_DIR/${skill}"
  [ -f "$HERMES_SKILLS_DIR/${skill}/SKILL.md" ] || fail "installed skill lacks SKILL.md: $HERMES_SKILLS_DIR/${skill}"
  pass "installed ${skill}"
}

check_runtime_link() {
  local relative_path="$1"
  [ -L "$HERMES_SKILLS_DIR/gstack/${relative_path}" ] || fail "runtime symlink missing: $HERMES_SKILLS_DIR/gstack/${relative_path}"
  [ -e "$HERMES_SKILLS_DIR/gstack/${relative_path}" ] || fail "runtime symlink broken: $HERMES_SKILLS_DIR/gstack/${relative_path}"
  pass "runtime ${relative_path}"
}

run_install() {
  local bun_bin hermes_bin
  ensure_paths
  bun_bin="$(resolve_bun)"
  hermes_bin="$(resolve_hermes)"

  log "Using bun: ${bun_bin}"
  log "Using hermes: ${hermes_bin}"

  (
    cd "$GSTACK_DIR"
    "$bun_bin" run gen:skill-docs --host hermes
    "$GSTACK_DIR/setup" --host hermes --quiet
  )
  pass "gstack Hermes install completed"
}

run_verify() {
  ensure_paths
  resolve_bun >/dev/null
  resolve_hermes >/dev/null

  check_generated_skill "gstack-browse"
  check_generated_skill "gstack-review"
  check_generated_skill "gstack-qa-only"

  check_installed_skill "gstack-browse"
  check_installed_skill "gstack-review"
  check_installed_skill "gstack-qa-only"

  [ -d "$HERMES_SKILLS_DIR/gstack" ] || fail "runtime root missing: $HERMES_SKILLS_DIR/gstack"
  pass "runtime root gstack"
  check_runtime_link "bin"
  check_runtime_link "browse/dist"
  check_runtime_link "browse/bin"

  if [ ! -d "$GSTACK_DIR/.git" ]; then
    log "INFO non-git checkout detected at $GSTACK_DIR; version stamping relies on gstack's non-fatal git fallback"
  fi

  pass "gstack Hermes verify completed"
}

run_uninstall() {
  ensure_paths
  (
    cd "$GSTACK_DIR"
    "$GSTACK_DIR/bin/gstack-uninstall" --force --keep-state
  )

  if find "$HERMES_SKILLS_DIR" -maxdepth 1 -name 'gstack*' | grep -q .; then
    fail "gstack entries still present under $HERMES_SKILLS_DIR after uninstall"
  fi
  pass "gstack Hermes uninstall completed"
}

COMMAND="${1:-}"
shift || true

while [ $# -gt 0 ]; do
  case "$1" in
    --gstack-dir)
      [ $# -ge 2 ] || fail "missing value for --gstack-dir"
      GSTACK_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

case "$COMMAND" in
  install)
    run_install
    ;;
  verify)
    run_verify
    ;;
  uninstall)
    run_uninstall
    ;;
  ""|-h|--help)
    usage
    ;;
  *)
    fail "unknown command: $COMMAND"
    ;;
esac
