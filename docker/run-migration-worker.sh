#!/usr/bin/env bash
set -euo pipefail

args=(
  --engine "${ENGINE_PATH:-/app/engine.py}"
  --embedding-model "${EMBEDDING_MODEL:-text-embedding-3-small}"
  --active-model "${ACTIVE_MODEL:-text-embedding-ada-002}"
  --batch-size "${BATCH_SIZE:-64}"
  --sleep-seconds "${SLEEP_SECONDS:-2}"
  --max-cycles "${MAX_CYCLES:-0}"
)

if [[ -n "${LIBRARIES_FILE:-}" ]]; then
  args+=(--libraries-file "${LIBRARIES_FILE}")
fi

if [[ -n "${LIBRARY_PATH:-}" ]]; then
  args+=(--library-path "${LIBRARY_PATH}")
fi

if [[ "${STATUS_ONLY:-0}" == "1" ]]; then
  args+=(--status-only)
fi

exec python3 /app/migrate_multi_library.py "${args[@]}"
