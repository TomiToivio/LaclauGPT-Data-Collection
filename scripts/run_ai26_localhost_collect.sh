#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT}/scripts/ai26_runtime.sh"
# shellcheck source=scripts/runtime_config.sh
. "$ROOT/scripts/runtime_config.sh"
# Issue #258: the runtime env, study config and source manifest are untracked
# private configuration. LACLAUGPT_RUNTIME_CONFIG_ROOT repoints where they are
# read from, which is the only supported way a runtime started from a Git
# worktree can use the main checkout's configuration without copying a file.
CONFIG_ROOT=$(laclaugpt_runtime_config_root "$ROOT")
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$CONFIG_ROOT/data/config/ai26-localhost.env"}
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$CONFIG_ROOT/data/config/ai26.sources.toml"}
STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$CONFIG_ROOT/data/config/ai26.yaml"}
LOCK_FILE=${LACLAUGPT_COLLECT_LOCK:-"$ROOT/data/tmp/ai26-localhost-collect.lock"}

# Cron has neither .venv/bin nor ~/.local/bin on PATH.
ai26_prepend_runtime_path

mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { laclaugpt_missing_runtime_config "runtime env" "$ENV_FILE" "$ROOT" docs/AI26_LOCALHOST_COLLECTION.md; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { laclaugpt_missing_runtime_config "private source manifest" "$SOURCE_MANIFEST" "$ROOT" docs/AI26_LOCALHOST_COLLECTION.md; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { laclaugpt_missing_runtime_config "private study config" "$STUDY_CONFIG" "$ROOT" docs/AI26_LOCALHOST_COLLECTION.md; exit 2; }

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
  --study-config "$STUDY_CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id ai26 \
  --worker-id localhost-rss \
  --max-feeds "${LACLAUGPT_RSS_MAX_FEEDS:-30}" \
  --per-feed-limit "${LACLAUGPT_RSS_PER_FEED_LIMIT:-6}" \
  --limit "${LACLAUGPT_RSS_BATCH_LIMIT:-120}"

# #378: queue dispatch is opt-in, exactly like the Laskin runner. Default stays the
# manifest pass so switching the live cron is an operator decision, not a side effect.
DISPATCH_ARGS=()
if [[ "${LACLAUGPT_AI26_DISTRIBUTED_JOBS:-0}" == "1" ]]; then
  DISPATCH_ARGS+=(--dispatch-mongo --worker-id "${LACLAUGPT_WORKER_ID:-localhost-$(hostname -s)}")
  DISPATCH_ARGS+=(--max-jobs "${LACLAUGPT_AI26_MAX_JOBS:-10}")
fi

python -m laclaugpt_data_collection.ai26_localhost_collect \
  --source-manifest "$SOURCE_MANIFEST" \
  --study-config "$STUDY_CONFIG" \
  --project-id ai26 \
  --collection-id ai26 \
  --machine "$LACLAUGPT_MACHINE" \
  --run-id "${LACLAUGPT_RUN_ID:-}" \
  ${DISPATCH_ARGS[@]+"${DISPATCH_ARGS[@]}"}
