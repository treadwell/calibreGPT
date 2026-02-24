#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./migrate_embeddings.sh --library-path PATH [options]

Required:
  --library-path PATH            Directory containing metadata.db/full-text-search.db

Options:
  --engine PATH                  Engine script path (default: ./engine.py)
  --embedding-model MODEL        Target model for migration (default: text-embedding-3-small)
  --active-model MODEL           Active query model used for normal queries (default: text-embedding-ada-002)
  --batch-size N                 Embedding batch size per migration step (default: 128)
  --sleep-seconds N              Pause between rounds (default: 5)
  --max-rounds N                 Stop after N rounds (default: 0, unlimited)
  --status-only                  Print migration status once and exit
  --debug                        Pass --debug to engine.py

Environment:
  OPENAI_TOKEN                   Required unless --status-only is used.
EOF
}

LIBRARY_PATH=""
ENGINE_PATH="./engine.py"
EMBEDDING_MODEL="text-embedding-3-small"
ACTIVE_MODEL="text-embedding-ada-002"
BATCH_SIZE="128"
SLEEP_SECONDS="5"
MAX_ROUNDS="0"
STATUS_ONLY="0"
DEBUG_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --library-path) LIBRARY_PATH="$2"; shift 2 ;;
    --engine) ENGINE_PATH="$2"; shift 2 ;;
    --embedding-model) EMBEDDING_MODEL="$2"; shift 2 ;;
    --active-model) ACTIVE_MODEL="$2"; shift 2 ;;
    --batch-size) BATCH_SIZE="$2"; shift 2 ;;
    --sleep-seconds) SLEEP_SECONDS="$2"; shift 2 ;;
    --max-rounds) MAX_ROUNDS="$2"; shift 2 ;;
    --status-only) STATUS_ONLY="1"; shift ;;
    --debug) DEBUG_FLAG="--debug"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$LIBRARY_PATH" ]]; then
  echo "Missing --library-path" >&2
  usage
  exit 1
fi

if [[ ! -f "$ENGINE_PATH" ]]; then
  echo "Engine not found: $ENGINE_PATH" >&2
  exit 1
fi

FP_FULLTEXT_DB="$LIBRARY_PATH/full-text-search.db"
FP_METADATA_DB="$LIBRARY_PATH/metadata.db"
FP_CALIBREGPT_DB="$LIBRARY_PATH/calibregpt.db"
FP_FAISS_INDEX="$LIBRARY_PATH/faiss.idx"

for db in "$FP_FULLTEXT_DB" "$FP_METADATA_DB"; do
  if [[ ! -f "$db" ]]; then
    echo "Required DB not found: $db" >&2
    exit 1
  fi
done

if [[ "$STATUS_ONLY" != "1" && -z "${OPENAI_TOKEN:-}" ]]; then
  echo "OPENAI_TOKEN is required for migration runs." >&2
  exit 1
fi

common_args=(
  --fulltext-db "$FP_FULLTEXT_DB"
  --metadata-db "$FP_METADATA_DB"
  --calibregpt-db "$FP_CALIBREGPT_DB"
  --faiss-index "$FP_FAISS_INDEX"
  --active-embedding-model "$ACTIVE_MODEL"
  --batch-size "$BATCH_SIZE"
)

if [[ -n "$DEBUG_FLAG" ]]; then
  common_args+=("$DEBUG_FLAG")
fi

run_engine() {
  python3 "$ENGINE_PATH" "${common_args[@]}" "$@"
}

print_status() {
  local output status error
  output="$(run_engine --embedding-model "$EMBEDDING_MODEL" migration-status)"
  error="$(printf '%s\n' "$output" | jq -r '.error // empty')"
  if [[ -n "$error" ]]; then
    echo "migration-status error: $error" >&2
    return 1
  fi
  status="$(printf '%s\n' "$output" | jq -c '.results')"
  printf '[%s] status %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$status"
}

if [[ "$STATUS_ONLY" == "1" ]]; then
  print_status
  exit 0
fi

round=0
while true; do
  print_status
  remaining="$(run_engine --embedding-model "$EMBEDDING_MODEL" migration-status | jq -r '.results.remaining')"
  if [[ "$remaining" == "0" ]]; then
    echo "Migration complete for model: $EMBEDDING_MODEL"
    break
  fi

  if [[ "$MAX_ROUNDS" != "0" && "$round" -ge "$MAX_ROUNDS" ]]; then
    echo "Reached max rounds ($MAX_ROUNDS). Remaining: $remaining"
    break
  fi

  output="$(run_engine --embedding-model "$EMBEDDING_MODEL" migrate-embeddings)"
  error="$(printf '%s\n' "$output" | jq -r '.error // empty')"
  if [[ -n "$error" ]]; then
    echo "migrate-embeddings error: $error" >&2
    exit 1
  fi
  result="$(printf '%s\n' "$output" | jq -c '.results')"
  printf '[%s] migrated %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$result"

  round=$((round + 1))
  sleep "$SLEEP_SECONDS"
done
