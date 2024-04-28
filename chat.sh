#!/bin/bash

set -e
set -o pipefail

# LIBRARY_NAME='Fiction Library'
LIBRARY_NAME='Calibre Travel Library'
# LIBRARY_NAME='Yoga Calibre Library'

BASE_PATH="/Users/kbrooks/Dropbox/Books/$LIBRARY_NAME"
FP_FULLTEXT_DB="$BASE_PATH/full-text-search.db"
FP_METADATA_DB="$BASE_PATH/metadata.db"
FP_CALIBREGPT_DB="$BASE_PATH/calibregpt.db"
FP_FAISS_INDEX="$BASE_PATH/faiss.idx"

state=""

while true; do
    read -p 'user] ' prompt
    state="$(python3 engine.py \
        --openai-token "$OPENAI_TOKEN" \
        --fulltext-db "$FP_FULLTEXT_DB" \
        --metadata-db "$FP_METADATA_DB" \
        --calibregpt-db "$FP_CALIBREGPT_DB" \
        --faiss-index "$FP_FAISS_INDEX" \
        --match-count 5 \
        --debug \
        generate-response \
        --state "$state" --prompt "$prompt" | \
            jq -c '.results')"
    printf "%s" "$state" | jq > .chat.json
    printf "assistant] "
    printf "%s" "$state" | jq -r '.[].content' | tail -n1
done