"""Conditional, validated refresh of the Toei Bus GTFS dataset.

The immutable ZIP object is uploaded first.  The small state JSON is the
authoritative pointer and is replaced only after validation and upload have
both completed, so a failed refresh cannot replace the active dataset.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol


DEFAULT_SOURCE_URL = (
    "https://api.odpt.org/api/v4/files/Toei/data/ToeiBus-GTFS.zip"
)
DEFAULT_STATE_KEY = "gtfs/toei/state.json"
DEFAULT_VERSION_PREFIX = "gtfs/toei/versions"
DEFAULT_MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

_CORE_FILES = {
    "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
    "routes.txt": {"route_id", "route_type"},
    "trips.txt": {"route_id", "service_id", "trip_id"},
    "stop_times.txt": {
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
    },
    "stops.txt": {"stop_id", "stop_name"},
}
_CALENDAR_COLUMNS = {
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
}
_CALENDAR_DATES_COLUMNS = {"service_id", "date", "exception_type"}


class GtfsRefreshError(RuntimeError):
    """Base error for a refresh that must leave the old dataset active."""


class GtfsDownloadError(GtfsRefreshError):
    pass


class GtfsValidationError(GtfsRefreshError):
    pass


@dataclass(frozen=True)
class RefreshState:
    etag: str | None
    last_modified: str | None
    sha256: str
    updated_at: str
    object_key: str
    source_url: str

    @classmethod
    def from_json(cls, payload: bytes | str) -> "RefreshState":
        try:
            raw = json.loads(payload)
            return cls(
                etag=raw.get("etag"),
                last_modified=raw.get("last_modified"),
                sha256=raw["sha256"],
                updated_at=raw["updated_at"],
                object_key=raw["object_key"],
                source_url=raw.get("source_url", DEFAULT_SOURCE_URL),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GtfsRefreshError("GTFS state JSON is invalid") from error

    def to_json(self) -> bytes:
        return (
            json.dumps(asdict(self), ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")


@dataclass(frozen=True)
class DownloadResult:
    status_code: int
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    size: int = 0


@dataclass(frozen=True)
class RefreshResult:
    status: str
    reason: str
    old_sha256: str | None = None
    new_sha256: str | None = None
    object_key: str | None = None


class Downloader(Protocol):
    def download(
        self,
        url: str,
        headers: Mapping[str, str],
        destination: str,
    ) -> DownloadResult: ...


class GtfsStore(Protocol):
    def load_state(self) -> RefreshState | None: ...

    def store_version(self, source_path: str, sha256: str) -> str: ...

    def save_state(self, state: RefreshState) -> None: ...


class UrllibDownloader:
    def __init__(
        self,
        timeout_seconds: int = 90,
        max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def download(
        self,
        url: str,
        headers: Mapping[str, str],
        destination: str,
    ) -> DownloadResult:
        request_headers = {
            "Accept": "application/zip, application/octet-stream",
            "User-Agent": "toeigo-gtfs-refresh/1.0",
            **headers,
        }
        request = urllib.request.Request(url, headers=request_headers, method="GET")

        try:
            response = urllib.request.urlopen(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return DownloadResult(status_code=304)
            raise GtfsDownloadError(
                f"GTFS download failed with HTTP {error.code}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise GtfsDownloadError("GTFS download failed") from error

        with response:
            status_code = getattr(response, "status", response.getcode())
            if status_code != 200:
                raise GtfsDownloadError(
                    f"GTFS download returned unexpected HTTP {status_code}"
                )

            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    if int(declared_length) > self.max_bytes:
                        raise GtfsDownloadError("GTFS download is too large")
                except ValueError:
                    pass

            digest = hashlib.sha256()
            size = 0
            with open(destination, "wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise GtfsDownloadError("GTFS download is too large")
                    digest.update(chunk)
                    output.write(chunk)

            if size == 0:
                raise GtfsDownloadError("GTFS download was empty")

            return DownloadResult(
                status_code=200,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                sha256=digest.hexdigest(),
                size=size,
            )


class LocalGtfsStore:
    """Filesystem store used by the local refresh command and tests."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        self.versions_dir = self.root / "versions"

    def load_state(self) -> RefreshState | None:
        if not self.state_path.exists():
            return None
        return RefreshState.from_json(self.state_path.read_bytes())

    def store_version(self, source_path: str, sha256: str) -> str:
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        target = self.versions_dir / f"{sha256}.zip"
        if not target.exists():
            temporary = target.with_suffix(".zip.tmp")
            shutil.copyfile(source_path, temporary)
            os.replace(temporary, target)
        return str(target.relative_to(self.root)).replace("\\", "/")

    def save_state(self, state: RefreshState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.root,
            prefix="state-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(state.to_json())
            temporary_path = temporary.name
        os.replace(temporary_path, self.state_path)


class S3GtfsStore:
    def __init__(
        self,
        bucket_name: str,
        state_key: str = DEFAULT_STATE_KEY,
        version_prefix: str = DEFAULT_VERSION_PREFIX,
        s3_client=None,
    ) -> None:
        if not bucket_name:
            raise ValueError("bucket_name is required")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        self.s3 = s3_client
        self.bucket_name = bucket_name
        self.state_key = state_key.strip("/")
        self.version_prefix = version_prefix.strip("/")

    @staticmethod
    def _error_code(error: Exception) -> str | None:
        response = getattr(error, "response", None)
        if not isinstance(response, dict):
            return None
        return response.get("Error", {}).get("Code")

    def load_state(self) -> RefreshState | None:
        try:
            response = self.s3.get_object(
                Bucket=self.bucket_name,
                Key=self.state_key,
            )
        except Exception as error:
            if self._error_code(error) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise GtfsRefreshError("Could not read GTFS state from S3") from error

        try:
            payload = response["Body"].read()
        except Exception as error:
            raise GtfsRefreshError("Could not read GTFS state body from S3") from error
        return RefreshState.from_json(payload)

    def store_version(self, source_path: str, sha256: str) -> str:
        object_key = f"{self.version_prefix}/{sha256}.zip"
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=object_key)
            return object_key
        except Exception as error:
            if self._error_code(error) not in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:
                raise GtfsRefreshError("Could not inspect GTFS version in S3") from error

        try:
            with open(source_path, "rb") as body:
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=body,
                    ContentType="application/zip",
                    Metadata={"sha256": sha256},
                )
        except Exception as error:
            raise GtfsRefreshError("Could not upload GTFS version to S3") from error
        return object_key

    def save_state(self, state: RefreshState) -> None:
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=self.state_key,
                Body=state.to_json(),
                ContentType="application/json",
                CacheControl="no-cache",
            )
        except Exception as error:
            raise GtfsRefreshError("Could not switch the active GTFS state in S3") from error


