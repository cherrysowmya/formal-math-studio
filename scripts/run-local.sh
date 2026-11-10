#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
export PATH="$project_root/runtime/lean-explore/.venv/bin:$project_root/runtime/lean-lsp/.venv/bin:$HOME/.elan/bin:$PATH"
if [[ $# -eq 0 ]]; then set -- serve; fi
python_bin="$project_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then python_bin="${PYTHON:-python3}"; fi
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m formal_math "$@"
