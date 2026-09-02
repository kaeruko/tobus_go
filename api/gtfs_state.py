from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from gtfs_loader import GtfsRepository


GTFS_STATE_SCHEMA_VERSION = 1
_COMPILED_STATE_SUFFIX = ".pkl.gz"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_PAYLOAD_KEYS = {
    "trips",
    "stop_times",
    "stops",
    "routes",
    "route_name_to_id",
    "timetable_index",
    "service_calendar",
    "service_exceptions",
}


class CompiledGtfsStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledGtfsArtifact:
    path: str
    sha256: str
    source_sha256: str
    schema_version: int
    record_counts: dict[str, int]


@dataclass(frozen=True)
class LambdaCompiledAssets:
    prebuilt_path: str
    compiled_state_path: str
    source_sha256: str


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CompiledGtfsStateError(f"{field_name} must be a lowercase SHA-256 hex string")
    return value


def _record_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    stop_times = payload["stop_times"]
    return {
        "stops": len(payload["stops"]),
        "routes": len(payload["routes"]),
        "trips": len(payload["trips"]),
        "stop_times": sum(len(rows) for rows in stop_times.values()),
        "timetable_keys": len(payload["timetable_index"]),
        "service_calendar": len(payload["service_calendar"]),
        "service_exception_dates": len(payload["service_exceptions"]),
    }


def repository_state_payload(
    repository: GtfsRepository,
    source_sha256: str,
) -> dict[str, Any]:
    if not repository.is_loaded:
        raise CompiledGtfsStateError("GTFS repository must be loaded before serialization")
    source_sha256 = _require_sha256(source_sha256, "source_sha256")

    payload: dict[str, Any] = {
        "trips": dict(repository.trips),
        "stop_times": {
            trip_id: dict(rows) for trip_id, rows in repository.stop_times.items()
        },
        "stops": dict(repository.stops),
        "routes": dict(repository.routes),
        "route_name_to_id": dict(repository.route_name_to_id),
        "timetable_index": {
            key: list(rows) for key, rows in repository.timetable_index.items()
        },
        "service_calendar": dict(repository.service_calendar),
        "service_exceptions": {
            date: dict(rows) for date, rows in repository.service_exceptions.items()
        },
    }
    counts = _record_counts(payload)
    if counts["stops"] <= 0 or counts["routes"] <= 0 or counts["trips"] <= 0:
        raise CompiledGtfsStateError(f"GTFS repository has invalid record counts: {counts}")
    if counts["stop_times"] <= 0:
        raise CompiledGtfsStateError("GTFS repository has no stop times")

    return {
        "schema_version": GTFS_STATE_SCHEMA_VERSION,
        "feed_id": repository.feed_id,
        "source_sha256": source_sha256,
        "record_counts": counts,
        "payload": payload,
    }


