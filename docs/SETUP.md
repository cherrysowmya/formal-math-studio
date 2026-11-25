# Local setup

The browser interface, orchestration, Lean compiler, goal inspection, retrieval,
and generated files all run on your machine. Select a model provider for each
role. The default is Anthropic's Claude Sonnet 5.5.

Requirements: Python 3.11+ for the application, Git, and [elan](https://github.com/leanprover/elan)
for Lean. The pinned optional tool environments require Python 3.13. Set
`PYTHON313=/absolute/path/to/python3.13` when that executable is not on PATH.

From the repository root:

```bash
bash scripts/setup-local.sh all
bash scripts/run-local.sh
```

Open **http://127.0.0.1:8765 → Model settings**, paste your provider's API key,
and click **Apply settings**. Choose the provider and served model for each role.
Keys are saved to the local `.env` file with owner-only permissions and are
loaded automatically. Both `.env` and its temporary files are Git-ignored. The
page shows whether a key is configured, never its saved value. Blank fields
keep the existing key; use the removal checkbox to delete a saved key.

You can also copy `.env.example` to `.env` and fill it in locally, or export
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` before launching. A nonempty `.env` key
takes precedence over the corresponding shell variable. The file is read as
data, not sourced as a shell script. By default it lives in the launcher's working
directory, the repository root. `app.env_file` can select a different local file
named `.env`. Never put actual keys in TOML, source code, or version control.

Setup stages can be run separately: `app`, `lean`, `retrieval`, and `lsp`.
Setup downloads dependencies and compiled library artifacts. It never downloads
evaluation problems, expected solutions, or proof-search workloads.

The local Lean project is Mathlib commit
`2df2f0150c275ad53cb3c90f7c98ec15a56a1a67`, using Lean `4.26.0`.
`setup-local.sh lean` refuses to overwrite a different existing checkout.
Alternatively set `lean.project_path` in your TOML configuration to an already
prepared compatible Lean project. Uploaded imports must exist in that project.
All configured filesystem paths refer to your local machine.

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

## Bring your own model server

For open-weight inference, users supply their own GPU server, model weights,
tokenizer, supporting files, and running inference service. Upload those files
directly to your GPU server using your own tools. The app does not provision GPUs,
upload or load inference models, launch model servers, or establish tunnels.
Only Lean files are uploaded through the proof interface.

The application connects to an existing HTTP(S) endpoint. Use **Model settings →
Add an API provider** and choose the self-hosted protocol for a server with
`/tokenize`, or Chat Completions for a compatible hosted API. Enter your served
model ID for each role. Alternatively add a provider to
the ignored `config/local.toml` (create it from `config/example.toml` if needed):

```toml
[providers.my_model_server]
kind = "openai_compatible"
base_url = "https://your-model-server.example/v1"
api_key_env = "MODEL_SERVER_API_KEY"
timeout_seconds = 600
```

Replace the URL with your own reachable endpoint. Restart the local app, then
select `my_model_server` and the exact model name served by that endpoint for
each desired role in **Model settings**. If the service requires a key, paste it
into that provider's password field; it is saved to `.env` too. For a service
without authentication, omit `api_key_env`. Use HTTPS for remote credentials,
or a loopback endpoint made available through a connection you manage yourself.

The service must support `/v1/chat/completions` and a `/tokenize` endpoint
accepting `model`, `messages`, `add_generation_prompt`, and
`chat_template_kwargs`, returning an integer `count` for the same model's rendered
prompt. `count_tokens_path` can override the counting path relative to the server
origin. A generic chat endpoint without this counting protocol is insufficient.
Configure each role's token budgets and context window to fit your served model.
Connection details alone do not start an inference service.

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
