#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
PRIVATE_DIR=${LACLAUGPT_PRIVATE_CONFIG_DIR:-"$PRIVATE_ROOT/collection/ai26"}

cd "$ROOT"
[[ -x .venv/bin/laclaugpt-collect ]] || {
  echo "Run scripts/install_common.sh first." >&2
  exit 2
}

mkdir -p data/{config,downloads/ai26,staging/ai26,logs,tmp,database,browser/ai26}
[[ -f data/config/ai26.yaml ]] || cp configs/studies/ai26.example.yaml data/config/ai26.yaml
[[ -f data/config/ai26.sources.toml ]] || cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
[[ -f data/config/ai26-localhost.env ]] || cp configs/ai26.browser.env.example data/config/ai26-localhost.env

echo "AI26 public runtime skeleton prepared."
echo "Private config root: $PRIVATE_DIR"
echo "Put real settings/source overlays/codebooks in LaclauGPT-Private, not here."
echo "Then edit data/config/ai26-localhost.env to point to that directory."