def hydrate_repository_state(
    repository: GtfsRepository,
    state: Mapping[str, Any],
    *,
    expected_source_sha256: str,
) -> None:
    if repository.is_loaded:
        raise CompiledGtfsStateError(
            f"GTFS repository {repository.feed_id!r} is already loaded from {repository.source_dir}"
        )
    if not isinstance(state, Mapping):
        raise CompiledGtfsStateError("Compiled GTFS state root must be an object")

    schema_version = state.get("schema_version")
    if schema_version != GTFS_STATE_SCHEMA_VERSION:
        raise CompiledGtfsStateError(
            "Compiled GTFS state schema mismatch: "
            f"expected={GTFS_STATE_SCHEMA_VERSION}, actual={schema_version!r}"
        )

    feed_id = state.get("feed_id")
    if feed_id != repository.feed_id:
        raise CompiledGtfsStateError(
            f"Compiled GTFS feed mismatch: expected={repository.feed_id!r}, actual={feed_id!r}"
        )

    expected_source_sha256 = _require_sha256(
        expected_source_sha256,
        "expected_source_sha256",
    )
    source_sha256 = _require_sha256(state.get("source_sha256"), "source_sha256")
    if source_sha256 != expected_source_sha256:
        raise CompiledGtfsStateError(
            "Compiled GTFS source mismatch: "
            f"expected={expected_source_sha256}, actual={source_sha256}"
        )

    payload = state.get("payload")
    if not isinstance(payload, Mapping):
        raise CompiledGtfsStateError("Compiled GTFS state payload must be an object")
    missing = sorted(_REQUIRED_PAYLOAD_KEYS.difference(payload))
    if missing:
        raise CompiledGtfsStateError(
            "Compiled GTFS state payload is missing keys: " + ", ".join(missing)
        )

    materialized: dict[str, Any] = {}
    for key in _REQUIRED_PAYLOAD_KEYS:
        value = payload[key]
        if not isinstance(value, Mapping):
            raise CompiledGtfsStateError(f"Compiled GTFS payload {key!r} must be an object")
        materialized[key] = dict(value)

    stop_times = {
        trip_id: dict(rows) for trip_id, rows in materialized["stop_times"].items()
    }
    timetable_index = {
        key: list(rows) for key, rows in materialized["timetable_index"].items()
    }
    service_exceptions = {
        date: dict(rows)
        for date, rows in materialized["service_exceptions"].items()
    }
    materialized["stop_times"] = stop_times
    materialized["timetable_index"] = timetable_index
    materialized["service_exceptions"] = service_exceptions

    counts = _record_counts(materialized)
    expected_counts = state.get("record_counts")
    if not isinstance(expected_counts, Mapping):
        raise CompiledGtfsStateError("Compiled GTFS record_counts must be an object")
    normalized_expected_counts = {
        str(key): value for key, value in expected_counts.items()
    }
    if normalized_expected_counts != counts:
        raise CompiledGtfsStateError(
            "Compiled GTFS record count mismatch: "
            f"expected={normalized_expected_counts}, actual={counts}"
        )
    if counts["stops"] <= 0 or counts["routes"] <= 0 or counts["trips"] <= 0:
        raise CompiledGtfsStateError(f"Compiled GTFS has invalid record counts: {counts}")
    if counts["stop_times"] <= 0:
        raise CompiledGtfsStateError("Compiled GTFS has no stop times")

    repository.trips = materialized["trips"]
    repository.stop_times = defaultdict(dict, stop_times)
    repository.stops = materialized["stops"]
    repository.routes = materialized["routes"]
    repository.route_name_to_id = materialized["route_name_to_id"]
    repository.timetable_index = defaultdict(list, timetable_index)
    repository.service_calendar = materialized["service_calendar"]
    repository.service_exceptions = defaultdict(dict, service_exceptions)
    repository._active_service_cache = {}
    repository.source_dir = f"compiled:{source_sha256}"
    repository.is_loaded = True


