"""Prepare a *local, unuploaded* Sendai GTFS+review directory for city S3.

The official feed and each review must already have been independently
approved. No source download, AWS request, date extension, or fallback occurs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.services.sendai_review_bundle import (  # noqa: E402
    REVIEW_FILES, REVIEW_MANIFEST, create_review_manifest, validated_reviewed_paths,
)
from sendai_operating_period import OperatingPeriodReview  # noqa: E402
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway  # noqa: E402
from sendai_transit import load_sendai_dataset  # noqa: E402


def prepare(
    *, gtfs_dir: Path, municipal: Path, published: Path, subway_review: Path,
    output: Path, expected_service_date: str, target_query_date: str,
) -> dict:
    """Atomically stage only a verified, date-scoped source + reviewed model."""
    gtfs_dir, output = gtfs_dir.resolve(), output.resolve()
    if not gtfs_dir.is_dir():
        raise ValueError("an existing approved Sendai GTFS directory is required")
    if output.exists():
        raise FileExistsError(f"refusing to replace existing Sendai staged directory: {output}")
    if output == gtfs_dir or gtfs_dir in output.parents:
        raise ValueError("reviewed output must not be inside the source GTFS directory")
    query_day = date.fromisoformat(target_query_date)
    bus = load_sendai_dataset(gtfs_dir, expected_service_date=expected_service_date)
    source_files = {"municipal": municipal, "subway_published": published,
                    "subway_review": subway_review}
    if any(not path.is_file() or path.is_symlink() for path in source_files.values()):
        raise ValueError("all three independently reviewed source files are required")
    raw_review = json.loads(municipal.read_text(encoding="utf-8"))
    if not isinstance(raw_review, dict):
        raise ValueError("Sendai municipal review must be a JSON object")
    period = OperatingPeriodReview.from_mapping(raw_review["operating_period"])
    subway, _ = load_reviewed_subway(published, subway_review, operating_period=period)
    network = build_reviewed_municipal_model(
        subway, bus, raw_review, accept_experimental_bus_transfers=True)
    period.require_query_days(query_day, (query_day,),
        additional_reviewed_days=(network.bus_reviewed_days,))

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        shutil.copytree(gtfs_dir, staged, dirs_exist_ok=True)
        for key, source in source_files.items():
            shutil.copyfile(source, staged / REVIEW_FILES[key])
        manifest = create_review_manifest(staged)
        (staged / REVIEW_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        validated_reviewed_paths(staged)
        if output.exists():
            raise FileExistsError(f"refusing to replace staged directory: {output}")
        os.replace(staged, output)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-gtfs-dir", type=Path, required=True)
    parser.add_argument("--municipal-review", type=Path, required=True)
    parser.add_argument("--subway-published", type=Path, required=True)
    parser.add_argument("--subway-review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-service-date", required=True)
    parser.add_argument("--target-query-date", required=True)
    args = parser.parse_args()
    manifest = prepare(
        gtfs_dir=args.bus_gtfs_dir, municipal=args.municipal_review,
        published=args.subway_published, subway_review=args.subway_review,
        output=args.output_dir, expected_service_date=args.expected_service_date,
        target_query_date=args.target_query_date)
    print(json.dumps({
        "status": "staged_not_uploaded", "output": str(args.output_dir),
        "source_sha256": manifest["bus_source_sha256"],
        "reviewed_query_start": manifest["query_start"],
        "reviewed_query_end": manifest["query_end"],
        "target_query_date": args.target_query_date,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
