#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BEGIN="# BEGIN LACLAUGPT BRAZIL26"
END="# END LACLAUGPT BRAZIL26"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

(crontab -l 2>/dev/null || true) | awk -v b="$BEGIN" -v e="$END" '
$0==b {skip=1; next} $0==e {skip=0; next} !skip {print}
' > "$TMP"

cat >> "$TMP" <<EOF
$BEGIN
12 * * * * cd $ROOT && /bin/bash scripts/run_brazil26_localhost_sync.sh >> data/logs/brazil26-sync.log 2>&1
22 * * * * cd $ROOT && /bin/bash scripts/run_brazil26_localhost_collect.sh >> data/logs/brazil26-collect.log 2>&1
32 * * * * cd $ROOT && /bin/bash scripts/run_brazil26_localhost_media.sh >> data/logs/brazil26-media.log 2>&1
$END
EOF
crontab "$TMP"
echo "Installed Brazil26 cron block."
