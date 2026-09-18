#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BEGIN="# BEGIN LACLAUGPT AI26"
END="# END LACLAUGPT AI26"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

(crontab -l 2>/dev/null || true) | awk -v b="$BEGIN" -v e="$END" '
$0==b {skip=1; next} $0==e {skip=0; next} !skip {print}
' > "$TMP"

cat >> "$TMP" <<EOF
$BEGIN
10 * * * * cd $ROOT && /bin/bash scripts/run_ai26_localhost_sync.sh >> data/logs/ai26-sync.log 2>&1
17 * * * * cd $ROOT && /bin/bash scripts/run_ai26_localhost_collect.sh >> data/logs/ai26-collect.log 2>&1
27 * * * * cd $ROOT && /bin/bash scripts/run_ai26_localhost_media.sh >> data/logs/ai26-media.log 2>&1
$END
EOF
crontab "$TMP"
echo "Installed AI26 cron block."
