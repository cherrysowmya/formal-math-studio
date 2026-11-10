#!/usr/bin/env bash
#SBATCH --job-name=formal-math-models
#SBATCH --partition=h200x4
#SBATCH --nodes=1
#SBATCH --gpus=2
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --output=formal-math-models-%j.log
# Only model inference lives on NVwulf. Submit from a vLLM-ready environment.
set -euo pipefail
: "${NVWULF_API_KEY:?Set a private NVWULF_API_KEY in your job environment}"
export VLLM_API_KEY="$NVWULF_API_KEY"
python_bin="${VLLM_PYTHON:-python}"
formal_port="${FORMAL_PORT:-8081}"
informal_port="${INFORMAL_PORT:-8082}"
gpu_list="${CUDA_VISIBLE_DEVICES:?Submit with two allocated GPUs}"
IFS=',' read -r -a allocated_gpus <<< "$gpu_list"
[[ ${#allocated_gpus[@]} -ge 2 ]] || { echo 'Two allocated GPUs are required, one per resident model.' >&2; exit 1; }
formal_pid=''
informal_pid=''
cleanup() {
  [[ -z "$formal_pid" ]] || kill "$formal_pid" 2>/dev/null || true
  [[ -z "$informal_pid" ]] || kill "$informal_pid" 2>/dev/null || true
  wait || true
}
trap cleanup EXIT INT TERM
echo "Model host: $(hostname). Both endpoints bind loopback; use the documented SSH tunnel."
CUDA_VISIBLE_DEVICES="${allocated_gpus[0]}" "$python_bin" -m vllm.entrypoints.openai.api_server \
  --model m-a-p/OProver-32B --served-model-name m-a-p/OProver-32B \
  --host 127.0.0.1 --port "$formal_port" \
  --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 40960 \
  --gpu-memory-utilization 0.85 --max-num-seqs 1 --reasoning-parser qwen3 &
formal_pid=$!
CUDA_VISIBLE_DEVICES="${allocated_gpus[1]}" "$python_bin" -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-8B --served-model-name Qwen/Qwen3-8B \
  --host 127.0.0.1 --port "$informal_port" \
  --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization 0.65 --max-num-seqs 1 --reasoning-parser qwen3 &
informal_pid=$!
# Exit if either service exits; cleanup terminates the remaining process.
while kill -0 "$formal_pid" 2>/dev/null && kill -0 "$informal_pid" 2>/dev/null; do sleep 2; done
echo 'One model server exited. Inspect this job log for details.' >&2
exit 1
