import sqlite3
import certifi
import ssl
import os
import faiss
import http.client
import json
import numpy as np 
import sys
import string
import math
import time
import random

DEBUG = False
DEBUG_FILE = None

def debug(*args):
    if DEBUG:
        print(*args, file = sys.stderr)
        print(*args, file = DEBUG_FILE)

def open_db(fp, auto_create = True, wal = False):
    if not auto_create and not os.path.exists(fp):
        raise ValueError("DB doesn't exist: " + fp)   
    conn = sqlite3.connect(fp, isolation_level = "DEFERRED")
    if wal:
        cursor = conn.cursor()
        cursor.execute("pragma journal_mode = WAL")
        cursor.execute("pragma synchronous = NORMAL")
    return conn
 
def close_db(db):
    db.close()

class FullTextTimestampsIter():
    def __init__(self, fulltext_db, metadata_db):
        self.cursor_md = metadata_db.cursor()
        self.cursor_md.execute("select id from books")
        self.fulltext_db = fulltext_db
    def __iter__(self):
        return self
    def __next__(self):
        while True:
            row = self.cursor_md.fetchone()
            if not row:
                raise StopIteration
            cursor_ft = self.fulltext_db.cursor()
            cursor_ft.execute("select book, timestamp from books_text where book = ?", [row[0]])
            row = cursor_ft.fetchone()
            if row is not None:
                return row

def check_metadata_id_exists(db, id):
    cursor = db.cursor()
    cursor.execute("select id from books where id = ?", [id])
    return cursor.fetchone() is not None

def check_calibregpt_id_exists(db, id):
    cursor = db.cursor()
    cursor.execute("select id from books where id = ?", [id])
    return cursor.fetchone() is not None

class CalibreUpdatesIter():
    def __init__(self, fulltext_db, calibregpt_db, metadata_db):
        self.state = "fulltext"
        self.fulltextiter = FullTextTimestampsIter(fulltext_db, metadata_db)
        self.calibregptiter = CalibreGptIdsIter(calibregpt_db)
        self.calibregpt_db = calibregpt_db
        self.fulltext_db = fulltext_db
        self.metadata_db = metadata_db
    def __iter__(self):
        return self
    def __next__(self):
        while True:
            if self.state == "fulltext":
                try:
                    id, timestamp = next(self.fulltextiter)
                    debug("\nCalibre Updates Iterator - fulltext: ", id)
                    row = get_calibregpt_timestamp(self.calibregpt_db, id)
                    if not row:
                        return (id, timestamp, "new")
                    _, timestamp0 = row
                    if timestamp0 < timestamp:
                        return (id, timestamp, "update")
                except StopIteration:
                    self.state = "gpt"
                    continue
            elif self.state == "gpt":
                try:
                    id = next(self.calibregptiter)
                    debug("\nCalibre Updates Iterator - gpt: ", id)
                    if not check_metadata_id_exists(self.metadata_db, id):
                        return (id, None, "delete")
                except StopIteration:
                    raise StopIteration
            else:
                raise ValueError("Invalid state: " + self.state)

class BookChunksIter():
    def __init__(self, id, db, chunk_size, overlap_percent):
        self.overlap_size = math.floor(chunk_size * overlap_percent)
        self.chunk_size = math.floor(chunk_size - 2 * self.overlap_size)
        debug("Check chunks:", self.overlap_size, self.chunk_size, chunk_size, overlap_percent)
        self.position = 0
        cursor = db.cursor()
        cursor.execute("select searchable_text from books_text where book = ?", [id])
        row = cursor.fetchone()
        self.text = "".join(filter(lambda x: x in string.printable, row[0]))
        self.text_length = len(self.text)
    def __iter__(self):
        return self
    def __next__(self):
        debug("Book Chunks Iterator - next")
        if self.position >= self.text_length:
            raise StopIteration
        start_idx = self.position - self.overlap_size
        if start_idx < 0:
            start_idx = 0
        end_idx = self.position + self.chunk_size + self.overlap_size
        if end_idx > self.text_length - 1:
            end_idx = self.text_length - 1
        # TODO: cutting words in half at boundaries
        self.position = end_idx + 1
        debug("BCI start: ", start_idx, "BCI end: ", end_idx, "BCI position: ", self.position)
        return self.text[start_idx:end_idx]

