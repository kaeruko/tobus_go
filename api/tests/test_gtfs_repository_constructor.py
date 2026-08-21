import unittest

from gtfs_loader import GtfsRepository


class GtfsRepositoryConstructorTest(unittest.TestCase):
    def test_constructor_returns_distinct_instances(self):
        first = GtfsRepository("first")
        second = GtfsRepository("second")

        self.assertIsNot(first, second)
        self.assertEqual(first.feed_id, "first")
        self.assertEqual(second.feed_id, "second")
        self.assertFalse(first.is_loaded)
        self.assertFalse(second.is_loaded)

    def test_invalid_feed_id_fails_without_normalizing(self):
        with self.assertRaises(ValueError):
            GtfsRepository(" Nagoya ")
        with self.assertRaises(ValueError):
            GtfsRepository("nagoya:bus")


if __name__ == "__main__":
    unittest.main()
