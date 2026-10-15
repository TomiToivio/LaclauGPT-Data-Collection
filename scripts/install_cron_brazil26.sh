#!/usr/bin/env bash
# Brazil26 localhost cron operator script (issue #233, checklist item 8).
#
# Three operations on the single marker-managed Brazil26 cron block:
#
#   install    (default)  write/refresh it idempotently
#   uninstall             remove ONLY the entries this installer owns
#   status                report whether the block is installed and healthy
#
# Modifiers:
#   --dry-run   print the plan; never touch the crontab (install and uninstall)
#   --yes, -y   confirm an uninstall without an interactive prompt
#
# The removal half is deliberately narrow. It strips the marker-managed block
# and any unmanaged line that names one of the four Brazil26 wrappers declared
# below; every other crontab line is preserved byte-for-byte. The previous
# crontab is backed up before any write, and the command refuses (exit 2)
# instead of guessing when the crontab is unreadable or its markers are not
# balanced -- the two cases where "remove my entries" cannot be told apart from
# "delete somebody else's job". Without --yes and without a terminal it refuses
# as well: an unattended run must never strip a schedule by accident.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BEGIN="# BEGIN LACLAUGPT BRAZIL26"
END="# END LACLAUGPT BRAZIL26"
TMP=$(mktemp)
WORK=$(mktemp -d)
trap 'rm -f "$TMP"; rm -rf "$WORK"' EXIT

# The only crontab lines this installer may ever write or supersede. Removal is
# limited to these names plus the marker-managed block: a hand-written or
# third-party job survives an uninstall untouched even if it mentions Brazil26.
BRAZIL26_WRAPPERS=(
  "run_brazil26_localhost_sync.sh"
  "run_brazil26_localhost_collect.sh"
  "run_brazil26_localhost_media.sh"
  "run_brazil26_localhost_media_distributed.sh"
)

usage() {
  cat <<'USAGE'
Brazil26 localhost cron: install (default), uninstall or status.

  install_cron_brazil26.sh [install] [--dry-run]
      Write/refresh the marker-managed 30-minute Brazil26 cron block.
  install_cron_brazil26.sh uninstall [--dry-run] [--yes]
      Remove ONLY this installer's Brazil26 entries. Prints the plan first,
      backs the crontab up, and leaves everything else untouched.
  install_cron_brazil26.sh status
      Report whether the block is installed, its media mode and cadence, and
      the Brazil26 logs. Exit 0 when healthy, 3 when absent or degraded.

  --dry-run   print the plan and touch nothing (install and uninstall)
  --yes, -y   skip the interactive uninstall confirmation
  --help, -h  this text
USAGE
}

MODE=install
DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    install|--install) MODE=install ;;
    uninstall|remove|--uninstall|--remove) MODE=uninstall ;;
    status|--status) MODE=status ;;
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *)
      echo "unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# --------------------------------------------------------------------------- #
# Crontab ownership: read, classify, remove, report
# --------------------------------------------------------------------------- #

read_crontab() {
  # $1: destination file. Returns 0 when the crontab was read (an empty file
  # means "this user has no crontab", which is not an error) and 2 when it
  # could not be read at all.
  local target="$1" err rc=0
  err="$1.err"
  crontab -l > "$target" 2> "$err" || rc=$?
  if [[ $rc -eq 0 ]]; then
    return 0
  fi
  if grep -qi "no crontab for" "$err" 2>/dev/null; then
    : > "$target"
    return 0
  fi
  if [[ ! -s "$err" ]]; then
    : > "$target"
    return 0
  fi
  echo "cannot read the crontab: 'crontab -l' exited $rc: $(sed -n 1p "$err")" >&2
  return 2
}

