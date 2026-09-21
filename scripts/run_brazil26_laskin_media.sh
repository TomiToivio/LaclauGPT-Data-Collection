#!/usr/bin/env bash
# Brazil26 shared-plane media/file worker on Laskin (one bounded batch).
#
# Pending references are discovered from canonical Brazil26 MongoDB state, so
# objects captured by localhost browser collection can be processed on Laskin.
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/.env"}
STUDY_CONFIG=${LACLAUGPT_BRAZIL26_STUDY_CONFIG:-"$ROOT_DIR/data/config/brazil26.yaml"}
DATA_ROOT=${LACLAUGPT_BRAZIL26_DATA_ROOT:-"$ROOT_DIR/data"}
LOCK_FILE=${LACLAUGPT_BRAZIL26_MEDIA_LOCK:-"$ROOT_DIR/data/tmp/brazil26-laskin-media.lock"}

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 Laskin media worker refuses LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID}" >&2
  exit 2
fi
if [[ "${LACLAUGPT_BROWSER:-none}" != "none" ]]; then
  echo "refusing Brazil26 Laskin media worker with LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER}; browser collection is localhost-only" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=laskin-cron

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Brazil26 Laskin media worker already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"

RUNNER="$ROOT_DIR/.venv/bin/laclaugpt-distributed-media"
if [[ -x "$RUNNER" ]]; then
  RUN=("$RUNNER")
else
  RUN=(python3 -m laclaugpt_data_collection.distributed_media_runner)
fi

echo "[$(date -Is)] Brazil26 Laskin media start"
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_BRAZIL26_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_BRAZIL26_MEDIA_LIMIT:-50}"
echo "[$(date -Is)] Brazil26 Laskin media end"
