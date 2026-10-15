#!/usr/bin/env python3
"""Inspect retained official files without downloads or production imports."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from sendai_subway_source_audit import STATION_CODES, audit_sources
from transit_adapters.sendai_subway import FILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", required=True, type=Path)
    parser.add_argument("--current-html-dir", required=True, type=Path,
                        help="retained official Shift_JIS current-CODE.raw.html files")
    args = parser.parse_args()
    result = audit_sources({name: (args.csv_dir / name).read_bytes() for name in FILES},
        {code: (args.current_html_dir / f"current-{code}.raw.html").read_bytes()
         for code in set().union(*map(set, STATION_CODES.values()))})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("READ_ONLY_SENDAI_SUBWAY_SOURCE_INSPECTION_OK")
    print("OPERATIONAL_CERTIFICATION_WITHHELD")


if __name__ == "__main__":
    main()
