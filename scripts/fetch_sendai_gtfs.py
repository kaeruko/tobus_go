from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from sendai_transit import fetch_sendai_gtfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the configured Sendai municipal-bus GTFS-JP source and "
            "validate an explicitly approved service date."
        )
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-service-date", required=True)
    args = parser.parse_args()

    token = os.getenv("ODPT_API_TOKEN")
    if token is None or token == "":
        raise RuntimeError("ODPT_API_TOKEN is required to fetch Sendai static GTFS")

    manifest = fetch_sendai_gtfs(
        args.output,
        expected_service_date=args.expected_service_date,
        consumer_key=token,
    )
    print(
        "Sendai GTFS fetched: "
        f"validated_service_date={manifest.validated_service_date} "
        f"coverage={manifest.valid_from}..{manifest.valid_until} "
        f"sha256={manifest.sha256}"
    )


if __name__ == "__main__":
    main()
