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

## 2026-10-24 transfer-time policy proposal

The current rule is safe but unnecessarily couples two different claims.  An
operator can officially designate a connection and publish a usable station
path without publishing a universal minimum platform-to-platform time.  The
absence of that last number should not turn the official connection into an
unknown topology.  Conversely, a connection relation alone still cannot prove
that a particular train-to-train itinerary is feasible.

The following evidence layers should remain distinct in data and UI:

| Layer | What it establishes | What it does not establish |
| --- | --- | --- |
| ODPT connection relation | The operator identifies the stations as connected | Gate/platform path or duration |
| Operator station/accessibility map | The path, gates, levels, equipment, direction and sometimes operating hours | A scaled path length or universal walk time |
| Operator distance/time | A quantitative operator value for the stated route and conditions | A guarantee for every passenger |
| Reviewed corridor | Every composed edge follows operator path evidence, with restrictions recorded | An operator-published minimum when none exists |
| App scheduling allowance | The minimum time this app permits when joining concrete trips | An official minimum, accessibility guarantee or passenger entitlement |

GTFS itself supports this separation.  `pathways.txt` and `levels.txt` model
the station graph, while `transfers.txt` `min_transfer_time` is the time that
should be sufficient for a typical rider and may include a reliability
buffer.  OpenTripPlanner similarly combines micromapped station paths with a
configurable walk speed and separate board/alight/transfer slack.  Therefore
an app-owned conservative allowance can be defensible without being presented
as an operator minimum, provided the path and the timing basis are auditable.

Proposed acceptance policy, not implemented in this continuation:

1. Keep ODPT `connectingStation` as a mandatory topology check.
2. Represent a station complex as a directed graph whose nodes are platforms,
   paid/unpaid gates, concourses and externally connected station areas.
3. Require every corridor edge to cite an operator map and record direction,
   paid-area transition, levels, equipment, opening hours and accessibility
   applicability.  A diagram that is not to scale supplies topology only.
4. Prefer an operator-published time or walked path distance.  If neither
   exists, accept an app allowance only after a documented on-site timing or
   independently measured *walked path* protocol, with repeated observations,
   the slowest reviewed observation, and a separately versioned safety buffer.
   Straight-line station coordinates and an unmeasured uniform value remain
   prohibited.
5. Compose a pair allowance as the sum of directed corridor allowances plus
   existing boarding/alighting slack.  Never take the fastest of an unknown
   edge, ignore a closed-time edge, or share a reverse value without review.
6. Label the result `reviewed_app_allowance`, not `official_minimum`, and state
   that individual walking time varies.  Accessibility-specific paths need
   separate coverage; the ordinary path must not imply accessibility.

This policy trades some false negatives for protection against false-positive
connections.  A value that is too short creates an impossible itinerary; a
value that is too long hides a legal itinerary.  Construction, gate closures,
crowding, direction-dependent escalators and first/last-train access can make
a once-reviewed value stale.  Each corridor therefore needs evidence dates,
expiry/review triggers and asymmetric tests.

Required tests before changing the runtime acceptance rule are: manifest
schema rejection tests; directed and time-window corridor composition; paid
and out-of-gate transitions; reverse/asymmetric paths; same-platform zero-walk
topology with nonzero board/alight slack; accessibility variants; exact
boundary tests where the earlier train is rejected and the next concrete trip
is accepted; the unchanged 600 m/continuous/total walking constraints; and
property tests that a composed allowance is never shorter than any constituent
path.  No transfer was enabled under this proposal in this continuation.

References for the model comparison:

- <https://gtfs.org/documentation/schedule/reference/#transferstxt>
- <https://gtfs.org/documentation/schedule/reference/#pathwaystxt>
- <https://docs.opentripplanner.org/en/latest/In-Station-Navigation/>
- <https://docs.opentripplanner.org/en/latest/RouteRequest/>

## Priority station-complex graph design

One reviewed corridor graph can safely support several ODPT pairs, but only
through explicit path composition.  It must not create a clique merely because
the stations share a complex name.

- **Otemachi:** platform nodes for Marunouchi, Tozai, Chiyoda, Hanzomon and
  Toei Mita connect through the exact concourses shown by the operator maps.
  Tokyo Metro's accessibility descriptions identify several particular
  line-to-line corridors, so these can become separately reviewed directed
  edges instead of ten hand-written pair values.
