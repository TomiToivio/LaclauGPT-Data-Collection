#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/ai26-localhost.env"}
STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$ROOT/data/config/ai26.yaml"}
DATA_ROOT=${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}
LOCK_FILE=${LACLAUGPT_MEDIA_LOCK:-"$ROOT/data/tmp/ai26-localhost-media.lock"}

mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing private study config: $STUDY_CONFIG" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Cron starts with a minimal PATH. Prefer the repository virtualenv and the
# user's local bin directory before falling back to the inherited PATH.
export PATH="$ROOT/.venv/bin:${HOME:-}/.local/bin:${PATH:-/usr/bin:/bin}"

export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-ai26}
export LACLAUGPT_PROFILE=${LACLAUGPT_PROFILE:-ai26-localhost-remote}
export LACLAUGPT_MACHINE=${LACLAUGPT_MACHINE:-laptop}
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER:-firefox-local}
export LACLAUGPT_CALLER=cron

command -v flock >/dev/null 2>&1 || { echo "flock is required for cron locking" >&2; exit 2; }
command -v laclaugpt-distributed-media >/dev/null 2>&1 || { echo "laclaugpt-distributed-media is not installed; install the repository virtualenv first" >&2; exit 2; }

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 media worker already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT"
exec laclaugpt-distributed-media \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_MEDIA_BATCH_LIMIT:-50}"
