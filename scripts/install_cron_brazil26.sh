#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BEGIN="# BEGIN LACLAUGPT BRAZIL26"
END="# END LACLAUGPT BRAZIL26"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$PRIVATE_ROOT/collection/brazil26/brazil-election-2026.yaml"}}}
DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}

[[ -f "$STUDY_CONFIG" ]] || {
  echo "missing Brazil26 private study config: $STUDY_CONFIG" >&2
  exit 2
}
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"

(crontab -l 2>/dev/null || true) | awk -v b="$BEGIN" -v e="$END" '
$0==b {skip=1; next} $0==e {skip=0; next} !skip {print}
' > "$TMP"

printf -v ROOT_Q '%q' "$ROOT"
printf -v ENV_Q '%q' "$ENV_FILE"
printf -v STUDY_Q '%q' "$STUDY_CONFIG"
printf -v DATA_Q '%q' "$DATA_ROOT"
cat >> "$TMP" <<EOF
$BEGIN
12 * * * * cd $ROOT_Q && /bin/bash scripts/run_brazil26_localhost_sync.sh >> data/logs/brazil26-sync.log 2>&1
22 * * * * cd $ROOT_Q && /bin/bash scripts/run_brazil26_localhost_collect.sh >> data/logs/brazil26-collect.log 2>&1
*/15 * * * * cd $ROOT_Q && LACLAUGPT_ENV_FILE=$ENV_Q LACLAUGPT_STUDY_CONFIG=$STUDY_Q LACLAUGPT_DATA_ROOT=$DATA_Q /bin/bash scripts/run_brazil26_localhost_media.sh >> data/logs/brazil26-media.log 2>&1
$END
EOF
crontab "$TMP"
echo "Installed/updated idempotent Brazil26 cron block."
echo "Media log: $ROOT/data/logs/brazil26-media.log"
