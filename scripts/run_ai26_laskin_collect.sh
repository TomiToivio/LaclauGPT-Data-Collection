#!/usr/bin/env bash
# AI26 non-browser collection on Laskin (cron-safe, one bounded cycle per call).
#
# Design constraints (issue #62):
#   - one bounded collection cycle, then exit; cron is the scheduler
#   - never starts a nested long-lived scheduler
#   - secrets are loaded only from the ignored runtime env file
#   - no Firefox / browser / X collector on this host
#   - flock prevents overlapping ticks from stacking
#
# The runtime env file is ignored by Git. Override it with
# LACLAUGPT_ENV_FILE if your private runtime contract lives elsewhere.
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

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 Laskin collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"

# Cron does not inherit an interactive shell, so resolve the console script
# inside this checkout's venv rather than relying on PATH.
RUNNER="$ROOT_DIR/.venv/bin/laclaugpt-server-rss"
if [[ -x "$RUNNER" ]]; then
  RUN=("$RUNNER")
else
  RUN=(python3 -m laclaugpt_data_collection.server_runner)
fi

echo "[$(date -Is)] AI26 Laskin collection start"
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id "${LACLAUGPT_PROJECT_ID:-ai26}" \
  --worker-id "${LACLAUGPT_AI26_WORKER_ID:-laskin-cron}" \
  --max-feeds "${LACLAUGPT_AI26_MAX_FEEDS:-8}" \
  --per-feed-limit "${LACLAUGPT_AI26_PER_FEED_LIMIT:-5}" \
  --limit "${LACLAUGPT_AI26_BATCH_LIMIT:-40}"
echo "[$(date -Is)] AI26 Laskin collection end"