class BookChunksEmbeddingsIter():
    def __init__(self, ids, db):
        debug(ids)
        self.cursor = db.cursor()
        self.cursor.execute(f"select embedding from book_chunks where id_book in ({','.join(['?' for _ in ids])})", list(map(int, ids)))
    def __iter__(self):
        return self
    def __next__(self):
        row = self.cursor.fetchone()
        if not row:
            raise StopIteration
        return row[0]
    
class MissingChunksIterator():
    def __init__(self, db):
        self.cursor = db.cursor()
        self.cursor.execute(f"select id, text from book_chunks where embedding is null")
    def __iter__(self):
        return self
    def __next__(self):
        row = self.cursor.fetchone()
        if not row:
            raise StopIteration
        return { "id": row[0], "text": row[1] }

def exp_backoff(fn, args=(), initial_wait=5.0, max_wait=32.0, backoff_factor=2.0, jitter_factor=0.5, max_tries=5):
    wait_time = initial_wait
    tries = 0
    while True:
        try:
            return fn(*args)
        except Exception as e:
            tries += 1
            if tries > max_tries:
                raise e
            debug(f"Attempt {tries}: Failed: {e}, retrying in {wait_time} seconds...")
            jitter = wait_time * jitter_factor * random.random()
            final_wait_time = min(wait_time + jitter, max_wait)
            time.sleep(final_wait_time)
            wait_time = min(final_wait_time * backoff_factor, max_wait)

def fetch_embeddings_nobackoff(chunks, token):
    for chunk in chunks:
        debug("fetch embedding: ", chunk[:50].replace('\n', ' ').replace('\r', ''))
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(certifi.where())
    connection = http.client.HTTPSConnection("api.openai.com", context=ssl_ctx)
    connection.request("POST", "/v1/embeddings", json.dumps({ 
        "input": chunks, 
        "model": "text-embedding-ada-002"
    }), {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
    })
    response = connection.getresponse()
    if response.status != 200:
        raise ValueError("OpenAI call failed " + str(response.status) + " with reason: " + response.reason)
    body = response.read()
    data = json.loads(body)
    return list(map(lambda x: np.array(x["embedding"]), data["data"]))

def fetch_embeddings(chunks, token):
    chunks = list(chunks)
    return exp_backoff(fetch_embeddings_nobackoff, (chunks, token))

def fetch_embedding(chunk, token):
    return fetch_embeddings([chunk], token)[0]

def fetch_missing_embeddings_(chunks, calibregpt_db, faiss_index, token):
    embeddings = fetch_embeddings(map(lambda x: x["text"], chunks), token)
    cursor_gpt = calibregpt_db.cursor()
    for chunk, embedding in zip(chunks, embeddings):
        cursor_gpt.execute("update book_chunks set embedding = ? where id = ?", [embedding, chunk["id"]])
    faiss_index.add_with_ids(np.vstack(embeddings), np.array(list(map(lambda x: x["id"], chunks))))

def fetch_missing_embeddings(batch_size, calibregpt_db, faiss_index, token):
    chunks = []
    for mc in MissingChunksIterator(calibregpt_db):
        chunks.append(mc)
        if len(chunks) >= batch_size:
            fetch_missing_embeddings_(chunks, calibregpt_db, faiss_index, token)
            chunks = []
    if len(chunks) > 0:
        fetch_missing_embeddings_(chunks, calibregpt_db, faiss_index, token)

def get_chunk_text(calibregpt_db, chunk_id):
    cursor = calibregpt_db.cursor()
    cursor.execute("select text from book_chunks where id = ?", [chunk_id])
    return cursor.fetchone()[0]

def fetch_gpt_nobackoff(messages, token):
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(certifi.where())
    connection = http.client.HTTPSConnection("api.openai.com", context=ssl_ctx)
    body = json.dumps({ 
        "messages": messages, 
        "model": "gpt-4"
    })
    connection.request("POST", "/v1/chat/completions", body, {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
    })
    response = connection.getresponse()
    if response.status != 200: 
        raise ValueError("OpenAI call failed " + str(response.status) + " with reason: " + response.reason)
    body = response.read()
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]

def fetch_gpt(messages, token):
    return exp_backoff(fetch_gpt_nobackoff, (messages, token))

def generate_response(calibregpt_db, openai_token, ranking, prompt):
    messages = [{"role": "system", "content": get_chunk_text(calibregpt_db, r["chunk_id"])} for r in ranking]
    messages = messages + [{"role": "user", "content": prompt}]
    return fetch_gpt(messages, openai_token)

