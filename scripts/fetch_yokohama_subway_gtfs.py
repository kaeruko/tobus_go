"""Download one explicitly pinned Yokohama subway GTFS edition for local review."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_subway import fetch_yokohama_subway_gtfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and validate the pinned Yokohama subway static GTFS locally."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-service-date", required=True)
    args = parser.parse_args()
    load_dotenv(API_DIR / ".env", override=False)
    token = os.environ.get("ODPT_API_TOKEN")
    if not token:
        raise RuntimeError(
            "ODPT_API_TOKEN is required in api/.env or the process environment"
        )
    result = fetch_yokohama_subway_gtfs(
        args.output,
        expected_service_date=args.expected_service_date,
        consumer_key=token,
    )
    # The token, full authenticated URL, and response body are never printed.
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
