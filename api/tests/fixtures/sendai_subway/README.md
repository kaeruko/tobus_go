# Sendai published subway source fixtures

Source/attribution: 仙台市「仙台市地下鉄時刻表データ」, base date 2023-07-01,
downloaded 2026-10-15. CC BY 4.0 (attribution to 仙台市).

- [Official source index](https://www.city.sendai.jp/joho-kikaku/shise/security/kokai/opendata_example.html)
- [Official license catalog, all eight exact download links](https://www.city.sendai.jp/opendata/index.php?asc=data_upddt&displayedresults=100&p=4_1)
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Download base: `https://www.city.sendai.jp/joho-kikaku/shise/security/kokai/documents/`

`published_20230701.json` stores unchanged original CP932 bytes as base64, and
each original SHA-256. This container encoding is the only transformation.
Decode strictly; do not normalize original bytes before checking hashes.
No official train number is present. File hash + source row identifies a row,
not a newly asserted official train identifier.

`inspection_20261015.json` records a one-time read-only comparison against 29
official current station HTML pages: 112 nonterminal station/direction/day-type
departure multisets agree. It records source hashes, not a claim of permanent
currentness or a fixture of approved arrival clocks/calendars. The copyrighted
HTML pages are not redistributed. Use the source acquisition and inspection
scripts to perform a new independently dated review when required.

The CSV source runs (1,046 including 10 crossing midnight) are real historical
inputs. Arrival/dwell values, municipal bus feeds and paths in unit tests are
explicitly synthetic. They must never be promoted to an operational dataset.
