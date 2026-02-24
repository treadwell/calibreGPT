import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import faiss
import numpy as np

from engine import (
    BookChunksIter,
    chunk_text_hash,
    get_faiss_index_path,
    migrate_embeddings,
    migration_status,
    open_db,
    query_embedding_model,
    setup_calibregpt_db,
)


def _make_fulltext_db(text):
    db = sqlite3.connect(":memory:")
    cursor = db.cursor()
    cursor.execute("create table books_text (book integer primary key, searchable_text text, timestamp integer)")
    cursor.execute(
        "insert into books_text (book, searchable_text, timestamp) values (?, ?, ?)",
        [1, text, 1],
    )
    db.commit()
    return db


class TestBookChunksIter(unittest.TestCase):
    def test_chunks_cover_all_characters_without_overlap(self):
        db = _make_fulltext_db("abcdefghij")
        chunks = list(BookChunksIter(1, db, chunk_size=4, overlap_percent=0.0))
        self.assertEqual(chunks, ["abcd", "efgh", "ij"])
        self.assertEqual("".join(chunks), "abcdefghij")

    def test_chunks_with_overlap_have_expected_windows(self):
        db = _make_fulltext_db("abcdefghij")
        chunks = list(BookChunksIter(1, db, chunk_size=6, overlap_percent=0.2))
        self.assertEqual(chunks, ["abcde", "defghi", "hij"])

    def test_invalid_overlap_percent_raises(self):
        db = _make_fulltext_db("abc")
        with self.assertRaises(ValueError):
            list(BookChunksIter(1, db, chunk_size=10, overlap_percent=0.5))


