from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from gtfs_refresh import (
    DEFAULT_SOURCE_URL,
    DEFAULT_STATE_KEY,
    DEFAULT_VERSION_PREFIX,
    DownloadResult,
    GtfsDownloadError,
    GtfsRefreshError,
    RefreshResult,
    RefreshState,
    S3GtfsStore,
    UrllibDownloader,
    advance_api_gtfs_version,
    build_authenticated_source_url,
    validate_gtfs_zip,
)
from gtfs_state import (
    GTFS_STATE_SCHEMA_VERSION,
    CompiledGtfsArtifact,
    build_compiled_state_from_zip,
    sha256_file,
)


DEFAULT_COMPILED_PREFIX = "gtfs/toei/compiled"


def _error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    return response.get("Error", {}).get("Code")


def _load_state_json(store: S3GtfsStore) -> dict[str, Any] | None:
    try:
        response = store.s3.get_object(
            Bucket=store.bucket_name,
            Key=store.state_key,
        )
    except Exception as error:
        if _error_code(error) in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise GtfsRefreshError("Could not read GTFS state from S3") from error

    try:
        raw = json.loads(response["Body"].read())
    except Exception as error:
        raise GtfsRefreshError("GTFS state JSON is invalid") from error
    if not isinstance(raw, dict):
        raise GtfsRefreshError("GTFS state JSON must be an object")

    # Reuse the existing strict validation for the authoritative raw GTFS fields.
    RefreshState.from_json(json.dumps(raw))
    return raw


def _compiled_pointer_is_current(state: dict[str, Any]) -> bool:
    return (
        isinstance(state.get("compiled_state_key"), str)
        and bool(state["compiled_state_key"])
        and isinstance(state.get("compiled_state_sha256"), str)
        and len(state["compiled_state_sha256"]) == 64
        and state.get("compiled_state_schema_version") == GTFS_STATE_SCHEMA_VERSION
        and isinstance(state.get("compiled_state_record_counts"), dict)
    )


def _store_compiled_state(
    store: S3GtfsStore,
    artifact: CompiledGtfsArtifact,
    *,
    compiled_prefix: str,
) -> str:
    object_key = f"{compiled_prefix.strip('/')}/{artifact.source_sha256}.pkl.gz"
    try:
        response = store.s3.head_object(
            Bucket=store.bucket_name,
            Key=object_key,
        )
    except Exception as error:
        if _error_code(error) not in {"NoSuchKey", "404", "NotFound"}:
            raise GtfsRefreshError("Could not inspect compiled GTFS state in S3") from error
    else:
        metadata = response.get("Metadata", {}) if isinstance(response, dict) else {}
        if (
            metadata.get("sha256") != artifact.sha256
            or metadata.get("source-sha256") != artifact.source_sha256
            or metadata.get("schema-version") != str(artifact.schema_version)
        ):
            raise GtfsRefreshError(
                f"Existing compiled GTFS object metadata does not match: {object_key}"
            )
        return object_key

    try:
        with open(artifact.path, "rb") as body:
            store.s3.put_object(
                Bucket=store.bucket_name,
                Key=object_key,
                Body=body,
                ContentType="application/gzip",
                Metadata={
                    "sha256": artifact.sha256,
                    "source-sha256": artifact.source_sha256,
                    "schema-version": str(artifact.schema_version),
                },
            )
    except Exception as error:
        raise GtfsRefreshError("Could not upload compiled GTFS state to S3") from error
    return object_key


