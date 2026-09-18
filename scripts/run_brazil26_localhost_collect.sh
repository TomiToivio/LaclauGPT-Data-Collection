#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$ROOT/data/config/brazil26.sources.toml"}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/brazil26-localhost-collect.lock"}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing private source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

set -a; source "$ENV_FILE"; set +a
export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-brazil26}
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

command -v flock >/dev/null
command -v laclaugpt-server-rss >/dev/null || { echo "laclaugpt-server-rss missing" >&2; exit 2; }

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 collection already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"
exec laclaugpt-server-rss   --source-manifest "$SOURCE_MANIFEST"   --collection-id brazil26   --worker-id localhost-rss   --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-30}"   --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}"   --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-120}"
