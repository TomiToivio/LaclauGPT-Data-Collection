#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$ROOT/data/config/brazil26.sources.toml"}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/brazil26-localhost-collect.lock"}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing Brazil26 source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

set -a; source "$ENV_FILE"; set +a
if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 worker refuses LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID}" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

command -v flock >/dev/null
command -v laclaugpt-server-rss >/dev/null || { echo "laclaugpt-server-rss missing" >&2; exit 2; }
command -v python >/dev/null || { echo "python missing" >&2; exit 2; }

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 collection already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"

# One scheduler, two canonical passes. RSS handles directly configured feeds.
# The plugin pass consumes only directly executable rows. It never expands a
# YouTube channel homepage into guessed video targets.
laclaugpt-server-rss \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id brazil26 \
  --worker-id localhost-rss \
  --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-3}" \
  --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}" \
  --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-30}"

python -m laclaugpt_data_collection.brazil26_localhost_collect \
  --source-manifest "$SOURCE_MANIFEST" \
  --project-id brazil26 \
  --collection-id brazil26 \
  --machine "${LACLAUGPT_MACHINE:-laptop}" \
  --run-id "${LACLAUGPT_RUN_ID:-}"
