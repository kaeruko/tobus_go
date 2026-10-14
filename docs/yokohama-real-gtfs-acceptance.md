## Real GTFS bus/subway acceptance (read-only, not public approval)

Source: `scripts/verify_yokohama_municipal_real_gtfs.py`. This is the
first-stage **two-feed** acceptance probe for #241, separate from the existing
bus-only `smoke_yokohama_real_gtfs.py`. It reads only installed manifests,
coverage, reviewed links and raw GTFS; it never downloads data or writes files.

Prerequisites:
1. Local bus GTFS with its validated pinned bus manifest, and its existing
   bus-specific review coverage; no automatic approval of additional bus routes.
2. ODPT subway GTFS pinned to the reviewed 20251226 edition, with manifest and
   matching file hashes. A login/consumer key may be required **for obtaining
   the data separately**, but the acceptance script itself never accesses one.
3. An *independently reviewed*, version-locked walking-link JSON
   (`YOKOHAMA_REVIEWED_TRANSFERS_PATH` format) with exact namespaced bus-pole
   and subway-station IDs, a measured route distance, a conservative walking
   duration, and official evidence. **An official page merely listing a nearby
   bus stop does not itself prove a specific pole-to-entrance pedestrian path.**
4. Exact origin/destination stop IDs in opposite feeds and a scheduled start
   clock for which that exact link should produce a route. Do not substitute
   same-named stops for IDs.

Example argument shape, with deliberate placeholders (not executable test data):

```text
python scripts/verify_yokohama_municipal_real_gtfs.py
  --bus-gtfs-dir <existing-bus-gtfs-dir>
  --bus-coverage <existing-reviewed-bus-coverage.json>
  --subway-gtfs-dir <existing-subway-gtfs-dir>
  --reviewed-links <verified-transfer-links.json>
  --service-date YYYY-MM-DD --start-time HH:MM
  --origin-stop-id yokohama_bus:<real-origin-id>
  --destination-stop-id yokohama_subway:<real-destination-id>
  --bus-transfer-stop-id yokohama_bus:<reviewed-pole-id>
  --subway-transfer-stop-id yokohama_subway:<reviewed-station-id>
```

The verifier must find and inspect a reviewed transfer for BOTH welfare and
senior passes. It compares every emitted bus and rail trip, GTFS stop sequence,
times, active service, exact walking link, ride order and extra-payment
quotations. Failures stop immediately with diagnostics. No synthetic proximity
transfer or fallback source is enabled.

A PASS is only **same-feed source consistency**, not independent verification of
official timetable accuracy, physical walking safety, accessibility, operator
GTFS redistribution rights, or comprehensive all-city search. Separate
independent acceptance should cross-check the exact physical pole-to-entrance
walk, any stairs/lifts/road crossings, and representative OD timetable against
the operator's own map/timetable.

As of 2026-10-14, the official site confirms that Sakuragicho subway station
lists Sakuragicho-ekimae among nearby municipal-bus stops:
https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/detail/Station?id=00002909
and the municipal operator provides a directional bus-bay map:
https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090408
These are useful **manual investigation evidence**, not approval of any exact
GTFS stop ID, measured walking distance or minutes. No production link file
was fabricated from these documents.

ODPT catalog lists the 20251226 subway edition as valid through 2026-12-31;
the source is registration-based and subject to the Basic License and
Specific Terms of Use:
https://ckan.odpt.org/dataset/yokohama_municipal_train


### Before approving any walking link

The existing read-only triage command extracts candidate feed stop IDs without
creating a public transfer link. Run only against installed, licensed GTFS:

```text
python scripts/audit_yokohama_transfer_candidates.py
  --bus-gtfs-dir <existing-bus-gtfs-dir>
  --bus-coverage <existing-reviewed-bus-coverage.json>
  --subway-gtfs-dir <existing-subway-gtfs-dir>
  --service-date YYYY-MM-DD
  --radius-m 300 --limit 40
  --include-bus-pole-fields
```

Its report is a **candidate shortlist**. Source GTFS `platform_code`,
`stop_code` and stop names must not be reinterpreted as a verified official
bay number. Human review must associate the exact bus pole and subway entrance
with the operator map, record feasible pedestrian geometry/estimated time and
any accessibility limits, and pin both feed versions. Only after that review
may a link be written to a local `YOKOHAMA_REVIEWED_TRANSFERS_PATH` file.

