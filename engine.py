import sqlite3
import certifi
import ssl
import os
import faiss
import http.client
import json
import numpy as np 
import sys

def open_db(fp, auto_create = True):
    if not auto_create and not os.path.exists(fp):
        raise ValueError("DB doesn't exist: " + fp)   
    conn = sqlite3.connect(fp, isolation_level = "DEFERRED")
    return conn

def close_db(db):
    db.close()

class FullTextTimestampsIter():
    def __init__(self, db):
        self.cursor = db.cursor()
        self.cursor.execute("select book, timestamp from books_text")
    def __iter__(self):
        return self
    def __next__(self):
        row = self.cursor.fetchone() 
        if not row:
            raise StopIteration
        return row

def check_fulltext_id_exists(db, id):
    cursor = db.cursor()
    cursor.execute("select id from books_text where id = ?", [id])
    return cursor.fetchone() is not None

class CalibreUpdatesIter():
    def __init__(self, fulltext_db, calibregpt_db):
        self.state = "fulltext"
        self.fulltextiter = FullTextTimestampsIter(fulltext_db)
        self.calibregptiter = CalibreGptIdsIter(calibregpt_db)
        self.calibregpt_db = calibregpt_db
        self.fulltext_db = fulltext_db
    def __iter__(self):
        return self
    def __next__(self):
        while True:
            if self.state == "fulltext":
                try:
                    id, timestamp = next(self.fulltextiter)
                    print("\nCalibre Updates Iterator - fulltext: ", id, file=sys.stderr)
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
                    print("\nCalibre Updates Iterator - gpt: ", id, file=sys.stderr)
                    if not check_fulltext_id_exists(self.fulltext_db, id):
                        return (id, None, "delete")
                except StopIteration:
                    raise StopIteration
            else:
                raise ValueError("Invalid state: " + self.state)

class BookChunksIter():
    def __init__(self, id, db, chunk_size = 4000, overlap_pcnt = 0.2):
        self.chunk_size = chunk_size
        self.overlap_pcnt = overlap_pcnt
        self.position = 0
        cursor = db.cursor()
        cursor.execute("select searchable_text from books_text where book = ?", [id])
        row = cursor.fetchone()
        self.text = str(row[0])
        self.text_length = len(self.text)
    def __iter__(self):
        return self
    def __next__(self):
        print("Book Chunks Iterator - next", file = sys.stderr)
        if self.position > self.text_length:
            raise StopIteration
        start_idx = self.position - int(self.chunk_size * self.overlap_pcnt)
        if start_idx < 0:
            start_idx = 0
        end_idx = self.position + int(self.chunk_size * (1 + self.overlap_pcnt))
        if end_idx > self.text_length - 1:
            end_idx = self.text_length - 1
        # TODO: cutting words in half at boundaries 
        self.position = self.position + self.chunk_size
        print("BCI start: ", start_idx, "BCI end: ", end_idx, "BCI position: ", self.position, file = sys.stderr)
        return self.text[start_idx:end_idx]

class BookChunksEmbeddingsIter():
    def __init__(self, ids, db):
        print(ids, file = sys.stderr)
        self.cursor = db.cursor()
        self.cursor.execute(f"select embedding from book_chunks where id_book in ({','.join(['?' for _ in ids])})", list(map(int, ids)))
    def __iter__(self):
        return self
    def __next__(self):
        row = self.cursor.fetchone()
        if not row:
            raise StopIteration
        return row[0]

def fetch_embedding(chunk, token):
    print("fetch embedding: ", chunk[:50].replace('\n', ' ').replace('\r', ''), file = sys.stderr)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(certifi.where())
    connection = http.client.HTTPSConnection("api.openai.com", context=ssl_ctx)
    connection.request("POST", "/v1/embeddings", json.dumps({ 
        "input": chunk, 
        "model": "text-embedding-ada-002"
    }), {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
    })
    response = connection.getresponse()
    assert response.status == 200, response.reason
    body = response.read()
    data = json.loads(body)
    return np.array(data["data"][0]["embedding"])

def update_indices(fulltext_db, metadata_db, calibregpt_db, faiss_index, faiss_index_fp, updates, token):
    print("starting update_indices", file = sys.stderr)
    # TODO: batch fetch embeddings
    # TODO: return/print number of books added or updated 
    counter = 0
    for update in updates:
        (id, timestamp, type) = update
        if type == "update":
            print("update indices  - update", file = sys.stderr)
            cursor = calibregpt_db.cursor()
            cursor.execute("delete from book_chunks where id_book = ?", [id])
            cursor.execute("delete from books where id = ?", [id])
            type = "new" 
        if type == "new":
            print("update indices - new", file = sys.stderr)
            cursor_md = metadata_db.cursor()
            cursor_md.execute("select id, title, author_sort from books where id = ?", [id])
            id, title, author = cursor_md.fetchone()
            cursor_gpt = calibregpt_db.cursor()
            cursor_gpt.execute("insert into books (id, timestamp, title, author) values (?, ?, ?, ?)", [id, timestamp, title, author])
            sequence = 0
            for chunk in BookChunksIter(id, fulltext_db):
                print("update indices - update chunks", file = sys.stderr)
                cursor_gpt.execute("insert into book_chunks (id_book, sequence, text) values (?, ?, ?)", [id, sequence, chunk])
                chunk_id = cursor_gpt.lastrowid
                embedding = fetch_embedding(chunk, token)
                cursor_gpt.execute("update book_chunks set embedding = ? where id = ?", [embedding, chunk_id])
                embeddings = np.array([embedding])
                chunk_ids = np.array([chunk_id])
                faiss_index.add_with_ids(embeddings, chunk_ids)
                sequence += 1
        counter += 1
        if counter > 20:
            calibregpt_db.commit()
            persist_faiss_index(faiss_index, faiss_index_fp)
            counter = 0
            print("\nupdate indices - batch committed", file = sys.stderr)
    calibregpt_db.commit()
    persist_faiss_index(faiss_index, faiss_index_fp)

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
    faiss.write_index(faiss_index, fp)
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
            print(f"No data found for chunk_id: {chunk_id}", file = sys.stderr)

    return results

def merge_book_embeddings(ids, db):
    arrays = list(map(lambda c: np.frombuffer(c, dtype = "float64"), 
                 BookChunksEmbeddingsIter(ids, db)))
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

    fulltext_db = open_db(fp_fulltext_db, False)
    medatadata_db = open_db(fp_metadata_db, False)
    calibregpt_db = open_db(fp_calibregpt_db, True)
    setup_calibregpt_db(calibregpt_db)
    faiss_index = open_faiss_index(fp_faiss_index)

    updates = CalibreUpdatesIter(fulltext_db, calibregpt_db)

    update_indices(fulltext_db, medatadata_db, calibregpt_db, faiss_index, fp_faiss_index, updates, openai_token)

    prompt_embedding = get_prompt(opts, calibregpt_db)

    ranking = search_faiss_index(faiss_index, prompt_embedding, calibregpt_db, match_count)
    
    close_db(fulltext_db)
    close_db(medatadata_db)
    close_db(calibregpt_db)

    return ranking

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog = 'CalibreGPT')
    parser.add_argument('--openai-token')
    parser.add_argument('--fulltext-db')
    parser.add_argument('--metadata-db')
    parser.add_argument('--calibregpt-db')
    parser.add_argument('--faiss-index')
    parser.add_argument('--match-count')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--prompt')
    mutex.add_argument('--ids')
    
    args = parser.parse_args()
    print(json.dumps(run_query(args)))