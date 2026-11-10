# NVwulf: model inference only

NVwulf hosts only the two open-weight model servers. Keep the browser app,
agent controller, Lean/Mathlib, Lean-LSP-MCP, LeanExplore, uploaded files,
run records, and downloadable results on your local machine.

The included Slurm launcher requests two H200 GPUs on one node: one for
`m-a-p/OProver-32B` (BF16, context 40,960), one for `Qwen/Qwen3-8B`
(BF16, context 32,768). This avoids competing memory pools for two resident
servers. Actual startup memory and tokenizer compatibility must be verified on
the allocated node; context-window support alone does not establish throughput.

Prepare a CUDA-compatible vLLM environment on the cluster using its supported
module/container workflow. Set `VLLM_PYTHON` to that environment's Python.
The server must support Qwen3, the `qwen3` reasoning parser, and the `/tokenize`
endpoint for chat messages. Model weights download to the cluster's normal
Hugging Face cache. Only this file needs to be copied to submit the job:

```bash
export NVWULF_API_KEY='a-long-private-random-value'
export VLLM_PYTHON=/your/vllm/environment/bin/python
sbatch deploy/nvwulf-models.slurm
```

If the earlier NVwulf inference environment is already installed, set
`MODEL_RUNTIME_ROOT` to its `.runtime` directory before submission. The launcher
reuses its vLLM executables, model cache, and build-tool paths; it does not start
the earlier agent harness or copy any local tools to the cluster. The batch shell
loads the site's `miniconda/3` module before starting the two model services.

Use the same private key in your local shell. Both servers bind `127.0.0.1`
and require API authentication via `VLLM_API_KEY`; they are not public services.
The job log prints the allocated compute hostname. Confirm that both servers
report successful startup before connecting. The job exits and cleans up if
either server exits.

## Forward model ports to your local machine

If your cluster permits SSH to allocated compute nodes through its login host:

```bash
bash deploy/tunnel-models.sh USER@LOGIN_HOST USER@ALLOCATED_COMPUTE_HOST
```

The destination of the SSH session must be the compute node. Forwarding from
the login host directly to a compute-node network address cannot reach a service
bound only to compute-node loopback. If compute-node SSH is unavailable, use
the cluster's supported authenticated interactive-node tunnel instead; do not
change the model service to a public bind address to work around this.

Keep the tunnel open. Your local provider endpoints are then:

| Provider | Local URL | Model |
| --- | --- | --- |
| `nvwulf_formal` | `http://127.0.0.1:8081/v1` | `m-a-p/OProver-32B` |
| `nvwulf_informal` | `http://127.0.0.1:8082/v1` | `Qwen/Qwen3-8B` |

Export `NVWULF_API_KEY` locally and start the local application. The app sends
only bounded model prompts to those endpoints. Reasoning tokens consume the
same generated-output allowance as final text. No hosted provider or model
availability is simulated when a service is missing.

For a different open-weight model, update its cluster launch command, configured
role model name, supported input/output/context limits, and tokenizer settings
together. Other API providers can serve any role independently of NVwulf.
Do not start the local harness or local tool servers in the Slurm job.
