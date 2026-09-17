#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT_DIR}/scripts/ai26_runtime.sh"
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/data/config/ai26-laskin.env"}
SOURCE_MANIFEST=${LACLAUGPT_AI26_SOURCE_MANIFEST:-"$ROOT_DIR/data/config/ai26.sources.toml"}
LOCK_FILE=${LACLAUGPT_AI26_COLLECT_LOCK:-"$ROOT_DIR/data/tmp/ai26-laskin-collect.lock"}

# Cron has neither .venv/bin nor ~/.local/bin on PATH. Fix that before the
# availability checks below, or every scheduled run exits 2 without collecting.
ai26_prepend_runtime_path

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

ai26_require_commands flock laclaugpt-server-rss || exit 2

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 Laskin collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"
echo "[$(date -Is)] AI26 Laskin collection start"
laclaugpt-server-rss \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id ai26 \
  --worker-id laskin-rss \
  --max-feeds "${LACLAUGPT_AI26_MAX_FEEDS:-30}" \
  --per-feed-limit "${LACLAUGPT_AI26_PER_FEED_LIMIT:-10}" \
  --limit "${LACLAUGPT_AI26_BATCH_LIMIT:-180}"
echo "[$(date -Is)] AI26 Laskin collection end"
