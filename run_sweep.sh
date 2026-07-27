#!/usr/bin/env bash
# Run a local ShopGoodwill sweep and export viewer data.
#
# Usage: ./run_sweep.sh [adam|marissa]   (default: adam)
#
# Bootstraps a stable .venv (gitignored) with the needed deps on first run, so
# the sweep survives across sessions and can be whitelisted by this script path
# instead of a per-session python binary.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PERSON="${1:-adam}"

# --- bootstrap venv ---
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import requests, openpyxl" 2>/dev/null; then
  echo "Bootstrapping $VENV ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet requests openpyxl
fi
PY="$VENV/bin/python"

# --- run the sweep ---
case "$PERSON" in
  adam)
    "$PY" "$ROOT/hunt.py" --output "$ROOT/runs/local_adam" \
      --per-query 10 --pages-per-query 2 --evidence-limit 0
    "$PY" "$ROOT/export_viewer.py" adam "$ROOT/runs/local_adam"
    ;;
  marissa)
    "$PY" "$ROOT/marissa_hunt.py" --output "$ROOT/runs/local_marissa" \
      --per-query 10 --pages-per-query 2
    "$PY" "$ROOT/export_viewer.py" marissa "$ROOT/runs/local_marissa"
    ;;
  *)
    echo "Unknown person '$PERSON' (expected adam or marissa)" >&2
    exit 1
    ;;
esac
