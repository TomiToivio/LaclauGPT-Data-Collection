#!/usr/bin/env bash
# AI26 non-browser collection on Laskin (cron-safe, one bounded cycle per call).
#
# One bounded Phase 1 cycle, no Firefox/browser/X collector, shared AI26
# MongoDB/Redis/S3 namespace, and flock overlap protection.
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT_DIR/.env"}
STUDY_CONFIG=${LACLAUGPT_AI26_STUDY_CONFIG:-"$ROOT_DIR/data/config/ai26.yaml"}
SOURCE_MANIFEST=${LACLAUGPT_AI26_SOURCE_MANIFEST:-"$ROOT_DIR/data/config/ai26.sources.toml"}
# Issue #206: the audited plan the deployed manifest should track. Reported, never
# enforced -- a drift line in the cycle log makes a stale deployment visible.
TRACKED_PLAN=${LACLAUGPT_AI26_TRACKED_PLAN:-"$ROOT_DIR/configs/studies/ai26.sources.example.toml"}
LOCK_FILE=${LACLAUGPT_AI26_COLLECT_LOCK:-"$ROOT_DIR/data/tmp/ai26-laskin-collect.lock"}

mkdir -p "$ROOT_DIR/data/tmp" "$ROOT_DIR/data/logs"
[[ -f "$ENV_FILE" ]] || { echo "missing env file: $ENV_FILE" >&2; exit 2; }
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
[[ -f "$SOURCE_MANIFEST" ]] || { echo "missing source manifest: $SOURCE_MANIFEST" >&2; exit 2; }

CALLER_OVERRIDE=${LACLAUGPT_CALLER-}
EXECUTION_OVERRIDE=${LACLAUGPT_EXECUTION-}

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Explicit invocation metadata wins over defaults in .env. This lets Hermes run the
# same operational wrapper with LACLAUGPT_CALLER=hermes-agent and
# LACLAUGPT_EXECUTION=agent without the sourced file silently erasing provenance.
if [[ -n "$CALLER_OVERRIDE" ]]; then
  export LACLAUGPT_CALLER="$CALLER_OVERRIDE"
fi
if [[ -n "$EXECUTION_OVERRIDE" ]]; then
  export LACLAUGPT_EXECUTION="$EXECUTION_OVERRIDE"
fi

if [[ "${LACLAUGPT_BROWSER:-none}" != "none" ]]; then
  echo "refusing Laskin collection with LACLAUGPT_BROWSER=${LACLAUGPT_BROWSER}; browser collection is localhost-only" >&2
  exit 2
fi
if [[ "${LACLAUGPT_PROJECT_ID:-ai26}" != "ai26" ]]; then
  echo "refusing Laskin AI26 worker with project id ${LACLAUGPT_PROJECT_ID:-unset}" >&2
  exit 2
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "AI26 Laskin collection already running; exiting cleanly" >&2
  exit 0
fi

cd "$ROOT_DIR"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  RUN=("$ROOT_DIR/.venv/bin/python" -m laclaugpt_data_collection.ai26_laskin_runner)
else
  RUN=(python3 -m laclaugpt_data_collection.ai26_laskin_runner)
fi

echo "[$(date -Is)] AI26 Laskin collection start"

# Issue #240: the end marker used to be emitted only on the normal path after the
# runner. #217 fixed the *exit-status* path (a partial tick no longer aborts under
# `set -e` before the marker), but any OTHER exit path still lost it — and on
# 2026-10-09T03:10 a tick emitted its complete JSON record and then nothing, with no
# OOM, no reboot and no cron timeout to explain it. The cause was not identifiable
# from the evidence available, so the fix is to make the invariant structural rather
# than to guess the trigger: an EXIT trap fires for every exit path, including a
# caught signal, so a tick can no longer read as a silently stopped stage.
#
# NOTE the trap is armed HERE, after the start marker and after the early
# preflight/lock exits above, because those must not emit an end for a tick that
# never started.
END_EMITTED=0
runner_status=""
RUNNER_PID=""
emit_end_marker() {
  # Exactly once, whatever path we leave by.
  [[ "$END_EMITTED" -eq 1 ]] && return 0
  END_EMITTED=1
  if [[ -n "$runner_status" && "$runner_status" -ne 0 ]]; then
    echo "[$(date -Is)] AI26 Laskin collection end runner_status=${runner_status} (tick partial; see status/errors above)"
  elif [[ -z "$runner_status" && -n "${SIGNALLED:-}" ]]; then
    # Killed before the runner reported: name the signal so the tick is diagnosable
    # instead of merely absent.
    echo "[$(date -Is)] AI26 Laskin collection end interrupted signal=${SIGNALLED} (runner never reported; see wrapper log)"
  else
    echo "[$(date -Is)] AI26 Laskin collection end"
  fi
}
# Convert catchable signals into a clean exit so the EXIT trap runs. 128+signo is
# the conventional shell status, and it keeps a signal distinguishable from a
# partial tick (1) in the marker. The runner is stopped first so we never orphan
# it while its parent exits.
on_signal() {
  SIGNALLED="$1"
  if [[ -n "$RUNNER_PID" ]] && kill -0 "$RUNNER_PID" 2>/dev/null; then
    kill -TERM "$RUNNER_PID" 2>/dev/null || true
    wait "$RUNNER_PID" 2>/dev/null || true
  fi
  exit "$2"
}
trap 'emit_end_marker' EXIT
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap 'on_signal HUP 129' HUP

# The runner returns 1 whenever any source recorded an error (status: partial),
# so a single transient upstream failure (e.g. arXiv HTTP 429) would abort this
# wrapper under `set -e` *before* the end marker below, leaving a tick that reads
# as a silently stopped stage even though its records were collected. Capture the
# runner status, always emit the end marker, and propagate the status so cron/CI
# still sees a non-zero exit for a partial tick.
#
# The runner is BACKGROUNDED and then waited on, not run in the foreground. This
# is load-bearing for #240: bash defers a trap for the whole lifetime of a
# foreground child, so a TERM arriving while the runner worked would not run any
# handler until the runner finished on its own — and if the runner was killed with
# the wrapper, the marker was lost outright. `wait` is interruptible, so the trap
# now fires promptly on the signal that actually occurred.
set +e
"${RUN[@]}" \
  --study-config "$STUDY_CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" \
  --collection-id "ai26" \
  --worker-id "${LACLAUGPT_AI26_WORKER_ID:-laskin-cron}" \
  --max-feeds "${LACLAUGPT_AI26_MAX_FEEDS:-8}" \
  --max-jobs "${LACLAUGPT_AI26_MAX_NON_BROWSER_JOBS:-6}" \
  --per-source-limit "${LACLAUGPT_AI26_PER_SOURCE_LIMIT:-5}" \
  --limit "${LACLAUGPT_AI26_BATCH_LIMIT:-40}" \
  --tracked-plan "$TRACKED_PLAN" &
RUNNER_PID=$!
wait "$RUNNER_PID"
runner_status=$?
set -e
RUNNER_PID=""
exit "$runner_status"
