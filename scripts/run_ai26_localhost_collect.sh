#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT}/scripts/ai26_runtime.sh"
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/ai26-localhost.env"}
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$ROOT/data/config/ai26.sources.toml"}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/ai26-localhost-collect.lock"}

# Cron has neither .venv/bin nor ~/.local/bin on PATH.
ai26_prepend_runtime_path

mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing private source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

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
ai26_require_commands laclaugpt-server-rss || exit 2

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT"
exec laclaugpt-server-rss \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id ai26 \
  --worker-id localhost-rss \
  --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-30}" \
  --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}" \
  --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-120}"
