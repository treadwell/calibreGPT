#!/bin/sh

set -e

PROMPT='Cloud Computing in Higher Education'
FP_FULLTEXT_DB='/Users/kbrooks/Dropbox/Books/Calibre Travel Library/full-text-search.db'
FP_METADATA_DB='/Users/kbrooks/Dropbox/Books/Calibre Travel Library/metadata.db'
FP_CALIBREGPT_DB='/Users/kbrooks/Dropbox/Books/Calibre Travel Library/calibregpt.db'
FP_FAISS_INDEX='/Users/kbrooks/Dropbox/Books/Calibre Travel Library/faiss.idx'

clear

echo "testing --prompt"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --match-count 10 \
    --prompt "$PROMPT"

echo "testing --ids"
python3 engine.py \
    --openai-token "$OPENAI_TOKEN" \
    --fulltext-db "$FP_FULLTEXT_DB" \
    --metadata-db "$FP_METADATA_DB" \
    --calibregpt-db "$FP_CALIBREGPT_DB" \
    --faiss-index "$FP_FAISS_INDEX" \
    --match-count 10 \
    --ids "40, 51"