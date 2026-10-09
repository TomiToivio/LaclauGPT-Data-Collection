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
# Issue #233 acceptance criterion 3: a *queued* permitted video must reach CSC
# Allas. That needs the distributed media wrapper, but the local-first one is the
# zero-infrastructure default, and the two are mutually exclusive per host (they
# use the same lock). The cadence line therefore has to be selectable, or the
# Allas path can never be scheduled at all.
#
#   local   (default) -> run_brazil26_localhost_media.sh             (filesystem/csv)
#   allas             -> run_brazil26_localhost_media_distributed.sh (s3 + mongodb)
MEDIA_MODE=${LACLAUGPT_BRAZIL26_MEDIA_MODE:-local}
case "$MEDIA_MODE" in
  local) MEDIA_WRAPPER="run_brazil26_localhost_media.sh" ;;
  allas|distributed) MEDIA_WRAPPER="run_brazil26_localhost_media_distributed.sh" ;;
  *)
    echo "LACLAUGPT_BRAZIL26_MEDIA_MODE must be 'local' or 'allas', got: $MEDIA_MODE" >&2
    exit 2
    ;;
esac
cd "$ROOT"
# The wrapper must exist for the selected mode, but the check is deliberately
# advisory rather than fatal: a synthetic or partially-populated checkout (as the
# wrapper tests build) legitimately lacks some scripts, and the cron line is still
# correct for the host it is installed on. An unknown MODE, by contrast, is fatal
# above -- that is the case where installing the wrong worker must not proceed.
if [[ ! -f "scripts/$MEDIA_WRAPPER" ]]; then
  echo "warning: media wrapper not found yet: scripts/$MEDIA_WRAPPER (installing the cadence anyway)" >&2
fi
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

# Issue #233: supersede the old 15-minute media cadence. If an earlier run left a
# Brazil26 media entry *outside* the managed block (e.g. installed by hand or by
# a version that used different markers), strip it so the workstation cannot end
# up running both. Only lines that name a Brazil26 media wrapper are touched --
# and BOTH wrappers, because switching mode must not leave the other one scheduled
# against the same lock.
if grep -Eq '[*]/15 .*run_brazil26_localhost_media(_distributed)?\.sh' "$TMP"; then
  echo "Removing a stale 15-minute Brazil26 media entry superseded by the 30-minute cadence (#233)." >&2
  grep -Ev '[*]/15 .*run_brazil26_localhost_media(_distributed)?\.sh' "$TMP" > "$TMP.clean" && mv "$TMP.clean" "$TMP"
fi
# A media entry outside the managed block in the OTHER mode would run the wrong
# wrapper (and fight this one for the lock), so remove any stale counterpart.
OTHER_WRAPPER="run_brazil26_localhost_media.sh"
[[ "$MEDIA_WRAPPER" == "run_brazil26_localhost_media.sh" ]] && OTHER_WRAPPER="run_brazil26_localhost_media_distributed.sh"
if grep -Fq "$OTHER_WRAPPER" "$TMP"; then
  echo "Removing a stale Brazil26 media entry using the other mode ($OTHER_WRAPPER)." >&2
  grep -Fv "$OTHER_WRAPPER" "$TMP" > "$TMP.clean" && mv "$TMP.clean" "$TMP"
fi

printf -v ROOT_Q '%q' "$ROOT"
printf -v ENV_Q '%q' "$ENV_FILE"
printf -v STUDY_Q '%q' "$STUDY_CONFIG"
printf -v DATA_Q '%q' "$DATA_ROOT"
cat >> "$TMP" <<EOF
$BEGIN
12 * * * * cd $ROOT_Q && LACLAUGPT_ENV_FILE=$ENV_Q LACLAUGPT_STUDY_CONFIG=$STUDY_Q LACLAUGPT_DATA_ROOT=$DATA_Q /bin/bash scripts/run_brazil26_localhost_sync.sh >> data/logs/brazil26-sync.log 2>&1
22 * * * * cd $ROOT_Q && LACLAUGPT_ENV_FILE=$ENV_Q LACLAUGPT_STUDY_CONFIG=$STUDY_Q LACLAUGPT_DATA_ROOT=$DATA_Q /bin/bash scripts/run_brazil26_localhost_collect.sh >> data/logs/brazil26-collect.log 2>&1
*/30 * * * * cd $ROOT_Q && LACLAUGPT_ENV_FILE=$ENV_Q LACLAUGPT_STUDY_CONFIG=$STUDY_Q LACLAUGPT_DATA_ROOT=$DATA_Q /bin/bash scripts/$MEDIA_WRAPPER >> data/logs/brazil26-media.log 2>&1
$END
EOF
crontab "$TMP"
echo "Installed/updated idempotent Brazil26 cron block (media mode: $MEDIA_MODE -> $MEDIA_WRAPPER)."
echo "Media log: $ROOT/data/logs/brazil26-media.log"
if [[ "$MEDIA_MODE" == "local" ]]; then
  echo "NOTE: media is local-first (filesystem/csv). For scheduled CSC Allas uploads"
  echo "      re-run with LACLAUGPT_BRAZIL26_MEDIA_MODE=allas."
fi