classify_crontab() {
  # $1: crontab file. Sets KEEP_LINES (not ours), OWNED_LINES (ours) and
  # BLOCK_INSTALLED (managed markers seen). Returns 2 on a layout that cannot
  # be interpreted safely: removal must never guess at where the block ends.
  local file="$1" line wrapper owned in_block=0 begins=0
  KEEP_LINES=()
  OWNED_LINES=()
  BLOCK_INSTALLED=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "$BEGIN" ]]; then
      if [[ $in_block -eq 1 ]]; then
        echo "the crontab nests a second '$BEGIN' inside the managed block" >&2
        return 2
      fi
      in_block=1
      begins=$((begins + 1))
      OWNED_LINES+=("$line")
      continue
    fi
    if [[ "$line" == "$END" ]]; then
      if [[ $in_block -eq 0 ]]; then
        echo "the crontab has an '$END' marker with no '$BEGIN' before it" >&2
        return 2
      fi
      in_block=0
      OWNED_LINES+=("$line")
      continue
    fi
    if [[ $in_block -eq 1 ]]; then
      OWNED_LINES+=("$line")
      continue
    fi
    owned=0
    for wrapper in "${BRAZIL26_WRAPPERS[@]}"; do
      if [[ "$line" == *"$wrapper"* ]]; then
        owned=1
        break
      fi
    done
    if [[ $owned -eq 1 ]]; then
      OWNED_LINES+=("$line")
    else
      KEEP_LINES+=("$line")
    fi
  done < "$file"
  if [[ $in_block -eq 1 ]]; then
    echo "the crontab opens '$BEGIN' but never closes it with '$END'" >&2
    return 2
  fi
  BLOCK_INSTALLED=$begins
  return 0
}

write_lines() {
  # $1: destination file; the remaining arguments are the lines to write.
  local destination="$1" line
  shift
  : > "$destination"
  for line in "$@"; do
    printf '%s\n' "$line" >> "$destination"
  done
}

remove_brazil26_cron() {
  local current="$WORK/crontab.current" owned line answer backup_dir backup
  if ! read_crontab "$current"; then
    return 2
  fi
  if ! classify_crontab "$current"; then
    echo "refusing to change the crontab: the layout above is ambiguous, so this" >&2
    echo "installer cannot tell its own Brazil26 entries from anyone else's." >&2
    return 2
  fi
  owned=${#OWNED_LINES[@]}
  if [[ $owned -eq 0 ]]; then
    echo "No Brazil26 cron entries present; nothing to remove (idempotent no-op)."
    return 0
  fi
  echo "Brazil26 cron removal plan:"
  echo "  entries this installer owns and will remove: $owned"
  for line in "${OWNED_LINES[@]}"; do
    echo "    - $line"
  done
  echo "  other crontab entries left untouched: ${#KEEP_LINES[@]}"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "dry-run: nothing was removed; the crontab is unchanged."
    return 0
  fi
  if [[ $ASSUME_YES -eq 0 ]]; then
    if [[ -t 0 ]]; then
      answer=""
      read -r -p "Remove these $owned entries from the crontab? [y/N] " answer || true
      case "$answer" in
        y|Y|yes|YES) ;;
        *) echo "aborted: the crontab is unchanged." >&2; return 2 ;;
      esac
    else
      echo "refusing to modify the crontab without confirmation: re-run with" >&2
      echo "--yes, or use --dry-run to only print the plan." >&2
      return 2
    fi
  fi
  backup_dir=${LACLAUGPT_CRON_BACKUP_DIR:-"$ROOT/data/backups"}
  mkdir -p "$backup_dir"
  backup="$backup_dir/crontab-brazil26-$(date -u +%Y%m%dT%H%M%SZ).txt"
  cp "$current" "$backup"
  write_lines "$WORK/crontab.keep" ${KEEP_LINES[@]+"${KEEP_LINES[@]}"}
  crontab "$WORK/crontab.keep"
  echo "Removed $owned Brazil26 cron entries; the previous crontab is backed up at $backup"
  return 0
}