- **Akasaka-mitsuke / Nagatacho:** model the Ginza/Marunouchi platform
  arrangement separately from the corridor to Nagatacho's Hanzomon,
  Yurakucho and Namboku areas.  Same- or opposite-platform cases are special
  platform adjacency edges, not generic station walks.  Elevator/escalator
  operating hours belong on the applicable edge.
- **Hibiya / Yurakucho:** keep paid/unpaid boundaries and the inter-station
  underground route explicit.  An accessibility surface route is a different
  path and cannot silently inherit the ordinary path's allowance.
- **Iidabashi:** the official accessibility description identifies the Tozai
  to Yurakucho/Namboku/Oedo transfer corridor.  Represent that shared corridor
  once, with platform-specific access legs at each end, direction/equipment
  restrictions and published operating hours.

Official material reviewed for those structures:

- <https://www.tokyometro.jp/station/otemachi/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/otemachi/accessibility/index.html>
- <https://www.tokyometro.jp/station/akasaka-mitsuke/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/akasaka-mitsuke/accessibility/index.html>
- <https://www.tokyometro.jp/lang_en/station/nagatacho/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/hibiya/yardmap/index_print.html>
- <https://www.tokyometro.jp/station/yurakucho/yardmap/index_print.html>
- <https://www.tokyometro.jp/safety/barrierfree/progress/hibiya/index.html?vm=r>
- <https://www.tokyometro.jp/station/iidabashi/accessibility/index.html>
- <https://www.tokyometro.jp/station/toppdf/iidabashi.pdf>
- <https://www.kotsu.metro.tokyo.jp/subway/stations/iidabashi.html>

The current 54-complex audit remains a topology/review queue, not an enabled
network.  Its raw 123 pairs also contain a canonicalization detail: Metro's
main Marunouchi and Marunouchi Branch station IDs at Nakano-sakaue share GTFS
station code M06 and load as one physical graph node.  That one interchange is
already operational without a walk edge.  The branch-to-Toei pair then
duplicates the main-line-to-Toei physical pair.  The accounting is therefore
4 reviewed manifest pairs, 1 same-physical-node interchange, 1 duplicate raw
relation and 117 unique unresolved physical walk pairs.  This does not change
the manifest count from four.

## Development-only full-connection stress

To estimate graph growth without asserting unverified facts, a fresh process
loaded the production graph and added all 117 unique unresolved walk pairs in
memory only.  The production manifest SHA-256 was checked before and after and
did not change.  Two deliberately synthetic profiles were used:

- short/adversarial: 3 minutes and 120 m per unresolved pair;
- buffered: 8 minutes and 500 m per unresolved pair.

Neither profile is an official value, a proposed manifest value or a valid
passenger itinerary model.  They exist only to expose search branching.  The
date was 2026-10-23 at 10:00, feed version `20261008`, with the unchanged
15-second and 100,000-pop limits.  The following is the one-run Windows result;
every row returned the requested candidates without an error.

| Scope | Current `time` pop / s | Synthetic-short `time` pop / s | Current `fewTransfers` pop / s | Synthetic-short `fewTransfers` pop / s |
| --- | ---: | ---: | ---: | ---: |
| Toei bus | 25,660 / 5.32 | 25,660 / 4.88 | 1,665 / 0.66 | 1,665 / 0.63 |
| Toei subway | 40 / 0.45 | 40 / 0.41 | 4,014 / 0.57 | 4,014 / 0.57 |
| Tokyo Metro | 130 / 0.73 | 166 / 0.73 | 27,370 / 1.16 | 67,862 / 2.28 |
| bus + Toei subway | 8,914 / 3.01 | 8,914 / 3.21 | 4,655 / 1.11 | 4,655 / 1.09 |
| bus + Metro | 260 / 1.16 | 260 / 1.27 | 2,137 / 1.21 | 2,143 / 1.32 |
| Toei subway + Metro | 40 / 1.09 | 40 / 1.17 | 4,014 / 1.06 | 4,015 / 1.11 |
| all three | 758 / 1.70 | 951 / 1.85 | 2,139 / 1.63 | 2,170 / 1.75 |