def commit_updates(calibregpt_db, faiss_index, faiss_index_fp):
    calibregpt_db.commit()
    persist_faiss_index(faiss_index, faiss_index_fp)

def update_indices(fulltext_db, metadata_db, calibregpt_db, faiss_index, faiss_index_fp, updates, token, batch_size, chunk_size, overlap_percent):
    debug("starting update_indices")
    # TODO: return/print number of books added or updated
    num_new_chunks = 0
    for update in updates:
        (id, timestamp, type) = update
        if type == "update" or type == "delete":
            debug("update indices - " + type)
            cursor = calibregpt_db.cursor()
            chunk_ids = cursor.execute("select id from book_chunks where id_book = ?", [id]).fetchall()
            faiss_index.remove_ids(faiss.IDSelectorBatch(np.array(chunk_ids)))
            cursor.execute("delete from book_chunks where id_book = ?", [id])
            cursor.execute("delete from books where id = ?", [id])
            if type == "update":
                type = "new"
            else:
                commit_updates(calibregpt_db, faiss_index, faiss_index_fp)
        if type == "new":
            debug("update indices - new")
            cursor_md = metadata_db.cursor()
            cursor_md.execute("select id, title, author_sort from books where id = ?", [id])
            id, title, author = cursor_md.fetchone()
            cursor_gpt = calibregpt_db.cursor()
            cursor_gpt.execute("insert into books (id, timestamp, title, author) values (?, ?, ?, ?)", [id, timestamp, title, author])
            sequence = 0
            for chunk in BookChunksIter(id, fulltext_db, chunk_size, overlap_percent):
                debug("update indices - update chunks")
                cursor_gpt.execute("insert into book_chunks (id_book, sequence, text) values (?, ?, ?)", [id, sequence, chunk])
                sequence += 1
                num_new_chunks += 1
                if num_new_chunks >= batch_size:
                    fetch_missing_embeddings(batch_size, calibregpt_db, faiss_index, token)
                    commit_updates(calibregpt_db, faiss_index, faiss_index_fp)
                    num_new_chunks = 0
    # TODO: only persist index if chunks are added or deleted
    # TODO: make sure this isn't called even when not needed.
    fetch_missing_embeddings(batch_size, calibregpt_db, faiss_index, token)
    commit_updates(calibregpt_db, faiss_index, faiss_index_fp)

def setup_calibregpt_db(calibregpt_db):
    cursor = calibregpt_db.cursor()
    cursor.execute("""
        create table if not exists books (
            id integer primary key,
            author text not null,
            title text not null,
            timestamp integer not null
        );
    """)
    cursor.execute("""
        create table if not exists book_chunks (
            id integer primary key,
            id_book integer references books(id),
            sequence integer not null,
            text text not null,
            embedding blob 
        );
    """)
    cursor.execute("""
        create index if not exists book_chunks_id_book on book_chunks (id_book);
    """)
    cursor.execute("""
        drop index if exists book_chunks_embedding;
    """)
    cursor.execute("""
        create index if not exists book_chunks_embedding_exists on book_chunks(embedding) where embedding is null;
    """)
    calibregpt_db.commit()

def get_calibregpt_timestamp(db, id):
    cursor = db.cursor()
    cursor.execute("select id, timestamp from books where id = ?", [id])
    return cursor.fetchone()

class CalibreGptIdsIter():
    def __init__(self, db):
        self.cursor = db.cursor()
        self.cursor.execute("select id from books")
    def __iter__(self):
        return self
    def __next__(self):
        row = self.cursor.fetchone()
        if not row:
            raise StopIteration
        id = row[0]
        return id

##### FAISS index handling
def open_faiss_index(fp):
    if os.path.exists(fp):
        return faiss.read_index(fp)
    else:
        # should be IndexFlatIP to leverage dot product speed
        return faiss.IndexIDMap(faiss.IndexFlatL2(1536))

def persist_faiss_index(faiss_index, fp):
    debug("Persist faiss index start")
    faiss.write_index(faiss_index, fp)
    debug("Persist faiss index done")
    return
    
