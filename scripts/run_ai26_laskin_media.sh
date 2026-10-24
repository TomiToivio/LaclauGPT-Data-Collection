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

if [[ "${LACLAUGPT_BROWSER:-none}" != "none" ]]; then
  echo "refusing Laskin media worker with LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER}; browser collection is localhost-only" >&2
  exit 2
fi

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
# Always report a terminal marker, including abnormal exits. The runner returns 1
# whenever any media object failed (distributed_media_runner.main: `return 0 if
# result["failed"] == 0 else 1`), so under `set -e` a cycle that downloaded its
# media normally aborted before the end echo and read as a silently stopped
# stage. Observed on Laskin: the 2026-10-23T00:30 (failed: 1) and 05:30
# (failed: 2) cycles both logged a summary and no end marker. This mirrors the
# collection wrapper (#217): always emit the marker, propagate the status.
cycle_finished=0
emit_end_marker() {
  # $? is captured as the first statement, before any other command can clobber it.
  local status=$?
  if [[ "$cycle_finished" -eq 0 ]]; then
    cycle_finished=1
    trap - EXIT
    if [[ "$status" -eq 0 ]]; then
      echo "[$(date -Is)] AI26 Laskin media end"
    else
      echo "[$(date -Is)] AI26 Laskin media end runner_status=$status (media failures recorded; see status above)"
    fi
  fi
}
trap emit_end_marker EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
set +e
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_AI26_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_AI26_MEDIA_LIMIT:-100}"
runner_status=$?
set -e
exit "$runner_status"
