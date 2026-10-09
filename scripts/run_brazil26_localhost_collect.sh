#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
MANIFEST_OVERRIDE=${LACLAUGPT_SOURCE_MANIFEST:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/brazil26-localhost-collect.lock"}
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}

export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }

cd "$ROOT"
set -a; source "$ENV_FILE"; set +a
SOURCE_MANIFEST=${MANIFEST_OVERRIDE:-${LACLAUGPT_SOURCE_MANIFEST:-"$ROOT/data/config/brazil26.sources.toml"}}
export LACLAUGPT_DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing Brazil26 source manifest: $SOURCE_MANIFEST" >&2; exit 2; }
if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 worker refuses LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID}" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

# This wrapper is the zero-infrastructure localhost path. Keep a repo-root .env
# or stale remote profile from silently switching it into the distributed plane.
# Explicit remote mirroring belongs to run_brazil26_localhost_sync.sh.
export LACLAUGPT_RECORD_BACKEND=csv
export LACLAUGPT_OBJECT_BACKEND=filesystem
export LACLAUGPT_CACHE_BACKEND=memory
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=local
export LACLAUGPT_MESSAGING_BACKEND=none
export LACLAUGPT_TASK_QUEUE_BACKEND=direct
export LACLAUGPT_MONGODB_URI=
export LACLAUGPT_REDIS_URL=
export LACLAUGPT_S3_BUCKET=

# laclaugpt-server-rss made --study-config a required argument; the RSS worker
# refuses to run without the private study identity. Resolve it after the
# runtime env is sourced so BRAZIL26_CONFIG from the ignored env file wins.
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$ROOT/data/config/brazil26.yaml"}}}
[[ -f "$STUDY_CONFIG" ]] || { echo "missing Brazil26 study config: $STUDY_CONFIG" >&2; exit 2; }

command -v flock >/dev/null
command -v laclaugpt-server-rss >/dev/null || { echo "laclaugpt-server-rss missing" >&2; exit 2; }
command -v python >/dev/null || { echo "python missing" >&2; exit 2; }

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 collection already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"

# Issue #233: the manifest is the source policy. Refuse a manifest that enables
# anything outside X/Instagram/TikTok before collecting a single row.
python -m laclaugpt_data_collection.source_allowlist \
  --manifest "$SOURCE_MANIFEST" --require-brazil26-only || {
  echo "Brazil26 source policy violation in $SOURCE_MANIFEST" >&2
  exit 3
}

# One scheduler, two canonical passes -- but only for families the manifest
# permits. The RSS pass runs only when the manifest enables the `rss` plugin;
# for the Brazil26 X/IG/TikTok-only policy it does not, so the scheduler is
# skipped rather than run and filtered. The plugin pass consumes only directly
# executable rows; it never expands a YouTube channel homepage into guessed
# video targets.
if python -m laclaugpt_data_collection.source_allowlist \
     --manifest "$SOURCE_MANIFEST" --require-plugin rss; then
  laclaugpt-server-rss \
    --study-config "$STUDY_CONFIG" \
    --source-manifest "$SOURCE_MANIFEST" \
    --collection-id brazil26 \
    --worker-id localhost-rss \
    --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-3}" \
    --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}" \
    --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-30}"
else
  echo "RSS is not an enabled Brazil26 source family; skipping the RSS pass (#233)."
fi

python -m laclaugpt_data_collection.brazil26_localhost_collect \
  --source-manifest "$SOURCE_MANIFEST" \
  --project-id brazil26 \
  --collection-id brazil26 \
  --machine "${LACLAUGPT_MACHINE:-laptop}" \
  --run-id "${LACLAUGPT_RUN_ID:-}"
