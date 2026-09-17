#!/usr/bin/env bash
# Shared cron runtime resolution for the AI26 wrappers.
#
# Why this exists: cron runs with a minimal PATH
# (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin), which contains
# neither this checkout's .venv/bin nor ~/.local/bin. A wrapper that assumes
# `laclaugpt-*` is already on PATH therefore fails under cron while working
# perfectly when a researcher runs it by hand. That failure is silent: cron
# discards the output and the collection simply never happens.
#
# Source this file, then call ai26_prepend_runtime_path. It prepends, in order:
#   1. $ROOT_DIR/.venv/bin   (the documented editable install)
#   2. ~/.local/bin          (pip install --user)
#   3. ~/.local/share/uv/tools/*/bin  (uv tool install)
# and then verifies the required console scripts are actually reachable.
#
# Sourced, never executed. Requires ROOT_DIR (or ROOT) to be set by the caller.

ai26_prepend_runtime_path() {
  # The wrappers name their checkout root either ROOT_DIR or ROOT.
  local root="${ROOT_DIR:-${ROOT:-}}"
  if [[ -z "${root}" ]]; then
    echo "ai26_prepend_runtime_path: caller must set ROOT_DIR or ROOT" >&2
    return 2
  fi
  # Real cron sets HOME, but tolerate an empty environment rather than
  # dying on `set -u` in a minimal test harness.
  local home="${HOME:-}"
  if [[ -z "${home}" ]]; then
    home=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6) || true
    home="${home:-/root}"
    export HOME="${home}"
  fi
  local candidate
  for candidate in \
    "${root}/.venv/bin" \
    "${home}/.local/bin" \
    "${home}"/.local/share/uv/tools/*/bin
  do
    if [[ -d "${candidate}" ]]; then
      PATH="${candidate}:${PATH}"
    fi
  done
  export PATH
  export AI26_REPO_ROOT="${root}"
}

# ai26_require_commands <command> [command...]
# Fail loudly with an actionable message instead of silently exiting 2.
ai26_require_commands() {
  local missing=()
  local cmd
  for cmd in "$@"; do
    command -v "${cmd}" >/dev/null 2>&1 || missing+=("${cmd}")
  done
  if (( ${#missing[@]} > 0 )); then
    {
      echo "AI26 wrapper cannot start: missing from PATH: ${missing[*]}"
      echo "Looked in: ${AI26_REPO_ROOT:-<unset>}/.venv/bin, ${HOME}/.local/bin"
      echo "Install with: python -m venv .venv && .venv/bin/pip install -e '.[distributed,feeds,youtube,documents]'"
    } >&2
    return 2
  fi
}
