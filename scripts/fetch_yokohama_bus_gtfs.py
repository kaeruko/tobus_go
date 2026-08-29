from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_transit import (
    YOKOHAMA_BUS_APPROVED_FEED_VERSION,
    YOKOHAMA_BUS_APPROVED_REVISION,
    YOKOHAMA_BUS_RESOURCE_ID,
    fetch_yokohama_bus_gtfs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the explicitly approved Yokohama municipal-bus GTFS-JP "
            "resource and validate an expected service date."
        )
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-service-date", required=True)
    args = parser.parse_args()

    # Local developer convenience: read api/.env once, while preserving any
    # explicitly exported process environment variable. The file is ignored by
    # git and is never uploaded by this script.
    load_dotenv(API_DIR / ".env", override=False)

    token = os.getenv("ODPT_API_TOKEN")
    if token is None or token == "":
        raise RuntimeError(
            "ODPT_API_TOKEN is required. Set it in api/.env or the process environment."
        )

    manifest = fetch_yokohama_bus_gtfs(
        args.output,
        expected_service_date=args.expected_service_date,
        consumer_key=token,
    )
    print(
        "Yokohama bus GTFS fetched: "
        f"resource_id={YOKOHAMA_BUS_RESOURCE_ID} "
        f"revision={YOKOHAMA_BUS_APPROVED_REVISION} "
        f"feed_version={YOKOHAMA_BUS_APPROVED_FEED_VERSION} "
        f"validated_service_date={manifest.validated_service_date} "
        f"feed_coverage={manifest.valid_from}..{manifest.valid_until} "
        f"calendar_coverage={manifest.calendar_coverage_from}.."
        f"{manifest.calendar_coverage_until} "
        f"sha256={manifest.sha256}"
    )


if __name__ == "__main__":
    main()
