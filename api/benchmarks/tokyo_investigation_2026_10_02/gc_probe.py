"""Measure full-GC cost with the Tokyo graph loaded, without running a route."""

from __future__ import annotations

import gc
import json
import pickle
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter


API_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_DIR))
import toei_engine  # noqa: E402,F401 -- required by the prebuilt pickle


def main() -> None:
    started = perf_counter()
    with (API_DIR / "data" / "app_data.pkl").open("rb") as source:
        data = pickle.load(source)
    load_ms = (perf_counter() - started) * 1000
    samples = []
    for _ in range(7):
        started = perf_counter()
        collected = gc.collect()
        samples.append(
            {"ms": (perf_counter() - started) * 1000, "collected": collected}
        )
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "graph_nodes": len(data["G"]),
        "graph_edges": data["G"].number_of_edges(),
        "load_ms": load_ms,
        "gc_full_collection_without_search": samples,
        "gc_median_ms": statistics.median(sample["ms"] for sample in samples),
    }
    encoded = json.dumps(result, indent=2) + "\n"
    Path(__file__).with_suffix(".json").write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
