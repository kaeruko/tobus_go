import hashlib
import os
import tempfile
import unittest
import zipfile

from gtfs_loader import GtfsRepository
from gtfs_state import (
    CompiledGtfsStateError,
    build_compiled_state_from_zip,
    hydrate_repository_state,
    load_compiled_state,
    repository_state_payload,
)


def _gtfs_zip(path: str) -> str:
    files = {
        "routes.txt": (
            "route_id,route_short_name,route_type\n"
            "R1,上23,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id\n"
            "R1,S1,T1\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,平井七丁目,35.7000,139.8500\n"
            "B,浅草雷門,35.7100,139.8600\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,A,1\n"
            "T1,10:20:00,10:20:00,B,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "S1,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
        "calendar_dates.txt": "service_id,date,exception_type\n",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        digest.update(file.read())
    return digest.hexdigest()


class CompiledGtfsStateTest(unittest.TestCase):
    def test_compiled_state_round_trip_preserves_runtime_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            zip_path = _gtfs_zip(os.path.join(directory, "gtfs.zip"))
            source_sha256 = _sha256(zip_path)
            state_path = os.path.join(directory, "gtfs_state.pkl.gz")

            artifact = build_compiled_state_from_zip(
                zip_path,
                source_sha256=source_sha256,
                output_path=state_path,
            )
            repository = GtfsRepository("toei_bus")
            load_compiled_state(
                repository,
                artifact.path,
                expected_source_sha256=source_sha256,
            )

            self.assertTrue(repository.is_loaded)
            self.assertEqual(repository.source_dir, f"compiled:{source_sha256}")
            self.assertEqual(repository.stops["A"]["name"], "平井七丁目")
            self.assertEqual(repository.routes["R1"]["route_short_name"], "上23")
            self.assertEqual(repository.get_trip_stop_ids("T1"), ["A", "B"])
            schedule = repository.get_trip_stop_schedule("T1")
            self.assertEqual(len(schedule), 2)
            self.assertEqual(schedule[0]["stop_id"], "A")
            self.assertEqual(schedule[1]["stop_id"], "B")
            self.assertEqual(artifact.record_counts["stop_times"], 2)

    def test_source_sha_mismatch_is_fatal_and_does_not_mutate_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            zip_path = _gtfs_zip(os.path.join(directory, "gtfs.zip"))
            source_sha256 = _sha256(zip_path)
            source = GtfsRepository("toei_bus")

            extract_dir = os.path.join(directory, "raw")
            os.makedirs(extract_dir)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            source.load_data(extract_dir)
            state = repository_state_payload(source, source_sha256)

            target = GtfsRepository("toei_bus")
            with self.assertRaisesRegex(
                CompiledGtfsStateError,
                "source mismatch",
            ):
                hydrate_repository_state(
                    target,
                    state,
                    expected_source_sha256="0" * 64,
                )

            self.assertFalse(target.is_loaded)
            self.assertEqual(target.trips, {})
            self.assertEqual(target.stops, {})

    def test_schema_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            zip_path = _gtfs_zip(os.path.join(directory, "gtfs.zip"))
            source_sha256 = _sha256(zip_path)
            extract_dir = os.path.join(directory, "raw")
            os.makedirs(extract_dir)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            source = GtfsRepository("toei_bus")
            source.load_data(extract_dir)
            state = repository_state_payload(source, source_sha256)
            state["schema_version"] = 999

            target = GtfsRepository("toei_bus")
            with self.assertRaisesRegex(CompiledGtfsStateError, "schema mismatch"):
                hydrate_repository_state(
                    target,
                    state,
                    expected_source_sha256=source_sha256,
                )
            self.assertFalse(target.is_loaded)


if __name__ == "__main__":
    unittest.main()
