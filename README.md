# Formal Math Studio

A local web workspace for writing and repairing Lean 4 proofs. Upload a `.lean`
file or type a theorem, run the agent system, inspect the resulting Lean code,
and download the output file.

The browser, orchestration, Lean compiler, optional Lean LSP inspection,
LeanExplore retrieval, and output storage run on your computer. Each model role
can use Anthropic, OpenAI, or a configured OpenAI-compatible model service.

## Start locally

The [GitHub Pages site](https://cherrysowmya.github.io/formal-math-studio/)
is an interface preview. It supports exploring the editor and provider choices.
Running agents, saving API keys to `.env`, and verifying Lean proofs require the
local app below. The public preview disables key entry and proof execution.
GitHub Pages serves static files; it does not host the Python backend.

The Pages workflow tests the application and publishes only the frontend assets
and preset configuration. It never uploads local settings, API keys, outputs,
Lean dependencies, or model files. To build the same preview locally, run
`python3 scripts/build-pages.py` and serve `_site/` with a static web server.

Requires Python 3.11+ for the application, Python 3.13 for the optional local tool
environments, and a prepared Lean/Mathlib project. The web application itself
uses the Python standard library and ships all frontend assets locally.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp config/example.toml config/local.toml
# Prepare local Lean, Mathlib, LeanExplore, and optional LSP tooling:
bash scripts/setup-local.sh
bash scripts/run-local.sh
```

Open **http://127.0.0.1:8765**, open **Model settings**, paste your Anthropic or
OpenAI API key, and click **Apply settings**. The app saves keys in the repository's
local `.env` file and loads them automatically on later runs.

The app deliberately binds to loopback. Each run
writes `input.lean`, an output `.lean` file, and public progress/usage metadata
under the configured local output directory. Source files and model messages
are sent only to the model providers selected for that run. Do not use confidential
source with a provider you have not approved.

The application can also run directly with `bash scripts/run-local.sh` without
installing the Python package; the script uses Python 3 and the checked-out
source when `.venv` is absent. Local Lean/retrieval tools still need preparation.

See [local setup](docs/SETUP.md) for using an existing Lean installation.

## Workflow

1. Lock the final named theorem's statement, imports, and preceding helpers.
2. Check an existing complete proof locally. An already-valid file returns
   immediately without model or retrieval calls.
3. Retrieve relevant library declarations locally and generate a formal proof.
4. After one failed model proof, generate and independently review a mathematical
   outline. Only a `PASS` outline enables its separate fact searches.
5. After two failed model proofs, request discussion advice and one fresh formal
   proof in an isolated context.
6. Repair using local compiler feedback, stopping on verified success or the
   configured formal-attempt/time limit. The fresh attempt counts toward that limit.

Informal review is advice. A result is marked **verified** only when the local
Lean compiler accepts the complete assembled file and the axiom audit passes.
Failed runs can return an **unverified candidate**; the UI keeps that distinction
visible and still permits downloading it. A failed run does not prove a theorem false.

The first version targets **one final named theorem or lemma per file**, with
already-proved helpers and context before it. Namespace closures are preserved.
Earlier unfinished declarations, arbitrary commands after the target, and
unsupported proof layouts produce a clear error. Output assembly preserves the
original theorem rather than adopting model-generated declarations.

## Model providers

Every role has its own provider, model, input/output caps, and context window.
The settings drawer lets you select provider/model per role for a run. Budgets,
tool commands come from the local TOML configuration. Provider connections can
be added in Model settings. API keys
can be entered in the website and saved locally. Existing connections cannot be overwritten by the browser; tool commands remain
server-controlled.

All six roles use Claude Sonnet 5.5 (`claude-sonnet-5-5`) with adaptive thinking
by default.

Paste credentials into the password fields under **Model settings → API keys and
connections**. Click **Apply settings** to save them to `.env` with owner-only file
permissions. Saved values are never returned by the server or stored in browser
storage. Blank fields keep existing keys; the removal checkbox deletes a saved key.
`.env` and its temporary files are excluded by `.gitignore`; `.env.example` contains
empty placeholders only. The app reads `.env` as data, without executing shell code.

Exported `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` variables remain supported as
fallbacks. A nonempty saved `.env` key takes precedence over an exported key. Changes
apply to new runs; a run already in progress retains its original credentials.
By default `.env` lives in the working directory (the repository root when using
the launcher). Set `app.env_file` to another local `.env` path if needed; its parent
directory must already exist. Ignore rules are maintained alongside that file.

To use OpenAI, enter its key and select OpenAI and a model available to your
account in the settings drawer. Configure model-specific budgets in TOML if its
limits differ from the defaults. For a permanent route, override the corresponding
`[roles.formal_initial]`, `[roles.formal_reviser]`, etc. tables in
`config/local.toml`. Store only the API-key variable name in that configuration,
never the key itself.

For an open-weight model, bring your own running inference server and served
model name. You arrange GPU access, upload the model weights and supporting
files, and run the service yourself. Add a generic OpenAI-compatible provider
to `config/local.toml`, restart the app, and select it for the desired roles.
See [connection setup](docs/SETUP.md#bring-your-own-model-server). This repository
does not include GPU provisioning, model uploads, model-serving scripts, or
inference model weights.

The same thinking configuration is supplied to both token counting and
generation. For a Claude model that requires a fixed thinking budget, set
`thinking_mode = "enabled"` under `[providers.anthropic]`. Provider API
versions are configurable.

Provider protocols:

- OpenAI: Responses generation and `/responses/input_tokens` counting.
- Anthropic: Messages generation and `/messages/count_tokens` counting.
- OpenAI-compatible services: chat completions and `/tokenize` using the same
  model's chat template, including the thinking setting.

Native OpenAI/Anthropic and self-hosted adapters require service-side token
counting. Hosted Chat Completions providers use a conservative UTF-8 byte estimate
plus a formatting allowance before generation, and record actual prompt usage
from the response when available. This estimate may trim more evidence than
necessary and cannot guarantee the exact count for every model or chat template.
Optional evidence is removed as whole records to fit; the immutable task,
current goal, proposal under review, and current proof candidate are retained.
Thinking tokens share the output allowance. No private reasoning transcripts
are copied to the reviewer or saved in run metadata.

## Additional API providers

Model settings includes OpenRouter, DeepSeek, and Groq, in addition to OpenAI
and Anthropic. Paste the chosen provider's key and enter its exact model ID for
each role. OpenRouter uses IDs such as `vendor/model`; model availability and
supported output limits depend on the provider and account.

Use **Add an API provider** for other services. Enter a unique connection name,
API protocol, and base URL, then add its key in the new password field. Connections
are saved locally in Git-ignored `providers.local.json` and reload automatically;
keys remain separately in `.env`. Adding a provider does not contact its server.
Choose Chat Completions for compatible hosted APIs, Anthropic Messages or OpenAI
Responses for those protocols, or the self-hosted option for exact `/tokenize`
counting. Arbitrary vendor-specific protocols require an adapter or a compatible
endpoint. Configure role budgets in TOML to match the chosen model's limits.

API references: [OpenRouter](https://openrouter.ai/docs/api/reference/overview),
[DeepSeek](https://api-docs.deepseek.com/), and
[Groq](https://console.groq.com/docs/openai).

## Baseline budgets

| Role | Input tokens | Output tokens | Context tokens |
| --- | ---: | ---: | ---: |
| Initial formal prover | 8,192 | 32,000 | 40,960 |
| Formal reviser | 12,288 | 24,576 | 40,960 |
| Informal generator | 8,192 | 16,384 | 32,768 |
| Informal reviewer | 12,288 | 8,192 | 32,768 |
| Discussion partner | 12,288 | 12,288 | 32,768 |
| Fresh formal prover | 8,192 | 32,000 | 40,960 |

Each call is stateless. Five formal attempts include the single fresh attempt;
the informal stage permits three generator/reviewer pairs. Input checks also
include complete role instructions and chat formatting. There is no hidden
512-token legacy/reset policy.

The earlier illustrative 73,728-input / 150,016-output trajectory describes
four formal calls and one informal pair, not the ceiling for this five-attempt,
three-pair configuration. Actual cumulative usage is recorded per run. With
all stages used at their per-call limits, the configured call sequence allows
126,976 input and 223,744 output tokens before any additional counting requests.

Local retrieval uses 12 ranked hits, at most four source requests per search,
five uncached task queries, two approved-outline queries, and seven combined.
Results are cached within a run and reused across roles. Retrieval packet caps
are 12,000 characters for formal/repair, 6,000 for discussion, 8,000 for fresh
proving, and 4,000 for each informal role. Compiler/LSP feedback has one combined
8,000-character cap, and failure memory has a 6,000-character/two-pair cap.

## Commands and checks

```bash
formal-math-studio --config config/local.toml serve --port 8765
formal-math-studio --config config/local.toml check /absolute/path/to/input.lean
formal-math-studio --config config/local.toml print-config
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The checks use small injected service fixtures to exercise workflow contracts;
they do not measure mathematical accuracy. A real provider run requires reachable
model services or API credentials, plus the local Lean and retrieval setup.

The CLI automatically loads `config/local.toml` when it exists; `--config`
selects a different file. Relative paths are resolved against that file's directory.

Cancellation stops subsequent local phases and interrupts local tool processes.
An already-sent synchronous API generation may continue at its provider until it
completes or times out. By default the server processes one run at a time to avoid overlapping
local verification and unbounded inference requests.

## Repository scope

This repository contains application source, local frontend assets,
configuration examples, local tool setup scripts, and focused runtime tests.
It contains no evaluation corpora, scoring runners, archived research results,
downloaded model weights, or vendored tool repositories. Mathlib and the
LeanExplore library index are runtime dependencies fetched outside the tracked
source tree; the index is necessary for lemma search. Generated proofs and
credentials are ignored by Git.

Local compiler checking runs with the permissions of the local user. This app
is intended for your own Lean files on loopback, not as a hosted service for
untrusted uploads. It is not an operating-system sandbox.

## License

MIT. See [LICENSE](LICENSE).