def search_faiss_index(faiss_index, prompt_embedding, calibregpt_db, match_count):
    ranks, ids = faiss_index.search(np.array([prompt_embedding]), match_count)
    results = []
    for chunk_id, rank in zip(np.nditer(ids), np.nditer(ranks)):
        chunk_id = chunk_id.item(0)
        rank = rank.item(0)
        cursor = calibregpt_db.cursor()
        cursor.execute("select b.id, b.author, b.title, c.text from books b, book_chunks c where b.id = c.id_book and c.id = ?", [chunk_id])
        row = cursor.fetchone()
        if row is not None:
            (book_id, author, title, excerpt) = row
            results.append(dict(
                book_id = book_id,
                chunk_id = chunk_id,
                distance = rank,
                author = author,
                title = title,
                excerpt = excerpt[:50].replace("\n", " ")
            ))
        else:
            debug(f"No data found for chunk_id: {chunk_id}")

    return results

class NoFulltextDataError(Exception):
    pass

def merge_book_embeddings(ids, db):
    arrays = list(map(lambda c: np.frombuffer(c, dtype = "float64"), 
                 BookChunksEmbeddingsIter(ids, db)))
    if len(arrays) == 0:
        raise NoFulltextDataError()
    return np.mean(np.vstack(arrays), axis = 0)

def get_prompt(opts, calibregpt_db):
    if opts.prompt:
        return fetch_embedding(opts.prompt, opts.openai_token)
    elif opts.ids:
        return merge_book_embeddings(opts.ids.split(","), calibregpt_db)
    else:
        raise ValueError('Neither prompt nor ids provided.')

def run_query(opts):

    openai_token = opts.openai_token
    fp_fulltext_db = opts.fulltext_db
    fp_metadata_db = opts.metadata_db
    fp_calibregpt_db = opts.calibregpt_db
    fp_faiss_index = opts.faiss_index
    match_count = int(opts.match_count)
    batch_size = int(opts.batch_size)
    chunk_size = int(opts.chunk_size)
    overlap_percent = float(opts.overlap_percent)

    fulltext_db = open_db(fp_fulltext_db, False)
    metadata_db = open_db(fp_metadata_db, False)
    calibregpt_db = open_db(fp_calibregpt_db, True, True)
    setup_calibregpt_db(calibregpt_db)
    faiss_index = open_faiss_index(fp_faiss_index)

    updates = CalibreUpdatesIter(fulltext_db, calibregpt_db, metadata_db)

    update_indices(fulltext_db, metadata_db, calibregpt_db, faiss_index, fp_faiss_index, updates, openai_token, batch_size, chunk_size, overlap_percent)

    result = None

    prompt_embedding = get_prompt(opts, calibregpt_db)
    ranking = search_faiss_index(faiss_index, prompt_embedding, calibregpt_db, match_count)

    if opts.command == "find-similar-chunks":
        result = ranking
    elif opts.command == "generate-response":
        result = generate_response(calibregpt_db, openai_token, ranking, opts.prompt)
    
    close_db(fulltext_db)
    close_db(metadata_db)
    close_db(calibregpt_db)

    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog = 'CalibreGPT')
    parser.add_argument('--debug', action = 'store_true')
    parser.add_argument('--debug-file')
    parser.add_argument('--openai-token')
    parser.add_argument('--fulltext-db')
    parser.add_argument('--metadata-db')
    parser.add_argument('--calibregpt-db')
    parser.add_argument('--faiss-index')
    parser.add_argument('--chunk-size', default = 4096)
    parser.add_argument('--overlap-percent', default = 0.2)
    parser.add_argument('--match-count', default = 30)
    parser.add_argument('--batch-size', default = 2048)
    subparsers = parser.add_subparsers(required = True, dest = "command")
    cmd_find_similar_chunks = subparsers.add_parser("find-similar-chunks")
    mutex = cmd_find_similar_chunks.add_mutually_exclusive_group()
    mutex.add_argument('--prompt')
    mutex.add_argument('--ids')
    cmd_generate_response = subparsers.add_parser("generate-response")
    cmd_generate_response.add_argument('--prompt')
    
    args = parser.parse_args()

    DEBUG = args.debug or args.debug_file is not None
    if DEBUG:
        if args.debug_file is None:
            args.debug_file = 'calibregpt.log' 
        DEBUG_FILE = open(args.debug_file, 'w')
    
    try:
        print(json.dumps({ "results": run_query(args) }))
    except NoFulltextDataError:
        print(json.dumps({ "error": "No full text data for selected books." }))