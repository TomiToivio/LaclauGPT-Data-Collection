#!/usr/bin/env bash
# Brazil26 distributed media worker (issue #233).
#
# The companion to run_brazil26_localhost_media.sh. That wrapper is the
# zero-infrastructure, local-first path and deliberately pins filesystem/csv so a
# repo-root .env cannot switch it into the distributed plane. This wrapper is the
# opposite: it is the *distributed* path the #233 deployment uses to download
# queued videos from X/Instagram/TikTok, upload the objects to CSC Allas, and
# record the object key and processing state in the project-scoped MongoDB.
#
# Use this wrapper when the deployment profile is brazil26-localhost-remote and
# MongoDB/S3 credentials are present. Use run_brazil26_localhost_media.sh when
# they are not. The two are mutually exclusive per host; install only one media
# cron entry.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
export PATH="$ROOT/.venv/bin:${HOME:-/root}/.local/bin:$PATH"
mkdir -p "$ROOT/data/logs" "$ROOT/data/tmp"
[[ -f "$ENV_FILE" ]] || { echo "missing runtime env: $ENV_FILE" >&2; exit 2; }
STUDY_OVERRIDE=${LACLAUGPT_STUDY_CONFIG:-}
DATA_OVERRIDE=${LACLAUGPT_DATA_ROOT:-}
set -a; source "$ENV_FILE"; set +a
STUDY_CONFIG=${STUDY_OVERRIDE:-${LACLAUGPT_STUDY_CONFIG:-${BRAZIL26_CONFIG:-"$PRIVATE_ROOT/collection/brazil26/brazil-election-2026.yaml"}}}
DATA_ROOT=${DATA_OVERRIDE:-${LACLAUGPT_DATA_ROOT:-"$ROOT/data"}}
LOCK_FILE=${LACLAUGPT_MEDIA_LOCK:-"$DATA_ROOT/tmp/brazil26-localhost-media.lock"}
[[ -f "$STUDY_CONFIG" ]] || { echo "missing study config: $STUDY_CONFIG" >&2; exit 2; }
if [[ "${LACLAUGPT_PROJECT_ID:-brazil26}" != "brazil26" ]]; then
  echo "Brazil26 media worker refuses a non-brazil26 project id" >&2
  exit 2
fi
export LACLAUGPT_PROJECT_ID=brazil26
export LACLAUGPT_EXECUTION=cron
export LACLAUGPT_CALLER=cron

# Source policy: the manifest must be X/Instagram/TikTok only. Refuse anything
# else before touching the network, so media can never be fetched for a family
# the deployment has disabled (#233).
SOURCE_MANIFEST=${LACLAUGPT_SOURCE_MANIFEST:-"$DATA_ROOT/config/brazil26.sources.toml"}
if [[ -f "$SOURCE_MANIFEST" ]]; then
  python -m laclaugpt_data_collection.source_allowlist \
    --manifest "$SOURCE_MANIFEST" --require-brazil26-only || {
    echo "Brazil26 source policy violation in $SOURCE_MANIFEST" >&2
    exit 3
  }
else
  echo "source manifest missing: $SOURCE_MANIFEST" >&2
  exit 2
fi

# Distributed plane: MongoDB is the record/status store and S3 is CSC Allas. This is
# not a default, it is this wrapper's contract -- so the backends are set
# unconditionally, and an explicit conflicting value is REFUSED rather than ignored.
#
# Both halves matter:
#   * an override that silently won (`${VAR:-s3}`) would leave this wrapper *called*
#     the distributed path while writing videos to the local filesystem and records
#     to CSV: #233's AC3 unmet while every log line looked healthy. That is the same
#     silent-bypass shape the local-first wrapper guards against in the opposite
#     direction, by pinning filesystem/csv outright;
#   * silently overriding an operator's explicit setting would be its own lie. If the
#     environment says filesystem, this host is misconfigured for the remote profile
#     and the operator should hear it, with the file to fix named.
require_distributed_backend() {
  local name="$1" want="$2" got="${!1:-}"
  if [[ -n "$got" && "$got" != "$want" ]]; then
    echo "distributed media requires $name=$want, but the environment set '$got'." >&2
    echo "This wrapper is the CSC Allas + MongoDB path (#233); run on the local plane it" >&2
    echo "would upload nothing while the cron still reported success." >&2
    echo "Fix: unset $name in the runtime env, or schedule the local-first wrapper" >&2
    echo "(run_brazil26_localhost_media.sh) via LACLAUGPT_BRAZIL26_MEDIA_MODE=local." >&2
    exit 2
  fi
  export "$name=$want"
}
require_distributed_backend LACLAUGPT_RECORD_BACKEND mongodb
require_distributed_backend LACLAUGPT_OBJECT_BACKEND s3
export LACLAUGPT_CACHE_BACKEND=${LACLAUGPT_CACHE_BACKEND:-memory}
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=${LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND:-local}
export LACLAUGPT_MESSAGING_BACKEND=${LACLAUGPT_MESSAGING_BACKEND:-none}
export LACLAUGPT_TASK_QUEUE_BACKEND=${LACLAUGPT_TASK_QUEUE_BACKEND:-direct}

# Fail closed with an actionable message rather than a stack trace when the
# deployment is not actually configured for Allas/Mongo. Unconditional now that the
# backends above cannot be anything else. Allas credentials come from allas-conf /
# ~/.aws (boto3), never from this env file.
if [[ -z "${LACLAUGPT_S3_BUCKET:-}" ]]; then
  echo "distributed media requires LACLAUGPT_S3_BUCKET (Allas bucket); refusing to fall back to filesystem" >&2
  exit 2
fi
if [[ -z "${LACLAUGPT_MONGODB_URI:-}" ]]; then
  echo "distributed media requires LACLAUGPT_MONGODB_URI; refusing to run without the metadata store" >&2
  exit 2
fi

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Brazil26 media worker already running; exiting cleanly" >&2; exit 0; }

cd "$ROOT"
exec laclaugpt-distributed-media \
  --study-config "$STUDY_CONFIG" \
  --data-root "$DATA_ROOT" \
  --workers "${LACLAUGPT_MEDIA_WORKERS:-2}" \
  --limit "${LACLAUGPT_MEDIA_BATCH_LIMIT:-50}" \
  --lock