The six non-Metro rows had identical candidate hashes and pop counts where
their scopes excluded Metro (bus, Toei subway, and their combination, both
objectives).  This confirms scope isolation in this probe.  The fixed Metro
Shibuya-to-Asakusa five-candidate case rose from 27,370 to 67,862 pops and its
maximum retained frontier rose from 28,734 to 70,917.  The buffered profile
still used 65,217 pops and 67,742 frontier labels, so the increase is mainly
the added connectivity and five-candidate enumeration, not just unrealistically
short transfers.

Synthetic priority probes demonstrated the intended branching but do not
validate the invented transfer duration:

- Nijubashimae 10:04--10:06 to Otemachi, synthetic walk 10:07--10:10,
  then an exact 10:12 train to Jimbocho: 5,340 `fewTransfers` pops;
- Tameike-sanno 10:03--10:05 to Akasaka-mitsuke, synthetic walk to Nagatacho
  10:06--10:09, then an exact 10:14 train to Kojimachi: 37,599 pops.

An additional 60 Metro-heavy distant-OD calls plus the nine base/priority
`fewTransfers` calls all returned five candidates without hitting the limit.
The worst was Nakano-sakaue to Nishi-funabashi at 85,942 pops, 88,811 retained
frontier labels and 3.01 seconds.  Only 14,058 pops (14.058%) remained.  This is
not a network-wide limit-hit rate and cannot support a production p95/p99
claim; it does show that full connectivity can move ordinary long Metro-only
queries close to the existing cap.

Candidate content is expected to change when real legal transfers are added.
The stress assertion is instead that every synthetic transfer in an output is
marked `synthetic_stress_only`, concrete GTFS trip IDs and board times are
respected conditional on that synthetic allowance, excluded services do not
enter their scopes, and no production file is mutated.

### Linux memory check

The same harness ran under local WSL Ubuntu with Python 3.12.  It read the
Windows worktree through the WSL mount, so timings are not Lambda timings.
Pops and candidate counts matched Windows exactly.

| Phase | Reviewed graph RSS | Synthetic-short RSS |
| --- | ---: | ---: |
| base pickle loaded | 596.3 MiB | 596.3 MiB |
| Toei bus GTFS loaded | 1,036.9 MiB | 1,036.8 MiB |
| Metro loaded | 1,196.5 MiB | 1,195.5 MiB |
| 117 synthetic pairs added | n/a | 1,195.5 MiB |
| final RSS after suite | 1,237.8 MiB | 1,241.1 MiB |
| process peak | 1,280.6 MiB | 1,281.1 MiB |

The edges themselves added less than the measurement resolution; loaded base
and bus data dominate.  The largest sampled frontier in the seven-scope suite
was still the Toei-bus `time` case (120,780 labels).  The committed string
sharing remains in use; no timetable structure was removed and no memory code
changed in this continuation.  Docker Desktop's Linux engine was unavailable,
so WSL was used locally.  No AWS login or resource access was performed.

## Safe search work and release gates

The current admissible lexicographic suffix bound is used for queue ordering.
With the exact five-result contract, a simple "stop after the fifth result"
branch-and-bound rule cannot reduce the work performed before that fifth
candidate is popped.  Collapsing concrete-run/boarding/walk-resource state,
fixed per-node label caps, bucket equality and heuristics based only on a
station name all have known counterexamples and remain rejected.

Two possible exact improvements deserve isolated proof and differential tests:

1. a lower bound on remaining elapsed time used only to reject a label that
   cannot satisfy the unchanged 180-minute deadline; it must cover every legal
   rail, bus and walk suffix and include a floating-point safety guard;
2. stronger route-based/RAPTOR-style admissible suffix preprocessing for
   ordering, or exact dominance only after proving that the key contains the
   complete future-equivalence state (concrete run and sequence, boarding
   phase, counts and all walking resources).

No new pruning was implemented because the present evidence does not prove
that the same five candidates and order are preserved.

Public release should remain blocked until: (a) useful origin-destination
coverage is defined and its necessary complexes have reviewed directed paths
and app allowances; (b) current, weekend/holiday, last-train, date-crossing,
direction, closure and missed-transfer cases pass on those paths; (c) a much
broader Metro-heavy corpus demonstrates acceptable cap margin and records any
100,000-pop failures without raising the cap; (d) Linux/Lambda-like cold-load
and search memory fit the intended deployment with operational headroom; and
(e) the UI clearly calls values app scheduling allowances rather than official
minimums or guarantees.  AWS/Lambda validation remains separate and was not
performed here.
