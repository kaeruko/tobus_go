# Tokyo Metro rail-transfer review

Review date: 2026-10-23 (Asia/Tokyo)

This review separates an official connection relation from a transfer path
that this application can safely schedule. The authenticated ODPT station
master is not committed. Run `scripts/audit_tokyo_metro_transfers.py` against
that local input to reproduce the complete inventory.

## Inventory and acceptance rule

The accepted ODPT station snapshot contains 123 distinct relevant station
pairs: 72 Tokyo Metro-to-Metro pairs and 51 Tokyo Metro-to-Toei subway pairs.
Pairs involving the Toei Arakawa Line or Nippori-Toneri Liner are excluded.

An ODPT `odpt:connectingStation` relation proves topology only. It does not
prove a platform/gate walking path or its duration. A pair is enabled only
when all of the following are available:

1. an official ODPT connection relation;
2. an official station map, transfer map, or operator transfer notice showing
   the actual route;
3. an official route distance or equivalent path evidence from which the
   existing 80 m/min walking floor can be applied without using straight-line
   station coordinates;
4. an application allowance that is no shorter than that walking floor;
5. explicit operator URLs and a review date in the committed manifest.

Rail alighting and boarding allowances already present in the search engine
are applied in addition to `minimum_minutes`. The values below are conservative
application scheduling allowances derived from official route/path evidence;
they are not represented as universal operator-published platform-to-platform
times. A delayed passenger or an entrance/platform choice can take longer.

## Enabled reviewed pairs

| Pair | Kind | Official path evidence | App walk allowance |
| --- | --- | --- | ---: |
| Hibiya Ningyocho ↔ Hanzomon Suitengumae | Metro ↔ Metro | Official 2018 interchange notice and Ningyocho route map; about 150 m | 7 min |
| Hanzomon Suitengumae ↔ Toei Asakusa Ningyocho | Metro ↔ Toei | Official 2018 interchange notice and Ningyocho route map; about 150 m | 8 min |
| Ginza Toranomon ↔ Hibiya Toranomon Hills | Metro ↔ Metro | Official 2020 route diagram; underground route about 450 m | 6 min |
| Ginza Ginza ↔ Yurakucho Ginza-itchome | Metro ↔ Metro | Official 2020 route diagram; the longer published route is about 300 m | 4 min |

Evidence:

- <https://www.tokyometro.jp/news/images_h/metroNews20180215_12.pdf>
- <https://www.tokyometro.jp/info/ningyocho.pdf>
- <https://www.tokyometro.jp/news/images_h/5dd3751942166712a7d85b7fa75bf25f_1.pdf>
- <https://www.tokyometro.jp/info/files/200514_ginza_norikaeeki.pdf>
- <https://www.tokyometro.jp/ticket/guide/transfertime/index.html>

The Tokyo Metro 60-minute rule on the last page is a fare-continuation window,
not a minimum transfer duration. It is not used as a search time.

The manifest is `api/config/tokyo_metro_reviewed_transfers.json`. Import fails
if a pair is absent from the official ODPT relation, an evidence URL is not on
an approved operator/ODPT host, a value is outside the existing 600 m walk
limit, or the minutes are shorter than the official-path-distance walking
floor. All other rail connections remain absent from the graph.

## Exact-route checks

The following local searches used GTFS feed `20261008`, service date
2026-10-23, departure 10:00, unchanged 15-second/100,000-pop limits, and the
committed manifest.

| Search | Reviewed transfer in first result | Concrete Metro legs | `fewTransfers` pop |
| --- | --- | --- | ---: |
| Hibiya Hatchobori → Hanzomon Kinshicho | Ningyocho 10:07 → Suitengumae 10:14 | `30B0958S00` 10:02–10:06; `70A0977S00` 10:16–10:24 | 16,669 |
| Yurakucho Toyosu → Ginza Shibuya | Ginza-itchome 10:09 → Ginza 10:13 | `61B0906M00` 10:02–10:08; `11A0957000` 10:15–10:31 | 21,783 |
| Hibiya Ebisu → Ginza Asakusa | Toranomon Hills 10:15 → Toranomon 10:21 | `30B1066S00` 10:03–10:14; `10B1005000` 10:23–10:44 | 36,280 |
| Toei Oedo Kachidoki → Ginza Shibuya | Toei Asakusa Ningyocho 10:27 → Suitengumae 10:35 | Metro `71B1064T00` 10:38–10:58 | 39,684 |

The response carries `walking_connection_verified=true`,
`walking_time_basis=reviewed_station_path`, and the official evidence URLs.
The unit regression also creates a train one minute too early for the reviewed
walk plus the existing boarding allowance and proves that it is rejected in
favor of the later exact trip. No timetable, walking, objective, timeout, pop,
or boarding constraint was relaxed.

## Unresolved pairs

119 pairs remain disabled: 69 Metro-to-Metro and 50 Metro-to-Toei subway.
This includes most high-usage ordinary interchanges such as Otemachi,
Omote-sando, Ueno, Iidabashi, and Jimbocho. Their ODPT relation and station map
may be available, but this review did not establish a complete path-distance
and safe scheduling allowance under the rule above. They must not be inferred
from a shared name, station coordinates, or the 60-minute fare rule.

This is therefore a useful but deliberately incomplete transfer network. It is
not ready to be described as full Tokyo Metro/Toei interchange coverage.
