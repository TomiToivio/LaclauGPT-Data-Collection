#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT_DIR}/scripts/ai26_runtime.sh"
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/data/config/ai26-laskin.env"}
STUDY_CONFIG=${LACLAUGPT_AI26_STUDY_CONFIG:-"$ROOT_DIR/data/config/ai26.yaml"}
DATA_ROOT=${LACLAUGPT_DATA_ROOT:-"$ROOT_DIR/data"}
LOCK_FILE=${LACLAUGPT_AI26_MEDIA_LOCK:-"$ROOT_DIR/data/tmp/ai26-laskin-media.lock"}

# Cron has neither .venv/bin nor ~/.local/bin on PATH.
ai26_prepend_runtime_path

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }

ai26_require_commands flock laclaugpt-distributed-media || exit 2

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 Laskin media worker already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"
echo "[$(date -Is)] AI26 Laskin media start"
laclaugpt-distributed-media \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_AI26_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_AI26_MEDIA_LIMIT:-100}"
echo "[$(date -Is)] AI26 Laskin media end"
