import datetime
import unittest

from toei_engine import determine_day_type


class DetermineDayTypeTest(unittest.TestCase):
    def test_weekday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 10)),
            "weekday",
        )

    def test_saturday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 8)),
            "saturday",
        )

    def test_sunday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 9)),
            "holiday",
        )

    def test_japanese_public_holiday(self):
        # 2026-08-11 is Mountain Day, even though it is a Tuesday.
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 11)),
            "holiday",
        )


if __name__ == "__main__":
    unittest.main()
