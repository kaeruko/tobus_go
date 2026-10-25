from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def _mib(value: int) -> float:
    return round(value / (1024 * 1024), 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()

    measurement = json.loads(args.measurement.read_text(encoding="utf-8"))
    workers = measurement["workers"]
    summary = {
        "schema": "tokyo_metro_phase4_linux_summary/v1",
        "environment": measurement["environment"],
        "inputs": measurement["inputs"],
        "modes": {},
        "comparison": measurement["comparison"],
        "warning": (
            "Local WSL2 evidence only. This is not a Lambda measurement and "
            "does not establish Lambda memory compatibility."
        ),
    }
    for name, worker in workers.items():
        ready = worker["ready"]
        summary["modes"][name] = {
            "feed": worker["feed"],
            "external_process_start_to_ready_seconds": ready[
                "external_process_start_to_ready_seconds"
            ],
            "stages": worker["stages"],
            "search": worker["summary"],
            "ready_rss_mib": _mib(ready["rss_bytes"]),
            "search_peak_rss_mib": _mib(
                worker["summary"]["max_sampled_peak_rss_bytes"]
            ),
        }

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with args.measurement.open("rb") as source, args.archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                target.write(block)


if __name__ == "__main__":
    main()
