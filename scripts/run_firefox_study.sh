#!/usr/bin/env bash
set -euo pipefail

STUDY_CONFIG=${1:?usage: run_firefox_study.sh STUDY_CONFIG DATA_ROOT [PORT]}
DATA_ROOT=${2:?usage: run_firefox_study.sh STUDY_CONFIG DATA_ROOT [PORT]}
PORT=${3:-${LACLAUGPT_CAPTURE_PORT:-8765}}

[[ -f "$STUDY_CONFIG" ]] || { echo "study config not found: $STUDY_CONFIG" >&2; exit 2; }
mkdir -p "$DATA_ROOT"

command -v laclaugpt-capture >/dev/null 2>&1 || {
  echo "laclaugpt-capture is not installed; install this package first" >&2
  exit 2
}

# Deliberately fixed to loopback. For a browser on another machine, expose this
# through an authenticated SSH tunnel or equivalent private transport rather
# than binding the research capture service to a public interface.
exec laclaugpt-capture \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --host 127.0.0.1 \
  --port "$PORT"
