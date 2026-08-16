import csv
import io
import unittest
import zipfile

from app.services.train_realtime import TrainRealtimeError
from app.services.train_service_calendar import (
    parse_service_date,
    parse_train_service_calendar,
)


class TrainServiceCalendarTest(unittest.TestCase):
    def _zip(self, *, calendar_dates_rows=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "trips.txt",
                self._csv(
                    ["route_id", "service_id", "trip_id"],
                    [
                        ["1", "weekday", "weekday-trip"],
                        ["1", "weekend", "weekend-trip"],
                        ["1", "special", "special-trip"],
                    ],
                ),
            )
            archive.writestr(
                "calendar.txt",
                self._csv(
                    [
                        "service_id",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                        "start_date",
                        "end_date",
                    ],
                    [
                        ["weekday", "1", "1", "1", "1", "1", "0", "0", "20260101", "20261231"],
                        ["weekend", "0", "0", "0", "0", "0", "1", "1", "20260101", "20261231"],
                        ["special", "0", "0", "0", "0", "0", "0", "0", "20260101", "20261231"],
                    ],
                ),
            )
            if calendar_dates_rows is not None:
                archive.writestr(
                    "calendar_dates.txt",
                    self._csv(
                        ["service_id", "date", "exception_type"],
                        calendar_dates_rows,
                    ),
                )
        return output.getvalue()

    @staticmethod
    def _csv(headers, rows):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue()

    def test_sunday_uses_only_weekend_service(self):
        index = parse_train_service_calendar(self._zip())

        active = index.active_trip_ids(parse_service_date("2026-08-16"))

        self.assertEqual(active, frozenset({"weekend-trip"}))

    def test_calendar_dates_adds_and_removes_service_for_exact_date(self):
        index = parse_train_service_calendar(
            self._zip(
                calendar_dates_rows=[
                    ["weekend", "20260816", "2"],
                    ["special", "20260816", "1"],
                ]
            )
        )

        active = index.active_trip_ids(parse_service_date("2026-08-16"))

        self.assertEqual(active, frozenset({"special-trip"}))

    def test_target_date_is_required_and_strict_iso_date(self):
        with self.assertRaises(TrainRealtimeError) as missing:
            parse_service_date(None)
        self.assertEqual(missing.exception.code, "train_service_date_missing")

        with self.assertRaises(TrainRealtimeError) as invalid:
            parse_service_date("2026/08/16")
        self.assertEqual(invalid.exception.code, "train_service_date_invalid")

    def test_unknown_service_id_is_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "trips.txt",
                self._csv(
                    ["route_id", "service_id", "trip_id"],
                    [["1", "missing", "trip-1"]],
                ),
            )
            archive.writestr(
                "calendar.txt",
                self._csv(
                    [
                        "service_id",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                        "start_date",
                        "end_date",
                    ],
                    [["other", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231"]],
                ),
            )

        with self.assertRaises(TrainRealtimeError) as raised:
            parse_train_service_calendar(output.getvalue())
        self.assertEqual(raised.exception.code, "train_static_calendar_invalid")


if __name__ == "__main__":
    unittest.main()
