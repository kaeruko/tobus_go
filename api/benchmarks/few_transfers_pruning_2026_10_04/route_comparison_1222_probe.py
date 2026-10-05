"""Replay the October 5 12:22 screenshot request using the production adapter.

Only the input and output directory of the existing reviewed measurement
pipeline are changed. No network calls or search-logic replacements are made.
"""
from types import SimpleNamespace

import time_astar_product_probe as product


def main():
    product.OUT = product.rss.OUT / "route_comparison_1222_2026_10_05"
    product.CASES = {
        "shibuya_1222": {
            "target_date_str": "2026-10-05", "start_time": "12:22",
            "blat": 35.658034, "blon": 139.701636,
        },
    }
    return product.worker(SimpleNamespace(mode="time", case="shibuya_1222", repeats=1))


if __name__ == "__main__":
    raise SystemExit(main())
