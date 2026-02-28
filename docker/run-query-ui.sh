#!/usr/bin/env bash
set -euo pipefail

args=(
  --engine "${ENGINE_PATH:-/app/engine.py}"
  --active-model "${ACTIVE_MODEL:-text-embedding-ada-002}"
  --batch-size "${BATCH_SIZE:-64}"
  --host 0.0.0.0
  --port 8770
)

if [[ -n "${LIBRARIES_FILE:-}" ]]; then
  args+=(--libraries-file "${LIBRARIES_FILE}")
fi

if [[ -n "${LIBRARY_PATH:-}" ]]; then
  args+=(--library-path "${LIBRARY_PATH}")
fi

exec python3 /app/query_dashboard.py "${args[@]}"
