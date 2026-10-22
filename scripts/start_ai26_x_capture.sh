#!/usr/bin/env bash
# AI26 X capture operator command (issue #258).
#
# The AI26 browser path has had three commands for a while — `check`, `backend`,
# `media` — but no single entry point a researcher can run before a capture
# session. The consequence is measurable: 55 X records exist, the newest is from
# 2026-09-16, and nothing on the workstation schedules or starts the capture
# backend, so the path sits configured-and-idle. This script is that entry point.
#
#   start    (default)  check AI26 identity, start the loopback capture backend,
#                       wait for /status and /tour, print the Firefox handoff and
#                       the capture-verification steps
#   status              is the backend up, does it serve AI26, how many canonical
#                       rows exist right now
#   stop                stop the backend this script started (idempotent)
#
# Deliberate non-goals, because they are the maintainer's decisions:
#
#   * This NEVER schedules an unattended X capture and never drives Firefox.
#     Issue #258 keeps browser navigation user-controlled, so the browser half is
#     a human session; the script only makes that session one command away.
#   * It does not touch the crontab. If X capture is ever to become a scheduled
#     cycle, that is a sampling/scheduling decision (#206/#217) and a separate
#     change.
#
# The backend binds loopback only (the Python CLI rejects anything else); this
# wrapper refuses a non-loopback --host before doing any work so the error is
# about the operator's intent rather than a traceback. Credentials are read from
# the private runtime env and never printed — every line this script prints is a
# path, a loopback URL, a study identity or a count.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/ai26_runtime.sh
. "${ROOT}/scripts/ai26_runtime.sh"
# shellcheck source=scripts/runtime_config.sh
. "${ROOT}/scripts/runtime_config.sh"

DOC=docs/AI26_FIREFOX_BROWSER_COLLECTION.md
CONFIG_ROOT=$(laclaugpt_runtime_config_root "$ROOT")
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$CONFIG_ROOT/data/config/ai26-localhost.env"}
STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-${AI26_CONFIG:-"$CONFIG_ROOT/data/config/ai26.yaml"}}
DATA_ROOT=""
DATA_ROOT_ARG=""
HOST=127.0.0.1
PORT=""
PID_FILE=${LACLAUGPT_X_CAPTURE_PID:-"$ROOT/data/tmp/ai26-x-capture.pid"}
LOG_FILE=${LACLAUGPT_X_CAPTURE_LOG:-"$ROOT/data/logs/ai26-x-capture.log"}
# Startup replays whatever the mirror has not yet synced (about 150 ms per record:
# a remote ingest plus an offset rewrite) and only then binds the port. After a
# month idle here that was ~4 minutes, so the default wait is generous and the loop
# reports progress instead of looking hung.
START_TIMEOUT=${LACLAUGPT_X_CAPTURE_TIMEOUT:-600}

MODE=start
DRY_RUN=0
PORT_ARG=""

usage() {
  cat <<'USAGE'
AI26 X capture operator command: start (default), status or stop.

  start_ai26_x_capture.sh [start] [--dry-run] [--host H] [--port N] [--data-root DIR]
      Verify the AI26 identity, start the loopback capture backend, wait until
      /status and /tour answer, then print the Firefox handoff and what to check
      after a capture. Does not schedule anything and does not touch the crontab.

  start_ai26_x_capture.sh status
      Report whether the backend this script started is alive, which study it
      serves, and how many canonical rows the data root holds. Exit 0 healthy,
      3 when it is not running or not serving AI26.

  start_ai26_x_capture.sh stop
      Stop the backend this script started. Idempotent: exit 0 when it is already
      stopped.

  --dry-run    print the resolved plan and touch nothing
  --host H     backend bind address; loopback only (default 127.0.0.1)
  --port N     backend port (default 8766, or $LACLAUGPT_BROWSER_PORT)
  --data-root  AI26-only data root (default $LACLAUGPT_AI26_DATA_ROOT, else
               $LACLAUGPT_DATA_ROOT/ai26 when it exists, else <checkout>/data)
  --help, -h   this text

Manual capture stays manual: issue #258 keeps browser navigation user-controlled,
so this command prepares and proves the route — it never drives Firefox.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    start|--start) MODE=start ;;
    status|--status) MODE=status ;;
    stop|--stop) MODE=stop ;;
    --dry-run) DRY_RUN=1 ;;
    --host) HOST=${2:?--host needs a value}; shift ;;
    --host=*) HOST=${1#*=} ;;
    --port) PORT_ARG=${2:?--port needs a value}; shift ;;
    --port=*) PORT_ARG=${1#*=} ;;
    --data-root) DATA_ROOT_ARG=${2:?--data-root needs a value}; shift ;;
    --data-root=*) DATA_ROOT_ARG=${1#*=} ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# Loopback-only, decided here so a typo cannot reach the network interface
# before the Python guard rejects it.
case "$HOST" in
  127.0.0.1|localhost|::1|\[::1\]) ;;
  *)
    echo "refusing non-loopback bind address: $HOST" >&2
    echo "the capture endpoint is unauthenticated by design; keep it on loopback" >&2
    exit 2
    ;;