The ODPT Public Transportation Open Data Basic License (Article 8) generally
prohibits redistribution of reusable copies of the original feed or reversible
derivative GTFS data, absent permission or applicable specific exceptions.
Do **not** commit the raw GTFS, manifest containing licensed data extracts,
or large GTFS-derived dumps to public GitHub merely to run this check.
Run it on an authorized local installation and share only the small diagnostic
summary consistent with the license. Check applicable Specific Terms of Use.
Official license: https://developer.odpt.org/terms/data_basic_license.html

### Official direction corroboration (2026-10-14; still unapproved)

The first real-feed candidate audit on 2026-09-04 (radius 300m,
`coverage_dev_288.json`) yielded **11 geometric pairs**. On two examples,
official **2026-10-14** route/direction listings independently corroborate
the GTFS names and directions:

| Feed-specific GTFS pole -> subway station | GTFS 8-series headsign | Official departure bay for that direction | Straight line | Status |
| --- | --- | --- | --- | --- |
| `yokohama_bus:3018_02` 高島町 -> `yokohama_subway:B19` | 本牧車庫前行 | 高島町 **2番** | 65.6m | direction corroborated, walking **NOT approved** |
| `yokohama_bus:2014_12` 桜木町駅前 -> `yokohama_subway:B18` | 横浜駅前行 | 桜木町駅前 **12番** | 83.6m | direction corroborated, walking **NOT approved** |

Sources (official Yokohama city bus direction/bay pages):
- https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090598
- https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090408

The raw `platform_code=12` in the second GTFS pole is a further
corroborating *source label*, but it does not independently prove spatial
GTFS-to-bay identity. In the first GTFS pole both `stop_code` and
`platform_code` are absent; suffix `_02` must **not** be assumed
to mean official bay 2. The maps describe October routes while the installed
GTFS sample is September: a full schedule/stop-map edition crosscheck is still
required. Station exits, pedestrian path, measured walking distance/time
and accessibility remain unknown. Do not add these as production
`ExplicitTransferLink` entries on the basis of this matching alone.

The offline survey and the development-only proximity mode now share the
same pure `iter_nearby_stop_pairs` geometry from
`api/transit_transfer_candidates.py`. Both feed searches continue to reuse
the common SearchCore, while official walking-link approval stays a distinct
explicit input. This change does NOT authorize proximity links in production.

### Cross-city reviewed transfer-time core (Tokyo and Yokohama)

`api/reviewed_walk_time.py` defines the common walking-time validation and
`walk_edge_elapsed_minutes` conversion. Without independently reviewed timing,
Tokyo's existing edge duration (GTFS/ODPT point distance divided by 80m/min)
is unchanged, and Yokohama continues to refuse public unreviewed links.

Tokyo's graph builder now accepts optional, **directional**
`reviewed_walk_links` containing `ReviewedWalkingLink` records. These
are applied only to **existing** graph edges, never created from nearby
coordinates. Their measured route meters and conservative time replace both
the cost weight and the elapsed walking minutes used by the selected journey;
detailed walk steps disclose `walking_time_basis` and
`walking_connection_verified`. Tokyo's reverse elapsed-time bound also uses
the same corrected duration. A missing edge, unmatched stop ID, duplicate
direction, implausible distance or missing station access review rejects the
entire correction batch without mutating any edge.

Do **not** infer a Tokyo link from station names or apply any official
departure-platform estimate without confirming the full station-to-platform
access component. The `includes_station_access=True` field is a human
review declaration and is not automatically inferred from nearby coordinates.
Published official standard walking minutes are not an accessible-route
promise. No verified Tokyo/Yokohama links have been shipped automatically
with this code. The same walk meter/minute minimum is applied to Yokohama's
existing `ExplicitTransferLink` validation; its city-specific government
URL check and version-scoped link file stay intact.

Because Tokyo's production graph has no new reviewed-link inventory configured,
**all present Tokyo routes remain on the old estimate until explicit approved
records are supplied**. This is an incremental migration, not a claim that
Tokyo stations already have accurate underground transfer timing.
