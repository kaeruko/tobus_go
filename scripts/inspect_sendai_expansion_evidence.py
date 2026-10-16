"""Hash explicit official evidence for this staged review, without substitutes."""
import hashlib
import json
from datetime import datetime, timezone

import httpx


SOURCES = {
    "holidays": "https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html",
    "normal_subway": "https://www.navi.kotsu.city.sendai.jp/dia/bustime/sp/subway/9285/",
    "subway_notices": "https://www.kotsu.city.sendai.jp/subway_news/",
    "bus_notices": "https://www.kotsu.city.sendai.jp/news/",
    "bus_special_day": "https://www.kotsu.city.sendai.jp/daigaku-jyoshiekiden/",
    "izumi_bays": "https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/izumichuo/izumityuuou_h3004.jpg",
    "izumi_station": "https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/09/N01_izumityuuou_25.pdf",
    "sanezawa_routes": "https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-7_sanezawa.pdf",
}


def main():
    result = {}
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for key, uri in SOURCES.items():
            response = client.get(uri)
            response.raise_for_status()
            if response.status_code != 200 or not response.content:
                raise ValueError(f"exact non-empty original source required: {key}")
            result[key] = {"uri": uri, "sha256": hashlib.sha256(response.content).hexdigest(),
                           "bytes": len(response.content), "retrieved_at": datetime.now(timezone.utc).isoformat()}
    # This inventory does not automatically approve any timetable or free path.
    print("SENDAI_EXPANSION_EVIDENCE=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