class TestMultiModelEmbeddings(unittest.TestCase):
    def test_get_faiss_index_path_uses_model_suffix(self):
        base = "/tmp/faiss.idx"
        self.assertEqual(get_faiss_index_path(base, "text-embedding-ada-002"), base)
        self.assertEqual(
            get_faiss_index_path(base, "text-embedding-3-small"),
            "/tmp/faiss.text-embedding-3-small.idx",
        )

    def test_migrate_embeddings_populates_chunk_embeddings_and_index(self):
        with tempfile.TemporaryDirectory() as td:
            db = open_db(f"{td}/calibregpt.db", auto_create=True, wal=False)
            setup_calibregpt_db(db)
            cursor = db.cursor()
            cursor.execute(
                "insert into books (id, author, title, timestamp) values (1, 'a', 't', 1)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (100, 1, 0, 'Hello world', null)"
            )
            db.commit()

            faiss_index = faiss.IndexIDMap(faiss.IndexFlatL2(3))
            faiss_fp = f"{td}/alt.idx"

            with patch(
                "engine.fetch_embeddings_for_model",
                return_value=[np.array([0.1, 0.2, 0.3], dtype="float64")],
            ):
                stats = migrate_embeddings(
                    batch_size=10,
                    calibregpt_db=db,
                    faiss_index=faiss_index,
                    faiss_index_fp=faiss_fp,
                    token="test-token",
                    embedding_model="text-embedding-3-small",
                )

            self.assertEqual(stats["processed"], 1)
            self.assertEqual(stats["remaining"], 0)

            row = db.cursor().execute(
                "select model, text_hash, embedding from chunk_embeddings where id_chunk = 100"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "text-embedding-3-small")
            self.assertEqual(len(np.frombuffer(row[2], dtype="float64")), 3)

    def test_migrate_embeddings_refreshes_stale_hash_rows(self):
        with tempfile.TemporaryDirectory() as td:
            db = open_db(f"{td}/calibregpt.db", auto_create=True, wal=False)
            setup_calibregpt_db(db)
            cursor = db.cursor()
            cursor.execute(
                "insert into books (id, author, title, timestamp) values (1, 'a', 't', 1)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (100, 1, 0, 'Hello world', null)"
            )
            cursor.execute(
                """
                insert into chunk_embeddings (id_chunk, model, text_hash, embedding, updated_at)
                values (?, ?, ?, ?, ?)
                """,
                [
                    100,
                    "text-embedding-3-small",
                    "stale-hash",
                    np.array([9.0, 9.0, 9.0], dtype="float64").tobytes(),
                    1,
                ],
            )
            db.commit()

            faiss_index = faiss.IndexIDMap(faiss.IndexFlatL2(3))
            faiss_index.add_with_ids(
                np.array([[9.0, 9.0, 9.0]], dtype="float64"),
                np.array([100], dtype="int64"),
            )
            faiss_fp = f"{td}/alt.idx"

            with patch(
                "engine.fetch_embeddings_for_model",
                return_value=[np.array([0.4, 0.5, 0.6], dtype="float64")],
            ):
                stats = migrate_embeddings(
                    batch_size=10,
                    calibregpt_db=db,
                    faiss_index=faiss_index,
                    faiss_index_fp=faiss_fp,
                    token="test-token",
                    embedding_model="text-embedding-3-small",
                )

            self.assertEqual(stats["processed"], 1)
            self.assertEqual(stats["inserted"], 0)
            self.assertEqual(stats["refreshed"], 1)

            row = db.cursor().execute(
                "select text_hash, embedding from chunk_embeddings where id_chunk = 100 and model = 'text-embedding-3-small'"
            ).fetchone()
            self.assertEqual(row[0], chunk_text_hash("Hello world"))
            self.assertTrue(
                np.allclose(
                    np.frombuffer(row[1], dtype="float64"),
                    np.array([0.4, 0.5, 0.6], dtype="float64"),
                )
            )

    def test_migration_status_counts_missing_and_stale(self):
        with tempfile.TemporaryDirectory() as td:
            db = open_db(f"{td}/calibregpt.db", auto_create=True, wal=False)
            setup_calibregpt_db(db)
            cursor = db.cursor()
            cursor.execute(
                "insert into books (id, author, title, timestamp) values (1, 'a', 't', 1)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (100, 1, 0, 'Hello world', null)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (101, 1, 1, 'Another chunk', null)"
            )
            cursor.execute(
                """
                insert into chunk_embeddings (id_chunk, model, text_hash, embedding, updated_at)
                values (?, ?, ?, ?, ?)
                """,
                [
                    100,
                    "text-embedding-3-small",
                    "stale-hash",
                    np.array([1.0, 2.0, 3.0], dtype="float64").tobytes(),
                    1,
                ],
            )
            db.commit()

            stats = migration_status(db, "text-embedding-3-small")
            self.assertEqual(stats["total_chunks"], 2)
            self.assertEqual(stats["missing"], 1)
            self.assertEqual(stats["stale"], 1)
            self.assertEqual(stats["remaining"], 2)
            self.assertEqual(stats["up_to_date"], 0)

    def test_migrate_embeddings_processes_single_batch_per_call(self):
        with tempfile.TemporaryDirectory() as td:
            db = open_db(f"{td}/calibregpt.db", auto_create=True, wal=False)
            setup_calibregpt_db(db)
            cursor = db.cursor()
            cursor.execute(
                "insert into books (id, author, title, timestamp) values (1, 'a', 't', 1)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (100, 1, 0, 'Chunk one', null)"
            )
            cursor.execute(
                "insert into book_chunks (id, id_book, sequence, text, embedding) values (101, 1, 1, 'Chunk two', null)"
            )
            db.commit()

            faiss_index = faiss.IndexIDMap(faiss.IndexFlatL2(3))
            faiss_fp = f"{td}/alt.idx"
            with patch(
                "engine.fetch_embeddings_for_model",
                return_value=[np.array([0.1, 0.2, 0.3], dtype="float64")],
            ):
                stats = migrate_embeddings(
                    batch_size=1,
                    calibregpt_db=db,
                    faiss_index=faiss_index,
                    faiss_index_fp=faiss_fp,
                    token="test-token",
                    embedding_model="text-embedding-3-small",
                )
            self.assertEqual(stats["processed"], 1)
            self.assertEqual(stats["remaining"], 1)


class TestModelSelection(unittest.TestCase):
    def test_query_embedding_model_prefers_explicit_model(self):
        class Opts:
            embedding_model = "text-embedding-3-large"
            active_embedding_model = "text-embedding-3-small"

        self.assertEqual(query_embedding_model(Opts()), "text-embedding-3-large")

    def test_query_embedding_model_falls_back_to_active_model(self):
        class Opts:
            embedding_model = None
            active_embedding_model = "text-embedding-3-small"

        self.assertEqual(query_embedding_model(Opts()), "text-embedding-3-small")


if __name__ == "__main__":
    unittest.main()
