# Tokyo Metro rail-transfer review

Review date: 2026-10-23 (Asia/Tokyo)

Continuation review: 2026-10-24 (Asia/Tokyo)

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

## 2026-10-24 station-complex audit

The official Metro GTFS snapshot has no `transfers.txt`, `pathways.txt`, or
`levels.txt`.  Its stop records describe one stop per line station and cannot
provide a platform/gate route or a minimum interchange time.  ODPT
`odpt:connectingStation` remains topology evidence only.

The audit script now groups the 123 pair relations into 54 connected station
complexes.  This is a safe way to reduce review work: a future corridor model
can represent platform/gate/corridor segments once and derive several pair
paths by composing only reviewed segments.  A derived pair must satisfy all of
these conditions before it can enter the runtime manifest:

1. every segment and its direction are shown by an official operator map;
2. every segment has an operator-published duration/distance, or another
   reviewed non-coordinate timing basis;
3. the composed allowance is no shorter than the sum of segment allowances;
4. opening hours, out-of-gate transitions, and accessibility restrictions are
   represented where applicable;
5. the final pair still exists in ODPT `connectingStation`.

Grouping never enables a transfer by itself.  A shared station name,
straight-line coordinates, or the 60-minute fare continuation rule remains
insufficient.  Tokyo Metro's public fare/transfer search also says that bulk
access for secondary use is not intended, so it is not scraped to manufacture
a transfer-time dataset.

The reproducible topology-only review order is the number of unresolved pairs,
then line count.  It measures review leverage, not passenger demand.

| Priority | Station complex | Lines | Pairs | Unresolved |
| ---: | --- | ---: | ---: | ---: |
| 1 | Otemachi | 5 | 10 | 10 |
| 2 | Akasaka-mitsuke / Nagatacho | 5 | 10 | 10 |
| 3 | Hibiya / Yurakucho | 4 | 6 | 6 |
| 4 | Iidabashi | 4 | 6 | 6 |
| 5 | Kokkai-gijidomae / Tameike-sanno | 4 | 6 | 6 |
| 6 | Kasuga / Korakuen | 4 | 5 | 5 |
| 7 | Ginza / Ginza-itchome | 4 | 6 | 5 |
| 17 | Omote-sando | 3 | 3 | 3 |
| 20 | Jimbocho | 3 | 2 | 2 |

Ueno (Ginza/Hibiya) is a single unresolved pair; the nearby
Ueno-hirokoji/Naka-okachimachi/Ueno-okachimachi complex is a separate
three-pair complex.  Official maps confirm routes at the named priority
stations.  The operator also explicitly describes the Ginza and Hanzomon
lines at Omote-sando as using the same platform.  None of those sources gives
a reusable minimum platform-to-platform duration.  Adding `1 minute` or an
invented metre value would violate the acceptance rule, so no new pair was
enabled in this continuation.  Counts remain 4 reviewed and 119 unresolved.

Reproduce the grouped inventory with:

```text
python scripts/audit_tokyo_metro_transfers.py \
  --stations <authenticated odpt_Station_TokyoMetro.json> \
  --output <local audit.json>
```

The output schema is `tokyo_metro_transfer_audit/v2`; the authenticated station
master and generated audit remain untracked.

Official sources reviewed for this continuation:

- <https://www.tokyometro.jp/station/otemachi/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/iidabashi/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/omote-sando/yardmap/index_print.html>
- <https://www.kotsu.metro.tokyo.jp/subway/stations/jimbocho.html>
- <https://www.tokyometro.jp/news/2017/190616.html>
- <https://ssl.tokyometro.jp/support/faq_answer?faqno=OpenFAQ-000204>
- <https://www.tokyometro.jp/transit/terms/index.html>

## 2026-10-24 performance and memory regression

No transfer pair was added, so there is no synthetic "after each addition"
measurement.  The fixed Shibuya to Asakusa Metro-only search remains five
candidates and 27,370 pops in `fewTransfers` (1.175 seconds in this Windows
run).  The four enabled-transfer probes also retained their concrete trips,
clocks, order, and pop counts: 16,669; 21,783; 36,280; and 39,684.

The GTFS loader now reuses the retained trip, stop, and route ID string objects
when constructing stop-time and timetable indexes.  Values, mappings, compiled
state, calendars, pickup/drop-off flags, and lookup behavior are unchanged.
The same Shibuya to Asakusa response differed only in
`tokyo_metro_data_obtained_at`; all five candidates were byte-equivalent after
excluding the existing volatile `step_id` fields and that observation
timestamp.

Fresh-process Windows memory (`app_data.pkl`, Toei bus GTFS, Metro import, then
the fixed search):

| Phase | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| after Toei bus GTFS | 1,168.1 MiB RSS | 1,042.1 MiB RSS | 126.0 MiB |
| after Metro import | 1,328.3 MiB RSS | 1,200.7 MiB RSS | 127.6 MiB |
| after search | 1,339.6 MiB RSS | 1,211.1 MiB RSS | 128.5 MiB |
| process peak working set | 1,359.8 MiB | 1,233.2 MiB | 126.6 MiB |

This reduces duplicate source-ID strings rather than deleting timetable data.
It does not prove Lambda peak memory: allocator and pickle behavior differ on
Linux, and the compiled bus asset must be regenerated with this loader to
retain object sharing.  A read-only Lambda measurement remains a pre-release
task; no AWS login or resource change was performed here.

Current local representative results (seconds are single-run observations):

| Scope | `time` pop / sec / candidates | `fewTransfers` pop / sec / candidates |
| --- | --- | --- |
| Toei bus | 25,660 / 4.488 / 1 | 1,665 / 0.609 / 5 |
| Toei subway | 40 / 0.414 / 1 | 4,014 / 0.451 / 5 |
| Tokyo Metro | 130 / 0.729 / 1 | 27,370 / 1.175 / 5 |
| bus + Toei subway | 8,914 / 2.725 / 1 | 4,655 / 1.100 / 5 |
| bus + Metro | 260 / 1.171 / 1 | 2,137 / 1.215 / 5 |
| Toei subway + Metro | 40 / 1.134 / 1 | 4,014 / 1.085 / 5 |
| all three | 758 / 1.671 / 1 | 2,139 / 1.606 / 5 |

The unchanged 15-second and 100,000-pop limits were used.  Weekend and holiday
Metro searches were 27,262 pops, the 23:40 last-train probe returned two
candidates at 629 pops, and the 23:20 date-crossing probe returned five at
1,803 pops.  These local samples do not establish production p95/p99 behavior.
