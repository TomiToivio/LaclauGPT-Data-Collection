#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PRIVATE_ROOT=${LACLAUGPT_PRIVATE_REPO:-"$ROOT/../LaclauGPT-Private"}
PRIVATE_DIR=${LACLAUGPT_PRIVATE_CONFIG_DIR:-"$PRIVATE_ROOT/collection/brazil26"}

cd "$ROOT"
[[ -x .venv/bin/laclaugpt-collect ]] || {
  echo "Run scripts/install_common.sh first." >&2
  exit 2
}

mkdir -p data/{config,downloads/brazil26,staging/brazil26,logs,tmp,database,browser/brazil26}
[[ -f data/config/brazil26.yaml ]] || cp configs/studies/brazil26.example.yaml data/config/brazil26.yaml
[[ -f data/config/brazil26.sources.toml ]] || cp configs/studies/brazil26.sources.example.toml data/config/brazil26.sources.toml
[[ -f data/config/brazil26-localhost.env ]] || cp configs/brazil26.env.example data/config/brazil26-localhost.env

echo "Brazil26 Phase 1 public runtime skeleton prepared."
echo "Private config root: $PRIVATE_DIR"
echo "Public source manifest: data/config/brazil26.sources.toml"
echo "Put live target overlays and private settings in LaclauGPT-Private, not here."
echo "Override LACLAUGPT_SOURCE_MANIFEST when the approved private manifest is ready."