def _safe_member_map(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise GtfsValidationError(f"Unsafe path in GTFS ZIP: {info.filename}")
        if info.flag_bits & 0x1:
            raise GtfsValidationError("Encrypted files are not allowed in GTFS ZIP")
        total_size += info.file_size
        if total_size > DEFAULT_MAX_UNCOMPRESSED_BYTES:
            raise GtfsValidationError("GTFS ZIP expands beyond the safety limit")
        basename = path.name
        if basename in members:
            raise GtfsValidationError(
                f"Duplicate GTFS filename in ZIP: {basename}"
            )
        members[basename] = info
    return members


def _validate_csv(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    required_columns: set[str],
) -> int:
    try:
        with archive.open(info, "r") as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
                reader = csv.reader(text, strict=True)
                header = next(reader, None)
                if not header:
                    raise GtfsValidationError(f"{info.filename} has no header")
                missing = required_columns.difference(header)
                if missing:
                    raise GtfsValidationError(
                        f"{info.filename} is missing columns: {', '.join(sorted(missing))}"
                    )
                row_count = 0
                expected_width = len(header)
                date_index = header.index("date") if "date" in header else None
                exception_index = (
                    header.index("exception_type")
                    if "exception_type" in header
                    else None
                )
                for row in reader:
                    if len(row) != expected_width:
                        raise GtfsValidationError(
                            f"{info.filename} contains a malformed CSV row"
                        )
                    if date_index is not None and not re.fullmatch(
                        r"\d{8}", row[date_index]
                    ):
                        raise GtfsValidationError(
                            f"{info.filename} contains an invalid service date"
                        )
                    if exception_index is not None and row[exception_index] not in {
                        "1",
                        "2",
                    }:
                        raise GtfsValidationError(
                            f"{info.filename} contains an invalid exception_type"
                        )
                    row_count += 1
                if row_count == 0:
                    raise GtfsValidationError(f"{info.filename} has no data rows")
                return row_count
    except UnicodeDecodeError as error:
        raise GtfsValidationError(
            f"{info.filename} is not valid UTF-8"
        ) from error
    except csv.Error as error:
        raise GtfsValidationError(
            f"{info.filename} could not be parsed as CSV"
        ) from error


def validate_gtfs_zip(path: str | os.PathLike[str]) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = _safe_member_map(archive)
            missing_core = set(_CORE_FILES).difference(members)
            if missing_core:
                raise GtfsValidationError(
                    "GTFS ZIP is missing required files: "
                    + ", ".join(sorted(missing_core))
                )
            if "calendar.txt" not in members and "calendar_dates.txt" not in members:
                raise GtfsValidationError(
                    "GTFS ZIP requires calendar.txt or calendar_dates.txt"
                )

            bad_file = archive.testzip()
            if bad_file is not None:
                raise GtfsValidationError(f"GTFS ZIP CRC failed: {bad_file}")

            for filename, columns in _CORE_FILES.items():
                _validate_csv(archive, members[filename], columns)
            if "calendar.txt" in members:
                _validate_csv(archive, members["calendar.txt"], _CALENDAR_COLUMNS)
            if "calendar_dates.txt" in members:
                _validate_csv(
                    archive,
                    members["calendar_dates.txt"],
                    _CALENDAR_DATES_COLUMNS,
                )
    except (zipfile.BadZipFile, EOFError, OSError) as error:
        raise GtfsValidationError("GTFS ZIP is corrupt") from error


def build_authenticated_source_url(source_url: str, token: str) -> str:
    if not token:
        raise GtfsRefreshError("ODPT_API_TOKEN is required")
    parts = urllib.parse.urlsplit(source_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "acl:consumerKey"]
    query.append(("acl:consumerKey", token))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


def refresh_gtfs(
    downloader: Downloader,
    store: GtfsStore,
    request_url: str,
    source_url: str = DEFAULT_SOURCE_URL,
    now: datetime | None = None,
) -> RefreshResult:
    previous = store.load_state()
    conditional_headers: dict[str, str] = {}
    if previous and previous.etag:
        conditional_headers["If-None-Match"] = previous.etag
    if previous and previous.last_modified:
        conditional_headers["If-Modified-Since"] = previous.last_modified

    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix="toei-gtfs-", suffix=".zip", delete=False
        ) as temporary:
            temporary_path = temporary.name

        downloaded = downloader.download(
            request_url,
            conditional_headers,
            temporary_path,
        )
        if downloaded.status_code == 304:
            return RefreshResult(
                status="unchanged",
                reason="http_304",
                old_sha256=previous.sha256 if previous else None,
                new_sha256=previous.sha256 if previous else None,
                object_key=previous.object_key if previous else None,
            )
        if downloaded.status_code != 200 or not downloaded.sha256:
            raise GtfsDownloadError(
                f"Unexpected GTFS download result: {downloaded.status_code}"
            )
        if previous and downloaded.sha256 == previous.sha256:
            return RefreshResult(
                status="unchanged",
                reason="same_sha256",
                old_sha256=previous.sha256,
                new_sha256=previous.sha256,
                object_key=previous.object_key,
            )

        validate_gtfs_zip(temporary_path)
        object_key = store.store_version(temporary_path, downloaded.sha256)
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        next_state = RefreshState(
            etag=downloaded.etag,
            last_modified=downloaded.last_modified,
            sha256=downloaded.sha256,
            updated_at=timestamp.isoformat().replace("+00:00", "Z"),
            object_key=object_key,
            source_url=source_url,
        )
        store.save_state(next_state)
        return RefreshResult(
            status="updated",
            reason="sha256_changed",
            old_sha256=previous.sha256 if previous else None,
            new_sha256=downloaded.sha256,
            object_key=object_key,
        )
    finally:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass


