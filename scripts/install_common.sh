#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${PYTHON:-python3}

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y     python3 python3-venv python3-pip git curl ca-certificates     cron util-linux sqlite3 ffmpeg build-essential
else
  echo "This installer currently targets WSL Ubuntu/apt." >&2
  exit 2
fi

cd "$ROOT"
if [[ ! -d .venv ]]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/python -m pip install -r requirements.txt

mkdir -p data/{config,downloads,staging,logs,tmp,database,browser}

cat <<EOF
Common collection workstation dependencies installed.

Next:
  scripts/install_ai26.sh
or
  scripts/install_brazil26.sh

Firefox itself is intentionally not installed here. On WSL, use the normal
interactive Firefox installation (Windows Firefox is fine) and keep the
capture backend bound to 127.0.0.1.
EOF
