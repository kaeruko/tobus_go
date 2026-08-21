from __future__ import annotations

import argparse
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from nagoya_transit import fetch_nagoya_gtfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the explicitly approved Nagoya city-bus GTFS-JP resource."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args()

    manifest = fetch_nagoya_gtfs(
        args.output,
        expected_revision=args.expected_revision,
    )
    print(
        "Nagoya GTFS fetched: "
        f"revision={manifest.revision} "
        f"resource_id={manifest.resource_id} "
        f"sha256={manifest.sha256}"
    )


if __name__ == "__main__":
    main()
