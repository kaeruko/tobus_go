from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def load(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare current Toei scopes to pre-Metro baseline")
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--pre-metro", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    current = load(args.current)
    baseline = load(args.pre_metro)
    current_rows = {
        (row["case"], row["mode"], row["candidate_limit"]): row
        for row in current["rows"]
        if "legacy_toei" in row["tags"] and not row["estimated_transfers"]
    }
    mismatches = []
    comparisons = []
    for old in baseline["rows"]:
        key = (old["case"], old["mode"], old["candidate_limit"])
        new = current_rows.pop(key, None)
        changed = []
        if new is None:
            changed.append("missing_current_row")
        else:
            for field in ("error", "candidate_count", "candidate_sha256", "candidates"):
                if new[field] != old[field]:
                    changed.append(field)
        comparisons.append({
            "case": old["case"],
            "mode": old["mode"],
            "candidate_limit": old["candidate_limit"],
            "baseline_method": old["baseline_method"],
            "changed_fields": changed,
        })
        if changed:
            mismatches.append({"key": key, "changed_fields": changed})
    for key in current_rows:
        mismatches.append({"key": key, "changed_fields": ["unexpected_current_row"]})
    output = {
        "schema": "pre_metro_toei_comparison/v1",
        "pre_metro_commit": baseline["source_commit"],
        "rows_compared": len(comparisons),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "subway_only_note": baseline["subway_only_note"],
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"compared {len(comparisons)} rows; mismatches={len(mismatches)}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
