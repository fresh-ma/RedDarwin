#!/usr/bin/env bash
# Run the selected single-call skills through their existing wrappers.
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin="${PYTHON_BIN:-$root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  python_bin=$(command -v python3)
fi
exec "$python_bin" "$root/scripts/lib/auto_redteaming.py" "$@"