esac
backend_url=""

# Resolve the two values the private env is allowed to set. Run AFTER sourcing the
# env file, or the operator's shell/env would be silently overridden by the script:
# `LACLAUGPT_BROWSER_PORT=8765` in the env is the port the extension already points
# at, and a wrapper that assumed 8766 would wait on the wrong port and report a
# timeout while the backend was in fact up.
resolve_targets() {
  local base="${LACLAUGPT_DATA_ROOT:-$ROOT/data}"
  # The data root must be AI26-only. `JsonlDistributedMirror` scans it while the
  # backend starts, and the shared `<checkout>/data` of a working researcher holds
  # tens of gigabytes of other studies' objects: pointed at that, the start looks
  # like a hang (measured >2 min with 27 GB, ~28 s with the 463 MB AI26 root).
  if [[ -z "$DATA_ROOT" ]]; then
    DATA_ROOT=${DATA_ROOT_ARG:-${LACLAUGPT_AI26_DATA_ROOT:-}}
    if [[ -z "$DATA_ROOT" ]]; then
      [[ -d "$base/ai26" ]] && DATA_ROOT="$base/ai26" || DATA_ROOT="$base"
    fi
  fi
  # The private env writes relative paths on purpose (`LACLAUGPT_DATA_ROOT=./data`);
  # resolve them against the checkout so the plan, the scan and the logs name the
  # same directory no matter where the operator ran the command from.
  case "$DATA_ROOT" in
    /*) ;;
    *) DATA_ROOT="$ROOT/${DATA_ROOT#./}" ;;
  esac
  PORT=${PORT_ARG:-${LACLAUGPT_BROWSER_PORT:-8766}}
  case "$PORT" in
    ''|*[!0-9]*) echo "invalid port: $PORT" >&2; exit 2 ;;
  esac
  backend_url="http://${HOST}:${PORT}"
}

# ---------------------------------------------------------------- probe helpers
# Written in the runtime Python so the script does not add a curl dependency to a
# workstation that only has the collector's venv.
probe_status() {
  "$PYTHON_BIN" - "$backend_url" <<'PY' 2>/dev/null
import json, sys, urllib.request

url = sys.argv[1].rstrip("/") + "/status"
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception:
    raise SystemExit(1)
print(json.dumps(payload, sort_keys=True))
PY
}

probe_tour() {
  "$PYTHON_BIN" - "$backend_url" <<'PY' 2>/dev/null
import sys, urllib.request

url = sys.argv[1].rstrip("/") + "/tour"
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        response.read()
except Exception:
    raise SystemExit(1)
PY
}

# One interpreter for every step. The first `python` on an operator's PATH is
# often a uv-tool shim (e.g. ~/.local/share/uv/tools/<tool>/bin/python) that has
# none of this checkout's packages, so `python -m laclaugpt_data_collection` fails
# with ModuleNotFoundError while a console script would have worked. Pin the venv
# interpreter explicitly and use it for the backend and for the HTTP probes.
resolve_python() {
  local candidate
  for candidate in "${ROOT}/.venv/bin/python" "${HOME:-}/.local/bin/python3"; do
    [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  command -v python3 >/dev/null 2>&1 || {
    echo "python3 not found; run scripts/install_common.sh first" >&2
    return 2
  }
  command -v python3
}

pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  head -n 1 "$PID_FILE" 2>/dev/null | tr -dc '0-9'
}

# Load the private runtime env first. It is the authority on the backend port and
# the data root, so every mode — including status and stop — must resolve them from
# the same file the cron wrappers and the Firefox extension use.
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
resolve_targets

# ---------------------------------------------------------------------- dry-run
if [[ $DRY_RUN -eq 1 ]]; then
  echo "AI26 X capture plan (dry run — nothing is started, written or scheduled)"
  echo "  checkout:      $ROOT"
  echo "  config root:   $CONFIG_ROOT"
  echo "  runtime env:   $ENV_FILE"
  echo "  study config:  $STUDY_CONFIG"
  echo "  data root:     $DATA_ROOT"
  echo "  backend bind:  $HOST:$PORT (loopback only)"
  echo "  log:           $LOG_FILE"
  echo "  pid file:      $PID_FILE"
  echo "  steps: 1. run ai26_browser check (AI26 identity + remote control plane)"
  echo "         2. start ai26_browser backend on $backend_url"
  echo "         3. wait for /status and /tour, then print the Firefox handoff"
  echo "  not done by this command: no crontab entry, no Firefox launch, no"
  echo "  unattended capture — issue #258 keeps browser navigation user-controlled."
  for path in "$ENV_FILE" "$STUDY_CONFIG"; do
    [[ -f "$path" ]] && echo "  present:       $path" || echo "  missing:       $path"
  done
  exit 0
fi

PYTHON_BIN=$(resolve_python) || exit 2

# ---------------------------------------------------------------------- status
if [[ "$MODE" == status ]]; then
  pid=$(read_pid || true)
  echo "AI26 X capture status"
  echo "  backend url:   $backend_url"
  echo "  log:           $LOG_FILE"
  if pid_alive "$pid"; then
    echo "  process:       running (pid $pid)"
  elif [[ -n "${pid:-}" ]]; then
    echo "  process:       stale pid file (pid $pid is gone) — run: $0 start"
  else
    echo "  process:       not running — run: $0 start"
  fi
  status_json=$(probe_status || true)
  if [[ -z "$status_json" ]]; then
    echo "  endpoint:      no answer on $backend_url/status"
  else
    echo "  study:         $(printf '%s' "$status_json" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("study") or d.get("project_id") or "unknown")' 2>/dev/null || echo unknown)"
    echo "  endpoint:      answers (sanitized)"
  fi
  # `pipefail` again: a missing normalized/ makes `find` exit non-zero and would
  # take the whole status command down with it.
  rows=$(find "$DATA_ROOT/normalized" -maxdepth 1 -name '*.jsonl' 2>/dev/null | wc -l || true)
  echo "  canonical:     $rows JSONL file(s) under $DATA_ROOT/normalized"
  if pid_alive "$pid" && [[ -n "$status_json" ]] && probe_tour; then
    echo "  health:        ok"
    exit 0
  fi
  echo "  health:        not serving AI26 capture"
  exit 3
fi

# ------------------------------------------------------------------------ stop
if [[ "$MODE" == stop ]]; then
  pid=$(read_pid || true)
  if ! pid_alive "$pid"; then
    echo "AI26 X capture backend is not running."
    rm -f "$PID_FILE"
    exit 0
  fi
  echo "stopping AI26 X capture backend (pid $pid)"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    pid_alive "$pid" || break
    sleep 0.5
  done
  if pid_alive "$pid"; then
    echo "process ignores SIGTERM; sending SIGKILL" >&2
    kill -9 "$pid" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f "$PID_FILE"
  pid_alive "$pid" && { echo "failed to stop pid $pid" >&2; exit 1; }
  echo "stopped."
  exit 0
fi

# ----------------------------------------------------------------------- start
# The shared helper explains the linked-worktree case in detail; a plain checkout
# only gets "missing X", so name the document that holds the setup order as well.
require_private_file() {
  local label="$1" path="$2"
  [[ -f "$path" ]] && return 0
  laclaugpt_missing_runtime_config "$label" "$path" "$ROOT" "$DOC" || true
  echo "See $DOC for the AI26 setup order." >&2
  exit 2
}
require_private_file "AI26 runtime env" "$ENV_FILE"
require_private_file "AI26 study config" "$STUDY_CONFIG"

"$PYTHON_BIN" -c 'import laclaugpt_data_collection' 2>/dev/null || {
  echo "laclaugpt_data_collection is not importable from $PYTHON_BIN" >&2
  echo "run scripts/install_common.sh (or pip install -e .) in this checkout first" >&2
  exit 2
}

mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp" "$DATA_ROOT"

# Serialise starts. The backend needs ~30 s before it binds the port, so "is the
# port in use?" is false for that whole window; without a lock two starts can
# enter the same data root and race on the mirror's offset file.
START_LOCK="$ROOT/data/tmp/ai26-x-capture-start.lock"
exec 8>"$START_LOCK"
if ! flock -n 8; then
  echo "another AI26 X capture start is already in progress (lock: $START_LOCK)" >&2
  exit 0
fi

# Two backends on one data root race on the mirror's offset file: both write the
# same `.ai26-distributed-offsets.json.tmp` and one `replace()` loses it, which
# surfaces as a FileNotFoundError traceback in the log while the port still looks
# dead. Refuse to start a second listener on the port.
if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  echo "something is already listening on $backend_url — not starting a second backend" >&2
  echo "run: bash $0 status   (identity of the running backend)" >&2
  echo "     bash $0 stop     (stop it if this script started it)" >&2
  exit 2
fi

# Already up? Do not start a second backend on the same port.
existing=$(read_pid || true)
if pid_alive "$existing"; then
  echo "AI26 X capture backend already running (pid $existing) on $backend_url"
  exit 0
fi
rm -f "$PID_FILE"

export LACLAUGPT_PROJECT_ID=${LACLAUGPT_PROJECT_ID:-ai26}

cd "$ROOT"

echo "1/3 verifying AI26 identity and the remote control plane …"
if ! "$PYTHON_BIN" -m laclaugpt_data_collection.ai26_browser check --study-config "$STUDY_CONFIG"; then
  echo "preflight failed; the backend was not started. Fix the AI26 configuration first." >&2
  exit 2
fi

echo "2/3 starting the loopback capture backend on $backend_url …"
echo "    (the backend scans $DATA_ROOT on startup; the first start can take a minute)"
nohup "$PYTHON_BIN" -m laclaugpt_data_collection.ai26_browser backend \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$LOG_FILE" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$PID_FILE"

# Readiness, not just a pid: the backend prints its summary, mirrors a first scan
# and only then binds. Watch the process too, so a crash is reported as a crash
# rather than as "did not start within N seconds".
ready=0
waited=0
for _ in $(seq 1 "$START_TIMEOUT"); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "backend exited during startup (pid $pid); last log lines:" >&2
    tail -n 20 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
  fi
  if probe_status >/dev/null && probe_tour; then
    ready=1
    break
  fi
  waited=$((waited + 1))
  # Say what it is doing: a first start replays the unsynced mirror backlog, and
  # silence for minutes reads as a hang.
  if (( waited % 15 == 0 )); then
    synced=$(sed -n 's/.*: *\([0-9][0-9]*\).*/\1/p' "$DATA_ROOT/.ai26-distributed-offsets.json" 2>/dev/null | head -n 1 || true)
    total=$(stat -c %s "$DATA_ROOT/normalized/x.jsonl" 2>/dev/null || echo 0)
    echo "    … still starting (${waited}s): mirror offset ${synced:-0} of ${total} bytes replayed"
  fi
  sleep 1
done
if [[ $ready -eq 0 ]]; then
  echo "backend is running (pid $pid) but /status or /tour did not answer within ${START_TIMEOUT}s." >&2
  echo "check: tail -n 30 $LOG_FILE" >&2
  exit 1
fi

echo "3/3 collecting the readiness summary …"
status_json=$(probe_status)
study=$(printf '%s' "$status_json" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("study") or d.get("project_id") or "unknown")' 2>/dev/null || echo unknown)

cat <<SUMMARY
AI26 X capture backend is up.
  study:       $study
  endpoint:    $backend_url  (/status and /tour answer)
  data root:   $DATA_ROOT
  pid:         $pid   (pid file: $PID_FILE)
  log:         $LOG_FILE

Firefox handoff (the manual half — browser navigation stays yours):
  1. open the dedicated AI26 profile (about:profiles), extension loaded
  2. extension backend URL: $backend_url
  3. browse a configured public X target; captures are mirrored to AI26 storage

After a capture, verify (this is what an idle month looked like):
  $0 status                        # study, endpoint, canonical row count
  tail -n 20 $LOG_FILE             # capture counters

Stop with:  $0 stop
SUMMARY
[[ "$study" == "ai26" ]] || echo "warning: /status reports '$study', not 'ai26' — stop and fix the private config" >&2
