#!/usr/bin/env python3
"""Download public official review inputs locally; never activate a feed."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from sendai_subway_source_audit import STATION_CODES
from transit_adapters.sendai_subway import FILES, SOURCE_BASE, inspect_csv


def fetch_sources(output: Path, *, get=requests.get):
    # A failed acquisition retains partial original bytes for diagnosis. It
    # cannot be resumed silently; use a distinct directory for a new snapshot.
    output.mkdir(parents=False, exist_ok=False)
    entries = []
    sources = [(name, SOURCE_BASE + name, "cp932") for name in FILES]
    sources += [(f"current-{code}.raw.html",
                 f"https://www.navi.kotsu.city.sendai.jp/dia/bustime/sp/subway/{code}/", "shift_jis")
                for code in sorted(set().union(*map(set, STATION_CODES.values())))]
    for name, uri, encoding in sources:
        response = get(uri, timeout=40)
        response.raise_for_status()
        raw = response.content
        raw.decode(encoding, errors="strict")
        if name in FILES:
            inspect_csv(name, raw)
        elif 'charset="shift_jis"' not in raw.decode(encoding).lower():
            raise ValueError("official current HTML changed charset/schema")
        (output / name).write_bytes(raw)
        entries.append({"name": name, "uri": uri, "sha256": hashlib.sha256(raw).hexdigest(),
                        "captured_at": datetime.now(timezone.utc).isoformat(), "encoding": encoding})
    (output / "acquisition.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    entries = fetch_sources(args.output_dir)
    print(json.dumps({"downloaded": len(entries), "operational_ready": False}))


if __name__ == "__main__":
    main()
