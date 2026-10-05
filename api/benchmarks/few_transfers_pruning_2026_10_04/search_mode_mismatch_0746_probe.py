"""Compare cost and fewTransfers for the October 6 07:46 screenshot.

The screenshot does not include destination coordinates. Reuse the Shibuya
ward office coordinates from the previous investigations as an explicit proxy.
No search priority, safety limit or realtime data is changed.
"""
import argparse
from types import SimpleNamespace

import time_astar_product_probe as product


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("cost", "fewTransfers"), required=True)
    args = parser.parse_args()
    product.OUT = product.rss.OUT / "search_mode_mismatch_2026_10_06"
    product.CASES = {
        "shibuya_0746": {
            "target_date_str": "2026-10-06", "start_time": "07:46",
            "blat": 35.6636842, "blon": 139.6977409,
        },
    }
    return product.worker(SimpleNamespace(mode=args.mode, case="shibuya_0746", repeats=1))


if __name__ == "__main__":
    raise SystemExit(main())
