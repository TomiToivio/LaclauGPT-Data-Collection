#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT=${1:-ai26}

case "$PROJECT" in
  ai26)
    ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/ai26-localhost.env"}
    STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$ROOT/data/config/ai26.yaml"}
    ;;
  brazil26|brasil26)
    PROJECT=brazil26
    ENV_FILE=${LACLAUGPT_ENV_FILE:-"$ROOT/data/config/brazil26-localhost.env"}
    STUDY_CONFIG=${LACLAUGPT_STUDY_CONFIG:-"$ROOT/data/config/brazil26.yaml"}
    ;;
  *) echo "usage: $0 ai26|brazil26" >&2; exit 2 ;;
esac

fail=0
check() { if "$@" >/dev/null 2>&1; then echo "OK   $*"; else echo "FAIL $*"; fail=1; fi; }

check test -x "$ROOT/.venv/bin/laclaugpt-collect"
check test -f "$ENV_FILE"
check test -f "$STUDY_CONFIG"
check command -v flock
check command -v cron

if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

if [[ "${LACLAUGPT_RECORD_BACKEND:-}" == "mongodb" ]]; then
  "$ROOT/.venv/bin/python" - <<'PY' || fail=1
import os
from pymongo import MongoClient
uri=os.environ.get("LACLAUGPT_MONGODB_URI")
assert uri, "LACLAUGPT_MONGODB_URI missing"
MongoClient(uri, serverSelectionTimeoutMS=5000).admin.command("ping")
print("OK   MongoDB ping")
PY
fi

if [[ "${LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND:-}" == "redis" || "${LACLAUGPT_CACHE_BACKEND:-}" == "redis" ]]; then
  "$ROOT/.venv/bin/python" - <<'PY' || fail=1
import os, redis
url=os.environ.get("LACLAUGPT_REDIS_URL")
assert url, "LACLAUGPT_REDIS_URL missing"
assert redis.Redis.from_url(url, socket_connect_timeout=5).ping()
print("OK   Redis ping")
PY
fi

if [[ "${LACLAUGPT_OBJECT_BACKEND:-}" == "s3" ]]; then
  if [[ -f "${HOME}/.aws/credentials" ]]; then
    echo "OK   Allas/AWS credential file present (created/managed by allas-conf)"
  else
    echo "FAIL ~/.aws/credentials missing; run CSC allas-conf in S3 mode"
    fail=1
  fi
fi

if [[ -x "$ROOT/.venv/bin/laclaugpt-collect" && -f "$STUDY_CONFIG" ]]; then
  "$ROOT/.venv/bin/laclaugpt-collect" distributed-check --study-config "$STUDY_CONFIG" || fail=1
fi

exit "$fail"
