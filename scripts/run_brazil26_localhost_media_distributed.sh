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

# Distributed plane: MongoDB is the record/status store and S3 is CSC Allas.
# These are set (not cleared) deliberately -- the point of this wrapper. Values
# come from the ignored runtime env or the environment; nothing is committed.
# Always force the distributed backends. A stale private env must never silently
# redirect this Allas deployment to local CSV/filesystem storage.
export LACLAUGPT_RECORD_BACKEND=mongodb
export LACLAUGPT_OBJECT_BACKEND=s3
export LACLAUGPT_CACHE_BACKEND=${LACLAUGPT_CACHE_BACKEND:-memory}
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=${LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND:-local}
export LACLAUGPT_MESSAGING_BACKEND=${LACLAUGPT_MESSAGING_BACKEND:-none}
export LACLAUGPT_TASK_QUEUE_BACKEND=${LACLAUGPT_TASK_QUEUE_BACKEND:-direct}

# Fail closed with an actionable message rather than a stack trace when the
# deployment is not actually configured for Allas/Mongo. Allas credentials come
# from allas-conf / ~/.aws (boto3), never from this env file.
if [[ "${LACLAUGPT_OBJECT_BACKEND}" == "s3" && -z "${LACLAUGPT_S3_BUCKET:-}" ]]; then
  echo "distributed media requires LACLAUGPT_S3_BUCKET (Allas bucket); refusing to fall back to filesystem" >&2
  exit 2
fi
if [[ "${LACLAUGPT_RECORD_BACKEND}" == "mongodb" && -z "${LACLAUGPT_MONGODB_URI:-}" ]]; then
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
