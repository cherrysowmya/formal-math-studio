#!/usr/bin/env bash
# Run on the local machine. A ProxyJump connection terminates on the compute node,
# allowing its loopback-bound model servers to stay private.
set -euo pipefail
[[ $# -eq 2 ]] || { echo 'Usage: deploy/tunnel-models.sh USER@LOGIN_HOST USER@ALLOCATED_COMPUTE_HOST' >&2; exit 2; }
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -J "$1" -L 127.0.0.1:8081:127.0.0.1:8081 \
  -L 127.0.0.1:8082:127.0.0.1:8082 "$2"