def advance_api_gtfs_version(
    function_name: str,
    sha256: str,
    lambda_client=None,
) -> bool:
    """Force warm API environments to reload after the active ZIP changes."""
    if not function_name or not sha256:
        return False
    if lambda_client is None:
        import boto3

        lambda_client = boto3.client("lambda")

    try:
        configuration = lambda_client.get_function_configuration(
            FunctionName=function_name
        )
        variables = dict(
            configuration.get("Environment", {}).get("Variables", {})
        )
        if variables.get("GTFS_DATA_VERSION") == sha256:
            return False
        variables["GTFS_DATA_VERSION"] = sha256
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Environment={"Variables": variables},
        )
    except Exception as error:
        raise GtfsRefreshError(
            f"Could not advance GTFS version for API Lambda {function_name}"
        ) from error
    return True


def lambda_handler(event, context):
    del event, context
    source_url = os.getenv("GTFS_SOURCE_URL", DEFAULT_SOURCE_URL)
    request_url = build_authenticated_source_url(
        source_url,
        os.getenv("ODPT_API_TOKEN", ""),
    )
    store = S3GtfsStore(
        bucket_name=os.getenv("S3_BUCKET_NAME", ""),
        state_key=os.getenv("GTFS_STATE_KEY", DEFAULT_STATE_KEY),
        version_prefix=os.getenv("GTFS_VERSION_PREFIX", DEFAULT_VERSION_PREFIX),
    )
    try:
        result = refresh_gtfs(
            downloader=UrllibDownloader(),
            store=store,
            request_url=request_url,
            source_url=source_url,
        )
        api_version_changed = advance_api_gtfs_version(
            os.getenv("API_FUNCTION_NAME", ""),
            result.new_sha256 or "",
        )
    except Exception as error:
        print(f"GTFS refresh failed: {error}", flush=True)
        raise

    if result.status == "updated":
        print(
            "GTFS updated: "
            f"{result.old_sha256 or 'none'} -> {result.new_sha256}",
            flush=True,
        )
    else:
        print("GTFS unchanged", flush=True)
    if api_version_changed:
        print(
            f"API GTFS version advanced: {result.new_sha256}",
            flush=True,
        )
    return asdict(result)
