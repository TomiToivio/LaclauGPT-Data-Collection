#!/usr/bin/env bash
# Brazil26 non-browser collection on Laskin (cron-safe, one bounded cycle).
#
# Browser-assisted X/Instagram/TikTok collection is localhost-only. This
# wrapper runs canonical Phase 1 non-browser collectors against the shared
# Brazil26 MongoDB/Redis/S3 namespace and exits after one bounded tick.
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/.env"}
STUDY_CONFIG=${LACLAUGPT_BRAZIL26_STUDY_CONFIG:-"$ROOT_DIR/data/config/brazil26.yaml"}
SOURCE_MANIFEST=${LACLAUGPT_BRAZIL26_SOURCE_MANIFEST:-"$ROOT_DIR/data/config/brazil26.sources.toml"}
LOCK_FILE=${LACLAUGPT_BRAZIL26_COLLECT_LOCK:-"$ROOT_DIR/data/tmp/brazil26-laskin-collect.lock"}

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 Laskin worker refuses LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID}" >&2
  exit 2
fi
if [[ "${LACLAUGPT_BROWSER:-none}" != "none" ]]; then
  echo "refusing Brazil26 Laskin collection with LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER}; browser collection is localhost-only" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=laskin-cron

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Brazil26 Laskin collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"

RUNNER="$ROOT_DIR/.venv/bin/laclaugpt-server-rss"
if [[ -x "$RUNNER" ]]; then
  RUN=("$RUNNER")
else
  RUN=(python3 -m laclaugpt_data_collection.server_runner)
fi

echo "[$(date -Is)] Brazil26 Laskin collection start"
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id brazil26 \
  --worker-id "${LACLAUGPT_BRAZIL26_WORKER_ID:-brazil26-laskin-cron}" \
  --max-feeds "${LACLAUGPT_BRAZIL26_MAX_FEEDS:-3}" \
  --per-feed-limit "${LACLAUGPT_BRAZIL26_PER_FEED_LIMIT:-6}" \
  --limit "${LACLAUGPT_BRAZIL26_BATCH_LIMIT:-30}"
echo "[$(date -Is)] Brazil26 Laskin collection end"
