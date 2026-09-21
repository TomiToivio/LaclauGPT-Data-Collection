#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT}/scripts/ai26_runtime.sh"
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/ai26-localhost.env"}
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$ROOT/data/config/ai26.sources.toml"}
STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$ROOT/data/config/ai26.yaml"}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/ai26-localhost-collect.lock"}

# Cron has neither .venv/bin nor ~/.local/bin on PATH.
ai26_prepend_runtime_path

mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing private source manifest: $SOURCE_MANIFEST" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing private study config: $STUDY_CONFIG" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-ai26}
export LACLAUGPT_PROFILE=${LACLAUGPT_PROFILE:-ai26-localhost-remote}
export LACLAUGPT_MACHINE=${LACLAUGPT_MACHINE:-laptop}
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER:-firefox-local}
export LACLAUGPT_CALLER=cron

command -v flock >/dev/null 2>&1 || { echo "flock is required for cron locking" >&2; exit 2; }
ai26_require_commands laclaugpt-server-rss python || exit 2

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT"

# One scheduler, two canonical passes:
# 1) the mature RSS worker;
# 2) Phase 1 plugins that can be executed safely from the same manifest.
# Both use collection_id=ai26 and the configured canonical record backend.
laclaugpt-server-rss \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id ai26 \
  --worker-id localhost-rss \
  --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-30}" \
  --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}" \
  --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-120}"

python -m laclaugpt_data_collection.ai26_localhost_collect \
  --source-manifest "$SOURCE_MANIFEST" \
  --study-config "$STUDY_CONFIG" \
  --project-id ai26 \
  --collection-id ai26 \
  --machine "$LACLAUGPT_MACHINE" \
  --run-id "${LACLAUGPT_RUN_ID:-}"