def _save_extended_state(
    store: S3GtfsStore,
    *,
    base_state: dict[str, Any],
    artifact: CompiledGtfsArtifact,
    compiled_state_key: str,
) -> None:
    state = dict(base_state)
    state.update(
        {
            "compiled_state_key": compiled_state_key,
            "compiled_state_sha256": artifact.sha256,
            "compiled_state_schema_version": artifact.schema_version,
            "compiled_state_record_counts": artifact.record_counts,
        }
    )
    payload = (
        json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        store.s3.put_object(
            Bucket=store.bucket_name,
            Key=store.state_key,
            Body=payload,
            ContentType="application/json",
            CacheControl="no-cache",
        )
    except Exception as error:
        raise GtfsRefreshError("Could not switch the active GTFS state in S3") from error


def _compile_and_publish(
    store: S3GtfsStore,
    *,
    source_zip_path: str,
    source_sha256: str,
    base_state: dict[str, Any],
    compiled_prefix: str,
) -> CompiledGtfsArtifact:
    compiled_path = os.path.join(
        tempfile.gettempdir(),
        f"toeigo-gtfs-{source_sha256}.pkl.gz",
    )
    try:
        artifact = build_compiled_state_from_zip(
            source_zip_path,
            source_sha256=source_sha256,
            output_path=compiled_path,
        )
        compiled_key = _store_compiled_state(
            store,
            artifact,
            compiled_prefix=compiled_prefix,
        )
        _save_extended_state(
            store,
            base_state=base_state,
            artifact=artifact,
            compiled_state_key=compiled_key,
        )
        return artifact
    finally:
        try:
            os.remove(compiled_path)
        except FileNotFoundError:
            pass


def _backfill_compiled_state(
    store: S3GtfsStore,
    previous: dict[str, Any],
    *,
    compiled_prefix: str,
) -> RefreshResult:
    previous_state = RefreshState.from_json(json.dumps(previous))
    with tempfile.NamedTemporaryFile(
        prefix="toei-gtfs-backfill-",
        suffix=".zip",
        delete=False,
    ) as temporary:
        source_path = temporary.name
    try:
        try:
            store.s3.download_file(
                store.bucket_name,
                previous_state.object_key,
                source_path,
            )
        except Exception as error:
            raise GtfsRefreshError(
                "Could not download the active GTFS ZIP for compiled-state backfill"
            ) from error
        actual_sha256 = sha256_file(source_path)
        if actual_sha256 != previous_state.sha256:
            raise GtfsRefreshError(
                "Active GTFS ZIP checksum does not match state during compiled-state backfill"
            )
        validate_gtfs_zip(source_path)
        _compile_and_publish(
            store,
            source_zip_path=source_path,
            source_sha256=previous_state.sha256,
            base_state=previous,
            compiled_prefix=compiled_prefix,
        )
        return RefreshResult(
            status="updated",
            reason="compiled_state_backfill",
            old_sha256=previous_state.sha256,
            new_sha256=previous_state.sha256,
            object_key=previous_state.object_key,
        )
    finally:
        try:
            os.remove(source_path)
        except FileNotFoundError:
            pass


def refresh_gtfs_with_compiled_state(
    *,
    downloader,
    store: S3GtfsStore,
    request_url: str,
    source_url: str = DEFAULT_SOURCE_URL,
    compiled_prefix: str = DEFAULT_COMPILED_PREFIX,
    now: datetime | None = None,
) -> RefreshResult:
    previous_raw = _load_state_json(store)

    # Migration is explicit and atomic: derive the compiled artifact from the
    # already-authoritative immutable ZIP, then add its pointer to state.json.
    if previous_raw is not None and not _compiled_pointer_is_current(previous_raw):
        return _backfill_compiled_state(
            store,
            previous_raw,
            compiled_prefix=compiled_prefix,
        )

    previous = (
        RefreshState.from_json(json.dumps(previous_raw))
        if previous_raw is not None
        else None
    )
    conditional_headers: dict[str, str] = {}
    if previous and previous.etag:
        conditional_headers["If-None-Match"] = previous.etag
    if previous and previous.last_modified:
        conditional_headers["If-Modified-Since"] = previous.last_modified

    with tempfile.NamedTemporaryFile(
        prefix="toei-gtfs-",
        suffix=".zip",
        delete=False,
    ) as temporary:
        source_path = temporary.name

    try:
        downloaded: DownloadResult = downloader.download(
            request_url,
            conditional_headers,
            source_path,
        )
        if downloaded.status_code == 304:
            if previous is None:
                raise GtfsDownloadError("GTFS source returned 304 without existing state")
            return RefreshResult(
                status="unchanged",
                reason="http_304",
                old_sha256=previous.sha256,
                new_sha256=previous.sha256,
                object_key=previous.object_key,
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

        validate_gtfs_zip(source_path)
        object_key = store.store_version(source_path, downloaded.sha256)
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        next_state = RefreshState(
            etag=downloaded.etag,
            last_modified=downloaded.last_modified,
            sha256=downloaded.sha256,
            updated_at=timestamp.isoformat().replace("+00:00", "Z"),
            object_key=object_key,
            source_url=source_url,
        )
        base_state = asdict(next_state)

        # state.json is not switched until both the immutable source ZIP and the
        # compiled artifact have been uploaded and validated.
        _compile_and_publish(
            store,
            source_zip_path=source_path,
            source_sha256=downloaded.sha256,
            base_state=base_state,
            compiled_prefix=compiled_prefix,
        )
        return RefreshResult(
            status="updated",
            reason="sha256_changed",
            old_sha256=previous.sha256 if previous else None,
            new_sha256=downloaded.sha256,
            object_key=object_key,
        )
    finally:
        try:
            os.remove(source_path)
        except FileNotFoundError:
            pass


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
        result = refresh_gtfs_with_compiled_state(
            downloader=UrllibDownloader(),
            store=store,
            request_url=request_url,
            source_url=source_url,
            compiled_prefix=os.getenv(
                "GTFS_COMPILED_PREFIX",
                DEFAULT_COMPILED_PREFIX,
            ),
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
            f"{result.old_sha256 or 'none'} -> {result.new_sha256} "
            f"reason={result.reason}",
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
