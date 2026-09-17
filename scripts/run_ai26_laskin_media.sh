#!/usr/bin/env bash
# AI26 media/file worker on Laskin (cron-safe, one bounded batch per call).
#
# Downloads media referenced by canonical records, stores deterministic
# objects under the shared CSC Allas / S3 prefix, persists checksums and
# refreshes the affected canonical MongoDB records. Bounded and idempotent;
# cron owns the schedule and flock prevents overlap.
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/.env"}
STUDY_CONFIG=${LACLAUGPT_AI26_STUDY_CONFIG:-"$ROOT_DIR/data/config/ai26.yaml"}
DATA_ROOT=${LACLAUGPT_AI26_DATA_ROOT:-"$ROOT_DIR/data"}
LOCK_FILE=${LACLAUGPT_AI26_MEDIA_LOCK:-"$ROOT_DIR/data/tmp/ai26-laskin-media.lock"}

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }

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

RUNNER="$ROOT_DIR/.venv/bin/laclaugpt-distributed-media"
if [[ -x "$RUNNER" ]]; then
  RUN=("$RUNNER")
else
  RUN=(python3 -m laclaugpt_data_collection.distributed_media_runner)
fi

echo "[$(date -Is)] AI26 Laskin media start"
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_AI26_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_AI26_MEDIA_LIMIT:-100}"
echo "[$(date -Is)] AI26 Laskin media end"
