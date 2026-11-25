# Formal Math Studio

A local web app for writing and repairing Lean 4 proofs. Upload a `.lean` file or
paste a theorem, choose your agent models, run the system, and download the
result. A proof is marked **verified** only after local Lean compilation and the
axiom audit pass.

The interface, agent orchestration, Lean checks, library search, and output files
run on your computer. Model requests go to the API providers or inference servers
you select. This README is the project's setup and operating guide.

## Start locally

Install these prerequisites:

- Python 3.11+ for the app; Python 3.13 for the local retrieval and LSP tools.
- Git and [elan](https://github.com/leanprover/elan), which supplies Lean and Lake.
- An API-provider account, or access to your own running model server.

From a terminal:

```bash
git clone https://github.com/cherrysowmya/formal-math-studio.git
cd formal-math-studio
cp config/example.toml config/local.toml
bash scripts/setup-local.sh all
bash scripts/run-local.sh
```

Open **http://127.0.0.1:8765**. Open **Model settings**, paste the selected
provider's API key, choose a provider and exact model ID for each role, and click
**Apply settings**. The default model for all roles is Claude Sonnet 5.5
(`claude-sonnet-5-5`) with adaptive thinking. You can mix providers across roles.

If Python 3.13 has a different executable path, set `PYTHON313` when installing:

```bash
PYTHON313=/absolute/path/to/python3.13 bash scripts/setup-local.sh all
```

Setup stages can also run separately: `app`, `lean`, `retrieval`, and `lsp`.
For example, `bash scripts/setup-local.sh retrieval` prepares only library search.
Setup downloads local dependencies and library artifacts; no evaluation datasets
or inference model weights are included.

For later sessions, just run `bash scripts/run-local.sh`. Stop the server with
**Ctrl-C** in that terminal. The launcher can run the checked-out app with Python
3 even without `.venv`; the Lean and retrieval tools still need preparation.

## Submit a proof task

1. Upload a UTF-8 `.lean` file or type Lean code in **Source**.
2. Include imports, any completed helpers, and one final named `theorem` or `lemma`.
   Use `sorry` for the proof you want the agents to complete.
3. Click **Run agent**. Follow compiler feedback and model calls in **Agent activity**.
4. Inspect **Result** and its verification status. Use **Copy**, **Use as source**,
   or **Download .lean** when the run finishes.

Example input:

```lean
import Mathlib

theorem addition_commutes (a b : Nat) : a + b = b + a := by
  sorry
```

Imports must exist in your configured Lean project. Earlier unfinished
declarations, anonymous examples, unsupported proof layouts, and arbitrary
commands after the target must be converted to a supported file layout first.
The system preserves the target's statement, imports, and preceding helpers.

An already-valid proof returns without model or retrieval calls. Otherwise,
formal proving is followed as needed by an informal outline and review,
discussion advice, a fresh formal attempt, and repairs using Lean feedback.
The search stops when Lean accepts a proof or a configured limit is reached.

A failed or exhausted run can return an **unverified candidate**, which you can
still download and inspect. It does not prove the theorem false. Only compiler
success and an axiom audit permitting `propext`, `Classical.choice`, and
`Quot.sound` produce verified status. Informal review alone cannot verify a proof.
Unfinished proofs, new axioms, native-evaluation proof escapes, compiler errors,
and timeouts cannot produce verified status. Acceptance uses local
`lake env lean` compilation followed by a `#print axioms` audit.

**Stop run** cancels later phases and local tool processes. An API request already
sent may continue remotely until completion or timeout. By default only one run
is processed at a time, with a two-hour run limit.

## Choose model providers and save keys

Built-in connections include **OpenRouter, DeepSeek, Groq, OpenAI, and Anthropic**.
Enter the exact model ID offered by your account for every role you change.
OpenRouter uses IDs such as `vendor/model`. Set token limits to values supported
by that model; choosing a provider does not adjust the limits automatically.

For another service, use **Model settings → Add an API provider**:

1. Enter a unique lowercase name using letters, digits, or underscores.
2. Select its API protocol and enter its base URL, without credentials or query parameters.
3. Click **Add provider**, paste its key in the new password field, and select the
   provider and model for the desired roles. Click **Apply settings**.

Connections are saved in local, Git-ignored `providers.local.json` and reload
on startup. Existing connection names cannot be overwritten through the UI;
use a new name for a different endpoint. Adding a connection does not start or
contact an inference server. Tool commands remain controlled by local TOML.

| API protocol | Use |
| --- | --- |
| Chat Completions (OpenAI-compatible) | Compatible hosted APIs, including OpenRouter, DeepSeek, and Groq |
| Anthropic Messages | Messages generation and `/messages/count_tokens` |
| OpenAI Responses | Responses generation and `/responses/input_tokens` |
| Self-hosted chat with `/tokenize` | Chat Completions with exact server-side prompt counting |

Native OpenAI/Anthropic and self-hosted adapters require the corresponding
counting API. Hosted Chat Completions uses a conservative UTF-8 byte estimate
with a formatting allowance, then records actual usage from the response when
provided. The estimate can remove more optional evidence than necessary and
cannot guarantee an exact count for every model or chat template. Vendor-specific
protocols require a supported compatible endpoint or an additional adapter.

API references: [OpenRouter](https://openrouter.ai/docs/api/reference/overview),
[DeepSeek](https://api-docs.deepseek.com/), and
[Groq](https://console.groq.com/docs/openai).

### API-key storage

Keys entered in **Model settings** are saved to `.env` with owner-only permissions.
The server never returns saved keys to the page or stores them in browser storage.
Blank fields keep the current key; the removal checkbox deletes the saved value.

You can alternatively copy `.env.example` to `.env` and fill it in locally, or
export the configured API-key environment variables before launching the app.
These include `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
`DEEPSEEK_API_KEY`, and `GROQ_API_KEY` for the built-in providers.
Nonempty `.env` values take precedence over exported values. Removing a saved
key still allows an exported key to be used. Changes apply to new runs; active
runs retain their original credentials.

The launcher uses the repository root for `.env`. `app.env_file` can specify a
different local file named `.env`; its parent directory must already exist.
The app reads this file as data and never executes it as a shell script. Keys
belong in `.env` or the environment, never in TOML or source code. `.env` and its
temporary files are Git-ignored; `.env.example` contains empty placeholders only.

### Bring your own model server

Arrange GPU access, upload your weights, tokenizer, and supporting files to your
own server, and start its inference service using your own tools. This repository
contains no GPU provisioning, model-upload, tunnel, or inference-serving scripts.
Only Lean files are uploaded through the proof interface.

Use **Add an API provider** with the server's reachable endpoint and served model
ID. Choose the self-hosted protocol for exact `/tokenize` counting, or Chat
Completions for a compatible API without that endpoint. Remote URLs require HTTPS;
HTTP is allowed for loopback connections you manage yourself.

Alternatively add a provider to `config/local.toml`, then restart the app:

```toml
[providers.my_model_server]
kind = "openai_compatible"
base_url = "https://your-model-server.example/v1"
api_key_env = "MODEL_SERVER_API_KEY"
timeout_seconds = 600
```

Select `my_model_server` and its exact model ID in Model settings. Paste its key
there if required; for an unauthenticated service, omit `api_key_env` in TOML.

The self-hosted protocol expects `/v1/chat/completions` and a `/tokenize` endpoint
accepting `model`, `messages`, `add_generation_prompt`, and `chat_template_kwargs`,
returning an integer `count` for that model's rendered prompt. Set
`count_tokens_path` to override the counting path relative to the server origin.
Connection details alone do not start a model service.

## Configure local Lean and retrieval

The CLI automatically loads `config/local.toml`; use `--config` for another file.
Paths in TOML resolve relative to that file's directory. The supplied example
uses `../runtime/...` because it lives inside `config/`.

Setup prepares Mathlib commit `2df2f0150c275ad53cb3c90f7c98ec15a56a1a67`
with Lean `4.26.0`. It refuses to overwrite a different existing checkout. To
use an existing compatible Lean project, set its path explicitly:

```toml
[lean]
project_path = "/absolute/path/to/your/lean-project"
command = ["lake", "env", "lean"]
lsp_command = ["lean-lsp-mcp"]
timeout_seconds = 240
lsp_timeout_seconds = 120
```

The launcher adds the prepared LeanExplore, Lean LSP, and elan executables to PATH.
Set `lean.lsp_command = []` to disable interactive goal inspection; compiler
verification still determines acceptance. Missing goal inspection is reported
in feedback and never grants proof acceptance.

The standard retrieval configuration in `config/local.toml` is:

```toml
[retrieval]
enabled = true
required = true
command = ["lean-explore", "mcp", "serve", "--backend", "local"]
cache_dir = "../runtime/lean-explore/cache"
hf_cache_dir = "../runtime/huggingface"
data_version = "20260714_172516"
packages = ["Mathlib", "Init"]
limit = 12
source_limit = 4
rerank_top = 0
```

Local retrieval uses LeanExplore `1.3.0`, index version `20260714_172516`, and
an embedding model stored under ignored `runtime/`. Setup prepares the index
and weights. Search then runs offline with `CUDA_VISIBLE_DEVICES` empty, using
the local hybrid lexical/semantic backend; cross-encoder reranking is
disabled. The index contains Lean/Mathlib declaration search material, not an
evaluation corpus. Retrieved declarations can differ from your project's library
revision; Lean compilation determines whether they are available and applicable.

A missing required retrieval service stops a run. To intentionally operate
without library search, set both values in `config/local.toml`:

```toml
[retrieval]
enabled = false
required = false
```

## Budgets and search limits

Edit `config/local.toml` and restart the app to change limits. Each role has its
own provider, model, input cap, output cap, and context window; input plus output
must fit the configured context. For permanent model choices, edit the matching
`[roles.formal_initial]`, `[roles.formal_reviser]`, `[roles.informal_generator]`,
`[roles.informal_reviewer]`, `[roles.discussion]`, or `[roles.fresh_formal]` table.

| Role | Input tokens | Output tokens | Context tokens |
| --- | ---: | ---: | ---: |
| Initial formal prover | 8,192 | 32,000 | 40,960 |
| Formal reviser | 12,288 | 24,576 | 40,960 |
| Informal generator | 8,192 | 16,384 | 32,768 |
| Informal reviewer | 12,288 | 8,192 | 32,768 |
| Discussion partner | 12,288 | 12,288 | 32,768 |
| Fresh formal prover | 8,192 | 32,000 | 40,960 |

The default ceiling is **five formal attempts**, including one fresh attempt,
and **seven supporting calls**: up to three generator/reviewer pairs and one
discussion call. An accepted proof stops the search early. The outline stage
starts after one failed model proof; discussion and the fresh attempt follow
after two failures. Only an approved `PASS` outline enables separate fact searches.

With every stage at its maximum, the sequence permits 126,976 input and 223,744
output tokens, excluding counting requests. These are caps, not expected usage
or a cost quote. Actual usage is recorded per run. Thinking tokens share the
output allowance, and calls do not share conversation history. Optional evidence
is removed as whole records to fit; the target and current candidate are retained.
Private reasoning transcripts are not copied to the reviewer or saved in metadata.

For Claude models requiring a fixed thinking budget, set
`thinking_mode = "enabled"` under `[providers.anthropic]`; the default is adaptive.
The same thinking configuration is supplied to counting and generation.

Retrieval defaults to 12 ranked hits, four source requests per search, five
uncached task queries, two approved-outline queries, and seven combined queries.
Results are cached within a run. Character caps are 12,000 for formal/repair,
6,000 for discussion, 8,000 for fresh proving, and 4,000 for each informal role.
Compiler/LSP feedback shares an 8,000-character cap; failure memory holds up to
two recent proof/error pairs within 6,000 characters.

## Output files and troubleshooting

Each run saves `input.lean`, `<name>_output.lean`, and `result.json` in a separate
local directory under `app.output_dir`. The example config uses `outputs/`;
without a config override, the default is `runtime/outputs/`. Run metadata records
progress, verification status, errors, and cumulative usage. Output files remain
on disk after the server stops; the browser's run history is session-scoped.

| Issue | What to check |
| --- | --- |
| Python 3.13 or Lake is missing | Install the prerequisites, set `PYTHON313` if needed, and check that elan is on PATH. |
| Lean imports fail | Check `lean.project_path`, the toolchain, and whether the imported libraries are built in that project. |
| Retrieval cannot start | Run the retrieval setup stage and check the configured executable and index paths, or explicitly disable retrieval. |
| Model endpoint cannot be reached | Check the service URL, network connection, and whether your model server is running. |
| API rejects a request | Check the provider key, exact model ID, account access, supported protocol, and model token limits. |
| Input budget is exceeded | Use a smaller task/context or increase the role's input cap while keeping input plus output within its model's context window. |
| Run agent or key entry is disabled on the public site | Open the local app; GitHub Pages hosts an interface preview only. |

Uploaded Lean code runs with your local user's permissions. Use files you trust
and keep the app bound to loopback. It is not a sandbox for untrusted uploads.
Source and model messages are sent to the providers selected for that run, so
use providers approved for the material you submit.

## Commands and development checks

From the repository root:

```bash
# Start on a different local port:
bash scripts/run-local.sh serve --port 8766
# Check a Lean file without model calls:
bash scripts/run-local.sh check /absolute/path/to/input.lean
# Print public settings without credentials:
bash scripts/run-local.sh print-config
# Use a different TOML configuration:
bash scripts/run-local.sh --config /absolute/path/to/settings.toml serve
# Run the fixture-based test suite:
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests check application behavior using injected services and dummy keys;
they do not measure mathematical accuracy. Real proof generation needs reachable
model services plus the configured local Lean and retrieval tools.

## GitHub Pages preview

The [published interface](https://cherrysowmya.github.io/formal-math-studio/)
supports exploring the editor and provider choices. Agent execution, `.env`
storage, and Lean verification require the local app. Key entry and proof runs
are disabled on the public site because GitHub Pages does not run Python services.

The Pages workflow tests the app and publishes only frontend assets and preset
configuration on pushes to `main`. It excludes local settings, keys, outputs,
Lean dependencies, and model files. To inspect the same static build locally:

```bash
python3 scripts/build-pages.py
python3 -m http.server 8767 --bind 127.0.0.1 --directory _site
```

Open **http://127.0.0.1:8767**. This is the preview, not the local agent server.

## License

MIT. See [LICENSE](LICENSE). The repository contains application code, frontend
assets, configuration examples, local setup scripts, and tests. Dependencies,
generated proofs, credentials, inference weights, and evaluation datasets are
not included in the tracked application source.
