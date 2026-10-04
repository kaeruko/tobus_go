"""Refresh only rail run metadata in a trusted local Tokyo prebuilt artifact."""

import argparse
from pathlib import Path
import pickle

from toei_engine import ensure_train_run_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prebuilt", type=Path, required=True)
    parser.add_argument("--train-timetables", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.prebuilt.resolve() or args.output.exists():
        parser.error("output must be a new file; the input artifact is retained")
    with args.prebuilt.open("rb") as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict) or "TM" not in data:
        parser.error("prebuilt artifact must contain TM")
    changed = ensure_train_run_metadata(data["TM"], str(args.train_timetables))
    with args.output.open("wb") as stream:
        pickle.dump(data, stream, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Rail metadata refreshed={changed}; saved {args.output}")


if __name__ == "__main__":
    main()
