#!/usr/bin/env bash
# Install local tools only. No proof search or model serving runs on NVwulf here.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
stage="${1:-all}"
python_bin="${PYTHON313:-python3.13}"
mathlib_revision="2df2f0150c275ad53cb3c90f7c98ec15a56a1a67"
index_version="20260714_172516"
case "$stage" in app|lean|retrieval|lsp|all) ;; *) echo 'Usage: scripts/setup-local.sh [app|lean|retrieval|lsp|all]' >&2; exit 2;; esac
if [[ "$stage" == app || "$stage" == all ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -e .
fi
if [[ "$stage" == lean || "$stage" == all ]]; then
  export PATH="$HOME/.elan/bin:$PATH"
  command -v lake >/dev/null || { echo 'Install elan from https://github.com/leanprover/elan, then retry.' >&2; exit 1; }
  mkdir -p runtime
  if [[ ! -d runtime/mathlib/.git ]]; then
    git clone --filter=blob:none --no-checkout https://github.com/leanprover-community/mathlib4.git runtime/mathlib
    git -C runtime/mathlib fetch --depth 1 origin "$mathlib_revision"
    git -C runtime/mathlib checkout --detach "$mathlib_revision"
  fi
  actual_revision="$(git -C runtime/mathlib rev-parse HEAD)"
  [[ "$actual_revision" == "$mathlib_revision" ]] || { echo 'Existing runtime/mathlib differs from the pinned revision; configure your project explicitly or use a new empty runtime directory.' >&2; exit 1; }
  (cd runtime/mathlib && lake exe cache get && lake build Mathlib)
fi
if [[ "$stage" == retrieval || "$stage" == lsp || "$stage" == all ]]; then
  command -v "$python_bin" >/dev/null || { echo 'Python 3.13 is required for the pinned local tools. Set PYTHON313 if necessary.' >&2; exit 1; }
fi
if [[ "$stage" == retrieval || "$stage" == all ]]; then
  "$python_bin" -m venv runtime/lean-explore/.venv
  runtime/lean-explore/.venv/bin/python -m pip install 'lean-explore[local]==1.3.0'
  export LEAN_EXPLORE_CACHE_DIR="$project_root/runtime/lean-explore/cache"
  export HF_HOME="$project_root/runtime/huggingface"
  export LEAN_EXPLORE_EMBEDDING_BATCH_SIZE=1
  export LEAN_EXPLORE_RERANKER_BATCH_SIZE=1
  runtime/lean-explore/.venv/bin/lean-explore data fetch --version "$index_version"
  runtime/lean-explore/.venv/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("Qwen/Qwen3-Embedding-0.6B", ignore_patterns=["onnx/*", "openvino/*"])'
fi
if [[ "$stage" == lsp || "$stage" == all ]]; then
  "$python_bin" -m venv runtime/lean-lsp/.venv
  runtime/lean-lsp/.venv/bin/python -m pip install 'lean-lsp-mcp==0.14.1' 'leanclient==0.5.5'
fi
echo 'Local setup completed. See docs/SETUP.md for the tool configuration and provider selection.'
