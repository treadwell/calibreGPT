from engine import run_query
import os

PROMPT = "I am proposing a college readiness website to help students without college preparation resources"
# PROMPT = "The sky is blue, the grass is green." 

OPENAI_TOKEN  = os.environ.get('OPENAI_TOKEN')
FP_FULLTEXT_DB = '/Users/kbrooks/Dropbox/Books/calbreGPT/full-text-search.db' 
FP_METADATA_DB = '/Users/kbrooks/Dropbox/Books/calbreGPT/metadata.db'
FP_CALIBREGPT_DB = '/Users/kbrooks/Dropbox/Books/calbreGPT/calibregpt.db'
FP_FAISS_INDEX = '/Users/kbrooks/Dropbox/Books/calbreGPT/faiss.idx'

ranking = run_query(PROMPT, 
                    OPENAI_TOKEN,
                    FP_FULLTEXT_DB, 
                    FP_METADATA_DB, 
                    FP_CALIBREGPT_DB,
                    FP_FAISS_INDEX)

print(ranking)