#!/usr/bin/env bash
# AI26 non-browser collection on Laskin (cron-safe, one bounded cycle per call).
#
# One bounded Phase 1 cycle, no Firefox/browser/X collector, shared AI26
# MongoDB/Redis/S3 namespace, and flock overlap protection.
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/.env"}
STUDY_CONFIG=${LACLAUGPT_AI26_STUDY_CONFIG:-"$ROOT_DIR/data/config/ai26.yaml"}
SOURCE_MANIFEST=${LACLAUGPT_AI26_SOURCE_MANIFEST:-"$ROOT_DIR/data/config/ai26.sources.toml"}
LOCK_FILE=${LACLAUGPT_AI26_COLLECT_LOCK:-"$ROOT_DIR/data/tmp/ai26-laskin-collect.lock"}

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${LACLAUGPT_BROWSER:-none}" != "none" ]]; then
  echo "refusing Laskin collection with LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER}; browser collection is localhost-only" >&2
  exit 2
fi
if [[ "${LACLAUGPT_PROJECT_ID:-ai26}" != "ai26" ]]; then
  echo "refusing Laskin AI26 worker with project id ${LACLAUGPT_PROJECT_ID:-unset}" >&2
  exit 2
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 Laskin collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  RUN=("$ROOT_DIR/.venv/bin/python" -m laclaugpt_data_collection.ai26_laskin_runner)
else
  RUN=(python3 -m laclaugpt_data_collection.ai26_laskin_runner)
fi

echo "[$(date -Is)] AI26 Laskin collection start"
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id "ai26" \
  --worker-id "${LACLAUGPT_AI26_WORKER_ID:-laskin-cron}" \
  --max-feeds "${LACLAUGPT_AI26_MAX_FEEDS:-8}" \
  --max-jobs "${LACLAUGPT_AI26_MAX_NON_BROWSER_JOBS:-6}" \
  --per-source-limit "${LACLAUGPT_AI26_PER_SOURCE_LIMIT:-5}" \
  --limit "${LACLAUGPT_AI26_BATCH_LIMIT:-40}"
echo "[$(date -Is)] AI26 Laskin collection end"
