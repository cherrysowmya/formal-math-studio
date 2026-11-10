# Local setup

The browser interface, orchestration, Lean compiler, goal inspection, retrieval,
and generated files all run on your machine. Model inference is selected per
role: an API provider, or an SSH-forwarded model service on NVwulf.

Requirements: Python 3.11+ for the application, Git, and [elan](https://github.com/leanprover/elan)
for Lean. The pinned optional tool environments require Python 3.13. Set
`PYTHON313=/absolute/path/to/python3.13` when that executable is not on PATH.

From the repository root:

```bash
bash scripts/setup-local.sh all
bash scripts/run-local.sh
```

Setup stages can be run separately: `app`, `lean`, `retrieval`, and `lsp`.
Setup downloads dependencies and compiled library artifacts. It never downloads
evaluation problems, expected solutions, or proof-search workloads.

The local Lean project is Mathlib commit
`2df2f0150c275ad53cb3c90f7c98ec15a56a1a67`, using Lean `4.26.0`.
`setup-local.sh lean` refuses to overwrite a different existing checkout.
Alternatively set `lean.project_path` in your TOML configuration to an already
prepared compatible Lean project. Uploaded imports must exist in that project.
All configured filesystem paths are local paths, not NVwulf paths.

## Local tool configuration

The launcher adds the prepared tool environments to PATH. The equivalent
configuration is:

```toml
[lean]
project_path = "runtime/mathlib"
command = ["lake", "env", "lean"]
lsp_command = ["lean-lsp-mcp"]
timeout_seconds = 240
lsp_timeout_seconds = 120

[retrieval]
enabled = true
required = true
command = ["lean-explore", "mcp", "serve", "--backend", "local"]
cache_dir = "runtime/lean-explore/cache"
hf_cache_dir = "runtime/huggingface"
data_version = "20260714_172516"
packages = ["Mathlib", "Init"]
limit = 12
source_limit = 4
rerank_top = 0
```

Paths in a custom TOML are resolved relative to its directory. Put a local config
in the repository root, or adjust `../runtime/...` paths for a config subfolder.
Set `lsp_command=[]` to use completed compiler diagnostics without interactive
goal inspection. Missing goal inspection is reported in feedback; it never
grants proof acceptance. A missing required retrieval service stops the run
with a service error. To run without lemma search, explicitly set
`retrieval.enabled=false` and `retrieval.required=false`.

LeanExplore `1.3.0` and its library-search index are external local dependencies.
The index contains Mathlib/Lean declaration search material; it is necessary to
find existing lemmas. It is not an evaluation corpus and is not committed to
this repository. The embedding weights and index stay under ignored `runtime/`.
Runtime search is offline after setup, with `CUDA_VISIBLE_DEVICES` empty and
the hybrid lexical/semantic backend running locally. The optional cross-encoder
is disabled. The index version can differ from the verification project's
library revision; Lean compilation determines whether a retrieved declaration
is actually available and applicable.

## Proof acceptance

The application accepts named `theorem`/`lemma` tasks supported by the proof-slot
parser. The original task is preserved during assembly. Final acceptance requires
local `lake env lean` completion and a `#print axioms` audit permitting only
`propext`, `Classical.choice`, and `Quot.sound`. Unfinished proofs, new axioms,
native evaluation proof escapes, compiler failures, and timeouts cannot produce
verified status. Anonymous examples and unsupported source layouts must be
converted to supported named declarations. Use the UI's status indicator to
distinguish a verified result from a latest unsuccessful candidate.

Uploaded Lean code runs in your local Lean environment. This is a personal local
tool for code you trust, not an execution sandbox for untrusted internet users.
Do not expose its HTTP server to the public internet. Output files and run
records are generated locally under the configured output directory.

No local LLM is required: configure provider API keys in your shell, or follow
[NVwulf model serving](NVWULF.md) for open-weight inference. Keys belong in local
environment variables and must not be committed or pasted into the browser.