brazil26_cron_status() {
  # Read-only health check for the *installed schedule* (the Python CLI's
  # `status` subcommand reports the researcher session, not the cron block).
  local current="$WORK/crontab.current" line log
  local installed=no mode=none cadence=missing health=ok
  local has_local=0 has_allas=0 has_sync=0 has_collect=0 has30=0 stale15=0
  if ! read_crontab "$current"; then
    return 2
  fi
  if ! classify_crontab "$current"; then
    echo "status: unsafe crontab layout; refusing to read it as installed" >&2
    return 3
  fi
  if [[ $BLOCK_INSTALLED -gt 0 ]]; then
    installed=yes
  fi
  for line in "${OWNED_LINES[@]}"; do
    case "$line" in *run_brazil26_localhost_media_distributed.sh*) has_allas=1 ;; esac
    case "$line" in *run_brazil26_localhost_media.sh*) has_local=1 ;; esac
    case "$line" in *run_brazil26_localhost_sync.sh*) has_sync=1 ;; esac
    case "$line" in *run_brazil26_localhost_collect.sh*) has_collect=1 ;; esac
    case "$line" in *"*/30"*) has30=1 ;; esac
    case "$line" in *"*/15"*) stale15=1 ;; esac
  done
  if [[ $has_allas -eq 1 && $has_local -eq 1 ]]; then
    mode=both
  elif [[ $has_allas -eq 1 ]]; then
    mode=allas
  elif [[ $has_local -eq 1 ]]; then
    mode=local
  fi
  if [[ $stale15 -eq 1 ]]; then
    cadence="stale 15-minute entry present"
  elif [[ $has30 -eq 1 ]]; then
    cadence="30-minute"
  fi
  if [[ $installed == no ]]; then
    health=absent
  elif [[ $mode == both || $mode == none ]]; then
    health=degraded
  elif [[ $has30 -eq 0 || $stale15 -eq 1 || $has_sync -eq 0 || $has_collect -eq 0 ]]; then
    health=degraded
  fi
  echo "brazil26 cron status"
  echo "  installed: $installed"
  echo "  owned_entries: ${#OWNED_LINES[@]}"
  echo "  media_mode: $mode"
  echo "  media_cadence: $cadence"
  echo "  workers: sync=$has_sync collect=$has_collect"
  echo "  health: $health"
  echo "  logs:"
  for log in "$ROOT/data/logs/brazil26-sync.log" "$ROOT/data/logs/brazil26-collect.log" "$ROOT/data/logs/brazil26-media.log"; do
    if [[ -f "$log" ]]; then
      echo "    - $log ($(wc -c < "$log" | tr -d ' ') bytes)"
    else
      echo "    - $log (absent)"
    fi
  done
  echo "  inspect: tail -n 50 $ROOT/data/logs/brazil26-media.log"
  if [[ $health == ok ]]; then
    return 0
  fi
  return 3
}

if [[ "$MODE" == "uninstall" ]]; then
  set +e
  remove_brazil26_cron
  STATUS=$?
  set -e
  exit "$STATUS"
fi

if [[ "$MODE" == "status" ]]; then
  set +e
  brazil26_cron_status
  STATUS=$?
  set -e
  exit "$STATUS"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  echo "dry-run: no crontab will be modified; the messages below are the plan." >&2
fi

# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #

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
if [[ $DRY_RUN -eq 1 ]]; then
  echo "dry-run: the crontab was NOT modified; this block would be installed:"
  sed -n "/^$BEGIN\$/,/^$END\$/p" "$TMP"
  exit 0
fi
crontab "$TMP"
echo "Installed/updated idempotent Brazil26 cron block (media mode: $MEDIA_MODE -> $MEDIA_WRAPPER)."
echo "Media log: $ROOT/data/logs/brazil26-media.log"
if [[ "$MEDIA_MODE" == "local" ]]; then
  echo "NOTE: media is local-first (filesystem/csv). For scheduled CSC Allas uploads"
  echo "      re-run with LACLAUGPT_BRAZIL26_MEDIA_MODE=allas."
fi
