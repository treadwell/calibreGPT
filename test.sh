#!/bin/sh

PROMPT='I am proposing a college readiness website to help students without college preparation resources'
FP_FULLTEXT_DB='/Users/kbrooks/Dropbox/Books/calbreGPT/full-text-search.db'
FP_METADATA_DB='/Users/kbrooks/Dropbox/Books/calbreGPT/metadata.db'
FP_CALIBREGPT_DB='/Users/kbrooks/Dropbox/Books/calbreGPT/calibregpt.db'
FP_FAISS_INDEX='/Users/kbrooks/Dropbox/Books/calbreGPT/faiss.idx'

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
    --ids "1,2"