def write_compiled_state(
    repository: GtfsRepository,
    *,
    source_sha256: str,
    output_path: str,
) -> CompiledGtfsArtifact:
    state = repository_state_payload(repository, source_sha256)
    output_dir = os.path.dirname(os.path.realpath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    temporary_path = output_path + ".tmp"
    try:
        # The compiled object is addressed by the source GTFS SHA. Make its bytes
        # reproducible so a retry after a partial S3 publish produces the same
        # artifact checksum instead of failing because gzip embedded wall time.
        with open(temporary_path, "wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=6,
                fileobj=raw,
                mtime=0,
            ) as compressed:
                pickle.dump(state, compressed, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary_path, output_path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass

    return CompiledGtfsArtifact(
        path=output_path,
        sha256=sha256_file(output_path),
        source_sha256=state["source_sha256"],
        schema_version=state["schema_version"],
        record_counts=dict(state["record_counts"]),
    )


def load_compiled_state(
    repository: GtfsRepository,
    path: str,
    *,
    expected_source_sha256: str,
) -> None:
    try:
        with gzip.open(path, "rb") as compressed:
            state = pickle.load(compressed)
    except Exception as error:
        raise CompiledGtfsStateError(
            f"Could not read compiled GTFS state from {path}"
        ) from error
    hydrate_repository_state(
        repository,
        state,
        expected_source_sha256=expected_source_sha256,
    )


def _safe_zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise CompiledGtfsStateError(f"Unsafe path in GTFS ZIP: {info.filename}")
        basename = path.name
        if basename in members:
            raise CompiledGtfsStateError(
                f"Duplicate GTFS filename in ZIP: {basename}"
            )
        members[basename] = info
    return members


def build_compiled_state_from_zip(
    zip_path: str,
    *,
    source_sha256: str,
    output_path: str,
    feed_id: str = "toei_bus",
) -> CompiledGtfsArtifact:
    source_sha256 = _require_sha256(source_sha256, "source_sha256")
    actual_source_sha256 = sha256_file(zip_path)
    if actual_source_sha256 != source_sha256:
        raise CompiledGtfsStateError(
            "GTFS ZIP checksum mismatch before compilation: "
            f"expected={source_sha256}, actual={actual_source_sha256}"
        )

    required = set(GtfsRepository.REQUIRED_FILES)
    optional = {"calendar.txt", "calendar_dates.txt"}

    with tempfile.TemporaryDirectory(prefix="toeigo-gtfs-compile-") as directory:
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                members = _safe_zip_members(archive)
                missing = sorted(required.difference(members))
                if missing:
                    raise CompiledGtfsStateError(
                        "GTFS ZIP is missing files required by GtfsRepository: "
                        + ", ".join(missing)
                    )
                for filename in sorted(required | optional):
                    info = members.get(filename)
                    if info is None:
                        continue
                    target = os.path.join(directory, filename)
                    with archive.open(info, "r") as source, open(target, "wb") as destination:
                        shutil.copyfileobj(source, destination)
        except (zipfile.BadZipFile, OSError) as error:
            raise CompiledGtfsStateError("Could not extract GTFS ZIP for compilation") from error

        repository = GtfsRepository(feed_id)
        try:
            repository.load_data(directory)
        except Exception as error:
            raise CompiledGtfsStateError("Could not parse GTFS for compiled state") from error
        return write_compiled_state(
            repository,
            source_sha256=source_sha256,
            output_path=output_path,
        )


def _load_manifest(s3, bucket_name: str, state_key: str) -> dict[str, Any]:
    try:
        response = s3.get_object(Bucket=bucket_name, Key=state_key)
        raw = json.loads(response["Body"].read())
    except Exception as error:
        raise CompiledGtfsStateError(
            f"Could not load GTFS state manifest from S3 key {state_key}"
        ) from error
    if not isinstance(raw, dict):
        raise CompiledGtfsStateError("GTFS state manifest must be a JSON object")
    return raw


def download_compiled_lambda_assets(data_dir: str = "/tmp/data") -> LambdaCompiledAssets:
    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        raise CompiledGtfsStateError("S3_BUCKET_NAME is required in lambda mode")
    state_key = os.getenv("S3_GTFS_STATE_KEY")
    if not state_key:
        raise CompiledGtfsStateError(
            "S3_GTFS_STATE_KEY is required for compiled Tokyo GTFS startup"
        )

    import boto3

    s3 = boto3.client("s3")
    manifest = _load_manifest(s3, bucket_name, state_key)
    source_sha256 = _require_sha256(manifest.get("sha256"), "state.sha256")
    compiled_key = manifest.get("compiled_state_key")
    if not isinstance(compiled_key, str) or not compiled_key:
        raise CompiledGtfsStateError(
            "GTFS state manifest is missing compiled_state_key; "
            "run the compiled GTFS refresh before deploying the API"
        )
    compiled_sha256 = _require_sha256(
        manifest.get("compiled_state_sha256"),
        "state.compiled_state_sha256",
    )
    schema_version = manifest.get("compiled_state_schema_version")
    if schema_version != GTFS_STATE_SCHEMA_VERSION:
        raise CompiledGtfsStateError(
            "GTFS state manifest compiled schema mismatch: "
            f"expected={GTFS_STATE_SCHEMA_VERSION}, actual={schema_version!r}"
        )

    os.makedirs(data_dir, exist_ok=True)
    prebuilt_key = os.getenv("S3_PREBUILT_KEY", "app_data.pkl")
    prebuilt_path = os.path.join(data_dir, "app_data.pkl")
    compiled_state_path = os.path.join(
        data_dir,
        f"gtfs_state-{source_sha256}{_COMPILED_STATE_SUFFIX}",
    )

    if not os.path.exists(prebuilt_path):
        print(f"[INFO] Downloading prebuilt data from S3 key {prebuilt_key}...")
        try:
            s3.download_file(bucket_name, prebuilt_key, prebuilt_path)
        except Exception as error:
            raise CompiledGtfsStateError(
                f"Could not download app_data.pkl from S3 key {prebuilt_key}"
            ) from error

    if not os.path.exists(compiled_state_path):
        print(f"[INFO] Downloading compiled GTFS state from S3 key {compiled_key}...")
        try:
            s3.download_file(bucket_name, compiled_key, compiled_state_path)
        except Exception as error:
            raise CompiledGtfsStateError(
                f"Could not download compiled GTFS state from S3 key {compiled_key}"
            ) from error

    actual_compiled_sha256 = sha256_file(compiled_state_path)
    if actual_compiled_sha256 != compiled_sha256:
        raise CompiledGtfsStateError(
            "Downloaded compiled GTFS state checksum mismatch: "
            f"expected={compiled_sha256}, actual={actual_compiled_sha256}"
        )

    return LambdaCompiledAssets(
        prebuilt_path=prebuilt_path,
        compiled_state_path=compiled_state_path,
        source_sha256=source_sha256,
    )
