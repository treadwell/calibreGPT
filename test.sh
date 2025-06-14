#!/bin/sh

set -e
set -o pipefail

PROMPT='Tai Chi Brush Knee'

# LIBRARY_NAME='Fiction Library'
# LIBRARY_NAME='Calibre Travel Library'
LIBRARY_NAME='Yoga Calibre Library'

BASE_PATH="/Users/kbrooks/Dropbox/Books/$LIBRARY_NAME"
FP_FULLTEXT_DB="$BASE_PATH/full-text-search.db"
FP_METADATA_DB="$BASE_PATH/metadata.db"
FP_CALIBREGPT_DB="$BASE_PATH/calibregpt.db"
FP_FAISS_INDEX="$BASE_PATH/faiss.idx"

clear

echo "testing find-similar-chunks --prompt"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --match-count 10 \
    --debug \
    find-similar-chunks \
    --prompt "$PROMPT" | jq

echo "testing find-similar-chunks --ids"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --match-count 10 \
    --debug \
    find-similar-chunks \
    --ids "1, 2" | jq

echo "testing generate-response --prompt"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --match-count 5 \
    --debug \
    generate-response \
    --prompt "$PROMPT" | jq

echo "testing find-unindexed"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --debug \
    find-unindexed | jq