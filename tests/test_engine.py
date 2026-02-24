import sqlite3
import unittest

from engine import BookChunksIter


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


if __name__ == "__main__":
    unittest.main()
