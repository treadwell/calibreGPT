import unittest

from retrieval_validation import hit_at_k, overlap_ratio, reciprocal_rank


class TestRetrievalValidationMetrics(unittest.TestCase):
    def test_overlap_ratio(self):
        self.assertEqual(overlap_ratio([1, 2, 3], [3, 4, 5], 3), 1 / 3)
        self.assertEqual(overlap_ratio([], [], 3), 0.0)

    def test_reciprocal_rank(self):
        self.assertEqual(reciprocal_rank([7, 9, 3], [3]), 1 / 3)
        self.assertEqual(reciprocal_rank([7, 9, 3], [5]), 0.0)

    def test_hit_at_k(self):
        self.assertEqual(hit_at_k([10, 20, 30], [20]), 1)
        self.assertEqual(hit_at_k([10, 20, 30], [99]), 0)


if __name__ == "__main__":
    unittest.main()
