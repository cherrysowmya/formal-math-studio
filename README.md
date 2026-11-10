# Formal Math Studio

A local web workspace for writing and repairing Lean 4 proofs. Upload a `.lean`
file or type a theorem, run the agent system, inspect the resulting Lean code,
and download the output file.

The browser, orchestration, Lean compiler, optional Lean LSP inspection,
LeanExplore retrieval, and output storage run on your computer. Model inference
uses independently configured providers: OpenAI, Anthropic, or open-weight
models served on NVwulf through SSH tunnels. No application hosting is needed.

## Start locally

Requires Python 3.11+ for the application, Python 3.13 for the optional local tool
environments, and a prepared Lean/Mathlib project. The web application itself
uses the Python standard library and ships all frontend assets locally.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp config/example.toml config/local.toml
# Prepare local Lean, Mathlib, LeanExplore, and optional LSP tooling:
bash scripts/setup-local.sh
# Connect model endpoints, or configure API providers as described below.
bash scripts/run-local.sh
```

Open **http://127.0.0.1:8765**. The app deliberately binds to loopback. Each run
writes `input.lean`, an output `.lean` file, and public progress/usage metadata
under the configured local output directory. Source files and model messages
are sent only to the model providers selected for that run. Do not use confidential
source with a provider you have not approved.

The application can also run directly with `bash scripts/run-local.sh` without
installing the Python package; the script uses Python 3 and the checked-out
source when `.venv` is absent. Local Lean/retrieval tools still need preparation.

See [local setup](docs/SETUP.md) for using an existing Lean installation and
[NVwulf model serving](docs/NVWULF.md) for model-only deployment and tunneling.

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
service URLs, tool commands, and credentials are controlled by the local TOML
configuration and server environment; the browser cannot replace service URLs
or execute commands.

Default routing is `m-a-p/OProver-32B` for formal work and `Qwen/Qwen3-8B` for
informal roles. Both use NVwulf endpoints forwarded to local ports 8081/8082.

For APIs, export credentials in the same shell that launches the local app:

```bash
export OPENAI_API_KEY='your-key'
export ANTHROPIC_API_KEY='your-key'
bash scripts/run-local.sh
```

Then choose a provider and an actual model name available to your account in
the settings drawer. Configure model-specific budgets in TOML if its limits
differ from the defaults. For a permanent route, override the corresponding
`[roles.formal_initial]`, `[roles.formal_reviser]`, etc. tables in
`config/local.toml`. Keys are read from environment-variable names, never stored
in source or browser storage. `.env.example` is documentation; the server does
not automatically execute or load `.env` files.

For Claude models requiring adaptive thinking, set `thinking_mode = "adaptive"`
under `[providers.anthropic]`. The same thinking configuration is supplied to
both token counting and generation. Provider API versions are configurable.

Provider protocols:

- OpenAI: Responses generation and `/responses/input_tokens` counting.
- Anthropic: Messages generation and `/messages/count_tokens` counting.
- NVwulf/vLLM: OpenAI-compatible chat completions and `/tokenize` using the same
  model's chat template, including the thinking setting.

Exact service-side token counting is required before generation. An endpoint
without the supported counting API fails visibly instead of silently guessing.
Optional evidence is removed as whole records to fit; the immutable task,
current goal, proposal under review, and current proof candidate are retained.
Thinking tokens share the output allowance. No private reasoning transcripts
are copied to the reviewer or saved in run metadata.

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
configuration examples, setup/deployment scripts, and focused runtime tests.
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
